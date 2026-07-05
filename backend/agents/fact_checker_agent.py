"""Fact-Checker agent — independently verifies claims via separate searches.

Improvements over previous version:
- Better query generation (no "verify:" prefix)
- Multi-step JSON extraction (handles markdown, trailing text, etc.)
- Instrumentation: logs query, source counts, parse method, scores
- Uses Tavily's LLM-generated answer summary
- Improved prompt with few-shot examples and source counting
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from backend.agents.base import BaseAgent
from backend.config import settings
from backend.tools.tavily_tool import tavily_search, get_tavily_answer
from backend.tools.exa_tool import exa_search
from backend.tools.ddg_tool import ddg_search
from backend.tools.query_normalizer import normalize_query
from backend.agents.searcher_agent import _call_tool_rate_limited

logger = logging.getLogger(__name__)

FACT_CHECKER_SYSTEM = """You are an independent fact-checker. You receive a claim and search results. Your job is to verify the claim and assign a trust score.

## CRITICAL: Score Based on Source Count, Not Gut Feeling

You MUST count sources first, then use the rubric below. Do NOT default to mid-range scores.

## Step 1: For Each Source, Write One Line
For each source, write exactly one of these labels with a brief reason:
- SUPPORT: Source contains facts that directly match the claim (same numbers, names, dates, events)
- PARTIAL: Source mentions the topic but lacks specific details from the claim
- CONTRADICT: Source states something that opposes the claim
- NEUTRAL: Source is unrelated or too vague to judge

## Step 2: Count and Score — Use This Exact Rubric

| SUPPORT count | Score range | Meaning |
|---|---|---|
| 4+ SUPPORT, 0 CONTRADICT | 90-100 | Strongly verified — overwhelming evidence |
| 3 SUPPORT, 0 CONTRADICT | 85-89 | Well verified — multiple confirming sources |
| 2 SUPPORT, 0 CONTRADICT | 75-84 | Well supported — two independent confirmations |
| 1 SUPPORT, 0 CONTRADICT | 65-74 | Partially supported — one source confirms |
| 0 SUPPORT, 2+ PARTIAL | 50-64 | Weak evidence — related but not confirming |
| 0 SUPPORT, 1 PARTIAL | 40-49 | Minimal evidence — barely relevant |
| All NEUTRAL | 30-39 | Unverifiable — no relevant information |
| Any CONTRADICT | 10-39 | Contradicted — sources oppose the claim |

IMPORTANT: If a source mentions the same facts as the claim (even with different wording), count it as SUPPORT, not PARTIAL. Be generous with SUPPORT — if the key facts match, it supports.

## Step 3: Set verified flag
- verified = true if SUPPORT count >= 1
- verified = false otherwise

## Examples — Study These Carefully

Example 1:
Claim: "Python was released in 1991"
Source 1: "Python was released in 1991 by Guido van Rossum" → SUPPORT (exact match)
Source 2: "The Python programming language debuted in 1991" → SUPPORT (same fact, different words)
Source 3: "Guido van Rossum created Python in the late 1980s, releasing it in 1991" → SUPPORT
→ SUPPORT: 3, verified: true, trust_score: 87

Example 2:
Claim: "Company X raised $50M in Series B funding"
Source 1: "Company X announced a $50M Series B round led by Sequoia" → SUPPORT (exact)
Source 2: "Company X raised funding to expand operations" → PARTIAL (no amount or round)
→ SUPPORT: 1, PARTIAL: 1, verified: true, trust_score: 68

Example 3:
Claim: "The Earth is flat"
Source 1: "Earth is an oblate spheroid, not flat" → CONTRADICT
Source 2: "Scientific consensus confirms Earth is round" → CONTRADICT
→ CONTRADICT: 2, verified: false, trust_score: 15

## Output Format
Output ONLY valid JSON:
{
  "claim": "the claim being checked",
  "verified": true|false,
  "trust_score": 0-100,
  "supporting_count": N,
  "partial_count": N,
  "contradict_count": N,
  "evidence": ["supporting fact 1", "contradicting fact 2"],
  "reasoning": "brief explanation citing source labels"
}"""


_WORD_TO_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}


def _word_to_number(word: str) -> int:
    """Convert a word number like 'fifty' or 'twenty three' to int."""
    words = word.strip().split()
    total = 0
    for w in words:
        if w in _WORD_TO_NUM:
            val = _WORD_TO_NUM[w]
            if val == 100 and total > 0:
                total *= 100
            else:
                total += val
    return total if total > 0 else 50  # fallback to 50 if unparseable


def _extract_json(text: str) -> dict | None:
    """Multi-step JSON extraction from LLM response.

    Returns parsed dict or None if all methods fail.
    """
    # Method 1: Try parsing the full response as JSON
    text_stripped = text.strip()
    try:
        return json.loads(text_stripped)
    except json.JSONDecodeError:
        pass

    # Method 2: Extract from ```json ... ``` code block
    match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Method 3: Extract from ``` ... ``` code block (no json label)
    match = re.search(r'```\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Method 4: Find the first complete { ... } block (greedy but balanced)
    # Find first { and last } and try parsing
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # Method 5: Try to find a JSON object with balanced braces
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    break

    return None


def _generate_search_query(claim: str) -> str:
    """Generate a fact-focused search query from a claim.

    Strips question words and filler to get better search results.
    """
    query = claim.strip()

    # Remove leading question phrases that hurt search
    prefixes_to_strip = [
        "what is ", "what are ", "how does ", "how do ",
        "why is ", "why are ", "when did ", "where is ",
        "who is ", "who are ", "is ", "are ", "can ", "does ",
        "verify: ", "check: ", "fact-check: ",
    ]
    query_lower = query.lower()
    for prefix in prefixes_to_strip:
        if query_lower.startswith(prefix):
            query = query[len(prefix):]
            break

    # Remove trailing question mark
    query = query.rstrip("?").strip()

    # If the query is very long (>150 chars), truncate to key terms
    if len(query) > 150:
        # Take first 150 chars and cut at last complete word
        query = query[:150].rsplit(' ', 1)[0]

    return query


class FactCheckerAgent(BaseAgent):
    model_tier = "fast"
    system_prompt = FACT_CHECKER_SYSTEM

    # FactChecker uses fast tier — search + structured verification doesn't
    # need deep reasoning. Override llm property to use fast model regardless.
    @property
    def llm(self):
        if self._llm is None:
            from backend.agents.base import get_fast_llm
            self._llm = get_fast_llm()
        return self._llm

    def _get_primary_model(self) -> str:
        from backend.config import settings
        return settings.model_fast

    async def _call_llm(self, prompt: str, max_tokens: int = 4096) -> str:
        """Call LLM directly without base agent's multi-model fallback.

        The fact-checker uses a single model (fast tier) and should NOT
        fall back to other models on errors — that causes 144 calls instead of 24.
        """
        from backend.agents.base import _next_openrouter_key, _or_key_index
        from backend.config import settings
        from langchain_core.messages import SystemMessage, HumanMessage

        model = self._get_primary_model()
        n_keys = len(settings.openrouter_keys)

        for key_attempt in range(n_keys):
            key = _next_openrouter_key()
            key_idx = _or_key_index - 1
            if not key:
                break
            try:
                llm = self._create_llm(model)
                messages = [
                    SystemMessage(content=self.system_prompt),
                    HumanMessage(content=prompt),
                ]
                response = await asyncio.wait_for(
                    llm.ainvoke(messages, config={"max_output_tokens": max_tokens}),
                    timeout=120.0,
                )
                return str(response.content) if response else ""
            except Exception as e:
                error_str = str(e).lower()
                if "429" in str(e) or "rate limit" in error_str:
                    logger.warning(f"FactChecker {model} key{key_idx} rate-limited, trying next key...")
                    continue
                if "503" in str(e) or "unavailable" in error_str:
                    logger.warning(f"FactChecker {model} key{key_idx} overloaded, trying next key...")
                    continue
                logger.error(f"FactChecker {model} key{key_idx} error: {e}")
                continue
        raise RuntimeError(f"FactChecker: all {n_keys} keys failed for {model}")

    def _create_llm(self, model: str):
        """Create LLM directly via OpenRouter (bypasses base agent's get_llm)."""
        from backend.agents.base import _next_openrouter_key, _or_key_index
        from backend.config import settings
        from langchain_openai import ChatOpenAI

        key = _next_openrouter_key()
        return ChatOpenAI(
            model=model, api_key=key,
            base_url="https://openrouter.ai/api/v1",
            temperature=0.0, max_retries=0,
        )

    async def verify_claim(self, claim: str, browser_facts: list[str] | None = None) -> dict[str, Any]:
        """Independently verify a single claim using separate searches.

        Includes full instrumentation: logs query, source counts, JSON parse
        method, and final scores for diagnostics.

        Args:
            claim: The claim to verify.
            browser_facts: Optional list of facts extracted by browser deep-fetches.
        """
        logger.info(f"Fact-Checker: verifying claim: {claim[:80]}...")

        # Per-agent tool call counter — each FactChecker instance gets its own
        call_counter = {"count": 0}

        # Generate tool-specific normalized queries
        tavily_query = normalize_query(claim, tool="tavily")
        semantic_query = normalize_query(claim, tool=settings.search_backend)
        ddg_query = normalize_query(claim, tool="ddg")
        logger.info(f"Fact-Checker: queries — tavily='{tavily_query[:60]}' | {settings.search_backend}='{semantic_query[:60]}'")

        sources = []
        tavily_count = 0
        semantic_count = 0
        ddg_count = 0
        tavily_answer = ""
        semantic_backend = settings.search_backend  # "exa" or "ddg"

        # Fetch Tavily answer summary (helps the LLM judge faster)
        try:
            tavily_answer = await asyncio.get_event_loop().run_in_executor(
                None, get_tavily_answer, tavily_query
            )
            if tavily_answer:
                logger.info(f"Fact-Checker: Tavily answer: {tavily_answer[:120]}...")
        except Exception as e:
            logger.warning(f"Fact-Checker: Tavily answer failed: {e}")

        # Search Tavily (rate-limited)
        try:
            tavily_results = await _call_tool_rate_limited("tavily", tavily_search, tavily_query, max_results=3, call_counter=call_counter)
            tavily_count = len(tavily_results)
            sources.extend([r.model_dump() for r in tavily_results])
        except Exception as e:
            logger.warning(f"Fact-Checker: tavily failed: {e}")

        # Search configured semantic backend (Exa or DDG) — rate-limited
        semantic_fn = exa_search if semantic_backend == "exa" else ddg_search
        try:
            semantic_results = await _call_tool_rate_limited(
                semantic_backend, semantic_fn, semantic_query, max_results=3, call_counter=call_counter
            )
            semantic_count = len(semantic_results)
            sources.extend([r.model_dump() for r in semantic_results])
        except Exception as e:
            logger.warning(f"Fact-Checker: {semantic_backend} failed: {e}")

        # Fallback: DDG if Tavily + semantic backend returned nothing
        if tavily_count + semantic_count == 0:
            logger.info("Fact-Checker: Tavily + semantic backend returned 0, falling back to DuckDuckGo")
            try:
                ddg_results = await ddg_search(query=ddg_query, max_results=3)
                ddg_count = len(ddg_results)
                sources.extend([r.model_dump() for r in ddg_results])
            except Exception as e:
                logger.warning(f"Fact-Checker: DuckDuckGo fallback failed: {e}")

        logger.info(
            f"Fact-Checker: sources retrieved — tavily={tavily_count}, "
            f"{semantic_backend}={semantic_count}, ddg={ddg_count}, total={len(sources)}"
        )

        if not sources:
            logger.warning("Fact-Checker: NO sources found for claim")
            return {
                "claim": claim,
                "verified": False,
                "trust_score": 15,
                "supporting_count": 0,
                "partial_count": 0,
                "contradict_count": 0,
                "evidence": [],
                "reasoning": "No independent sources found to verify",
                "tool_calls": call_counter["count"],
            }

        # Build source text for the LLM
        source_text = "\n".join(
            f"[{s.get('tool_name', '')}] {s.get('title', '')}: {s.get('snippet', '')}"
            for s in sources
        )

        # Include browser-extracted facts if available (compact format)
        browser_section = ""
        if browser_facts:
            # Compact: one line per fact, truncate long facts, cap at 5
            compact_facts = [f[:150] for f in browser_facts[:5]]
            browser_section = "\n## Deep-Fetched Page Facts\n" + "\n".join(f"- {f}" for f in compact_facts)
            logger.info(f"Fact-Checker: {len(compact_facts)} browser facts included (compact)")

        # Include Tavily answer if available
        answer_section = ""
        if tavily_answer:
            answer_section = f"\n## Search Engine Summary\n{tavily_answer}\n"

        prompt = (
            f"Claim to verify: {claim}\n\n"
            f"## Search Results ({len(sources)} sources)\n{source_text}"
            f"{browser_section}"
            f"{answer_section}\n"
            f"## Your Task\n"
            f"1. Label each source as SUPPORT/PARTIAL/CONTRADICT/NEUTRAL with a one-line reason\n"
            f"2. Tally: SUPPORT=N, PARTIAL=N, CONTRADICT=N, NEUTRAL=N (replace N with actual counts)\n"
            f"3. Apply the scoring rubric EXACTLY based on your SUPPORT count\n"
            f"4. Set verified=true if SUPPORT count >= 1\n"
            f"\n"
            f"REMEMBER: If a source mentions the same key facts as the claim (same numbers,\n"
            f"names, dates), count it as SUPPORT even if wording differs. Be generous.\n"
            f"\n"
            f"Output ONLY valid JSON."
        )
        response = await self._call_llm(prompt)

        # Multi-step JSON extraction
        parse_method = "full_response"
        result = _extract_json(response)

        if result is None:
            # Try extracting from markdown code blocks with more permissive regex
            parse_method = "regex_fallback"
            match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
            if match:
                inner = match.group(1).strip()
                # Try to find JSON within the code block
                inner_result = _extract_json(inner)
                if inner_result:
                    result = inner_result
                    parse_method = "code_block_extracted"

        if result is None:
            # Last resort: try to find any JSON-like structure
            parse_method = "last_resort"
            # Look for "trust_score" pattern — digits or word numbers
            score_match = re.search(
                r'"trust_score"\s*:\s*(\d+|' +
                r'(?:one|two|three|four|five|six|seven|eight|nine|ten|' +
                r'eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|' +
                r'thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)(?:\s+(?:one|two|three|four|five|six|seven|eight|nine))?)',
                response, re.IGNORECASE
            )
            verified_match = re.search(r'"verified"\s*:\s*(true|false)', response, re.IGNORECASE)
            if score_match:
                raw_score = score_match.group(1)
                # Convert word numbers to int
                if raw_score.isdigit():
                    score_val = int(raw_score)
                else:
                    score_val = _word_to_number(raw_score.lower())
                result = {
                    "claim": claim,
                    "verified": verified_match.group(1).lower() == "true" if verified_match else False,
                    "trust_score": score_val,
                    "supporting_count": 0,
                    "partial_count": 0,
                    "contradict_count": 0,
                    "evidence": [],
                    "reasoning": f"Partial extraction (word number: '{raw_score}' → {score_val})",
                }
                parse_method = "field_extraction"

        if result is None:
            # Complete fallback — log the full response for debugging
            logger.warning(
                f"Fact-Checker: JSON parse FAILED for claim: {claim[:60]}... "
                f"Response (first 500 chars): {response[:500]}"
            )
            parse_method = "failed"
            result = {
                "claim": claim,
                "verified": False,
                "trust_score": 50,
                "supporting_count": 0,
                "partial_count": 0,
                "contradict_count": 0,
                "evidence": [],
                "reasoning": f"JSON parse failed. Raw response: {response[:200]}",
            }

        result["claim"] = claim

        # Log instrumentation
        # Count successful DDG fallback as a tool call
        if ddg_count > 0:
            call_counter["count"] += 1

        result["tool_calls"] = call_counter["count"]

        logger.info(
            f"Fact-Checker result — query='{tavily_query[:60]}' | "
            f"sources={len(sources)} (tavily={tavily_count},{semantic_backend}={semantic_count},ddg={ddg_count}) | "
            f"parse={parse_method} | "
            f"verified={result.get('verified')} | "
            f"trust_score={result.get('trust_score')} | "
            f"supporting={result.get('supporting_count', '?')} | "
            f"tool_calls={call_counter['count']} | "
            f"reasoning={result.get('reasoning', '')[:80]}"
        )

        return result

    async def verify_claim_with_evidence(
        self, claim: str, browser_facts: list[str] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Like verify_claim but also returns the sources actually used for verification.

        The 5-dimension trust score needs claim-specific sources (not a global top-3)
        to compute accurate authority/agreement/recency dimensions.

        Optimized: runs searches ONCE and reuses them for both verification and
        source attribution, instead of duplicating search calls.
        """
        import asyncio
        from backend.tools.tavily_tool import tavily_search, get_tavily_answer
        from backend.tools.exa_tool import exa_search
        from backend.tools.ddg_tool import ddg_search
        from backend.agents.searcher_agent import _call_tool_rate_limited

        call_counter = {"count": 0}

        tavily_query = normalize_query(claim, tool="tavily")
        semantic_query = normalize_query(claim, tool=settings.search_backend)
        ddg_query = normalize_query(claim, tool="ddg")

        all_sources: list[dict[str, Any]] = []
        tavily_answer = ""

        # Fetch Tavily answer summary
        try:
            tavily_answer = await asyncio.get_event_loop().run_in_executor(
                None, get_tavily_answer, tavily_query
            )
        except Exception:
            pass

        # Search Tavily
        try:
            tavily_results = await _call_tool_rate_limited(
                "tavily", tavily_search, tavily_query, max_results=3, call_counter=call_counter,
            )
            all_sources.extend(r.model_dump() for r in tavily_results)
        except Exception:
            pass

        # Search semantic backend
        semantic_fn = exa_search if settings.search_backend == "exa" else ddg_search
        try:
            semantic_results = await _call_tool_rate_limited(
                settings.search_backend, semantic_fn, semantic_query, max_results=3, call_counter=call_counter,
            )
            all_sources.extend(r.model_dump() for r in semantic_results)
        except Exception:
            pass

        # Fallback: DDG if nothing found
        ddg_count = 0
        if not all_sources:
            try:
                ddg_results = await ddg_search(query=ddg_query, max_results=3)
                ddg_count = len(ddg_results)
                all_sources.extend(r.model_dump() for r in ddg_results)
            except Exception:
                pass

        # Count successful DDG fallback as a tool call
        if ddg_count > 0:
            call_counter["count"] += 1

        # Now build the prompt and call LLM (same as verify_claim but with our sources)
        source_text = "\n".join(
            f"[{s.get('tool_name', '')}] {s.get('title', '')}: {s.get('snippet', '')}"
            for s in all_sources
        )
        browser_section = ""
        if browser_facts:
            compact_facts = [f[:150] for f in browser_facts[:5]]
            browser_section = "\n## Deep-Fetched Page Facts\n" + "\n".join(f"- {f}" for f in compact_facts)
        answer_section = f"\n## Search Engine Summary\n{tavily_answer}\n" if tavily_answer else ""

        prompt = (
            f"Claim to verify: {claim}\n\n"
            f"## Search Results ({len(all_sources)} sources)\n{source_text}"
            f"{browser_section}"
            f"{answer_section}\n"
            f"## Your Task\n"
            f"1. Label each source as SUPPORT/PARTIAL/CONTRADICT/NEUTRAL with a one-line reason\n"
            f"2. Tally: SUPPORT=N, PARTIAL=N, CONTRADICT=N, NEUTRAL=N\n"
            f"3. Apply the scoring rubric EXACTLY based on your SUPPORT count\n"
            f"4. Set verified=true if SUPPORT count >= 1\n"
            f"\nOutput ONLY valid JSON."
        )
        response = await self._call_llm(prompt)
        result = _extract_json(response)
        if result is None:
            match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
            if match:
                result = _extract_json(match.group(1).strip())
        if result is None:
            result = {"claim": claim, "verified": False, "trust_score": 25,
                      "supporting_count": 0, "partial_count": 0, "contradict_count": 0,
                      "reasoning": f"JSON parse failed: {response[:100]}"}

        result["tool_calls"] = call_counter["count"]
        return result, all_sources

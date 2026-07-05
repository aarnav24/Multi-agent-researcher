"""Synthesizer agent — integrates all verified findings into a coherent, structured report."""

from __future__ import annotations

import itertools
import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.base import BaseAgent

logger = logging.getLogger(__name__)

import random

# 3-key round-robin for Gemini (synthesizer only uses 1 call/run)
# Randomize starting key so each run hits a different key
_synth_gemini_cycle: itertools.cycle | None = None


def reset_synth_gemini_key_cycle():
    """Reset the synthesizer key cycle. Call at the start of each pipeline run."""
    global _synth_gemini_cycle
    _synth_gemini_cycle = None


def _next_synth_gemini_key() -> str:
    global _synth_gemini_cycle
    from backend.config import settings
    if _synth_gemini_cycle is None:
        keys = settings.google_keys
        # Random starting position so each run distributes across keys
        start_idx = random.randrange(len(keys))
        shuffled = keys[start_idx:] + keys[:start_idx]
        _synth_gemini_cycle = itertools.cycle(shuffled)
    return next(_synth_gemini_cycle)

SYNTHESIZER_SYSTEM = """You are a research report synthesizer. You receive verified claims, sources, and trust scores.

Your job: produce a comprehensive, well-structured research report with:
1. Executive summary (2-3 sentences)
2. Key findings (each with inline citations and trust scores)
3. Detailed analysis organized by topic
4. Areas of uncertainty (claims with low trust scores)
5. Conclusion

Format the report in Markdown. You MUST include a trust annotation after
every claim using this EXACT format (the UI parses this pattern):
  — Trust: HIGH (74/100)
Trust levels by score: HIGH (81-100), MODERATE (51-80), LOW (0-50).
Do not skip this — every factual claim needs its trust badge.

Only use the verified claims and approved sources provided. Do NOT fabricate information."""


class SynthesizerAgent(BaseAgent):
    model_tier = "reasoning"
    system_prompt = SYNTHESIZER_SYSTEM

    def _get_primary_model(self) -> str:
        """Synthesizer uses gemini-3.5-flash directly via GOOGLE_API_KEY.

        Bypasses OpenRouter to avoid queuing for large token requests.
        Only 1 call per run, so stays within Gemini daily limits.
        Uses 3-key round-robin via _next_synth_gemini_key().
        """
        from backend.config import settings
        return settings.model_synthesizer

    def _create_llm(self, model: str):
        """Create Gemini LLM directly via GOOGLE_API_KEY round-robin.

        Bypasses get_llm() which would route through OpenRouter.
        """
        from langchain_google_genai import ChatGoogleGenerativeAI
        key = _next_synth_gemini_key()
        return ChatGoogleGenerativeAI(
            model=model,
            api_key=key,
            temperature=0.0,
            max_retries=2,
        )

    async def run(self, user_message, *, max_tokens=4096, **kwargs):
        """Override run to use Gemini directly, with model fallback chain.

        Model chain:
          1. gemini-2.5-flash (all 4 keys, round-robin on any error)
          2. OpenRouter gpt-oss-120b (all 8 keys, round-robin on 429)

        On any Gemini error → try next key (don't waste time on 3.5).
        On Gemini exhausted → fall back to OpenRouter.
        """
        import asyncio
        import re
        import time

        from backend.agents.base import llm_timing
        from backend.config import settings

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_message),
        ]
        input_text = "\n".join(str(m.content) for m in messages)
        input_tokens = llm_timing.count_tokens(input_text)

        def _is_server_error(e: Exception) -> bool:
            """Check if error is a 5xx / unavailable / overloaded error."""
            s = str(e)
            sl = s.lower()
            return (
                "503" in s or "500" in s or "502" in s or "504" in s or
                "service unavailable" in sl or
                "internal server error" in sl or
                "overloaded" in sl or
                "unavailable" in sl
            )

        def _is_rate_limit(e: Exception) -> bool:
            """Check if error is a 429 rate limit."""
            s = str(e)
            sl = s.lower()
            return "429" in s or "rate limit" in sl or "rate-limit" in sl

        def _is_denied(e: Exception) -> bool:
            """Check if error is a 403 permission denied."""
            s = str(e)
            sl = s.lower()
            return "403" in s or "permission_denied" in sl

        async def _try_gemini_key(model: str, key_idx: int, is_first_model: bool) -> str | None:
            """Try one Gemini key. Returns response text on success, None on failure.

            On 503/unavailable: return 'FALLBACK' signal to skip to next model.
            On 403/429/other: return None to try next key.
            """
            llm = self._create_llm(model)
            try:
                _call_start = time.time()
                response = await llm.ainvoke(messages, config={"max_output_tokens": max_tokens})
                _latency = time.time() - _call_start
                output_text = str(response.content) if response else ""
                output_tokens = llm_timing.count_tokens(output_text)
                llm_timing.record(
                    tier="reasoning",
                    agent=self.__class__.__name__,
                    model=model,
                    latency_s=_latency,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    key_idx=key_idx,
                )
                return output_text
            except Exception as e:
                if _is_denied(e):
                    logger.warning(f"Synthesizer {model} key{key_idx} denied (403), trying next key...")
                    return None
                if _is_rate_limit(e):
                    wait = 10 * (key_idx + 1)
                    logger.warning(f"Synthesizer {model} key{key_idx} rate-limited (429), waiting {wait}s...")
                    await asyncio.sleep(wait)
                    try:
                        _call_start = time.time()
                        response = await llm.ainvoke(messages, config={"max_output_tokens": max_tokens})
                        _latency = time.time() - _call_start
                        output_text = str(response.content) if response else ""
                        output_tokens = llm_timing.count_tokens(output_text)
                        llm_timing.record(
                            tier="reasoning",
                            agent=self.__class__.__name__,
                            model=model,
                            latency_s=_latency,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            key_idx=key_idx,
                        )
                        return output_text
                    except Exception:
                        logger.warning(f"Synthesizer {model} key{key_idx} failed again after retry, trying next key...")
                        return None
                if _is_server_error(e):
                    logger.warning(
                        f"Synthesizer {model} key{key_idx} returned server error "
                        f"(model overloaded), skipping remaining keys, falling back to next model..."
                    )
                    return "FALLBACK"
                logger.error(f"Synthesizer {model} key{key_idx} error: {e}")
                return None

        # ── Phase 1: gemini-2.5-flash with 4 keys (PRIMARY) ──────────────────
        # Try all 4 keys once. On 503 → skip to fallback immediately.
        # On 403/429 → try next key. If all fail → fallback.
        for key_idx in range(4):
            result = await _try_gemini_key("gemini-2.5-flash", key_idx, is_first_model=True)
            if result == "FALLBACK":
                break  # Model overloaded, skip to fallback
            if result is not None:
                return result

        # ── Phase 2: OpenRouter gpt-oss-120b with 8 keys (FALLBACK) ──────────
        logger.warning("gemini-2.5-flash unavailable, falling back to OpenRouter gpt-oss-120b")
        from backend.agents.base import _get_openrouter_llm
        for or_attempt in range(8):
            llm, key_idx = _get_openrouter_llm(
                settings.model_reasoning, return_key_idx=True,
            )
            try:
                _call_start = time.time()
                response = await llm.ainvoke(messages, max_tokens=max_tokens)
                _latency = time.time() - _call_start
                output_text = str(response.content) if response else ""
                output_tokens = llm_timing.count_tokens(output_text)
                llm_timing.record(
                    tier="reasoning",
                    agent=self.__class__.__name__,
                    model=settings.model_reasoning,
                    latency_s=_latency,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    key_idx=key_idx,
                )
                return output_text
            except Exception as e:
                if _is_server_error(e):
                    logger.warning(f"Synthesizer OpenRouter key{key_idx} overloaded, skipping remaining {7 - or_attempt} key(s)")
                    break
                logger.warning(f"Synthesizer OpenRouter key{key_idx} error, trying next key...")

        raise RuntimeError("All Gemini and OpenRouter models failed for synthesizer")

    async def synthesize(
        self,
        query: str,
        verified_claims: list[dict],
        sources: list[dict],
    ) -> str:
        """Integrate all verified findings into a coherent report."""
        logger.info(f"Synthesizer: creating report from {len(verified_claims)} claims, {len(sources)} sources")

        # Strip non-serializable fields (date objects) before JSON encoding
        safe_claims = json.loads(json.dumps(verified_claims, default=str))
        # Compact sources: keep only essential fields, cap at 30 most relevant
        compact_sources = [
            {'url': s.get('url',''), 'title': s.get('title',''), 'snippet': s.get('snippet','')[:200]}
            for s in sources[:30]
        ]
        # Use compact JSON (no indent) to minimize token count
        claims_json = json.dumps(safe_claims, separators=(',', ':'))
        sources_json = json.dumps(compact_sources, separators=(',', ':'))
        prompt = (
            f"Research Query: {query}\n\n"
            f"Verified Claims (with trust scores):\n{claims_json}\n\n"
            f"Approved Sources (top {len(compact_sources)} of {len(sources)}):\n{sources_json}\n\n"
            f"Write a comprehensive research report."
        )
        report = await self.run(prompt, max_tokens=8000)
        # Post-process: if the LLM dropped trust annotations, inject them.
        # This guarantees the UI always has trust badges to render, even
        # when the LLM omits them against instructions.
        report = self._inject_trust_badges(report, safe_claims)
        return report

    def _inject_trust_badges(self, report: str, claims: list[dict]) -> str:
        """Disabled to keep final report text clean and reader-friendly."""
        return report
        TRUST_RE = re.compile(r"Trust:\s*(HIGH|MODERATE|LOW)\s*\(\d+\s*/\s*100\)", re.IGNORECASE)
        # Build a lookup: first ~40 chars of claim text -> trust label+score
        trust_by_text: dict[str, str] = {}
        for c in claims:
            text = (c.get("claim") or "").strip()
            score = c.get("trust_score", 0)
            label = c.get("trust_label") or ("HIGH" if score >= 81 else "MODERATE" if score >= 51 else "LOW")
            if text:
                trust_by_text[text[:50]] = f"{label} ({score}/100)"

        if not trust_by_text:
            return report

        lines = report.split("\n")
        new_lines: list[str] = []
        injected = 0
        for line in lines:
            # Already has a trust badge? Leave it alone.
            if TRUST_RE.search(line):
                new_lines.append(line)
                continue
            # Does this line reference any claim text?
            matched_key = None
            for key, badge in trust_by_text.items():
                if key.lower() in line.lower():
                    matched_key = key
                    break
            if matched_key and len(line.strip()) > 20:
                badge = trust_by_text[matched_key]
                separator = " " if line.rstrip().endswith(".") else " — "
                new_lines.append(f"{line.rstrip()}{separator}Trust: {badge}")
                injected += 1
            else:
                new_lines.append(line)
        if injected:
            logger.info(f"Synthesizer: injected {injected} missing trust badges into report")
        return "\n".join(new_lines)

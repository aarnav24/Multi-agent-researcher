"""Critic agent — reviews findings for gaps, contradictions, weak sourcing. Creates self-correction loop."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage

from backend.agents.base import BaseAgent
from backend.agents.synthesizer_agent import _next_synth_gemini_key

logger = logging.getLogger(__name__)

CRITIC_SYSTEM = """You are an adversarial research critic. Your job is to find weaknesses in the current research findings.

Review the findings and identify:
1. Logical gaps — what questions remain unanswered?
2. Contradictions — do any sources disagree?
3. Weak sourcing — are claims poorly supported?
4. Missing perspectives — what viewpoints or angles haven't been explored?

Output JSON:
{
  "has_gaps": true|false,
  "gaps": ["gap1", "gap2"],
  "contradictions": [{"claim": "...", "sources": ["source1", "source2"]}],
  "follow_up_questions": ["question1", "question2"],
  "overall_quality": "high|medium|low",
  "recommendation": "proceed|research_more"
}

Be thorough but fair. Output ONLY valid JSON."""


class CriticAgent(BaseAgent):
    model_tier = "reasoning"
    system_prompt = CRITIC_SYSTEM

    def _create_llm(self, model: str):
        """Create Gemini LLM directly via GOOGLE_API_KEY round-robin."""
        from langchain_google_genai import ChatGoogleGenerativeAI
        from backend.agents.synthesizer_agent import _next_synth_gemini_key
        key = _next_synth_gemini_key()
        return ChatGoogleGenerativeAI(
            model=model,
            api_key=key,
            temperature=0.0,
            max_retries=2,
        )

    async def _call_llm(self, prompt: str, max_tokens: int = 4096) -> str:
        """Call LLM directly with gemini-2.5-flash primary, OpenRouter fallback.

        Model chain:
          1. gemini-2.5-flash (4 keys, try all on any error except 503)
          2. Fast OpenRouter model (8 keys, round-robin on 429)

        Error handling:
          429 (rate limit) → try next key
          403 (denied) → try next key
          503 (unavailable) → skip remaining keys, go to fallback
        """
        import time
        from backend.agents.base import llm_timing, _is_server_error, _next_openrouter_key, _or_key_index
        from backend.config import settings

        # ── Phase 1: gemini-2.5-flash (PRIMARY) ──────────────────────────────
        for key_idx in range(4):
            try:
                llm = self._create_llm("gemini-2.5-flash")
                _call_start = time.time()
                response = await asyncio.wait_for(
                    llm.ainvoke([HumanMessage(content=prompt)], config={"max_output_tokens": max_tokens}),
                    timeout=120.0,
                )
                _latency = time.time() - _call_start
                output_text = str(response.content) if response else ""
                output_tokens = llm_timing.count_tokens(output_text)
                input_tokens = llm_timing.count_tokens(prompt)
                llm_timing.record(
                    tier="reasoning",
                    agent=self.__class__.__name__,
                    model="gemini-2.5-flash",
                    latency_s=_latency,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    key_idx=key_idx,
                )
                return output_text
            except Exception as e:
                if _is_server_error(e):
                    logger.warning(f"Critic gemini-2.5-flash key{key_idx} overloaded (503), falling back to OpenRouter")
                    break
                logger.warning(f"Critic gemini-2.5-flash key{key_idx} error: {e}")
                continue

        # ── Phase 2: Fast OpenRouter fallback (nemotron-3-nano) ──────────────
        # Use the fast model (not gpt-oss-120b) for acceptable latency
        fallback_model = settings.model_fast  # nvidia/nemotron-3-nano-30b-a3b:free
        logger.warning(f"Critic: all Gemini keys failed, falling back to {fallback_model}")
        n_keys = len(settings.openrouter_keys)
        for key_attempt in range(n_keys):
            key = _next_openrouter_key()
            key_idx = _or_key_index - 1
            if not key:
                break
            try:
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(
                    model=fallback_model, api_key=key,
                    base_url="https://openrouter.ai/api/v1",
                    temperature=0.0, max_retries=0,
                )
                _call_start = time.time()
                response = await asyncio.wait_for(
                    llm.ainvoke(prompt, max_tokens=max_tokens),
                    timeout=120.0,
                )
                _latency = time.time() - _call_start
                output_text = str(response.content) if response else ""
                output_tokens = llm_timing.count_tokens(output_text)
                input_tokens = llm_timing.count_tokens(prompt)
                llm_timing.record(
                    tier="reasoning",
                    agent=self.__class__.__name__,
                    model=fallback_model,
                    latency_s=_latency,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    key_idx=key_idx,
                )
                return output_text
            except Exception as e:
                if "429" in str(e) or "rate limit" in str(e).lower():
                    logger.warning(f"Critic OpenRouter key{key_idx} rate-limited, trying next key...")
                    continue
                logger.error(f"Critic OpenRouter key{key_idx} error: {e}")
                continue
        raise RuntimeError("Critic: all Gemini and OpenRouter keys failed")

    async def run(self, user_message, **kwargs):
        """Override run to use direct LLM call with capped retries."""
        for attempt in range(2):
            try:
                return await self._call_llm(user_message, **kwargs)
            except Exception as e:
                if attempt == 1:
                    raise
                logger.warning(f"CriticAgent retry {attempt+1}/2: {e}")
                import asyncio
                await asyncio.sleep(2 * (attempt + 1))

    async def review(
        self,
        query: str,
        findings: list[dict],
        sources: list[dict],
    ) -> dict[str, Any]:
        """Review all findings and identify gaps/contradictions."""
        logger.info(f"Critic: reviewing {len(findings)} findings with {len(sources)} sources")
        # Strip non-serializable fields (date objects) before JSON encoding
        safe_findings = json.loads(json.dumps(findings, default=str))
        # Keep all sources with snippets — critic needs evidence to judge
        safe_sources = [
            {"url": s.get("url","")[:120], "title": s.get("title","")[:100], "snippet": s.get("snippet","")[:200]}
            for s in sources[:30]
        ]
        # Keep full summaries and all key_facts — critic needs complete picture
        compact_findings = []
        for f in safe_findings:
            compact_findings.append({
                "question": f.get("question", "")[:200],
                "summary": f.get("summary", "")[:500],
                "key_facts": f.get("key_facts", [])[:8],
            })
        prompt = (
            f"Query: {query}\n\n"
            f"Findings ({len(compact_findings)}):\n{json.dumps(compact_findings, separators=(',',':'))}\n\n"
            f"Sources ({len(safe_sources)}):\n{json.dumps(safe_sources, separators=(',',':'))}\n\n"
            f"Review for gaps, contradictions, and weak sourcing. Output JSON with has_gaps, gaps, follow_up_questions."
        )
        response = await self.run(prompt)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            return {
                "has_gaps": False,
                "gaps": [],
                "contradictions": [],
                "follow_up_questions": [],
                "overall_quality": "medium",
                "recommendation": "proceed",
            }

"""Synthesizer agent — integrates all verified findings into a coherent, structured report."""

from __future__ import annotations

import itertools
import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.base import BaseAgent

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
    from app.config import settings
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

Format the report in Markdown. Each claim should be followed by:
- [Source: Title](url) — Trust: HIGH/MODERATE/LOW (score/100)

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
        from app.config import settings
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
        """Override run to use Gemini directly, with OpenRouter fallback.

        Tries all 3 Google keys round-robin, then falls back to OpenRouter
        (gpt-oss-120b) if all Gemini keys are rate-limited or denied.
        """
        import asyncio
        import time

        from app.agents.base import llm_timing
        from app.config import settings

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_message),
        ]
        input_text = "\n".join(str(m.content) for m in messages)
        input_tokens = llm_timing.count_tokens(input_text)

        # ── Phase 1: Try all 3 Gemini keys round-robin ──────────────────────
        for key_idx in range(3):
            llm = self._create_llm("gemini-3.5-flash")
            try:
                _call_start = time.time()
                response = await llm.ainvoke(messages, config={"max_output_tokens": max_tokens})
                _latency = time.time() - _call_start
                output_text = str(response.content) if response else ""
                output_tokens = llm_timing.count_tokens(output_text)
                llm_timing.record(
                    tier="reasoning",
                    agent=self.__class__.__name__,
                    model="gemini-3.5-flash",
                    latency_s=_latency,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    key_idx=key_idx,
                )
                return output_text
            except Exception as e:
                error_str = str(e).lower()
                is_perm_denied = "403" in str(e) or "permission_denied" in error_str
                is_rate_limit = "429" in str(e) or "rate limit" in error_str
                if is_perm_denied:
                    logger.warning(f"Synthesizer Gemini key{key_idx} denied (403), trying next key...")
                    continue
                if is_rate_limit:
                    wait = 10 * (key_idx + 1)
                    logger.warning(f"Synthesizer Gemini key{key_idx} rate-limited, waiting {wait}s...")
                    await asyncio.sleep(wait)
                    # Retry same key once
                    try:
                        _call_start = time.time()
                        response = await llm.ainvoke(messages, config={"max_output_tokens": max_tokens})
                        _latency = time.time() - _call_start
                        output_text = str(response.content) if response else ""
                        output_tokens = llm_timing.count_tokens(output_text)
                        llm_timing.record(
                            tier="reasoning",
                            agent=self.__class__.__name__,
                            model="gemini-3.5-flash",
                            latency_s=_latency,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            key_idx=key_idx,
                        )
                        return output_text
                    except Exception:
                        logger.warning(f"Synthesizer Gemini key{key_idx} failed again, trying next key...")
                        continue
                logger.error(f"Synthesizer Gemini key{key_idx} error: {e}")

        # ── Phase 2: Fallback to OpenRouter (gpt-oss-120b) ───────────────────
        logger.warning("All Gemini keys failed, falling back to OpenRouter gpt-oss-120b")
        from app.agents.base import _get_openrouter_llm
        llm, key_idx = _get_openrouter_llm(
            settings.model_reasoning, return_key_idx=True,
        )
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
        return report

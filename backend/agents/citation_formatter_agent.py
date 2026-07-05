"""Citation Formatter agent — verifies every claim has a working source link using embedding similarity."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from backend.agents.base import BaseAgent
from backend.utils.embeddings import check_citation

logger = logging.getLogger(__name__)

CITATION_FORMATTER_SYSTEM = """You are a citation formatter. You receive a draft report with claims and sources.

Your job:
1. Verify each claim has a corresponding source citation
2. Format all citations consistently (use numbered footnotes: [1], [2], etc.)
3. Add a bibliography section at the end
4. Flag any claims that lack proper sourcing

Output the final formatted report in Markdown with:
- Inline numbered citations [1], [2], etc.
- A "Bibliography" section at the end with full source details

If a claim lacks a source, add: ⚠️ [Unsourced Claim]"""

class CitationFormatterAgent(BaseAgent):
    model_tier = "fast"
    system_prompt = CITATION_FORMATTER_SYSTEM

    async def _call_llm(self, prompt: str, max_tokens: int = 8000) -> str:
        """Call LLM directly without base agent's multi-model fallback."""
        from backend.agents.base import _next_openrouter_key, _or_key_index
        from backend.config import settings
        from langchain_core.messages import SystemMessage, HumanMessage
        from langchain_openai import ChatOpenAI

        model = settings.model_fast
        n_keys = len(settings.openrouter_keys)

        for key_attempt in range(n_keys):
            key = _next_openrouter_key()
            key_idx = _or_key_index - 1
            if not key:
                break
            try:
                llm = ChatOpenAI(
                    model=model, api_key=key,
                    base_url="https://openrouter.ai/api/v1",
                    temperature=0.0, max_retries=0,
                )
                messages = [
                    SystemMessage(content=self.system_prompt),
                    HumanMessage(content=prompt),
                ]
                response = await asyncio.wait_for(
                    llm.ainvoke(messages, max_tokens=max_tokens),
                    timeout=120.0,
                )
                return str(response.content) if response else ""
            except Exception as e:
                if "429" in str(e) or "rate limit" in str(e).lower():
                    wait = 5 * (key_attempt + 1)
                    logger.warning(f"CitationFormatter {model} key{key_idx} rate-limited (429), waiting {wait}s...")
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"CitationFormatter {model} key{key_idx} error: {e}")
                continue
        raise RuntimeError(f"CitationFormatter: all keys failed")

    async def format_and_verify(
        self,
        draft_report: str,
        claims: list[dict],
        sources: list[dict],
        similarity_threshold: float = 0.7,
    ) -> str:
        """Verify citations with embedding similarity and format the final report."""
        logger.info(f"Citation Formatter: verifying {len(claims)} claims against {len(sources)} sources")

        # Embedding-based verification
        verified_claims = []
        flagged_claims = []

        for claim_data in claims:
            claim_text = claim_data.get("claim", "")
            claim_sources = claim_data.get("sources", [])

            best_similarity = 0.0
            for src in claim_sources:
                snippet = src.get("snippet", "")
                if snippet:
                    passes, sim = check_citation(claim_text, snippet, threshold=similarity_threshold)
                    best_similarity = max(best_similarity, sim)
                    if not passes:
                        flagged_claims.append({
                            "claim": claim_text,
                            "source_url": src.get("url", ""),
                            "similarity": round(sim, 3),
                        })

            verified_claims.append({
                "claim": claim_text,
                "best_similarity": round(best_similarity, 3),
                "passes_threshold": best_similarity >= similarity_threshold,
            })

        # Strip non-serializable fields before JSON encoding
        safe_verified = json.loads(json.dumps(verified_claims, default=str))
        safe_flagged = json.loads(json.dumps(flagged_claims, default=str))

        # Truncate draft report to avoid exceeding model token limits
        # Keep first 30000 chars (intro + key findings) + last 10000 chars (conclusions)
        max_report_chars = 40000
        if len(draft_report) > max_report_chars:
            head_len = 30000
            tail_len = max_report_chars - head_len
            truncated_report = (
                draft_report[:head_len]
                + f"\n\n... [{len(draft_report) - max_report_chars} chars truncated] ...\n\n"
                + draft_report[-tail_len:]
            )
        else:
            truncated_report = draft_report

        # Compact verification results — keep enough of the claim to identify it
        compact_verified = [
            {"claim": v["claim"][:200], "similarity": v["best_similarity"], "passes": v["passes_threshold"]}
            for v in safe_verified
        ]
        compact_flagged = [
            {"claim": f["claim"][:200], "source": f["source_url"][:120], "similarity": f["similarity"]}
            for f in safe_flagged
        ]

        # Ask LLM to format the final report
        prompt = (
            f"Draft Report:\n{truncated_report}\n\n"
            f"Citation Verification Summary: {len(compact_verified)} claims checked, "
            f"{sum(1 for v in compact_verified if not v['passes'])} failed threshold.\n\n"
            f"Flagged Citations ({len(compact_flagged)}):\n{json.dumps(compact_flagged, indent=2)}\n\n"
            f"Format the final report with proper citations and bibliography. "
            f"Flag any unsourced or poorly-supported claims."
        )
        final_report = await self._call_llm(prompt, max_tokens=8000)
        return final_report

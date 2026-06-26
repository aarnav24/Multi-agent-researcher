"""Critic agent — reviews findings for gaps, contradictions, weak sourcing. Creates self-correction loop."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agents.base import BaseAgent

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

    async def run(self, user_message, **kwargs):
        """Override run to cap total retries at 2 attempts."""
        for attempt in range(2):
            try:
                return await super().run(user_message, **kwargs)
            except Exception as e:
                if attempt == 1:  # Last attempt failed
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

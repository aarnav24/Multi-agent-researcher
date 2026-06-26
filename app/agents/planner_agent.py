"""Planner agent — generates hypothesis tree + search strategy before orchestration starts."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """You are a research planning expert. Your job is to create a comprehensive research plan for a complex query.

Given a user query, produce a JSON research plan with:
1. hypothesis_tree: A tree of hypotheses and sub-hypotheses to investigate
2. key_entities: List of key entities, people, concepts, or technologies to research
3. search_strategy: For each key area, describe the search approach
4. tool_routing: Map each research area to the best tools to use following these rules:
   - "academic" / "scientific" -> ["arxiv", "exa"]
     Arxiv has structured metadata for papers; Exa is semantic-first, returns clean academic content
   - "general" / "current_events" / "news" -> ["serper", "tavily"]
     Serper for freshness (Google search); Tavily for LLM-optimized clean content
   - "code" / "technical" -> ["github", "tavily"]
     GitHub for repo search + README extraction; Tavily for docs pages
   - "deep_fetch" -> ["browser"]
     For URLs that need full page content extraction
   - "internal" / "corpus" / "documents" -> ["pgvector"]
     For searching user-uploaded documents in the local vector store
   - "ddg" (DuckDuckGo) is the unlimited free fallback for tavily and exa — only used when BOTH tavily AND exa return zero results

Output ONLY valid JSON in this exact format:
{
  "hypothesis_tree": { "main_hypothesis": "...", "sub_hypotheses": ["..."] },
  "key_entities": ["entity1", "entity2"],
  "search_strategy": { "area1": "approach1" },
  "tool_routing": { "area1": ["arxiv", "exa"] }
}"""


class PlannerAgent(BaseAgent):
    model_tier = "reasoning"
    system_prompt = PLANNER_SYSTEM

    async def create_plan(self, query: str) -> dict[str, Any]:
        """Generate a research plan for the given query."""
        logger.info(f"Planner: creating plan for query: {query[:80]}...")
        response = await self.run(query)
        try:
            plan = json.loads(response)
            return plan
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
            if match:
                plan = json.loads(match.group(1))
                return plan
            logger.warning("Planner: failed to parse JSON, returning raw")
            return {"raw_plan": query, "hypothesis_tree": {}, "key_entities": [], "search_strategy": {}, "tool_routing": {}}

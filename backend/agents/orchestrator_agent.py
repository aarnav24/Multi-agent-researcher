"""Lead Orchestrator agent — decomposes query, dispatches workers, runs sufficiency checks."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from backend.agents.base import BaseAgent

logger = logging.getLogger(__name__)

ORCHESTRATOR_SYSTEM = """You are the Lead Orchestrator of a multi-agent research swarm.

Your responsibilities:
1. Decompose the research query into 3-8 focused sub-questions (scale with query complexity)
2. Assign each sub-question to the appropriate tool(s) based on question type (see rules below)
3. After every 3 sub-questions are answered, run a "sufficiency check"

TOOL ASSIGNMENT RULES (follow strictly):
The Research Plan contains a "tool_routing" map. ALWAYS use the tools specified there.
If the plan does not provide tool_routing, use these fallback rules:
- "academic" / "scientific" / "papers" → ["arxiv", "exa"]
  Use ONLY for: research papers, preprints, theoretical protocols, algorithm descriptions.
  Arxiv has structured metadata for papers; Exa is semantic-first, returns clean academic content.
- "news" / "recent" / "industry" / "developments" → ["serper", "tavily"]
  Use for: recent events, industry news, company announcements, product releases, funding rounds.
  Serper (Google Search) for maximum freshness; Tavily for LLM-optimized clean content.
- "code" / "frameworks" / "technical" → ["github", "tavily"]
  GitHub for repo search + README extraction; Tavily for docs pages, API references.
- "deep_fetch" → ["browser"]
  For URLs that need full page content extraction.
- "internal" / "corpus" / "documents" → ["pgvector"]
  For searching user-uploaded documents in the local vector store.

IMPORTANT DISTINCTION:
- "Latest advances in quantum ERROR CORRECTION TECHNIQUES" → academic (papers/theory) → arxiv+exa
- "Latest INDUSTRY DEVELOPMENTS in quantum computing" → news (companies/funding) → serper+tavily
- "Latest FEATURES of open-source FRAMEWORKS" → code (repos/releases) → github+tavily
When a question mixes both academic and industry aspects, prefer serper+tavily for recency.

For each sub-question, output JSON:
{
  "sub_questions": [
    {
      "id": "unique-id",
      "question": "focused sub-question text",
      "assigned_tools": ["arxiv", "exa"],
      "question_type": "academic|general|code|deep_fetch"
    }
  ]
}

For sufficiency checks, output JSON:
{
  "sufficiency_met": true|false,
  "reasoning": "why we have enough or what's still missing",
  "additional_questions": [...]  // only if sufficiency_met is false
}

Output ONLY valid JSON."""


class OrchestratorAgent(BaseAgent):
    model_tier = "reasoning"
    system_prompt = ORCHESTRATOR_SYSTEM

    async def decompose(
        self,
        query: str,
        plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Decompose query into sub-questions based on the research plan.

        Uses the planner's tool_routing to assign tools to each sub-question.
        The tool_routing map from the plan is: {area: [tool1, tool2, ...]}

        If the user has uploaded documents (corpus), append "pgvector" to every
        sub-question's tool list so the searcher pulls relevant chunks from the
        user's knowledge base alongside the web tools chosen by the planner.
        """
        logger.info("Orchestrator: decomposing query into sub-questions")
        tool_routing = plan.get("tool_routing", {})

        # Auto-include pgvector when the user has indexed any documents.
        # Skipped for anonymous users (user_id is None/empty) — the pgvector
        # tool would just return empty results and waste a tool call anyway.
        include_corpus = bool(getattr(self, "user_id", None))
        if include_corpus:
            try:
                from backend.tools.pgvector_tool import has_documents
                include_corpus = await has_documents(self.user_id)
            except Exception as e:
                logger.warning(f"Orchestrator: has_documents check failed, skipping corpus: {e}")
                include_corpus = False
        if include_corpus:
            logger.info("Orchestrator: user has corpus docs → auto-adding pgvector to sub-questions")

        prompt = (
            f"Query: {query}\n\n"
            f"Research Plan: {json.dumps(plan)}\n\n"
            f"Tool Routing (MUST follow strictly): {json.dumps(tool_routing)}\n\n"
            + (
                "Note: the user has uploaded documents — include them where relevant.\n\n"
                if include_corpus else ""
            )
            + f"Decompose into 3-5 focused sub-questions. "
            f"For each sub-question, assign the tools from the tool_routing map based on its research area. "
            f"If a sub-question doesn't match any routing key, use ['tavily'] as default."
        )
        response = await self.run(prompt)
        sub_questions = self._parse_sub_questions(response)

        # Enforce tool assignments from planner's tool_routing
        if tool_routing:
            for sq in sub_questions:
                # Try to match sub-question to a routing area
                sq_lower = sq.get("question", "").lower()
                assigned = None
                for area, tools in tool_routing.items():
                    if area.lower() in sq_lower:
                        assigned = tools
                        break
                if assigned:
                    sq["assigned_tools"] = assigned
                    logger.info(f"Orchestrator: '{sq.get('question', '')[:50]}' → tools: {assigned}")

        # Append pgvector to every sub-question if the user has docs.
        # Dedupe so we never add it twice when the planner already routed there.
        if include_corpus:
            for sq in sub_questions:
                tools = sq.get("assigned_tools") or ["tavily"]
                if "pgvector" not in tools:
                    sq["assigned_tools"] = list(tools) + ["pgvector"]
            logger.info(
                f"Orchestrator: appended pgvector to {len(sub_questions)} sub-questions"
            )

        return sub_questions

    async def sufficiency_check(
        self,
        query: str,
        findings: list[dict],
        sub_questions: list[dict],
    ) -> dict[str, Any]:
        """Check if current findings are sufficient to answer the original query."""
        logger.info(f"Orchestrator: running sufficiency check ({len(findings)} findings)")
        # Compact findings to avoid token blowup — only keep summary + key_facts
        compact_findings = []
        for f in findings:
            compact_findings.append({
                "question": f.get("question", "")[:100],
                "summary": f.get("summary", "")[:200],
                "key_facts": f.get("key_facts", [])[:3],
            })
        prompt = (
            f"Original Query: {query}\n\n"
            f"Sub-questions investigated ({len(sub_questions)}):\n"
            + "\n".join(f"  - {sq.get('question','')[:120]}" for sq in sub_questions)
            + f"\n\nFindings so far ({len(compact_findings)}):\n"
            + json.dumps(compact_findings, separators=(',', ':'))
            + "\n\nCan we now answer the original query comprehensively? "
            "If sufficiency is met, no more research is needed. Be strict — "
            "only say met if we have enough for a thorough report."
        )
        response = await self.run(prompt)
        try:
            result = json.loads(response)
            return result
        except json.JSONDecodeError:
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            return {"sufficiency_met": False, "reasoning": "parse_error", "additional_questions": []}

    def _parse_sub_questions(self, response: str) -> list[dict]:
        try:
            data = json.loads(response)
            sqs = data.get("sub_questions", [])
        except json.JSONDecodeError:
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                sqs = data.get("sub_questions", [])
            else:
                return []
        # Ensure IDs
        for sq in sqs:
            if "id" not in sq:
                sq["id"] = str(uuid.uuid4())
        return sqs

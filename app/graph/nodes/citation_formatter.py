"""Citation Formatter node — verifies every claim has a working source link."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.citation_formatter_agent import CitationFormatterAgent
from app.graph.state import ResearchGraphState
from app.state.store import StateStore

logger = logging.getLogger(__name__)


async def citation_formatter_node(state: ResearchGraphState, config: RunnableConfig | None = None) -> ResearchGraphState:
    """Run the Citation Formatter to verify and format all citations."""
    logger.info("Node: citation_formatter")
    store: StateStore | None = (config or {}).get("configurable", {}).get("store")

    agent = CitationFormatterAgent()
    draft_report = state.get("final_report", "")
    verified_claims = state.get("verified_claims", [])
    sources = state.get("all_sources", [])

    final_report = await agent.format_and_verify(
        draft_report=draft_report,
        claims=verified_claims,
        sources=sources,
        similarity_threshold=0.7,
    )

    # Persist to shared store
    if store:
        session_id = state["session_id"]
        await store.write_global(session_id, "report", final_report, agent="citation_formatter")
        await store.write_global(session_id, "citations_verified", True, agent="citation_formatter")
        await store.write_global(session_id, "status", "done", agent="citation_formatter")

    return {
        **state,
        "final_report": final_report,
        "citations_verified": True,
        "status": "done",
    }

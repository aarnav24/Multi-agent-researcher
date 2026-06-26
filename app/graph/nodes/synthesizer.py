"""Synthesizer node — integrates verified findings into a coherent report."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.synthesizer_agent import SynthesizerAgent
from app.graph.state import ResearchGraphState
from app.state.store import StateStore

logger = logging.getLogger(__name__)


async def synthesizer_node(state: ResearchGraphState, config: RunnableConfig | None = None) -> ResearchGraphState:
    """Run the Synthesizer agent to create the final report."""
    logger.info("Node: synthesizer")
    store: StateStore | None = (config or {}).get("configurable", {}).get("store")

    agent = SynthesizerAgent()
    verified_claims = state.get("verified_claims", [])
    sources = state.get("all_sources", [])

    # Enforce input contract: synthesizer only receives verified claims (trust_score >= 40)
    unverified = [c for c in verified_claims if c.get("trust_score", 0) < 40]
    if unverified:
        logger.warning(
            f"Synthesizer: filtering out {len(unverified)} unverified claims "
            f"(trust_score < 40) before synthesis"
        )
        verified_claims = [c for c in verified_claims if c.get("trust_score", 0) >= 40]

    report = await agent.synthesize(
        query=state["query"],
        verified_claims=verified_claims,
        sources=sources,
    )

    # Persist to shared store
    if store:
        session_id = state["session_id"]
        await store.write_global(session_id, "report", report, agent="synthesizer")
        await store.write_global(session_id, "status", "synthesizing", agent="synthesizer")

    return {
        **state,
        "final_report": report,
        "status": "synthesizing",
    }

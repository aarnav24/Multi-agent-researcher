"""Critic node — reviews findings for gaps, contradictions, weak sourcing."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from backend.agents.critic_agent import CriticAgent
from backend.graph.state import ResearchGraphState
from backend.state.store import StateStore

logger = logging.getLogger(__name__)


async def critic_node(state: ResearchGraphState, config: RunnableConfig | None = None) -> ResearchGraphState:
    """Run the Critic agent to review all findings."""
    logger.info("Node: critic")
    store: StateStore | None = (config or {}).get("configurable", {}).get("store")
    sse = (config or {}).get("configurable", {}).get("sse")
    if sse:
        sse.emit("agent_start", {
            "agent": "critic",
            "message": "Critic reviewing findings",
            "tier": "reasoning",
            "model": "critic",
        })

    agent = CriticAgent()
    from backend.agents.base import apply_user_id_to_agent
    apply_user_id_to_agent(agent, config)
    findings = state.get("all_findings", [])
    sources = state.get("all_sources", [])

    review = await agent.review(state["query"], findings, sources)

    critic_rounds = state.get("critic_rounds", 0) + 1
    gaps = review.get("follow_up_questions", [])
    has_gaps = review.get("has_gaps", False) and len(gaps) > 0

    # Persist to shared store
    if store:
        session_id = state["session_id"]
        await store.write_slot(
            session_id,
            "worker:critic-0:gaps",
            {"gaps": gaps, "has_gaps": has_gaps},
            agent="critic",
            worker_id="critic-0",
        )
        await store.write_global(session_id, "critic_rounds", critic_rounds, agent="critic")
        await store.write_global(session_id, "critic_done", not has_gaps, agent="critic")
        await store.write_global(session_id, "status", "critiquing", agent="critic")

    return {
        **state,
        "critic_rounds": critic_rounds,
        "critic_gaps": gaps,
        "critic_done": not has_gaps,  # True if no gaps found
        "status": "critiquing",
    }

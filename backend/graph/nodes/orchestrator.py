"""Orchestrator nodes — decomposes query and runs sufficiency checks."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from backend.agents.orchestrator_agent import OrchestratorAgent
from backend.graph.state import ResearchGraphState
from backend.state.store import StateStore

logger = logging.getLogger(__name__)


async def orchestrator_node(state: ResearchGraphState, config: RunnableConfig | None = None) -> ResearchGraphState:
    """Decompose query into sub-questions and dispatch workers."""
    logger.info("Node: orchestrator")
    store: StateStore | None = (config or {}).get("configurable", {}).get("store")
    sse = (config or {}).get("configurable", {}).get("sse")
    if sse:
        sse.emit("agent_start", {
            "agent": "orchestrator",
            "message": "Orchestrator decomposing query",
            "tier": "reasoning",
            "model": "orchestrator",
        })

    agent = OrchestratorAgent()
    from backend.agents.base import apply_user_id_to_agent
    apply_user_id_to_agent(agent, config)
    plan = state.get("plan") or {}
    sub_questions = await agent.decompose(state["query"], plan)

    # Persist sub-questions to shared store (global write — orchestrator's privilege)
    if store:
        session_id = state["session_id"]
        await store.write_global(session_id, "sub_questions", sub_questions, agent="orchestrator")
        await store.write_global(session_id, "status", "researching", agent="orchestrator")

    return {
        **state,
        "sub_questions": sub_questions,
        "status": "researching",
        "sufficiency_met": False,
    }


async def sufficiency_check_node(state: ResearchGraphState, config: RunnableConfig | None = None) -> ResearchGraphState:
    """Run sufficiency check — can we answer the query yet?

    Uses LLM judgment + a heuristic: if we have ≥15 sources and ≥3 findings
    covering all sub-questions, we can skip browser deep-fetches.
    """
    logger.info("Node: sufficiency_check")
    store: StateStore | None = (config or {}).get("configurable", {}).get("store")

    agent = OrchestratorAgent()
    from backend.agents.base import apply_user_id_to_agent
    apply_user_id_to_agent(agent, config)
    findings = state.get("all_findings", [])
    sub_questions = state.get("sub_questions", [])
    sources = state.get("all_sources", [])

    result = await agent.sufficiency_check(state["query"], findings, sub_questions)
    llm_says_sufficient = result.get("sufficiency_met", False)

    # Heuristic: enough sources + all sub-questions have findings
    answered_questions = {f.get("sub_question_id", "") for f in findings}
    if sub_questions:
        all_answered = all(
            sq.get("id", "") in answered_questions for sq in sub_questions
        )
    else:
        all_answered = False
    has_enough_sources = len(sources) >= 15 and len(findings) >= 3

    sufficiency_met = llm_says_sufficient or (all_answered and has_enough_sources)

    if sufficiency_met:
        logger.info("Sufficiency check: MET — skipping browser deep-fetches")
    else:
        logger.info("Sufficiency check: NOT MET — proceeding to browser deep-fetches")

    # Persist to shared store
    if store:
        session_id = state["session_id"]
        await store.write_global(session_id, "sufficiency_met", sufficiency_met, agent="orchestrator")
        await store.write_global(session_id, "critic_gaps", result.get("additional_questions", []), agent="orchestrator")

    return {
        **state,
        "sufficiency_met": sufficiency_met,
        "critic_gaps": result.get("additional_questions", []),
    }

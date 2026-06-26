"""Planner node — generates hypothesis tree + search strategy."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.planner_agent import PlannerAgent
from app.graph.state import ResearchGraphState
from app.state.store import StateStore

logger = logging.getLogger(__name__)


async def planner_node(state: ResearchGraphState, config: RunnableConfig | None = None) -> ResearchGraphState:
    """Run the Planner agent to create a research plan."""
    logger.info("Node: planner")
    store: StateStore | None = (config or {}).get("configurable", {}).get("store")

    agent = PlannerAgent()
    plan = await agent.create_plan(state["query"])

    # Persist plan to shared store
    if store:
        session_id = state["session_id"]
        await store.write_global(session_id, "plan", plan, agent="planner")
        await store.write_global(session_id, "status", "planning", agent="planner")

    return {
        **state,
        "plan": plan,
        "plan_ready": True,
        "status": "planning",
    }

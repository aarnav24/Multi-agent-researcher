"""Searcher nodes — dispatch parallel Searcher workers and collect results."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from backend.agents.searcher_agent import SearcherAgent
from backend.graph.state import ResearchGraphState
from backend.state.store import StateStore
from backend.utils.concurrency import agent_slot, check_kill_switches

logger = logging.getLogger(__name__)


async def _run_single_searcher(
    sub_question: dict[str, Any],
    stagger_delay: float = 0.0,
    sse: Any = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Run a single Searcher worker for one sub-question."""
    if stagger_delay > 0:
        await asyncio.sleep(stagger_delay)
    async with agent_slot():
        agent = SearcherAgent(user_id=user_id)
        question = sub_question.get("question", "")
        tools = sub_question.get("assigned_tools", ["tavily"])
        result = await agent.search(question, tools)
        result["sub_question_id"] = sub_question.get("id", "")
        result["question"] = question
        return result


async def searcher_dispatch_node(state: ResearchGraphState, config: RunnableConfig | None = None) -> ResearchGraphState:
    """Dispatch all Searcher workers in parallel."""
    logger.info("Node: searcher_dispatch")
    store: StateStore | None = (config or {}).get("configurable", {}).get("store")
    sse = (config or {}).get("configurable", {}).get("sse")
    if sse:
        sse.emit("agent_start", {
            "agent": "searchers",
            "message": "Searchers searching sub-questions",
            "tier": "fast",
            "model": "searchers",
        })

    # Hard kill switch: check if we've hit session-level limits
    kill_reason = check_kill_switches(state)
    if kill_reason:
        logger.warning(f"Searcher dispatch BLOCKED by kill switch: {kill_reason}")
        if sse:
            sse.emit("agent_status", {
                "agent_id": "system",
                "status": "failed",
                "message": f"Kill switch: {kill_reason}",
            })
        return {**state, "status": "searchers_done"}

    sub_questions = state.get("sub_questions", [])

    # Filter to only pending sub-questions
    pending = [sq for sq in sub_questions if sq.get("status") != "done"]
    if not pending:
        return {**state, "status": "searchers_done"}

    logger.info(f"Dispatching {len(pending)} Searcher workers")

    # Emit agent_status for each searcher worker before dispatch
    if sse:
        for i, sq in enumerate(pending):
            sse.emit("agent_status", {
                "agent_id": f"searcher-{i}",
                "status": "running",
                "question": sq.get("question", "")[:100],
                "model": "fast",
                "tier": "fast",
            })

    # Extract user_id from config
    user_id = (config or {}).get("configurable", {}).get("user_id")

    # Run all searchers in parallel with staggered starts (1s apart) to avoid rate limits
    tasks = [_run_single_searcher(sq, stagger_delay=i * 1.0, sse=sse, user_id=user_id) for i, sq in enumerate(pending)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect findings and sources
    new_findings = []
    new_sources = []
    new_tool_calls = 0
    errors = []

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            errors.append(str(result))
            logger.error(f"Searcher {i} failed: {result}")
            if sse:
                sse.emit("agent_status", {
                    "agent_id": f"searcher-{i}",
                    "status": "failed",
                    "model": "fast",
                    "tier": "fast",
                })
            continue
        # Accumulate tool calls from this searcher
        new_tool_calls += result.get("tool_calls", 0)
        # Emit tool_call events and completion status for this searcher
        if sse:
            tool_names = result.get("tools_used", [])
            for tool_name in tool_names:
                sse.emit("tool_call", {
                    "agent_id": f"searcher-{i}",
                    "tool_name": tool_name,
                    "latency_ms": 0,
                })
            sse.emit("agent_status", {
                "agent_id": f"searcher-{i}",
                "status": "completed",
                "model": "fast",
                "tier": "fast",
                "question": result.get("question", ""),
            })
        # Enforce return contract: must have summary (sources can be empty for edge cases)
        if not result.get("summary"):
            # Try to synthesize from key_facts if available
            key_facts = result.get("key_facts", [])
            if key_facts:
                result["summary"] = ". ".join(key_facts[:3])
                result.setdefault("sources", [])
                logger.info(f"Searcher {i}: synthesized summary from key_facts")
            else:
                logger.warning(f"Searcher {i} returned malformed result (no summary, no key_facts), skipping")
                continue
        # Cap sources per finding to prevent context bloat (max 10 per worker)
        if len(result.get("sources", [])) > 10:
            result["sources"] = result["sources"][:10]
        new_findings.append(result)
        for src in result.get("sources", []):
            new_sources.append(src)

        # Write each searcher result to its own slot in the shared store
        if store:
            worker_id = f"searcher-{i}"
            await store.write_slot(
                state["session_id"],
                f"worker:{worker_id}:results",
                result,
                agent="searcher",
                worker_id=worker_id,
            )

    # Merge with existing
    all_findings = list(state.get("all_findings", [])) + new_findings
    all_sources = list(state.get("all_sources", [])) + new_sources

    agent_count = state.get("agent_count", 0) + len(pending)
    tool_call_count = state.get("tool_call_count", 0) + new_tool_calls
    searcher_rounds = state.get("searcher_rounds", 0) + 1

    # Persist accumulated findings and sources to shared store
    if store:
        session_id = state["session_id"]
        await store.write_global(session_id, "findings", all_findings, agent="orchestrator")
        await store.write_global(session_id, "sources", all_sources, agent="orchestrator")
        await store.write_global(session_id, "agent_count", agent_count, agent="orchestrator")
        await store.write_global(session_id, "searcher_rounds", searcher_rounds, agent="orchestrator")
        await store.write_global(session_id, "status", "searchers_done", agent="orchestrator")

        # Layer C — add searcher sources to citation graph as unverified nodes
        citation_graph = store.get_citation_graph(session_id)
        if citation_graph:
            for finding in new_findings:
                sub_q_id = finding.get("sub_question_id")
                for src in finding.get("sources", []):
                    await citation_graph.add_unverified_source(
                        url=src.get("url", ""),
                        title=src.get("title", ""),
                        snippet=src.get("snippet", ""),
                        tool_name=src.get("tool_name", ""),
                        sub_question_id=sub_q_id,
                    )

    return {
        **state,
        "all_findings": all_findings,
        "all_sources": all_sources,
        "agent_count": agent_count,
        "tool_call_count": tool_call_count,
        "searcher_rounds": searcher_rounds,
        "status": "searchers_done",
    }


async def searcher_worker_node(state: ResearchGraphState, config: RunnableConfig | None = None) -> ResearchGraphState:
    """Alias for searcher_dispatch_node — used for LangGraph routing."""
    return await searcher_dispatch_node(state, config=config)

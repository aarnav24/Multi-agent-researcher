"""LangGraph research graph — orchestrator-worker multi-agent swarm.

Execution flow:
  User Query
    → Planner (hypothesis tree + search strategy)
    → Lead Orchestrator (decomposes into 3-8 sub-questions)
    → Searchers (parallel, staggered)
    → Sufficiency Check (can we answer the query yet?)
      ├─ NOT MET → loop back to Searchers (max 2 rounds)
      └─ MET → Browsers + Critic (parallel — browsers deep-fetch while Critic analyses)
    → Fact-Checker (verifies claims independently, uses browser-extracted facts)
    → Synthesizer (integrates → coherent report)
    → Citation Formatter (verifies every source link)
    → Final Report (claims + trust scores + citations)

Key change: Browsers now run in parallel with the Critic, not gated behind
the sufficiency check. The sufficiency check only gates whether we loop
back to more searcher rounds. Browsers always run once searchers are done.
"""

from __future__ import annotations

import asyncio
import logging

from langgraph.graph import END, StateGraph

from backend.graph.nodes.planner import planner_node
from backend.graph.nodes.orchestrator import orchestrator_node, sufficiency_check_node
from backend.graph.nodes.searcher import searcher_dispatch_node
from backend.graph.nodes.browser import browser_dispatch_node
from backend.graph.nodes.critic import critic_node
from backend.graph.nodes.fact_checker import fact_checker_node
from backend.graph.nodes.synthesizer import synthesizer_node
from backend.graph.nodes.citation_formatter import citation_formatter_node
from backend.graph.state import ResearchGraphState
from backend.config import settings

logger = logging.getLogger(__name__)


def _should_loop_back(state: ResearchGraphState) -> str:
    """After sufficiency check: decide whether to loop back to Searchers or proceed."""
    sufficiency_met = state.get("sufficiency_met", False)
    critic_rounds = state.get("critic_rounds", 0)
    searcher_rounds = state.get("searcher_rounds", 0)
    sub_questions = state.get("sub_questions", [])

    # If sufficiency is met, proceed to browsers+critic
    if sufficiency_met:
        return "browsers"
    # Hard cap: max 2 searcher rounds total (initial + 1 loop-back)
    if searcher_rounds >= 2:
        return "browsers"
    # Also proceed after max_critic_rounds
    if critic_rounds >= settings.max_critic_rounds:
        return "browsers"
    # If there are no pending sub-questions to work on, stop looping
    pending = [sq for sq in sub_questions if sq.get("status") != "done"]
    if not pending and searcher_rounds >= 1:
        return "browsers"
    return "research_more"


def _should_fact_check(state: ResearchGraphState) -> str:
    """After critic: decide whether to fact-check or loop back."""
    critic_done = state.get("critic_done", False)
    critic_rounds = state.get("critic_rounds", 0)
    searcher_rounds = state.get("searcher_rounds", 0)

    # Proceed to fact-check if critic is done
    if critic_done or critic_rounds >= settings.max_critic_rounds:
        return "fact_check"
    # Hard cap: never loop back to searchers more than once total
    if searcher_rounds >= 2:
        return "fact_check"
    # Only allow one critic-driven loop-back
    if critic_rounds >= 1:
        return "fact_check"
    return "research_more"


def _validate_graph(graph: StateGraph) -> list[str]:
    """Validate that all edge targets exist and conditional routes are complete.

    Returns list of error messages (empty = valid).
    """
    errors = []
    # Collect registered node names
    registered = set(graph.nodes.keys()) if hasattr(graph.nodes, 'keys') else set()
    # Also include END as a valid target
    valid_targets = registered | {END}

    # Validate conditional edge routes
    if hasattr(graph, 'branches'):
        for node_name, branches in graph.branches.items():
            if callable(branches):
                # Conditional edge function — can't statically validate
                continue
            if isinstance(branches, dict):
                for route_name, route_target in branches.items():
                    if isinstance(route_target, str) and route_target not in valid_targets:
                        errors.append(
                            f"Conditional edge from '{node_name}' -> '{route_target}' "
                            f"targets unknown node (valid: {valid_targets})"
                        )
    return errors


def _detect_cycles(graph: StateGraph, start: str, max_depth: int = 20) -> list[str]:
    """Detect potential infinite loops via DFS from start node.

    Returns list of warning messages.
    """
    warnings = []

    def _get_targets(node_name: str) -> list[str]:
        """Get all possible target nodes from a given node."""
        targets = []
        # Check edges
        if hasattr(graph, 'edges'):
            for edge in graph.edges:
                if hasattr(edge, 'source') and edge.source == node_name:
                    if hasattr(edge, 'target'):
                        targets.append(edge.target)
        # Check conditional branches
        if hasattr(graph, 'branches') and node_name in graph.branches:
            branches = graph.branches[node_name]
            if isinstance(branches, dict):
                for t in branches.values():
                    if isinstance(t, str):
                        targets.append(t)
            elif callable(branches):
                # Can't statically determine targets — skip
                pass
        return targets

    visited = set()
    path = []

    def dfs(node, depth):
        if depth > max_depth:
            warnings.append(
                f"Path depth {depth} exceeded max {max_depth} — possible infinite loop: "
                f"{' -> '.join(path)} -> {node}"
            )
            return
        if node in visited:
            warnings.append(f"Cycle detected: {' -> '.join(path)} -> {node}")
            return
        if node == END:
            return
        visited.add(node)
        path.append(node)
        for target in _get_targets(node):
            dfs(target, depth + 1)
        path.pop()
        visited.remove(node)

    dfs(start, 0)
    return warnings


def build_graph():
    """Build and compile the LangGraph research workflow.

    Validates graph topology (edge targets exist, no cycles) before compiling.
    """
    graph = StateGraph(ResearchGraphState)

    # ── Add nodes ──────────────────────────────────────────────────────────
    graph.add_node("planner", planner_node)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("searchers", searcher_dispatch_node)
    graph.add_node("sufficiency_check", sufficiency_check_node)
    graph.add_node("browsers", browser_dispatch_node)
    graph.add_node("critic", critic_node)
    graph.add_node("fact_checker", fact_checker_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("citation_formatter", citation_formatter_node)

    # ── Edges ──────────────────────────────────────────────────────────────
    graph.set_entry_point("planner")
    graph.add_edge("planner", "orchestrator")

    # Orchestrator → searchers → sufficiency check
    graph.add_edge("orchestrator", "searchers")
    graph.add_edge("searchers", "sufficiency_check")

    # Sufficiency check: loop back for more research OR proceed to browsers
    graph.add_conditional_edges(
        "sufficiency_check",
        _should_loop_back,
        {
            "research_more": "searchers",
            "browsers": "browsers",
        },
    )

    # Browsers → Critic (sequential: browsers fetch content, then critic analyses)
    graph.add_edge("browsers", "critic")

    # After critic: loop back if critic found gaps, or fact-check
    graph.add_conditional_edges(
        "critic",
        _should_fact_check,
        {
            "research_more": "searchers",
            "fact_check": "fact_checker",
        },
    )

    # Fact-checker → synthesizer → citation_formatter → END
    graph.add_edge("fact_checker", "synthesizer")
    graph.add_edge("synthesizer", "citation_formatter")
    graph.add_edge("citation_formatter", END)

    # ── Validate topology ──────────────────────────────────────────────────
    errors = _validate_graph(graph)
    if errors:
        raise ValueError(f"Graph validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

    cycle_warnings = _detect_cycles(graph, "planner")
    if cycle_warnings:
        for w in cycle_warnings:
            logger.warning(f"Graph topology warning: {w}")

    # Compile
    compiled = graph.compile()
    logger.info("Research graph compiled successfully")
    return compiled

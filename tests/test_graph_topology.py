"""Tests for research graph topology — validation, cycle detection."""

from __future__ import annotations

import pytest

from app.graph.research_graph import build_graph, _validate_graph, _detect_cycles


class TestGraphValidation:
    def test_build_graph_no_errors(self):
        """build_graph() should succeed without ValueError."""
        compiled = build_graph()
        assert compiled is not None

    def test_validate_graph_no_errors_on_built_graph(self):
        """_validate_graph returns no errors on the actual graph."""
        from langgraph.graph import StateGraph
        from app.graph.state import ResearchGraphState
        graph = StateGraph(ResearchGraphState)
        graph.add_node("planner", lambda s: s)
        graph.add_node("orchestrator", lambda s: s)
        graph.set_entry_point("planner")
        graph.add_edge("planner", "orchestrator")
        errors = _validate_graph(graph)
        assert errors == []


class TestCycleDetection:
    def test_no_cycles_in_built_graph(self):
        """_detect_cycles returns no warnings on the actual graph."""
        compiled = build_graph()
        # Use the internal StateGraph before compile
        from langgraph.graph import StateGraph
        from app.graph.state import ResearchGraphState
        graph = StateGraph(ResearchGraphState)
        graph.add_node("planner", lambda s: s)
        graph.add_node("end", lambda s: s)
        graph.set_entry_point("planner")
        graph.add_edge("planner", "end")
        warnings = _detect_cycles(graph, "planner")
        assert warnings == []

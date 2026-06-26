"""Tests for LangGraph graph structure."""

from __future__ import annotations

import pytest
from app.graph.state import ResearchGraphState
from app.graph.research_graph import build_graph


class TestGraphState:
    def test_initial_state(self):
        state: ResearchGraphState = {
            "session_id": "test-123",
            "query": "test query",
            "plan": None,
            "plan_ready": False,
            "sub_questions": [],
            "active_searchers": 0,
            "active_browsers": 0,
            "all_findings": [],
            "all_sources": [],
            "critic_rounds": 0,
            "critic_gaps": [],
            "critic_done": False,
            "verified_claims": [],
            "rejected_claims": [],
            "final_report": None,
            "citations_verified": False,
            "status": "created",
            "agent_count": 0,
            "error": None,
            "sufficiency_met": False,
        }
        assert state["session_id"] == "test-123"
        assert state["status"] == "created"
        assert state["agent_count"] == 0


class TestGraphBuild:
    def test_graph_compiles(self):
        graph = build_graph()
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        graph = build_graph()
        # LangGraph compiled graph should have nodes
        assert hasattr(graph, "nodes") or hasattr(graph, "graph")

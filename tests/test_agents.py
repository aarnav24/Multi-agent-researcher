"""Tests for agent layer."""

from __future__ import annotations

import pytest
from backend.agents.base import BaseAgent, get_llm
from backend.agents.searcher_agent import SearcherAgent
from backend.agents.planner_agent import PlannerAgent
from backend.agents.critic_agent import CriticAgent
from backend.agents.synthesizer_agent import SynthesizerAgent


class TestBaseAgent:
    def test_base_agent_creation(self):
        agent = BaseAgent()
        assert agent.model_tier == "fast"

    def test_searcher_uses_fast_tier(self):
        agent = SearcherAgent()
        assert agent.model_tier == "fast"

    def test_planner_uses_reasoning_tier(self):
        agent = PlannerAgent()
        assert agent.model_tier == "reasoning"

    def test_critic_uses_reasoning_tier(self):
        agent = CriticAgent()
        assert agent.model_tier == "reasoning"

    def test_synthesizer_uses_reasoning_tier(self):
        agent = SynthesizerAgent()
        assert agent.model_tier == "reasoning"


class TestGetLlm:
    def test_returns_chat_openai(self):
        try:
            llm = get_llm("anthropic/claude-haiku-4.5")
            assert llm is not None
        except RuntimeError:
            pytest.skip("No OpenRouter keys configured")

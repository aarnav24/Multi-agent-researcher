"""Tests for BaseAgent — timeout, fallback, retry in run_with_messages."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.base import BaseAgent, _get_fallback_models, DEFAULT_LLM_TIMEOUT


class ConcreteAgent(BaseAgent):
    """Concrete agent for testing."""
    model_tier = "fast"
    system_prompt = "Test prompt"


class TestFallbackModels:
    def test_returns_tuple(self):
        """_get_fallback_models returns a tuple (immutable)."""
        result = _get_fallback_models("primary-model", "fast")
        assert isinstance(result, tuple)
        assert result[0] == "primary-model"

    def test_excludes_primary_from_fallbacks(self):
        """Primary model appears only once (at the start)."""
        result = _get_fallback_models("primary-model", "fast")
        assert result.count("primary-model") == 1

    def test_reasoning_tier_uses_reasoning_fallbacks(self):
        """Reasoning tier uses _REASONING_FALLBACKS."""
        result = _get_fallback_models("gemini-3.5-flash", "reasoning")
        assert "openai/gpt-oss-120b:free" in result


class TestAgentRun:
    @pytest.mark.asyncio
    async def test_timeout_raises_after_elapsed(self):
        """run() raises TimeoutError if all model attempts exceed timeout."""
        agent = ConcreteAgent()

        # Mock the LLM to hang
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=lambda *a, **kw: asyncio.sleep(100))
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        with patch("app.agents.base.get_llm", return_value=(mock_llm, 0)):
            with pytest.raises((TimeoutError, RuntimeError)):
                await agent.run("test", timeout=0.1)

    @pytest.mark.asyncio
    async def test_fallback_on_rate_limit(self):
        """run() falls back to next model on 429."""
        agent = ConcreteAgent()

        # First model raises 429, second succeeds
        mock_llm_1 = AsyncMock()
        mock_llm_1.ainvoke = AsyncMock(side_effect=Exception("429 rate limit"))

        mock_llm_2 = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "success"
        mock_llm_2.ainvoke = AsyncMock(return_value=mock_response)

        call_count = 0
        def mock_get_llm(model, return_key_idx=False):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return (mock_llm_1, 0) if return_key_idx else mock_llm_1
            return (mock_llm_2, 1) if return_key_idx else mock_llm_2

        with patch("app.agents.base.get_llm", side_effect=mock_get_llm):
            with patch("app.agents.base._get_fallback_models", return_value=("model-1", "model-2")):
                result = await agent.run("test", timeout=10.0)
                assert result == "success"

    @pytest.mark.asyncio
    async def test_all_models_fail_raises_runtime_error(self):
        """run() raises RuntimeError if all models fail."""
        agent = ConcreteAgent()

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("Some error"))

        with patch("app.agents.base.get_llm", return_value=(mock_llm, 0)), \
             patch("app.agents.base._get_fallback_models", return_value=("model-1",)):
            with pytest.raises(RuntimeError, match="All LLM attempts failed"):
                await agent.run("test", timeout=1.0)


class TestRunWithMessages:
    @pytest.mark.asyncio
    async def test_run_with_messages_retries(self):
        """run_with_messages uses retry + fallback logic."""
        agent = ConcreteAgent()
        messages = [SystemMessage(content="test"), HumanMessage(content="hello")]

        mock_response = MagicMock()
        mock_response.content = "response"
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        with patch("app.agents.base.get_llm", return_value=(mock_llm, 0)):
            result = await agent.run_with_messages(messages, timeout=10.0)
            assert result == "response"

    @pytest.mark.asyncio
    async def test_run_with_messages_timeout(self):
        """run_with_messages respects timeout."""
        agent = ConcreteAgent()
        messages = [SystemMessage(content="test"), HumanMessage(content="hello")]

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=lambda *a, **kw: asyncio.sleep(100))

        with patch("app.agents.base.get_llm", return_value=(mock_llm, 0)):
            with pytest.raises((TimeoutError, RuntimeError)):
                await agent.run_with_messages(messages, timeout=0.1)

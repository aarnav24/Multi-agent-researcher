"""Tests for SearcherAgent — circuit breaker, timeout, DDG fallback."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agents.searcher_agent import (
    SearcherAgent,
    ToolCircuitBreaker,
    _call_tool_rate_limited,
    _circuit_breaker,
)


class TestToolCircuitBreaker:
    def test_opens_after_threshold(self):
        cb = ToolCircuitBreaker(threshold=3)
        assert not cb.is_open("tavily")
        cb.record_failure("tavily")
        cb.record_failure("tavily")
        assert not cb.is_open("tavily")
        cb.record_failure("tavily")
        assert cb.is_open("tavily")

    def test_resets_on_success(self):
        cb = ToolCircuitBreaker(threshold=3)
        cb.record_failure("tavily")
        cb.record_failure("tavily")
        cb.record_success("tavily")
        cb.record_failure("tavily")
        cb.record_failure("tavily")
        # Should not be open: only 2 consecutive failures after reset
        assert not cb.is_open("tavily")

    def test_per_tool_isolation(self):
        cb = ToolCircuitBreaker(threshold=2)
        cb.record_failure("tavily")
        cb.record_failure("tavily")
        assert cb.is_open("tavily")
        assert not cb.is_open("exa")  # Other tool unaffected


class TestCallToolRateLimited:
    @pytest.mark.asyncio
    async def test_circuit_breaker_skips_open_tool(self):
        """If circuit breaker is open, tool returns empty list immediately."""
        # Open the circuit breaker for this test
        original_failures = _circuit_breaker.failures.copy()
        _circuit_breaker.failures["test_tool"] = 999
        try:
            result = await _call_tool_rate_limited("test_tool", AsyncMock(), "query", 5, {"count": 0})
            assert result == []
        finally:
            _circuit_breaker.failures = original_failures

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self):
        """If tool times out, returns empty list and records failure."""
        async def slow_tool(*args, **kwargs):
            await asyncio.sleep(100)
            return []

        # Temporarily reduce timeout
        import backend.agents.searcher_agent as sa_module
        original_timeout = sa_module._TOOL_TIMEOUT
        sa_module._TOOL_TIMEOUT = 0.1
        original_failures = _circuit_breaker.failures.copy()
        try:
            result = await _call_tool_rate_limited("test_tool", slow_tool, "query", 5, {"count": 0})
            assert result == []
            assert _circuit_breaker.failures.get("test_tool", 0) >= 1
        finally:
            sa_module._TOOL_TIMEOUT = original_timeout
            _circuit_breaker.failures = original_failures


class TestSearcherAgentSearch:
    @pytest.mark.asyncio
    async def test_ddg_fallback_when_primary_empty(self, caplog):
        """DDG fallback runs when primary tools return no results."""
        from backend.agents.searcher_agent import TOOL_MAP

        agent = SearcherAgent()

        # Mock all primary tools to return empty
        async def empty_search(*args, **kwargs):
            return []

        # Mock DDG to return results
        mock_ddg_result = MagicMock()
        mock_ddg_result.model_dump.return_value = {
            "url": "https://example.com", "title": "Test",
            "snippet": "Test snippet", "tool_name": "ddg",
        }
        mock_ddg = AsyncMock(return_value=[mock_ddg_result])

        # Patch the TOOL_MAP directly (since it's built at import time)
        original_tavily = TOOL_MAP["tavily"]
        original_exa = TOOL_MAP["exa"]
        original_ddg = TOOL_MAP["ddg"]
        TOOL_MAP["tavily"] = empty_search
        TOOL_MAP["exa"] = empty_search
        TOOL_MAP["ddg"] = mock_ddg
        try:
            with patch.object(agent, "run", AsyncMock(return_value='{"summary": "test", "key_facts": [], "confidence": "low"}')):
                result = await agent.search("test question", tools=["tavily", "exa", "ddg"])
                assert result["confidence"] == "low"
                # DDG should have been called
                assert mock_ddg.called
        finally:
            # Restore original tools
            TOOL_MAP["tavily"] = original_tavily
            TOOL_MAP["exa"] = original_exa
            TOOL_MAP["ddg"] = original_ddg

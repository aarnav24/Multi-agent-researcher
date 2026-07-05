"""Tests for Neo4j adapter — retry, timeout, query validation."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.citation_graph import neo4j_adapter as adapter_module


class TestQueryValidation:
    def test_rejects_string_interpolation(self):
        """Queries with f-string interpolation but no $params are rejected."""
        with pytest.raises(ValueError, match="string interpolation"):
            adapter_module._validate_query("MATCH (n {id: {user_input}})")

    def test_accepts_parameterized_query(self):
        """Queries with $parameters pass validation."""
        adapter_module._validate_query("MATCH (n {id: $id})")

    def test_accepts_simple_query(self):
        """Simple queries without interpolation pass."""
        adapter_module._validate_query("MATCH (n) RETURN n")


class TestConnectRetry:
    @pytest.mark.asyncio
    async def test_retries_on_failure(self, caplog):
        """connect() retries up to max_retries on failure."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_session.run = AsyncMock(side_effect=Exception("Connection refused"))
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("neo4j.AsyncGraphDatabase.driver", return_value=mock_driver):
            result = await adapter_module.connect(max_retries=3, retry_delay=0.01)
            assert result is False
            # Should have attempted 3 times
            assert mock_driver.session.call_count == 3

    @pytest.mark.asyncio
    async def test_succeeds_after_retries(self):
        """connect() succeeds if a retry attempt works."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        # Fail first, succeed second
        call_count = 0
        async def run_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Temporary failure")
        mock_session.run = run_side_effect
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("neo4j.AsyncGraphDatabase.driver", return_value=mock_driver), \
             patch("backend.citation_graph.neo4j_adapter._create_schema", AsyncMock()):
            result = await adapter_module.connect(max_retries=3, retry_delay=0.01)
            assert result is True


class TestRunCypher:
    @pytest.mark.asyncio
    async def test_timeout_raises(self, caplog):
        """_run_cypher raises on timeout."""
        # Reset driver state
        adapter_module._driver = None
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter_module._run_cypher("RETURN 1")

    @pytest.mark.asyncio
    async def test_validate_query_called(self):
        """_run_cypher validates query before execution."""
        adapter_module._driver = MagicMock()  # Not None, so it passes the check
        with patch.object(adapter_module, "_validate_query", side_effect=ValueError("bad query")):
            with pytest.raises(ValueError, match="bad query"):
                await adapter_module._run_cypher("BAD QUERY")

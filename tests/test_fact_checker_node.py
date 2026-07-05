"""Tests for fact_checker_node — validation, timeout, circuit breaker."""

from __future__ import annotations

import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.graph.nodes.fact_checker import (
    _validate_fact_check_result,
    _verify_single_claim,
    fact_checker_node,
    CIRCUIT_BREAKER_THRESHOLD,
)


class TestValidateFactCheckResult:
    def test_valid_result_passes(self):
        result = {
            "claim": "Earth is round",
            "verified": True,
            "trust_score": 85,
            "supporting_count": 3,
            "reasoning": "Multiple sources confirm",
        }
        validated = _validate_fact_check_result(result, "Earth is round")
        assert validated is not None
        assert validated["trust_score"] == 85

    def test_missing_field_returns_none(self):
        result = {"claim": "test", "verified": True}  # missing trust_score
        assert _validate_fact_check_result(result, "test") is None

    def test_wrong_type_returns_none(self):
        result = {
            "claim": "test",
            "verified": "not-a-bool",  # wrong type
            "trust_score": 50,
            "supporting_count": 1,
            "reasoning": "",
        }
        assert _validate_fact_check_result(result, "test") is None

    def test_not_dict_returns_none(self):
        assert _validate_fact_check_result("not a dict", "test") is None


class TestVerifySingleClaim:
    @pytest.mark.asyncio
    async def test_timeout_returns_fallback(self):
        """If verify_claim hangs, timeout returns a fallback result."""
        with patch("backend.graph.nodes.fact_checker.FactCheckerAgent") as MockAgent:
            mock_instance = MockAgent.return_value
            # Make verify_claim hang
            async def slow_claim(*args, **kwargs):
                await asyncio.sleep(100)
                return {"claim": "test"}
            mock_instance.verify_claim = slow_claim

            # Override timeout for faster test
            import backend.graph.nodes.fact_checker as fc_module
            original_timeout = fc_module.CLAIM_TIMEOUT
            fc_module.CLAIM_TIMEOUT = 0.1
            try:
                result, sources = await _verify_single_claim("test claim")
                assert result["verified"] is False
                assert "Timeout" in result["reasoning"]
            finally:
                fc_module.CLAIM_TIMEOUT = original_timeout


class TestFactCheckerNode:
    @pytest.mark.asyncio
    async def test_no_claims_returns_empty(self, caplog):
        """When no claims extracted, returns empty lists."""
        state = {
            "session_id": "test-1",
            "all_findings": [],
            "all_sources": [],
        }
        result = await fact_checker_node(state)
        assert result["verified_claims"] == []
        assert result["rejected_claims"] == []

    @pytest.mark.asyncio
    async def test_circuit_breaker_trips_after_threshold(self, caplog):
        """After CIRCUIT_BREAKER_THRESHOLD consecutive failures, remaining claims are rejected."""
        # Each key_facts item must be > 10 chars to pass the filter
        facts = [f"this is fact number {i} with enough length" for i in range(CIRCUIT_BREAKER_THRESHOLD + 3)]
        state = {
            "session_id": "test-1",
            "all_findings": [
                {"key_facts": facts},
            ],
            "all_sources": [],
            "browser_facts": [],
        }
        with patch("backend.graph.nodes.fact_checker.FactCheckerAgent") as MockAgent:
            mock_instance = MockAgent.return_value
            mock_instance.verify_claim = AsyncMock(side_effect=Exception("LLM failed"))

            result = await fact_checker_node(state)
            # CIRCUIT_BREAKER_THRESHOLD failures should cause remaining claims to be rejected
            assert len(result["rejected_claims"]) > 0
            assert any(r["reason"] == "circuit_breaker" for r in result["rejected_claims"])

    @pytest.mark.asyncio
    async def test_malformed_result_goes_to_rejected(self, caplog):
        """Fact-check results missing required fields go to rejected."""
        state = {
            "session_id": "test-1",
            "all_findings": [{"key_facts": ["some claim that is long enough"]}],
            "all_sources": [],
            "browser_facts": [],
        }
        with patch("backend.graph.nodes.fact_checker.FactCheckerAgent") as MockAgent, \
             patch("backend.graph.nodes.fact_checker.compute_trust_score", return_value=50):
            mock_instance = MockAgent.return_value
            mock_instance.verify_claim = AsyncMock(return_value={"claim": "incomplete"})  # missing fields

            result = await fact_checker_node(state)
            assert any(r["reason"] == "malformed_fact_check_result" for r in result["rejected_claims"])

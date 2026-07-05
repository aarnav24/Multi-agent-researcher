"""Tests for StateStore — field coercion, atomic writes, replay."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.state.store import StateStore
from backend.state.models import ResearchSession


@pytest.fixture
def store():
    """Create a StateStore in in-memory mode (no Redis/Postgres)."""
    s = StateStore()
    s._connected = True
    return s


@pytest.mark.asyncio
async def test_create_and_get_session(store):
    """Round-trip: create session, then retrieve it."""
    session = await store.create_session("test-1", "What is quantum computing?")
    assert session.session_id == "test-1"
    assert session.query == "What is quantum computing?"

    retrieved = await store.get_session("test-1")
    assert retrieved is not None
    assert retrieved.session_id == "test-1"
    assert retrieved.query == "What is quantum computing?"


@pytest.mark.asyncio
async def test_write_slot_prefix_validation(store):
    """write_slot raises ValueError if slot doesn't match worker_id prefix."""
    with pytest.raises(ValueError, match="does not belong to worker"):
        await store.write_slot("test-1", "worker:other:results", {"data": 1}, agent="searcher", worker_id="my-worker")


@pytest.mark.asyncio
async def test_write_slot_valid_prefix(store):
    """write_slot succeeds with correct prefix."""
    await store.write_slot("test-1", "worker:my-worker:results", {"key": "value"}, agent="searcher", worker_id="my-worker")
    result = await store.read_slot("test-1", "worker:my-worker:results")
    assert result == {"key": "value"}


@pytest.mark.asyncio
async def test_write_global_updates_snapshot(store):
    """write_global updates the session snapshot."""
    await store.create_session("test-1", "query")
    await store.write_global("test-1", "status", "researching", agent="orchestrator")

    session = await store.get_session("test-1")
    assert session is not None
    assert session.status == "researching"


@pytest.mark.asyncio
async def test_write_global_coerces_claims(store):
    """write_global with key='claims' coerces verified/rejected lists."""
    await store.create_session("test-1", "query")
    await store.write_global("test-1", "claims", {
        "verified": [{"claim": "Earth is round", "trust_score": 95}],
        "rejected": [{"claim": "Earth is flat", "reason": "wrong"}],
    }, agent="fact_checker")

    session = await store.get_session("test-1")
    assert session is not None
    assert len(session.verified_claims) == 1
    assert session.verified_claims[0].claim == "Earth is round"
    assert len(session.rejected_claims) == 1


@pytest.mark.asyncio
async def test_replay_from_replays_global_writes(store):
    """replay_from reconstructs state from audit log."""
    await store.create_session("test-1", "query")
    await store.write_global("test-1", "status", "researching", agent="orchestrator")
    await store.write_global("test-1", "agent_count", 5, agent="orchestrator")

    # Replay from beginning — session is in memory (snapshot)
    session = await store.replay_from("test-1", from_seq=0)
    assert session is not None
    assert session.status == "researching"
    assert session.agent_count == 5


@pytest.mark.asyncio
async def test_replay_from_replays_slot_writes(store):
    """replay_from reconstructs slot data from audit log."""
    await store.create_session("test-1", "query")
    await store.write_slot("test-1", "worker:searcher-0:results", {"summary": "test"}, agent="searcher", worker_id="searcher-0")

    # Clear memory
    store._memory_slots.clear()

    # Replay
    await store.replay_from("test-1", from_seq=0)
    key = "session:test-1:worker:searcher-0:results"
    assert store._memory_slots.get(key) == {"summary": "test"}


@pytest.mark.asyncio
async def test_set_session_field_unknown_key_logs_warning(store, caplog):
    """Setting an unknown field logs a warning."""
    session = ResearchSession(session_id="test-1", query="test")
    store._set_session_field(session, "nonexistent_field", "value")
    assert "unknown session field" in caplog.text


@pytest.mark.asyncio
async def test_write_global_report_alias(store):
    """write_global with key='report' sets final_report."""
    await store.create_session("test-1", "query")
    await store.write_global("test-1", "report", "Final report content", agent="synthesizer")

    session = await store.get_session("test-1")
    assert session is not None
    assert session.final_report == "Final report content"

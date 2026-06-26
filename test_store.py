"""Unit tests for StateStore - verifies Layer A shared memory architecture.

Tests:
1. Session CRUD (create, read, update)
2. Slot-based write isolation (worker writes to own slot only)
3. Global writes (orchestrator writes to session snapshot)
4. Audit log (every write generates an entry)
5. replay_from() (crash recovery from audit log)
6. Concurrent write safety (per-session lock)
"""

import asyncio
import io
import logging
import sys

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from app.state.store import StateStore


async def test_basic_crud():
    """Test 1: Session creation and retrieval."""
    store = StateStore()
    await store.connect()

    session = await store.create_session("test-crud", "What is quantum computing?")
    assert session.session_id == "test-crud"
    assert session.query == "What is quantum computing?"
    assert session.status == "created"

    # Read back from memory
    retrieved = await store.get_session("test-crud")
    assert retrieved is not None
    assert retrieved.session_id == "test-crud"

    # Read back from Redis (if available)
    if store._use_redis:
        raw = await store._redis.get("session:test-crud")
        assert raw is not None
        print("  ✅ Test 1: Basic CRUD works (memory + Redis)")

    await store.disconnect()


async def test_slot_isolation():
    """Test 2: Workers can only write to their own slot."""
    store = StateStore()
    await store.connect()
    await store.create_session("test-slots", "test query")

    # Worker-0 writes to its own slot — should succeed
    await store.write_slot("test-slots", "worker:worker-0:results", {"finding": "result1"}, agent="searcher", worker_id="worker-0")
    data = await store.read_slot("test-slots", "worker:worker-0:results")
    assert data is not None
    assert data["finding"] == "result1"

    # Worker-0 tries to write to worker-1's slot — should fail
    try:
        await store.write_slot("test-slots", "worker:worker-1:results", {"finding": "hacked"}, agent="searcher", worker_id="worker-0")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "does not belong" in str(e)
        print("  ✅ Test 2: Slot isolation enforced (cross-slot write rejected)")

    await store.disconnect()


async def test_global_write_updates_snapshot():
    """Test 3: Global writes update the session snapshot."""
    store = StateStore()
    await store.connect()
    await store.create_session("test-global", "test query")

    # Orchestrator writes sub-questions
    sub_questions = [
        {"id": "sq1", "question": "What is X?", "status": "pending"},
        {"id": "sq2", "question": "What is Y?", "status": "pending"},
    ]
    await store.write_global("test-global", "sub_questions", sub_questions, agent="orchestrator")

    # Read back — snapshot should be updated
    session = await store.get_session("test-global")
    assert session is not None
    assert len(session.sub_questions) == 2
    assert session.sub_questions[0].question == "What is X?"

    # Write findings
    findings = [{"question": "What is X?", "summary": "X is a thing", "sub_question_id": "sq1"}]
    await store.write_global("test-global", "findings", findings, agent="orchestrator")

    session = await store.get_session("test-global")
    assert len(session.findings) == 1
    print("  ✅ Test 3: Global writes update session snapshot correctly")

    await store.disconnect()


async def test_audit_log():
    """Test 4: Every write generates an audit entry."""
    store = StateStore()
    await store.connect()
    await store.create_session("test-audit", "test query")

    await store.write_global("test-audit", "status", "researching", agent="orchestrator")
    await store.write_global("test-audit", "findings", [{"q": "test"}], agent="orchestrator")
    await store.write_slot("test-audit", "worker:searcher-0:results", {"data": 1}, agent="searcher", worker_id="searcher-0")

    audit = await store.get_audit_log("test-audit")
    # 1 (session_created) + 1 (status) + 1 (findings) + 1 (slot) = 4
    assert len(audit) == 4, f"Expected 4 audit entries, got {len(audit)}"
    assert audit[0].event_type == "session_created"
    assert audit[1].event_type == "global_write:status"
    assert audit[3].event_type == "slot_write:worker:searcher-0:results"
    print("  ✅ Test 4: Audit log captures every write (4 entries)")

    await store.disconnect()


async def test_replay():
    """Test 5: replay_from() reconstructs state from audit log."""
    store = StateStore()
    await store.connect()
    await store.create_session("test-replay", "test query")

    # Simulate a sequence of writes
    await store.write_global("test-replay", "status", "researching", agent="orchestrator")
    await store.write_global("test-replay", "findings", [{"q": "A"}], agent="orchestrator")
    await store.write_global("test-replay", "status", "done", agent="orchestrator")

    # Replay from seq 1 (skip session_created)
    session = await store.replay_from("test-replay", from_seq=1)
    assert session is not None
    # After replay: status should be "done" (last write), findings should be [{"q": "A"}]
    assert session.status == "done"
    assert len(session.findings) == 1
    print("  ✅ Test 5: replay_from() correctly reconstructs state from audit log")

    await store.disconnect()


async def test_concurrent_writes():
    """Test 6: Concurrent writes don't corrupt the session snapshot."""
    store = StateStore()
    await store.connect()
    await store.create_session("test-concurrent", "test query")

    # Launch 5 concurrent global writes to different keys
    async def write_field(key: str, value: str):
        await store.write_global("test-concurrent", key, value, agent="test")

    await asyncio.gather(
        write_field("status", "researching"),
        write_field("agent_count", 5),
        write_field("searcher_rounds", 1),
    )

    # All writes should be visible in the final snapshot
    session = await store.get_session("test-concurrent")
    assert session is not None
    assert session.status == "researching"
    assert session.agent_count == 5
    assert session.searcher_rounds == 1
    print("  ✅ Test 6: Concurrent writes are safe (per-session lock works)")

    await store.disconnect()


async def main():
    print("=" * 60)
    print("STATE STORE UNIT TESTS — Layer A Shared Memory Architecture")
    print("=" * 60)

    tests = [
        ("Basic CRUD", test_basic_crud),
        ("Slot Isolation", test_slot_isolation),
        ("Global Write Updates Snapshot", test_global_write_updates_snapshot),
        ("Audit Log", test_audit_log),
        ("Replay from Audit Log", test_replay),
        ("Concurrent Write Safety", test_concurrent_writes),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"\n{name}:")
        try:
            await test_fn()
            passed += 1
        except Exception as e:
            print(f"  ❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

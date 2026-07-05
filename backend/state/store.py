"""State store — shared memory layer for all agents in a research session.

Architecture (Layer A — Shared Memory Store):
  - Redis: hot state, sub-ms reads, full session snapshot + per-key slots
  - Postgres: audit log (every write), crash recovery snapshot
  - In-memory: fallback when Redis/Postgres unavailable

Write isolation:
  - Workers write only to their assigned slot (worker:{id}:*)
  - Orchestrator is the only agent that writes globally (session:{sid}:*)
  - Every write generates an audit entry in Postgres

Key schema:
  session:{sid}            → full ResearchSession JSON (snapshot)
  session:{sid}:plan       → plan sub-state
  session:{sid}:sub_questions → sub-questions sub-state
  session:{sid}:findings   → accumulated findings
  session:{sid}:sources    → accumulated sources
  session:{sid}:claims     → verified/rejected claims
  session:{sid}:report     → final report
  worker:{wid}:results     → per-worker slot (write isolation)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from backend.config import settings
from backend.state.models import AuditEntry, ResearchSession

logger = logging.getLogger(__name__)


class StateStore:
    """Shared memory store with Redis (hot) + Postgres (persistent) + in-memory fallback.

    Slot-based write isolation:
    - write_slot(session_id, slot, data, worker_id) — slot must start with worker:{worker_id}:
    - write_global(session_id, key, data, agent) — any key (intended for Orchestrator)

    Every write_global call updates the in-memory session snapshot AND persists
    it to all backends (memory → Redis → Postgres) in one shot.
    """

    # ── Field coercion registry ────────────────────────────────────────────
    # Maps session keys to coercion functions. Unknown keys fall back to
    # setattr; ValidationError is raised (not silently swallowed).

    @staticmethod
    def _coerce_claims(session: ResearchSession, data: Any) -> None:
        from backend.state.models import VerifiedClaim, RejectedClaim
        if isinstance(data, dict):
            if "verified" in data:
                session.verified_claims = [
                    VerifiedClaim(**c) if isinstance(c, dict) else c
                    for c in data["verified"]
                ]
            if "rejected" in data:
                session.rejected_claims = [
                    RejectedClaim(**c) if isinstance(c, dict) else c
                    for c in data["rejected"]
                ]

    @staticmethod
    def _coerce_sub_questions(session: ResearchSession, data: Any) -> None:
        from backend.state.models import SubQuestion
        if isinstance(data, list):
            session.sub_questions = [
                SubQuestion(**sq) if isinstance(sq, dict) else sq
                for sq in data
            ]

    @staticmethod
    def _coerce_report(session: ResearchSession, data: Any) -> None:
        session.final_report = data if isinstance(data, str) else str(data)

    @staticmethod
    def _coerce_critic_gaps(session: ResearchSession, data: Any) -> None:
        session.critic_followups = data if isinstance(data, list) else []

    @staticmethod
    def _coerce_plan(session: ResearchSession, data: Any) -> None:
        from backend.state.models import ResearchPlan
        if isinstance(data, dict):
            session.plan = ResearchPlan(**data)
        elif data is None:
            session.plan = None

    @staticmethod
    def _coerce_verified_claims(session: ResearchSession, data: Any) -> None:
        from backend.state.models import VerifiedClaim
        if isinstance(data, list):
            session.verified_claims = [
                VerifiedClaim(**c) if isinstance(c, dict) else c
                for c in data
            ]

    @staticmethod
    def _coerce_rejected_claims(session: ResearchSession, data: Any) -> None:
        from backend.state.models import RejectedClaim
        if isinstance(data, list):
            session.rejected_claims = [
                RejectedClaim(**c) if isinstance(c, dict) else c
                for c in data
            ]

    _FIELD_COERCION: dict = {
        "claims": _coerce_claims.__func__,
        "sub_questions": _coerce_sub_questions.__func__,
        "report": _coerce_report.__func__,
        "critic_gaps": _coerce_critic_gaps.__func__,
        "plan": _coerce_plan.__func__,
        "verified_claims": _coerce_verified_claims.__func__,
        "rejected_claims": _coerce_rejected_claims.__func__,
    }

    def __init__(self):
        self._redis = None
        self._pg = None
        self._neo4j: "Neo4jAdapter | None" = None
        self._citation_graphs: dict[str, "CitationGraph"] = {}  # session_id → graph
        self._memory_sessions: dict[str, ResearchSession] = {}
        self._memory_slots: dict[str, Any] = {}  # key -> data
        self._audit_log: list[AuditEntry] = []
        self._audit_seq: dict[str, int] = {}  # session_id -> last seq
        self._use_redis = False
        self._connected = False
        self._locks: dict[str, asyncio.Lock] = {}  # session_id -> lock (prevents concurrent write races)

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def connect(self):
        """Try Redis + Postgres, fall back to in-memory if unavailable."""
        try:
            import redis.asyncio as redis
            self._redis = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                max_connections=settings.redis_max_connections,
                protocol=2,  # Use RESP2 for Redis 7 compatibility
            )
            await self._redis.ping()
            self._use_redis = True
            logger.info("StateStore: Redis connected")
        except Exception as e:
            logger.warning(f"StateStore: Redis unavailable ({e}), using in-memory")
            self._redis = None
            self._use_redis = False

        if self._use_redis:
            try:
                import asyncpg
                self._pg = await asyncpg.create_pool(
                    dsn=settings.database_url.replace("+asyncpg", ""),
                    min_size=settings.postgres_min_pool,
                    max_size=settings.postgres_max_pool,
                )
                async with self._pg.acquire() as conn:
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS research_sessions (
                            session_id  TEXT PRIMARY KEY,
                            query       TEXT NOT NULL,
                            state       TEXT NOT NULL DEFAULT '{}',
                            status      TEXT NOT NULL DEFAULT 'created',
                            cost_usd    TEXT NOT NULL DEFAULT '0',
                            agent_count INTEGER NOT NULL DEFAULT 0,
                            created_at  TEXT NOT NULL,
                            updated_at  TEXT NOT NULL
                        )
                    """)
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS session_audit_log (
                            id          BIGSERIAL PRIMARY KEY,
                            session_id  TEXT NOT NULL,
                            seq         INTEGER NOT NULL,
                            event_type  TEXT NOT NULL,
                            agent       TEXT NOT NULL,
                            worker_id   TEXT,
                            payload     TEXT NOT NULL DEFAULT '{}',
                            created_at  TEXT NOT NULL
                        )
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_audit_session_seq
                        ON session_audit_log (session_id, seq)
                    """)
                    # Users table (authentication)
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS users (
                            id TEXT PRIMARY KEY,
                            username TEXT UNIQUE NOT NULL,
                            email TEXT UNIQUE,
                            password_hash TEXT NOT NULL,
                            name TEXT NOT NULL,
                            is_active BOOLEAN NOT NULL DEFAULT TRUE,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    # User API keys table
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS user_api_keys (
                            id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            provider TEXT NOT NULL,
                            api_key TEXT NOT NULL,
                            model_name TEXT NOT NULL DEFAULT '',
                            base_url TEXT NOT NULL DEFAULT '',
                            is_active BOOLEAN NOT NULL DEFAULT TRUE,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_user_api_keys_user_provider
                        ON user_api_keys (user_id, provider, is_active)
                    """)
                    # Daily research count tracking (for free tier rate limiting)
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS daily_research_counts (
                            user_id TEXT NOT NULL,
                            date DATE NOT NULL DEFAULT CURRENT_DATE,
                            count INTEGER NOT NULL DEFAULT 0,
                            PRIMARY KEY (user_id, date)
                        )
                    """)
                logger.info("StateStore: Postgres connected")
            except Exception as e:
                logger.warning(f"StateStore: Postgres unavailable ({e}), audit log disabled")
                self._pg = None

        # Neo4j (Layer C — Citation Graph)
        try:
            from backend.citation_graph.neo4j_adapter import Neo4jAdapter, connect as neo4j_connect
            self._neo4j = Neo4jAdapter(enabled=False)  # disabled until connected
            neo4j_ok = await neo4j_connect()
            if neo4j_ok:
                self._neo4j = Neo4jAdapter(enabled=True)
                logger.info("StateStore: Neo4j connected (citation graph enabled)")
            else:
                logger.info("StateStore: Neo4j unavailable (citation graph disabled)")
        except Exception as e:
            logger.info(f"StateStore: Neo4j unavailable ({e}), citation graph disabled")
            self._neo4j = Neo4jAdapter(enabled=False)

        if not self._use_redis and self._pg is None:
            logger.info("StateStore: running in-memory mode (no Redis, no Postgres)")

        self._connected = True

    async def disconnect(self):
        if self._redis:
            await self._redis.close()
        if self._pg:
            await self._pg.close()
        if self._neo4j and self._neo4j.enabled:
            from backend.citation_graph.neo4j_adapter import disconnect as neo4j_disconnect
            await neo4j_disconnect()
        self._connected = False

    # ── helpers ──────────────────────────────────────────────────────────────

    def _session_key(self, session_id: str) -> str:
        return f"session:{session_id}"

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create a per-session lock to prevent concurrent write races."""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    def _serialize_session(self, session: ResearchSession) -> str:
        return session.model_dump_json()

    def _deserialize_session(self, raw: str) -> ResearchSession:
        return ResearchSession.model_validate_json(raw)

    def _serialize_data(self, data: Any) -> str:
        if isinstance(data, str):
            return data
        return json.dumps(data, default=str)

    def _deserialize_data(self, raw: str) -> Any:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def _persist_session(self, session: ResearchSession) -> None:
        """Persist full session snapshot to all backends (memory + Redis + Postgres)."""
        session.updated_at = datetime.utcnow()
        raw = self._serialize_session(session)
        sid = session.session_id

        # Memory
        self._memory_sessions[sid] = session

        # Redis
        if self._use_redis:
            try:
                await self._redis.set(self._session_key(sid), raw)
            except Exception as e:
                logger.warning(f"StateStore: Redis session persist failed for {sid}: {e}")

        # Postgres
        if self._pg:
            try:
                now = datetime.utcnow().isoformat()
                async with self._pg.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO research_sessions (session_id, query, state, status, agent_count, created_at, updated_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)
                           ON CONFLICT (session_id) DO UPDATE SET
                               state=$3, status=$4, agent_count=$5, updated_at=$7""",
                        sid, session.query, raw, session.status,
                        session.agent_count,
                        session.created_at.isoformat(), now,
                    )
            except Exception as e:
                logger.warning(f"StateStore: Postgres session persist failed for {sid}: {e}")

    # ── session CRUD ────────────────────────────────────────────────────────

    async def create_session(self, session_id: str, query: str) -> ResearchSession:
        """Create a new research session."""
        session = ResearchSession(
            session_id=session_id,
            query=query,
            status="created",
        )
        await self._persist_session(session)
        await self._append_audit(session_id, "session_created", {"query": query}, agent="system")
        logger.info(f"StateStore: created session {session_id}")
        return session

    async def get(self, session_id: str) -> Optional[ResearchSession]:
        """Alias for get_session (used by routes.py)."""
        return await self.get_session(session_id)

    async def update(self, session: ResearchSession) -> None:
        """Alias for update_session (used by routes.py)."""
        await self.update_session(session)

    async def get_session(self, session_id: str) -> Optional[ResearchSession]:
        """Get session state. Tries memory → Redis → Postgres."""
        # Memory first (fastest)
        if session_id in self._memory_sessions:
            return self._memory_sessions[session_id]

        # Try Redis
        if self._use_redis:
            try:
                raw = await self._redis.get(self._session_key(session_id))
                if raw:
                    session = self._deserialize_session(raw)
                    self._memory_sessions[session_id] = session
                    return session
            except Exception as e:
                logger.warning(f"StateStore: Redis read failed for {session_id}: {e}")

        # Try Postgres
        if self._pg:
            try:
                async with self._pg.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT state FROM research_sessions WHERE session_id=$1", session_id
                    )
                if row:
                    session = ResearchSession.model_validate_json(row["state"])
                    self._memory_sessions[session_id] = session
                    return session
            except Exception as e:
                logger.warning(f"StateStore: Postgres read failed for {session_id}: {e}")

        return None

    async def update_session(self, session: ResearchSession) -> None:
        """Persist full session state to all backends."""
        await self._persist_session(session)

    # ── user API keys ────────────────────────────────────────────────────────

    async def get_user_keys(self, user_id: str, provider: str | None = None) -> list[dict]:
        """Get user's active API keys, optionally filtered by provider."""
        if not self._pg:
            return []
        try:
            async with self._pg.acquire() as conn:
                if provider:
                    rows = await conn.fetch(
                        "SELECT id, provider, api_key, model_name, base_url, is_active "
                        "FROM user_api_keys WHERE user_id=$1 AND provider=$2 AND is_active=TRUE "
                        "ORDER BY created_at",
                        user_id, provider,
                    )
                else:
                    rows = await conn.fetch(
                        "SELECT id, provider, api_key, model_name, base_url, is_active "
                        "FROM user_api_keys WHERE user_id=$1 AND is_active=TRUE "
                        "ORDER BY created_at",
                        user_id,
                    )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"StateStore: get_user_keys failed: {e}")
            return []

    async def add_user_key(self, user_id: str, provider: str, api_key: str,
                          model_name: str = "", base_url: str = "") -> str:
        """Add a new API key for a user. Returns the key ID."""
        if not self._pg:
            raise RuntimeError("Postgres not available")
        key_id = str(uuid.uuid4())
        async with self._pg.acquire() as conn:
            await conn.execute(
                "INSERT INTO user_api_keys (id, user_id, provider, api_key, model_name, base_url) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                key_id, user_id, provider, api_key, model_name, base_url,
            )
        return key_id

    async def delete_user_key(self, key_id: str, user_id: str) -> bool:
        """Deactivate a user's API key (soft delete)."""
        if not self._pg:
            return False
        async with self._pg.acquire() as conn:
            result = await conn.execute(
                "UPDATE user_api_keys SET is_active=FALSE WHERE id=$1 AND user_id=$2",
                key_id, user_id,
            )
            return result == "UPDATE 1"

    # ── user authentication ──────────────────────────────────────────────────

    async def create_user(self, username: str, email: str, password_hash: str, name: str) -> dict:
        """Create a new user. Returns user dict or raises on duplicate."""
        if not self._pg:
            raise RuntimeError("Postgres not available")
        user_id = str(uuid.uuid4())
        async with self._pg.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (id, username, email, password_hash, name) "
                "VALUES ($1, $2, $3, $4, $5)",
                user_id, username, email, password_hash, name,
            )
        return {"id": user_id, "username": username, "email": email, "name": name}

    async def get_user_by_username(self, username: str) -> dict | None:
        """Look up user by username."""
        if not self._pg:
            return None
        try:
            async with self._pg.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, username, email, password_hash, name, is_active "
                    "FROM users WHERE username=$1",
                    username,
                )
            return dict(row) if row else None
        except Exception as e:
            logger.warning(f"get_user_by_username failed: {e}")
            return None

    async def get_user_by_id(self, user_id: str) -> dict | None:
        """Look up user by ID."""
        if not self._pg:
            return None
        try:
            async with self._pg.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id, username, email, password_hash, name, is_active "
                    "FROM users WHERE id=$1",
                    user_id,
                )
            return dict(row) if row else None
        except Exception as e:
            logger.warning(f"get_user_by_id failed: {e}")
            return None

    async def verify_user_password(self, username: str, password: str) -> dict | None:
        """Verify username + password. Returns user dict on success, None on failure."""
        import bcrypt
        user = await self.get_user_by_username(username)
        if not user or not user.get("is_active"):
            return None
        stored_hash = user.get("password_hash", "")
        if bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
            return {"id": user["id"], "username": user["username"], "email": user.get("email"), "name": user["name"]}
        return None

    # ── slot-based writes (worker isolation) ─────────────────────────────────

    async def write_slot(
        self,
        session_id: str,
        slot: str,
        data: Any,
        agent: str,
        worker_id: Optional[str] = None,
    ) -> None:
        """Write data to a worker-specific slot. Slot must start with worker:{worker_id}:.

        Uses a per-session lock to prevent concurrent write races with write_global.
        Stores full data in audit payload for crash recovery replay.
        """
        if worker_id:
            expected_prefix = f"worker:{worker_id}:"
            if not slot.startswith(expected_prefix):
                raise ValueError(
                    f"Slot '{slot}' does not belong to worker '{worker_id}'. "
                    f"Slot must start with '{expected_prefix}'"
                )

        lock = self._get_session_lock(session_id)
        async with lock:
            key = f"session:{session_id}:{slot}"

            # Write to memory first
            self._memory_slots[key] = data

            # Write to Redis
            if self._use_redis:
                try:
                    serialized = self._serialize_data(data)
                    await self._redis.set(key, serialized)
                except Exception as e:
                    logger.warning(f"StateStore: Redis slot write failed for {key}: {e}")

            # Audit — store full data for crash recovery replay
            await self._append_audit(
                session_id,
                f"slot_write:{slot}",
                {"slot": slot, "data": data, "data_preview": str(data)[:200]},
                agent=agent,
                worker_id=worker_id,
            )

    async def read_slot(self, session_id: str, slot: str) -> Optional[Any]:
        """Read data from a slot."""
        key = f"session:{session_id}:{slot}"

        if key in self._memory_slots:
            return self._memory_slots[key]

        if self._use_redis:
            try:
                raw = await self._redis.get(key)
                if raw:
                    return self._deserialize_data(raw)
            except Exception as e:
                logger.warning(f"StateStore: Redis slot read failed for {key}: {e}")

        return None

    # ── global writes (orchestrator only) ────────────────────────────────────

    async def write_global(
        self,
        session_id: str,
        key: str,
        data: Any,
        agent: str,
    ) -> None:
        """Write data to a global session key.

        Updates the in-memory session snapshot by setting the named field,
        then persists the full snapshot to all backends.
        Uses a per-session lock to prevent concurrent write races.
        """
        lock = self._get_session_lock(session_id)
        async with lock:
            full_key = f"session:{session_id}:{key}"

            # Write to memory slot
            self._memory_slots[full_key] = data

            # Update the session snapshot in memory
            session = self._memory_sessions.get(session_id)
            if session:
                self._set_session_field(session, key, data)
                # Persist updated snapshot to all backends
                await self._persist_session(session)

            # Write slot to Redis
            if self._use_redis:
                try:
                    serialized = self._serialize_data(data)
                    await self._redis.set(full_key, serialized)
                except Exception as e:
                    logger.warning(f"StateStore: Redis global write failed for {full_key}: {e}")

            # Audit — store full data for crash recovery replay
            await self._append_audit(
                session_id,
                f"global_write:{key}",
                {"key": key, "data": data, "data_preview": str(data)[:300]},
                agent=agent,
            )

    async def read_global(self, session_id: str, key: str) -> Optional[Any]:
        """Read data from a global session key."""
        full_key = f"session:{session_id}:{key}"

        if full_key in self._memory_slots:
            return self._memory_slots[full_key]

        if self._use_redis:
            try:
                raw = await self._redis.get(full_key)
                if raw:
                    return self._deserialize_data(raw)
            except Exception as e:
                logger.warning(f"StateStore: Redis global read failed for {full_key}: {e}")

        return None

    # ── session field manipulation ──────────────────────────────────────────

    def _set_session_field(self, session: ResearchSession, key: str, data: Any) -> None:
        """Set a field on the ResearchSession model.

        Uses a coercion registry for known fields. Unknown keys fall back
        to setattr. ValidationError is raised (not silently swallowed).
        """
        coerce = self._FIELD_COERCION.get(key)
        if coerce is not None:
            coerce(session, data)
        elif hasattr(session, key):
            setattr(session, key, data)
        else:
            logger.warning(f"StateStore: unknown session field '{key}'")

    # ── audit log ────────────────────────────────────────────────────────────

    async def _append_audit(
        self,
        session_id: str,
        event_type: str,
        payload: dict,
        agent: str,
        worker_id: Optional[str] = None,
    ) -> None:
        """Append an audit entry. Called automatically by write_slot/write_global."""
        seq = self._audit_seq.get(session_id, 0) + 1
        self._audit_seq[session_id] = seq

        entry = AuditEntry(
            session_id=session_id,
            seq=seq,
            event_type=event_type,
            agent=agent,
            worker_id=worker_id,
            payload=payload,
        )

        # Always keep in memory
        self._audit_log.append(entry)

        # Write to Postgres
        if self._pg:
            try:
                async with self._pg.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO session_audit_log
                           (session_id, seq, event_type, agent, worker_id, payload, created_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        session_id, seq, event_type, agent, worker_id,
                        json.dumps(payload, default=str),
                        entry.timestamp.isoformat(),
                    )
            except Exception as e:
                logger.warning(f"StateStore: audit log write failed: {e}")

    async def get_audit_log(self, session_id: str) -> list[AuditEntry]:
        """Get all audit entries for a session, ordered by seq."""
        return [e for e in self._audit_log if e.session_id == session_id]

    # ── aggregators ─────────────────────────────────────────────────────────

    async def get_all_findings(self, session_id: str) -> list[dict]:
        """Get all findings from the session state."""
        session = await self.get_session(session_id)
        if not session:
            return []
        return session.findings

    async def get_all_sources(self, session_id: str) -> list[dict]:
        """Get all sources from the session state."""
        session = await self.get_session(session_id)
        if not session:
            return []
        return session.sources

    # ── replay (crash recovery) ─────────────────────────────────────────────

    async def replay_from(self, session_id: str, from_seq: int = 0) -> Optional[ResearchSession]:
        """Replay audit log from a given sequence number to reconstruct state.

        Snapshot + incremental: loads latest snapshot, then replays
        audit entries after from_seq. Replays both global_write and slot_write
        events to reconstruct full state.
        """
        session = await self.get_session(session_id)
        if not session:
            logger.warning(f"StateStore: cannot replay — session {session_id} not found")
            return None

        entries = [e for e in self._audit_log if e.session_id == session_id and e.seq > from_seq]
        entries.sort(key=lambda e: e.seq)

        if not entries:
            return session

        logger.info(f"StateStore: replaying {len(entries)} audit entries from seq {from_seq + 1}")

        for entry in entries:
            if entry.event_type.startswith("global_write:"):
                key = entry.event_type.replace("global_write:", "")
                self._set_session_field(session, key, entry.payload.get("data"))
            elif entry.event_type.startswith("slot_write:"):
                # Reconstruct slot data from audit payload
                slot = entry.event_type.replace("slot_write:", "")
                slot_data = entry.payload.get("data")
                if slot_data is not None:
                    key = f"session:{session_id}:{slot}"
                    self._memory_slots[key] = slot_data

        return session

    # ── citation graph (Layer C) ─────────────────────────────────────────

    def get_citation_graph(self, session_id: str) -> "CitationGraph | None":
        """Get or create the citation graph for a session.

        Always returns a graph object — falls back to in-memory mode when
        Neo4j is disabled. Returns None only if no adapter is configured.
        """
        if self._neo4j is None:
            return None
        if session_id not in self._citation_graphs:
            from backend.citation_graph.graph import CitationGraph
            self._citation_graphs[session_id] = CitationGraph(self._neo4j)
        return self._citation_graphs[session_id]

    async def delete_citation_graph(self, session_id: str) -> None:
        """Remove the citation graph for a session (cleanup)."""
        self._citation_graphs.pop(session_id, None)

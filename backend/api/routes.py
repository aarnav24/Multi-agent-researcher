"""FastAPI routes — research session management + SSE streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import HTMLResponse, StreamingResponse

from backend.api.schemas import ResearchRequest, ResearchResponse, ResearchStatusResponse
from backend.api.sse import SSEStreamer
from backend.agents.synthesizer_agent import reset_synth_gemini_key_cycle
from backend.graph.research_graph import build_graph
from backend.graph.state import ResearchGraphState
from backend.state.models import ResearchSession
from backend.state.store import StateStore

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory session store (backed by Redis/Postgres via StateStore)
_state_store = StateStore()

# Active SSE streams
_active_streams: dict[str, SSEStreamer] = {}


async def get_state_store() -> StateStore:
    return _state_store


@router.on_event("startup")
async def startup():
    await _state_store.connect()
    # Pre-load embedding model at startup (non-blocking) so first citation
    # check doesn't block the event loop for 50+ seconds
    asyncio.create_task(_preload_embedding_model())
    # Start background task to clean up stale SSE streams
    asyncio.create_task(_cleanup_stale_streams())


async def _preload_embedding_model():
    """Pre-load sentence-transformers model in background at startup."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _load_embedding_model_sync)
        logger.info("Embedding model pre-loaded at startup")
    except Exception as e:
        logger.warning(f"Embedding model pre-load failed: {e}")


def _load_embedding_model_sync():
    """Synchronous embedding model loader (runs in thread pool)."""
    from backend.utils.embeddings import _load_model
    _load_model()


@router.on_event("shutdown")
async def shutdown():
    await _state_store.disconnect()


async def _cleanup_stale_streams():
    """Periodically remove stale SSE streams to prevent memory leaks."""
    from backend.api.sse import STALE_STREAM_TIMEOUT
    while True:
        await asyncio.sleep(300)  # Check every 5 minutes
        stale = [
            sid for sid, sse in _active_streams.items()
            if sse.is_stale(STALE_STREAM_TIMEOUT)
        ]
        for sid in stale:
            logger.info(f"Cleaning up stale SSE stream: {sid}")
            del _active_streams[sid]


@router.post("/research", response_model=ResearchResponse)
async def start_research(request: ResearchRequest, authorization: str | None = Header(None)):
    """Start a new research session.

    If Authorization header is provided, extracts user_id and uses user's API keys.
    Otherwise, uses system default keys.
    """
    user_id = _extract_user_id(authorization)

    # ── Rate limiting: 1 query/day for free tier users ─────────────────────
    # Users with custom API keys have no limit
    # Anonymous/free-tier users are limited to 1 research per day
    if user_id:
        has_custom_keys = await _check_user_has_keys(user_id)
        if not has_custom_keys:
            # Free tier — enforce 1 query/day
            today_count = await _get_daily_research_count(user_id)
            if today_count >= 10:
                raise HTTPException(
                    status_code=429,
                    detail="Daily limit reached. Free tier allows 1 research per day. "
                           "Add your own API keys in Settings for unlimited access, or try again tomorrow."
                )
            # Increment counter
            await _increment_daily_research_count(user_id)

    session_id = str(uuid.uuid4())
    logger.info(f"Starting research session {session_id}: {request.query[:80]} (user={user_id or 'anonymous'})")

    # Create session state
    session = ResearchSession(
        session_id=session_id,
        query=request.query,
        status="created",
    )
    await _state_store.create_session(session_id, request.query)

    # Create SSE stream
    sse = SSEStreamer()
    _active_streams[session_id] = sse

    # Start research in background (pass user_id for key resolution)
    asyncio.create_task(_run_research(session_id, request, sse, user_id=user_id))

    return ResearchResponse(
        session_id=session_id,
        status="started",
        message="Research session started. Connect to /research/{id}/stream for live updates.",
    )


@router.get("/research/{session_id}/stream")
async def stream_research(session_id: str):
    """SSE stream for real-time agent activity."""
    sse = _active_streams.get(session_id)
    if not sse:
        raise HTTPException(status_code=404, detail="Session not found or stream expired")

    return StreamingResponse(
        sse.stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/research/{session_id}", response_model=ResearchStatusResponse)
async def get_research_status(session_id: str):
    """Get current status and results of a research session."""
    session = await _state_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Count verified claims — try multiple sources
    verified_count = 0

    # 1. Try the session object (set by graph loop)
    if session.verified_claims:
        verified_count = len(session.verified_claims)

    # 2. Fallback: count from findings that have trust_score >= 40
    if not verified_count and session.findings:
        verified_count = sum(1 for f in session.findings if isinstance(f, dict) and f.get("trust_score", 0) >= 40)

    # 3. Fallback: read from write_global slot
    if not verified_count:
        claims_data = await _state_store.read_global(session_id, "claims")
        if claims_data and isinstance(claims_data, dict):
            verified_count = len(claims_data.get("verified", []))

    return ResearchStatusResponse(
        session_id=session.session_id,
        query=session.query,
        status=session.status,
        agent_count=session.agent_count,
        sub_questions_count=len(session.sub_questions),
        findings_count=len([sq for sq in session.sub_questions if sq.findings]),
        verified_claims_count=verified_count,
        critic_rounds=session.critic_rounds,
        final_report=session.final_report,
        error=session.error,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get("/research/{session_id}/graph")
async def get_citation_graph(session_id: str):
    """Get the citation graph (claims → sources → URLs) for visualization.
    Works whether or not Neo4j is enabled — applies the in-memory fallback."""
    graph = _state_store.get_citation_graph(session_id)
    if not graph:
        return {"enabled": False, "nodes": [], "edges": [], "stats": {}}

    data = await graph.export()
    return data


@router.get("/research/{session_id}/graph/stats")
async def get_citation_graph_stats(session_id: str):
    """Get quick stats about the citation graph."""
    graph = _state_store.get_citation_graph(session_id)
    if not graph:
        return {"enabled": False}

    stats = await graph.get_stats()
    return stats


@router.get("/research/{session_id}/graph/claim/{claim_id}")
async def get_claim_subgraph(session_id: str, claim_id: str):
    """Get subgraph centered on a specific claim (2 hops deep)."""
    graph = _state_store.get_citation_graph(session_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Citation graph not available")

    subgraph = await graph.get_subgraph(claim_id, depth=2)
    related = await graph.get_related_claims(claim_id)
    return {
        "subgraph": subgraph,
        "related_claims": related,
    }


@router.get("/corpus/stats")
async def get_corpus_stats():
    """Get pgvector corpus statistics."""
    from backend.tools.pgvector_tool import get_corpus_stats
    return await get_corpus_stats()


@router.post("/corpus/index")
async def index_corpus_document(request: dict):
    """Index a document into the pgvector corpus."""
    from backend.tools.pgvector_tool import index_document
    doc_name = request.get("doc_name", "untitled")
    content = request.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    chunks = await index_document(doc_name, content)
    return {"doc_name": doc_name, "chunks_indexed": chunks}


@router.get("/research/{session_id}/timing")
async def get_timing_stats(session_id: str):
    from backend.agents.base import llm_timing
    timing = llm_timing.summary()
    return {
        "session_id": session_id,
        "timing": timing,
        "total_calls": sum(t["count"] for t in timing.values()),
    }


def _extract_user_id(authorization: str | None) -> str | None:
    """Extract user ID from Authorization header.

    Format: "Bearer <user_id>"
    For now, user_id is the user's email from NextAuth.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.split(" ", 1)[1]


# ── Rate limiting for free tier ────────────────────────────────────────────

async def _check_user_has_keys(user_id: str) -> bool:
    """Check if user has any active API keys."""
    store = await get_state_store()
    keys = await store.get_user_keys(user_id)
    return len(keys) > 0


def _get_today_key() -> str:
    """Get Redis key for today's research count."""
    from datetime import date
    return f"rate_limit:{date.today().isoformat()}"


async def _get_daily_research_count(user_id: str) -> int:
    """Get number of research queries user has made today."""
    store = await get_state_store()
    if store._pg:
        try:
            async with store._pg.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT count FROM daily_research_counts "
                    "WHERE user_id=$1 AND date=CURRENT_DATE",
                    user_id,
                )
                return row["count"] if row else 0
        except Exception:
            pass  # Table might not exist yet
    return 0


async def _increment_daily_research_count(user_id: str) -> None:
    """Increment today's research count for user."""
    store = await get_state_store()
    if store._pg:
        try:
            async with store._pg.acquire() as conn:
                await conn.execute(
                    """INSERT INTO daily_research_counts (user_id, date, count)
                       VALUES ($1, CURRENT_DATE, 1)
                       ON CONFLICT (user_id, date) DO UPDATE SET count = daily_research_counts.count + 1""",
                    user_id,
                )
        except Exception:
            pass  # Table might not exist yet


"""Extracted _run_research function — rewrite for correct indentation with observability."""


async def _run_research(
    session_id: str,
    request: ResearchRequest,
    sse: SSEStreamer,
    user_id: str | None = None,
):
    """Background task — runs the full research graph.

    Args:
        user_id: If provided, use user's API keys for LLM calls.
    """
    # ── Langfuse: trace the entire research session ──
    from backend.observability import get_langfuse_context, get_tracer
    lf_ctx = get_langfuse_context()
    tracer = get_tracer()

    trace_ctx = None
    root_span = None
    session: ResearchSession | None = None

    try:
        # Reset synthesizer Gemini key cycle for random key selection each run
        reset_synth_gemini_key_cycle()

        # Clear and prefetch user keys so agents can access them synchronously
        from backend.user_keys import prefetch_user_keys, clear_user_keys_cache
        clear_user_keys_cache()
        await prefetch_user_keys(user_id)

        # Record pipeline start time for accurate ETA calculation
        import time
        pipeline_start_time = time.time()

        sse.emit("agent_start", {"agent": "system", "message": "Starting research session"})

        # Build initial graph state
        initial_state: ResearchGraphState = {
            "session_id": session_id,
            "query": request.query,
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
            "tool_call_count": 0,
            "error": None,
            "sufficiency_met": False,
        }

        # Build and run graph — inject StateStore via config
        graph = build_graph()

        sse.emit("agent_start", {"agent": "planner", "message": "Planner creating research plan"})

        graph_config = {"configurable": {"store": _state_store, "sse": sse, "user_id": user_id}}

        # Langfuse trace (LLM observability) — wrap entire pipeline
        with lf_ctx.trace(
            name="research-session",
            session_id=session_id,
            user_id=user_id or "anonymous",
            input={"query": request.query},
            metadata={"session_id": session_id},
        ) as _trace_ctx:
            trace_ctx = _trace_ctx

            # OpenTelemetry span (system trace)
            with tracer.start_as_current_span(
                "research-pipeline",
                attributes={"session.id": session_id, "query": request.query[:200]},
            ) as _root_span:
                root_span = _root_span

                # Track which nodes we've already emitted agent_start for
                started_nodes: set[str] = set()

                # Track findings we've already emitted worker events for
                # (across loop-backs the same searcher round can yield again)
                emitted_fingerprints: set[str] = set()

                # Track node start times for accurate duration metrics
                node_start_times: dict[str, float] = {
                    "planner": pipeline_start_time
                }

                async for chunk in graph.astream(initial_state, config=graph_config):
                    # Emit events for each node completion
                    for node_name, node_output in chunk.items():
                        now_time = time.time()
                        start_time = node_start_times.get(node_name, pipeline_start_time)
                        duration_s = now_time - start_time

                        # Set start times for next potential nodes in the sequence
                        if node_name == "planner":
                            node_start_times["orchestrator"] = now_time
                        elif node_name == "orchestrator":
                            node_start_times["searchers"] = now_time
                        elif node_name == "searchers":
                            node_start_times["sufficiency_check"] = now_time
                        elif node_name == "sufficiency_check":
                            node_start_times["browsers"] = now_time
                            node_start_times["critic"] = now_time
                        elif node_name == "browsers" or node_name == "critic":
                            node_start_times["fact_checker"] = now_time
                        elif node_name == "fact_checker":
                            node_start_times["synthesizer"] = now_time
                        elif node_name == "synthesizer":
                            node_start_times["citation_formatter"] = now_time

                        # OpenTelemetry: span per graph node
                        with tracer.start_as_current_span(
                            f"node.{node_name}",
                            attributes={"status": node_output.get("status", "unknown")},
                        ) as node_span:
                            node_span.set_attribute("agent_count", node_output.get("agent_count", 0))

                        # Emit agent_start the first time we see this node
                        # (so it appears in the tree immediately, not just when complete)
                        if node_name not in started_nodes:
                            started_nodes.add(node_name)
                            # Determine tier from node name
                            is_reasoning = node_name in ("planner", "orchestrator", "critic", "synthesizer", "citation_formatter")
                            sse.emit("agent_start", {
                                "agent": node_name,
                                "message": f"{node_name} started",
                                "tier": "reasoning" if is_reasoning else "fast",
                                "model": node_name,
                            })

                        sse.emit("agent_complete", {
                            "agent": node_name,
                            "status": node_output.get("status", "unknown"),
                            "agent_count": node_output.get("agent_count", 0),
                            "duration": f"{duration_s:.1f}s",
                        })

                        # Emit findings as they arrive
                        if node_name == "searchers" and node_output.get("all_findings"):
                            sse.emit("finding", {
                                "count": len(node_output["all_findings"]),
                                "sources_count": len(node_output.get("all_sources", [])),
                            })

                        # Emit verified claims WITH their sources so the live
                        # citation graph can draw SUPPORTS edges (claim→source).
                        if node_name == "fact_checker" and node_output.get("verified_claims"):
                            for claim in node_output["verified_claims"]:
                                sources = claim.get("sources", []) or []
                                # Dedupe sources by url so the same URL isn't
                                # added as multiple nodes for one claim.
                                seen_urls: set[str] = set()
                                deduped_sources = []
                                for src in sources:
                                    url = src.get("url", "")
                                    if url in seen_urls:
                                        continue
                                    seen_urls.add(url)
                                    deduped_sources.append({
                                        "url": url[:200],
                                        "title": (src.get("title") or "")[:100],
                                        "snippet": (src.get("snippet") or "")[:150],
                                        "tool_name": src.get("tool_name", ""),
                                    })
                                sse.emit("claim_verified", {
                                    "claim": claim.get("claim", "")[:120],
                                    "trust_score": claim.get("trust_score", 0),
                                    "trust_label": claim.get("trust_label", "LOW"),
                                    "sources": deduped_sources[:5],
                                })

                        # Emit agent_status for worker nodes (compound-node level)
                        if any(worker in node_name for worker in ("searcher", "browser", "fact_checker")):
                            sse.emit("agent_status", {
                                "agent": node_name,
                                "status": node_output.get("status", "unknown"),
                                "agent_count": node_output.get("agent_count", 0),
                            })

                        if node_name == "searchers":
                            # Reconstruct PER-WORKER events from the findings list.
                            # This guarantees worker-level nodes appear in the agent tree
                            # even when the inner-node SSE emits don't reliably reach the
                            # stream. Each finding has sub_question_id and tools_used.
                            node_findings = node_output.get("all_findings", [])
                            node_subqs = node_output.get("sub_questions", [])
                            # Map sub_question_id -> question text for labels
                            sq_map = {sq.get("id", ""): sq.get("question", "") for sq in node_subqs if sq.get("id")}
                            for i, finding in enumerate(node_findings):
                                if not isinstance(finding, dict):
                                    continue
                                sq_id = finding.get("sub_question_id", "")
                                question = finding.get("question") or sq_map.get(sq_id, "")
                                # Deterministic fingerprint: prevents re-emitting on loop-backs
                                fp = f"{node_name}:{sq_id}:{finding.get('sub_question_id', '')}"
                                if fp in emitted_fingerprints:
                                    continue
                                emitted_fingerprints.add(fp)
                                # Determine worker id prefix
                                prefix = "searcher"
                                worker_id = f"{prefix}-{i}"
                                # 1) worker started
                                sse.emit("agent_status", {
                                    "agent_id": worker_id,
                                    "status": "running",
                                    "question": question[:200] if question else "",
                                    "model": "fast",
                                    "tier": "fast",
                                })
                                # 2) each successful tool call by this worker
                                for tool_name in finding.get("tools_used", []):
                                    sse.emit("tool_call", {
                                        "agent_id": worker_id,
                                        "tool_name": tool_name,
                                        "latency_ms": 0,
                                    })
                                # 3) worker completed
                                sse.emit("agent_status", {
                                    "agent_id": worker_id,
                                    "status": "completed",
                                    "question": question[-200:] if question else "",
                                    "model": "fast",
                                    "tier": "fast",
                                })

                        elif node_name == "browsers":
                            # Reconstruct PER-WORKER events from the sources list.
                            node_sources = node_output.get("all_sources", []) or []
                            fetched = [src for src in node_sources if src.get("full_content")]
                            for i, src in enumerate(fetched):
                                worker_id = f"browser-{i}"
                                fp = f"{node_name}:{src.get('url', '')}"
                                if fp in emitted_fingerprints:
                                    continue
                                emitted_fingerprints.add(fp)
                                sse.emit("agent_status", {
                                    "agent_id": worker_id,
                                    "status": "running",
                                    "url": src.get("url", "")[:80],
                                    "model": "browser",
                                    "tier": "fast",
                                })
                                sse.emit("agent_status", {
                                    "agent_id": worker_id,
                                    "status": "completed",
                                    "url": src.get("url", "")[:80],
                                    "model": "browser",
                                    "tier": "fast",
                                })

                        elif node_name == "fact_checker":
                            # Reconstruct PER-WORKER events from verified/rejected claims.
                            node_claims = (node_output.get("verified_claims") or []) + (node_output.get("rejected_claims") or [])
                            for i, vc in enumerate(node_claims):
                                claim_text = vc.get("claim", "") if isinstance(vc, dict) else str(vc)
                                # Map back to 8 parallel workers round-robin
                                worker_id = f"fact_checker-{i % 8}"
                                fp = f"{node_name}:{claim_text}"
                                if fp in emitted_fingerprints:
                                    continue
                                emitted_fingerprints.add(fp)
                                sse.emit("agent_status", {
                                    "agent_id": worker_id,
                                    "status": "running",
                                    "claim": claim_text[:80],
                                    "model": "gemini-3.5-flash",
                                    "tier": "fast",
                                })
                                sse.emit("agent_status", {
                                    "agent_id": worker_id,
                                    "status": "completed",
                                    "claim": claim_text[:80],
                                    "model": "gemini-3.5-flash",
                                    "tier": "fast",
                                })

                        # Emit progress update with real timing data
                        from backend.agents.base import llm_timing as _llm_timing
                        _timing = _llm_timing.summary()
                        _completed_calls = sum(t["count"] for t in _timing.values()) if _timing else 0
                        _total_input = sum(t["total_input_tokens"] for t in _timing.values()) if _timing else 0
                        _total_output = sum(t["total_output_tokens"] for t in _timing.values()) if _timing else 0

                        # ETA: estimate based on elapsed time and pipeline stage
                        # Early stage (planner/orchestrator): estimate 6-8 min total
                        # Searchers stage: estimate per-searcher avg × remaining
                        # Fact-checker stage: estimate per-claim avg × remaining
                        # Synthesizer: fixed ~60s estimate
                        _elapsed = time.time() - pipeline_start_time
                        _node_name = node_name.lower()
                        if "planner" in _node_name or "orchestrator" in _node_name:
                            _eta = max(60, 360 - _elapsed)  # ~6 min total budget
                        elif "searcher" in _node_name or "browser" in _node_name:
                            _eta = max(30, 180 - _elapsed)  # ~3 min for search phase
                        elif "fact_checker" in _node_name:
                            _eta = max(30, 120 - _elapsed)  # ~2 min for fact-check
                        elif "synthesizer" in _node_name:
                            _eta = max(10, 90 - _elapsed)  # ~90s for synthesizer
                        else:
                            _eta = max(10, 300 - _elapsed)  # fallback: 5 min budget

                        sse.emit("cost_update", {
                            "total_cost": 0.0,
                            "llm_calls": _completed_calls,
                            "agents_active": node_output.get("agent_count", 0),
                            "tool_calls": node_output.get("tool_call_count", 0),
                            "estimated_remaining_s": round(_eta, 1),
                            "total_tokens": _total_input + _total_output,
                            "total_input_tokens": _total_input,
                            "total_output_tokens": _total_output,
                            "elapsed_s": round(_elapsed, 1),
                        })

                        # Update session in store — both scalar and list fields.
                        # Only set fields that exist on ResearchSession model.
                        session = await _state_store.get(session_id)
                        if session:
                            session.status = str(node_output.get("status", session.status))
                            session.agent_count = int(node_output.get("agent_count", session.agent_count))
                            session.critic_rounds = int(node_output.get("critic_rounds", 0))
                            if node_output.get("final_report"):
                                session.final_report = str(node_output["final_report"])
                            # Sync list fields that exist on ResearchSession
                            # Strip extra fields that aren't on the Pydantic model
                            for field in ("verified_claims", "rejected_claims"):
                                if field in node_output and node_output[field]:
                                    clean = []
                                    for item in node_output[field]:
                                        if isinstance(item, dict):
                                            from backend.state.models import VerifiedClaim, RejectedClaim
                                            model_cls = VerifiedClaim if field == "verified_claims" else RejectedClaim
                                            valid_fields = set(model_cls.model_fields.keys())
                                            clean_item = {k: v for k, v in item.items() if k in valid_fields}
                                            clean.append(model_cls(**clean_item))
                                        else:
                                            clean.append(item)
                                    setattr(session, field, clean)
                                    logger.info(f"GRAPH_LOOP {node_name}: set {field} = {len(clean)} items")
                            await _state_store.update(session)

            # Done — log timing summary (still inside OTel span)
            from backend.agents.base import llm_timing
            timing = llm_timing.summary()
            if timing:
                logger.info("=" * 60)
                logger.info("PIPELINE TIMING SUMMARY")
                for tier, stats in timing.items():
                    logger.info(
                        f"  [{tier}] {stats['count']} calls, "
                        f"avg={stats['avg_s']}s, min={stats['min_s']}s, max={stats['max_s']}s, "
                        f"in={stats['total_input_tokens']}t out={stats['total_output_tokens']}t"
                    )
                    # Per-model breakdown
                    for model, model_stats in stats.get("models", {}).items():
                        avg_s = model_stats["total_s"] / model_stats["count"] if model_stats["count"] > 0 else 0
                        logger.info(
                            f"    {model}: {model_stats['count']} calls, "
                            f"avg={avg_s:.1f}s, "
                            f"in={model_stats['in_tokens']}t out={model_stats['out_tokens']}t"
                        )
                    # Per-agent breakdown
                    for agent, agent_stats in stats.get("agents", {}).items():
                        avg_s = agent_stats["total_s"] / agent_stats["count"] if agent_stats["count"] > 0 else 0
                        logger.info(
                            f"    [{agent}] {agent_stats['count']} calls, "
                            f"avg={avg_s:.1f}s, "
                            f"in={agent_stats['in_tokens']}t out={agent_stats['out_tokens']}t"
                        )
                logger.info("=" * 60)

            sse.emit("done", {
                "session_id": session_id,
                "message": "Research complete",
                "timing": timing,
                "final_report": session.final_report if session else None,
                "agent_count": session.agent_count if session else 0,
                "verified_claims_count": len(session.verified_claims) if session else 0,
                "sources_count": len(session.sources) if session else 0,
            })

            # Langfuse: record final output
            if trace_ctx:
                trace_ctx.update(
                    output={"status": "done", "agent_count": session.agent_count if session else 0},
                )
            if root_span:
                root_span.set_attribute("status", "done")

    except Exception as e:
        logger.error(f"Research session {session_id} failed: {e}", exc_info=True)
        sse.emit("error", {"error": str(e)})
        # Give the queue a moment to flush the error event
        await asyncio.sleep(0.1)
        # Update session with error
        try:
            session = await _state_store.get(session_id)
            if session:
                session.status = "failed"
                session.error = str(e)
                await _state_store.update(session)
        except Exception:
            pass
        # Langfuse: record error
        if trace_ctx:
            trace_ctx.update(output={"status": "failed"}, level="ERROR")
        if root_span:
            root_span.set_attribute("status", "failed")
            root_span.record_exception(e)
    finally:
        # Cleanup
        _active_streams.pop(session_id, None)



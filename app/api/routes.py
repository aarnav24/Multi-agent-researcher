"""FastAPI routes — research session management + SSE streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from app.api.schemas import ResearchRequest, ResearchResponse, ResearchStatusResponse
from app.api.sse import SSEStreamer
from app.agents.synthesizer_agent import reset_synth_gemini_key_cycle
from app.graph.research_graph import build_graph
from app.graph.state import ResearchGraphState
from app.state.models import ResearchSession
from app.state.store import StateStore

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
    from app.utils.embeddings import _get_model
    _get_model()


@router.on_event("shutdown")
async def shutdown():
    await _state_store.disconnect()


async def _cleanup_stale_streams():
    """Periodically remove stale SSE streams to prevent memory leaks."""
    from app.api.sse import STALE_STREAM_TIMEOUT
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
async def start_research(request: ResearchRequest):
    """Start a new research session."""
    session_id = str(uuid.uuid4())
    logger.info(f"Starting research session {session_id}: {request.query[:80]}")

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

    # Start research in background
    asyncio.create_task(_run_research(session_id, request, sse))

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

    return ResearchStatusResponse(
        session_id=session.session_id,
        query=session.query,
        status=session.status,
        agent_count=session.agent_count,
        sub_questions_count=len(session.sub_questions),
        findings_count=len([sq for sq in session.sub_questions if sq.findings]),
        verified_claims_count=len(session.verified_claims),
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
    from app.tools.pgvector_tool import get_corpus_stats
    return await get_corpus_stats()


@router.post("/corpus/index")
async def index_corpus_document(request: dict):
    """Index a document into the pgvector corpus."""
    from app.tools.pgvector_tool import index_document
    doc_name = request.get("doc_name", "untitled")
    content = request.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    chunks = await index_document(doc_name, content)
    return {"doc_name": doc_name, "chunks_indexed": chunks}


@router.get("/research/{session_id}/timing")
async def get_timing_stats(session_id: str):
    from app.agents.base import llm_timing
    timing = llm_timing.summary()
    return {
        "session_id": session_id,
        "timing": timing,
        "total_calls": sum(t["count"] for t in timing.values()),
    }


"""Extracted _run_research function — rewrite for correct indentation with observability."""


async def _run_research(
    session_id: str,
    request: ResearchRequest,
    sse: SSEStreamer,
):
    """Background task — runs the full research graph."""
    # ── Langfuse: trace the entire research session ──
    from app.observability import get_langfuse_context, get_tracer
    lf_ctx = get_langfuse_context()
    tracer = get_tracer()

    trace_ctx = None
    root_span = None
    session: ResearchSession | None = None

    try:
        # Reset synthesizer Gemini key cycle for random key selection each run
        reset_synth_gemini_key_cycle()

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
            "error": None,
            "sufficiency_met": False,
        }

        # Build and run graph — inject StateStore via config
        graph = build_graph()

        sse.emit("agent_start", {"agent": "planner", "message": "Planner creating research plan"})

        graph_config = {"configurable": {"store": _state_store, "sse": sse}}

        # Langfuse trace (LLM observability) — wrap entire pipeline
        with lf_ctx.trace(
            name="research-session",
            user_id=session_id,
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

                async for chunk in graph.astream(initial_state, config=graph_config):
                    # Emit events for each node completion
                    for node_name, node_output in chunk.items():
                        # OpenTelemetry: span per graph node
                        with tracer.start_as_current_span(
                            f"node.{node_name}",
                            attributes={"status": node_output.get("status", "unknown")},
                        ) as node_span:
                            node_span.set_attribute("agent_count", node_output.get("agent_count", 0))

                        sse.emit("agent_complete", {
                            "agent": node_name,
                            "status": node_output.get("status", "unknown"),
                            "agent_count": node_output.get("agent_count", 0),
                        })

                        # Emit findings as they arrive
                        if node_name == "searchers" and node_output.get("all_findings"):
                            sse.emit("finding", {
                                "count": len(node_output["all_findings"]),
                                "sources_count": len(node_output.get("all_sources", [])),
                            })

                        # Emit verified claims
                        if node_name == "fact_checker" and node_output.get("verified_claims"):
                            for claim in node_output["verified_claims"]:
                                sse.emit("claim_verified", {
                                    "claim": claim.get("claim", "")[:100],
                                    "trust_score": claim.get("trust_score", 0),
                                    "trust_label": claim.get("trust_label", "LOW"),
                                })

                        # Emit agent_status for worker nodes
                        if any(worker in node_name for worker in ("searcher", "browser", "fact_checker")):
                            sse.emit("agent_status", {
                                "agent": node_name,
                                "status": node_output.get("status", "unknown"),
                                "agent_count": node_output.get("agent_count", 0),
                            })

                        # Emit progress update (all tools are free — no dollar cost)
                        sse.emit("cost_update", {
                            "total_cost": 0.0,
                            "api_calls": node_output.get("agent_count", 0),
                            "agents_active": node_output.get("agent_count", 0),
                            "estimated_remaining_s": max(0, 120 - node_output.get("agent_count", 0) * 3),
                        })

                        # Update session in store
                        session = await _state_store.get(session_id)
                        if session:
                            session.status = str(node_output.get("status", session.status))
                            session.agent_count = int(node_output.get("agent_count", session.agent_count))
                            session.critic_rounds = int(node_output.get("critic_rounds", 0))
                            if node_output.get("final_report"):
                                session.final_report = str(node_output["final_report"])
                            await _state_store.update(session)

            # Done — log timing summary (still inside OTel span)
            from app.agents.base import llm_timing
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



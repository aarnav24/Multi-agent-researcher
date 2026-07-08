"""FastAPI application entry point."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.api.auth_routes import router as auth_router
from backend.api.user_keys import router as user_keys_router
from backend.api.users import router as users_router
from backend.api.corpus_routes import router as corpus_router
from backend.observability import observability_lifespan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="Deep Research Swarm",
    description="Multi-agent deep research system using orchestrator-worker pattern",
    version="0.1.0",
    lifespan=observability_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://140.245.120.11",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(user_keys_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(corpus_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "deep-research-swarm"}

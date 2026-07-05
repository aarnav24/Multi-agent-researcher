"""API request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=5, description="The research query to investigate")
    max_agents: int = Field(default=15, ge=3, le=30, description="Max agent invocations")


class ResearchResponse(BaseModel):
    session_id: str
    status: str
    message: str = "Research session started"


class ResearchStatusResponse(BaseModel):
    session_id: str
    query: str
    status: str
    agent_count: int = 0
    sub_questions_count: int = 0
    findings_count: int = 0
    verified_claims_count: int = 0
    critic_rounds: int = 0
    final_report: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SSEEvent(BaseModel):
    """Server-Sent Event for real-time agent activity streaming."""
    event: str  # agent_start, agent_complete, finding, claim_verified, cost_update, error, done
    data: dict[str, Any]

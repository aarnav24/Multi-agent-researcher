"""Pydantic models for the shared research session state."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class SubQuestionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Source(BaseModel):
    """Unified source schema — every tool returns this same structure."""
    source_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    url: str = ""
    title: str = ""
    snippet: str = ""  # 200-token summary
    full_content: Optional[str] = None  # fetched on demand by Browser Worker
    published_date: Optional[date] = None
    domain_authority: float = 0.0  # 0–100
    tool_name: str = ""  # "tavily" | "arxiv" | "github" | "serper" | "exa" | "ddg" | "browser"


class SubQuestion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question: str = ""
    status: SubQuestionStatus = SubQuestionStatus.PENDING
    assigned_to: Optional[str] = None  # agent type: "searcher" | "browser"
    assigned_tools: list[str] = Field(default_factory=list)
    findings: Optional[str] = None  # 200–500 token summary
    sources: list[Source] = Field(default_factory=list)
    tool_call_count: int = 0


class VerifiedClaim(BaseModel):
    claim: str = ""
    sources: list[Source] = Field(default_factory=list)
    trust_score: int = 0  # 0–100
    trust_label: str = "LOW"  # HIGH | MODERATE | LOW
    fact_check_passed: bool = False


class RejectedClaim(BaseModel):
    claim: str = ""
    reason: str = ""


class ResearchPlan(BaseModel):
    hypothesis_tree: dict = Field(default_factory=dict)
    key_entities: list[str] = Field(default_factory=list)
    search_strategy: dict = Field(default_factory=dict)
    tool_routing: dict[str, list[str]] = Field(default_factory=dict)  # sub_q_id -> tools


class ResearchSession(BaseModel):
    """Full session state — stored in Redis (hot) + Postgres (audit).

    This is the shared memory schema. All agents read/write fields on this model.
    Workers write to their assigned slots; Orchestrator writes globally.
    """
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    query: str = ""
    plan: Optional[ResearchPlan] = None
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    verified_claims: list[VerifiedClaim] = Field(default_factory=list)
    rejected_claims: list[RejectedClaim] = Field(default_factory=list)
    critic_rounds: int = 0
    critic_done: bool = False
    critic_followups: list[str] = Field(default_factory=list)
    sufficiency_met: bool = False
    agent_count: int = 0
    final_report: Optional[str] = None
    status: str = "created"  # created | planning | researching | critiquing | fact_checking | synthesizing | done | failed | killed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    error: Optional[str] = None

    # ── extended fields (written by nodes via write_global) ───────────────
    findings: list[dict] = Field(default_factory=list)  # accumulated searcher findings
    sources: list[dict] = Field(default_factory=list)  # accumulated sources
    browser_facts: list[str] = Field(default_factory=list)  # extracted facts from browsers
    searcher_rounds: int = 0  # total searcher dispatch rounds completed
    citations_verified: bool = False


class AuditEntry(BaseModel):
    """Audit log entry — one per state change, stored in Postgres for crash recovery."""
    session_id: str
    seq: int  # Monotonically increasing per session
    event_type: str  # "plan_created", "finding_added", "claim_verified", etc.
    agent: str  # "planner", "orchestrator", "searcher", etc.
    worker_id: Optional[str] = None  # Set for worker agents
    payload: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class UserAPIKey(BaseModel):
    """User-provided API key for LLM providers. Stored in Postgres."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str  # NextAuth user ID (email or UUID)
    provider: str  # "openrouter" | "gemini" | "anthropic" | "groq" | "deepseek" | "openai"
    api_key: str
    model_name: str = ""  # e.g., "claude-sonnet-4-6", "gpt-4o"
    base_url: str = ""  # e.g., "https://api.anthropic.com/v1"
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        # Extra fields allowed for flexibility
        extra = "ignore"

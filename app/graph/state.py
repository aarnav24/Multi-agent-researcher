"""LangGraph TypedDict state — flows between all nodes in the research graph.

This is the minimal, flat state that LangGraph nodes read/write.
The full ResearchSession (app/state/models.py) is stored in Redis/Postgres
and synced with this graph state at node boundaries.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import add_messages


class ResearchGraphState(TypedDict):
    # ── identity ──────────────────────────────────────────────────────────────
    session_id: str
    query: str

    # ── plan ─────────────────────────────────────────────────────────────────
    plan: Optional[dict]  # ResearchPlan as dict
    plan_ready: bool

    # ── sub-questions ────────────────────────────────────────────────────────
    sub_questions: list[dict]  # list of SubQuestion dicts
    active_searchers: int  # count of currently running searcher futures
    active_browsers: int  # count of currently running browser futures

    # ── findings ─────────────────────────────────────────────────────────────
    all_findings: list[dict]  # accumulated findings from all workers
    all_sources: list[dict]  # accumulated sources from all workers

    # ── quality control ──────────────────────────────────────────────────────
    critic_rounds: int
    critic_gaps: list[str]  # follow-up questions from Critic
    critic_done: bool
    verified_claims: list[dict]
    rejected_claims: list[dict]
    browser_facts: list[str]  # extracted facts from browser deep-fetches

    # ── output ───────────────────────────────────────────────────────────────
    final_report: Optional[str]
    citations_verified: bool

    # ── control flow ────────────────────────────────────────────────────────
    status: str  # created | planning | researching | critiquing | fact_checking | synthesizing | done | failed | killed
    agent_count: int
    error: Optional[str]
    sufficiency_met: bool
    searcher_rounds: int  # total number of searcher dispatch rounds completed

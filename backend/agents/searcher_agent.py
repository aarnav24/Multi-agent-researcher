"""Searcher Worker agent — stateless, receives one sub-question + tools, returns summary.

Uses query normalization to transform natural-language sub-questions into
tool-specific search queries for better retrieval quality.

Per-tool rate limiting: concurrent searchers share async semaphores per API
endpoint so that even with 5 parallel workers, arXiv gets at most 1 req/sec
and Tavily/Exa/Serper get at most 3 concurrent calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from backend.agents.base import BaseAgent
from backend.config import settings
from backend.tools.base import sanitize_snippet
from backend.tools.tavily_tool import tavily_search
from backend.tools.arxiv_tool import arxiv_search
from backend.tools.github_tool import github_search
from backend.tools.serper_tool import serper_search
from backend.tools.exa_tool import exa_search
from backend.tools.ddg_tool import ddg_search
from backend.tools.pgvector_tool import pgvector_search
from backend.tools.query_normalizer import normalize_query, get_metrics, log_all_metrics

logger = logging.getLogger(__name__)

# ── Per-tool rate limiting configuration ────────────────────────────────────
# arXiv: 1 req/sec free tier → semaphore=1 with built-in delay in arxiv_tool
# Tavily: ~10 req/sec on free tier → semaphore=8
# Exa: ~5 req/sec → semaphore=8
# Serper: ~5 req/sec → semaphore=8
# GitHub: 30 req/min with token → semaphore=4
# DDG: unlimited → no semaphore needed
_TOOL_SEMAPHORES: dict[str, asyncio.Semaphore] = {
    "arxiv": asyncio.Semaphore(1),
    "tavily": asyncio.Semaphore(8),
    "exa": asyncio.Semaphore(8),
    "serper": asyncio.Semaphore(8),
    "github": asyncio.Semaphore(4),
}
# Minimum delay between consecutive calls to the same tool (seconds)
_TOOL_MIN_DELAY: dict[str, float] = {
    "arxiv": 1.5,
    "tavily": 0.3,
    "exa": 0.3,
    "github": 0.5,
}
# Per-tool call timeout (seconds)
_TOOL_TIMEOUT = 30.0
# Circuit breaker threshold: consecutive failures before skipping a tool
CIRCUIT_BREAKER_THRESHOLD = 3


class ToolCircuitBreaker:
    """Tracks per-tool consecutive failures and opens circuit after threshold."""

    def __init__(self, threshold: int = CIRCUIT_BREAKER_THRESHOLD):
        self.failures: dict[str, int] = {}
        self.threshold = threshold

    def record_failure(self, tool_name: str) -> None:
        self.failures[tool_name] = self.failures.get(tool_name, 0) + 1
        if self.failures[tool_name] >= self.threshold:
            logger.warning(f"Circuit breaker OPEN for {tool_name} after {self.failures[tool_name]} failures")

    def record_success(self, tool_name: str) -> None:
        if tool_name in self.failures:
            self.failures[tool_name] = 0

    def is_open(self, tool_name: str) -> bool:
        return self.failures.get(tool_name, 0) >= self.threshold


# Module-level circuit breaker shared across all searcher instances
_circuit_breaker = ToolCircuitBreaker()

# Track last call time per tool for delay enforcement (shared across workers)
_last_tool_call: dict[str, float] = {}


async def _call_tool_rate_limited(tool_name: str, tool_fn, query: str, max_results: int, call_counter: dict):
    """Call a search tool with per-tool rate limiting, timeout, and circuit breaker.

    Uses a semaphore to cap concurrency, optional minimum delay between
    consecutive calls, and a per-call timeout.
    Enforces hard cap of max_tool_calls_per_agent (default 8) total tool calls.
    call_counter is a mutable dict {"count": N} passed per-agent to track calls.
    """
    # Hard kill switch: per-agent tool call cap
    if call_counter["count"] >= settings.max_tool_calls_per_agent:
        logger.warning(
            f"Tool call cap reached for agent ({call_counter['count']}/{settings.max_tool_calls_per_agent}), "
            f"skipping {tool_name}"
        )
        return []

    if _circuit_breaker.is_open(tool_name):
        logger.debug(f"Tool {tool_name} circuit breaker is open, skipping")
        return []

    sem = _TOOL_SEMAPHORES.get(tool_name)
    min_delay = _TOOL_MIN_DELAY.get(tool_name, 0.0)

    # Enforce minimum delay between calls to the same tool
    if min_delay > 0 and tool_name in _last_tool_call:
        elapsed = time.time() - _last_tool_call[tool_name]
        if elapsed < min_delay:
            await asyncio.sleep(min_delay - elapsed)

    try:
        if sem:
            async with sem:
                result = await asyncio.wait_for(
                    tool_fn(query=query, max_results=max_results),
                    timeout=_TOOL_TIMEOUT,
                )
        else:
            result = await asyncio.wait_for(
                tool_fn(query=query, max_results=max_results),
                timeout=_TOOL_TIMEOUT,
            )
        _last_tool_call[tool_name] = time.time()
        _circuit_breaker.record_success(tool_name)
        call_counter["count"] += 1
        return result
    except asyncio.TimeoutError:
        logger.warning(f"Tool {tool_name} timed out after {_TOOL_TIMEOUT}s for query: {query[:60]}")
        _circuit_breaker.record_failure(tool_name)
        return []
    except Exception as e:
        _last_tool_call[tool_name] = time.time()
        _circuit_breaker.record_failure(tool_name)
        raise


SEARCHER_SYSTEM = """You are a specialized research searcher. You receive ONE sub-question and a set of search tools.

Your job:
1. Use the provided tools to search for information
2. Synthesize findings into a concise 200-500 token summary
3. List all sources with their URLs

Output JSON:
{
  "summary": "concise findings summary (200-500 tokens)",
  "key_facts": ["fact1", "fact2"],
  "sources": [
    {"url": "...", "title": "...", "snippet": "...", "tool_name": "..."}
  ],
  "confidence": "high|medium|low"
}

Be factual. If sources contradict, note the contradiction. Output ONLY valid JSON."""

# Tool dispatch map — semantic backend is configurable via settings.search_backend
# During testing: set SEARCH_BACKEND=ddg in .env to use DuckDuckGo (unlimited free)
# During deployment: set SEARCH_BACKEND=exa to use Exa (semantic search, uses credits)
_SEMANTIC_BACKEND = {
    "exa": exa_search,
    "ddg": ddg_search,
}.get(settings.search_backend, exa_search)


async def _pgvector_search_with_user(query: str, max_results: int = 5, **_):
    """Adapter so the orchestrator can drop `pgvector` into TOOL_MAP without
    having to thread user_id through each tool ref. We pull user_id from the
    `user_keys` module's per-thread cache (set at the start of each run).
    """
    try:
        from backend.user_keys import get_current_user_id
        uid = get_current_user_id()
    except Exception:
        uid = None
    return await pgvector_search(query=query, max_results=max_results, user_id=uid)


TOOL_MAP = {
    "tavily": tavily_search,
    "arxiv": arxiv_search,
    "github": github_search,
    "serper": serper_search,
    "exa": _SEMANTIC_BACKEND,
    "ddg": ddg_search,
    "pgvector": _pgvector_search_with_user,
}


class SearcherAgent(BaseAgent):
    model_tier = "fast"
    system_prompt = SEARCHER_SYSTEM

    async def search(
        self,
        sub_question: str,
        tools: list[str],
        max_tool_calls: int = 8,
    ) -> dict[str, Any]:
        """Execute searches for a sub-question using assigned tools.

        Uses query normalization to transform the sub-question into
        tool-specific queries for better retrieval.
        Per-agent call counter enforces max_tool_calls_per_agent (default 8).
        """
        logger.info(f"Searcher: researching '{sub_question[:60]}...' with tools: {tools}")

        all_sources: list[dict] = []
        tool_results_text = []
        primary_sources: list[dict] = []
        tools_used: list[str] = []

        # Per-agent tool call counter — each Searcher instance gets its own
        call_counter = {"count": 0}

        # Execute each assigned tool with normalized queries
        for tool_name in tools[:max_tool_calls]:
            tool_fn = TOOL_MAP.get(tool_name)
            if not tool_fn:
                continue

            # Skip tools with open circuit breaker
            if _circuit_breaker.is_open(tool_name):
                logger.info(f"Searcher: skipping {tool_name} (circuit breaker open)")
                continue

            # Normalize the query for this specific tool
            tool_query = normalize_query(sub_question, tool=tool_name)
            metrics = get_metrics(tool_name)

            try:
                start = time.time()
                results = await _call_tool_rate_limited(tool_name, tool_fn, tool_query, max_results=5, call_counter=call_counter)
                latency_ms = (time.time() - start) * 1000

                success = len(results) > 0
                metrics.record_call(
                    success=success,
                    latency_ms=latency_ms,
                    error="" if success else "no results",
                )

                # Track that this tool was successfully used
                tools_used.append(tool_name)

                for r in results:
                    src = r.model_dump()
                    all_sources.append(src)
                    # Defense: sanitize snippet to prevent prompt injection
                    # from search results containing malicious instructions
                    safe_snippet = sanitize_snippet(r.snippet)
                    tool_results_text.append(
                        f"[{tool_name}] {r.title}\nURL: {r.url}\n{safe_snippet}\n"
                    )
                    # Track primary tool results (tavily/exa/serper) for fallback decision
                    if tool_name in ("tavily", "exa", "serper"):
                        primary_sources.append(src)

                logger.info(
                    f"Searcher: {tool_name} → {len(results)} results "
                    f"({latency_ms:.0f}ms) query='{tool_query[:60]}'"
                )

            except Exception as e:
                latency_ms = (time.time() - start) * 1000 if 'start' in dir() else 0
                error_str = str(e)
                is_rate_limit = "429" in error_str or "rate" in error_str.lower()
                metrics.record_call(
                    success=False,
                    latency_ms=latency_ms,
                    error=error_str[:200],
                    rate_limited=is_rate_limit,
                )
                logger.warning(f"Searcher: tool {tool_name} failed: {e}")

        # Fallback: if primary tools returned no results, try DuckDuckGo
        # DDG does NOT count toward the per-agent call cap — it's an emergency fallback only
        if not primary_sources:
            ddg_query = normalize_query(sub_question, tool="ddg")
            logger.info("Searcher: primary search tools returned no results, falling back to DuckDuckGo")
            try:
                start = time.time()
                ddg_results = await asyncio.wait_for(
                    ddg_search(query=ddg_query, max_results=5),
                    timeout=_TOOL_TIMEOUT,
                )
                latency_ms = (time.time() - start) * 1000
                get_metrics("ddg").record_call(
                    success=len(ddg_results) > 0,
                    latency_ms=latency_ms,
                )
                for r in ddg_results:
                    src = r.model_dump()
                    all_sources.append(src)
                    safe_snippet = sanitize_snippet(r.snippet)
                    tool_results_text.append(
                        f"[ddg] {r.title}\nURL: {r.url}\n{safe_snippet}\n"
                    )
                # Count successful DDG fallback as a tool call
                if ddg_results:
                    call_counter["count"] += 1
            except asyncio.TimeoutError:
                logger.warning(f"Searcher: DuckDuckGo fallback timed out after {_TOOL_TIMEOUT}s")
            except Exception as e:
                logger.warning(f"Searcher: DuckDuckGo fallback also failed: {e}")

        # Log metrics summary
        log_all_metrics()

        if not all_sources:
            return {
                "summary": f"No results found for: {sub_question}",
                "key_facts": [],
                "sources": [],
                "confidence": "low",
                "tool_calls": call_counter["count"],
                "tools_used": tools_used,
            }

        # Ask LLM to synthesize findings (enforce 200-500 token summary)
        synthesis_prompt = (
            f"Sub-question: {sub_question}\n\n"
            f"Search results:\n" + "\n---\n".join(tool_results_text) +
            "\n\nSynthesize a concise answer (200-500 tokens only). "
            f"Be strict: maximum 8 sentences total. "
            f"Include key facts as a short list. "
            f"Output JSON with 'summary', 'key_facts', 'confidence'."
        )
        synthesis = await self.run(synthesis_prompt, max_tokens=768)

        try:
            parsed = json.loads(synthesis)
            parsed["sources"] = all_sources
            parsed["tool_calls"] = call_counter["count"]
            parsed["tools_used"] = tools_used
            # Enforce summary length cap (≈500 tokens ≈ 2000 chars)
            if len(parsed.get("summary", "")) > 2000:
                parsed["summary"] = parsed["summary"][:1997] + "..."
            # Cap key_facts at 8 items
            parsed["key_facts"] = parsed.get("key_facts", [])[:8]
            return parsed
        except json.JSONDecodeError:
            # Truncate non-JSON output to enforce return contract
            return {
                "summary": synthesis[:1000],
                "key_facts": [],
                "sources": all_sources,
                "confidence": "medium",
                "tool_calls": call_counter["count"],
                "tools_used": tools_used,
            }

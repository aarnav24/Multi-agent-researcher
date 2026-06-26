"""Browser nodes — dispatch parallel Browser workers to deep-fetch URLs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.browser_agent import BrowserAgent
from app.config import settings
from app.graph.state import ResearchGraphState
from app.state.store import StateStore
from app.utils.concurrency import agent_slot

logger = logging.getLogger(__name__)

# Separate concurrency pool for browser workers (I/O-bound deep fetches)
# Independent of the searcher semaphore so slow page loads don't block search
_browser_semaphore = asyncio.Semaphore(settings.max_browser_workers)


async def _run_single_browser_with_pool(
    url: str,
    research_question: str,
    stagger_delay: float = 0.0,
) -> dict[str, Any]:
    """Run a single Browser worker with dedicated browser concurrency pool."""
    if stagger_delay > 0:
        await asyncio.sleep(stagger_delay)
    async with _browser_semaphore:
        return await _run_single_browser(url, research_question, 0)


async def _run_single_browser(
    url: str,
    research_question: str,
    stagger_delay: float = 0.0,
) -> dict[str, Any]:
    """Run a single Browser worker to fetch and extract content from a URL."""
    if stagger_delay > 0:
        await asyncio.sleep(stagger_delay)
    async with agent_slot():
        agent = BrowserAgent()
        result = await agent.fetch_and_extract(url, research_question)
        return result


async def browser_dispatch_node(state: ResearchGraphState, config: RunnableConfig | None = None) -> ResearchGraphState:
    """Dispatch Browser workers for top URLs from search results.

    Selects up to 3 URLs prioritising diversity (different domains) and
    sources that lack full_content. Runs independently of the sufficiency
    gate — browsers are I/O-bound and add minimal wall-clock time.
    """
    logger.info("Node: browser_dispatch")
    store: StateStore | None = (config or {}).get("configurable", {}).get("store")
    sse = (config or {}).get("configurable", {}).get("sse")

    sources = state.get("all_sources", [])
    urls_to_fetch = []
    seen_urls = set()
    seen_domains = set()

    for src in sources:
        url = src.get("url", "")
        if not url or url in seen_urls or src.get("full_content"):
            continue
        # Prefer URL diversity — one per domain
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        if domain in seen_domains:
            continue
        urls_to_fetch.append(url)
        seen_urls.add(url)
        seen_domains.add(domain)
        if len(urls_to_fetch) >= settings.max_browser_workers:
            break

    if not urls_to_fetch:
        logger.info("No URLs to fetch, skipping browser workers")
        return {**state, "status": "browsers_done"}

    logger.info(f"Dispatching {len(urls_to_fetch)} Browser workers")

    # Context isolation: pass only the specific sub-question this URL is relevant to,
    # not the full research query (Layer B — per-agent context isolation)
    query = state.get("query", "")
    sub_questions = state.get("sub_questions", [])

    def _find_relevant_subquestion(url: str) -> str:
        """Find the most relevant sub-question for a URL based on source matching."""
        for sq in sub_questions:
            for src in sq.get("sources", []):
                if src.get("url") == url:
                    return sq.get("question", query)
        return query  # fallback to full query if no match

    # No stagger needed — all workers are already parallel
    # Use dedicated browser concurrency pool (separate from searcher pool)
    if sse:
        for i, url in enumerate(urls_to_fetch):
            sse.emit("agent_status", {
                "agent_id": f"browser-{i}",
                "status": "running",
                "url": url[:80],
                "model": "browser",
                "tier": "fast",
            })
    tasks = [
        asyncio.create_task(_run_single_browser_with_pool(
            url,
            _find_relevant_subquestion(url),
            stagger_delay=0,
        ))
        for url in urls_to_fetch
    ]
    # Global timeout: 90s max for all browsers (prevents one slow URL from blocking)
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=90.0,
        )
    except asyncio.TimeoutError:
        logger.warning("Browser workers timed out after 90s, using partial results")
        results = []
        for task in tasks:
            if task.done() and not task.cancelled():
                try:
                    results.append(task.result())
                except Exception as e:
                    results.append(e)
            else:
                task.cancel()
                results.append(Exception("Browser worker timed out"))

    # Emit completion events for successful workers
    if sse:
        for i, result in enumerate(results):
            if not isinstance(result, Exception):
                sse.emit("agent_status", {
                    "agent_id": f"browser-{i}",
                    "status": "completed",
                })

    # Merge browser results back into sources
    updated_sources = list(sources)
    browser_facts = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Browser worker failed: {result}")
            continue
        source_data = result.get("source", {})
        url = source_data.get("url", "")
        # Collect extracted facts for the fact-checker
        if result.get("extracted_facts"):
            browser_facts.extend(result["extracted_facts"])
        # Write each browser result to its own slot in the shared store
        if store:
            worker_id = f"browser-{i}"
            await store.write_slot(
                state["session_id"],
                f"worker:{worker_id}:results",
                result,
                agent="browser",
                worker_id=worker_id,
            )
        # Update the source with full content
        for j, src in enumerate(updated_sources):
            if src.get("url") == url:
                updated_sources[j] = {**src, **source_data}
                break

    agent_count = state.get("agent_count", 0) + len(urls_to_fetch)

    # Persist to shared store
    if store:
        session_id = state["session_id"]
        await store.write_global(session_id, "sources", updated_sources, agent="orchestrator")
        await store.write_global(session_id, "browser_facts", browser_facts, agent="orchestrator")
        await store.write_global(session_id, "agent_count", agent_count, agent="orchestrator")
        await store.write_global(session_id, "status", "browsers_done", agent="orchestrator")

    return {
        **state,
        "all_sources": updated_sources,
        "browser_facts": state.get("browser_facts", []) + browser_facts,
        "agent_count": agent_count,
        "status": "browsers_done",
    }


async def browser_worker_node(state: ResearchGraphState, config: RunnableConfig | None = None) -> ResearchGraphState:
    """Alias for browser_dispatch_node — used for LangGraph routing."""
    return await browser_dispatch_node(state, config=config)

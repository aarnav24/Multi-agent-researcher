"""Tavily search tool — LLM-optimized clean content."""

from __future__ import annotations

import logging
import random
from typing import Optional

import httpx

from backend.config import settings
from backend.tools.base import ToolOutput, estimate_domain_authority, sanitize_snippet

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


def _get_tavily_key() -> str:
    """Get a random Tavily API key from the 5-key pool."""
    keys = settings.tavily_keys
    if not keys:
        logger.warning("No Tavily API keys configured")
        return ""
    return random.choice(keys)


async def tavily_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "advanced",
) -> list[ToolOutput]:
    """Search using Tavily API. Returns list of ToolOutput."""
    api_key = _get_tavily_key()
    if not api_key:
        return []

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TAVILY_URL,
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": search_depth,
                "max_results": max_results,
                "include_answer": True,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    results: list[ToolOutput] = []
    for r in data.get("results", []):
        url = r.get("url", "")
        results.append(
            ToolOutput(
                url=url,
                title=r.get("title", ""),
                snippet=sanitize_snippet(r.get("content", "")[:800]),
                domain_authority=estimate_domain_authority(url),
                tool_name="tavily",
            )
        )
    return results


def get_tavily_answer(query: str) -> str:
    """Get Tavily's LLM-generated answer summary for a query.

    This is a synchronous helper that the fact-checker can call via
    run_in_executor. Returns the answer string or empty string on failure.
    """
    import httpx
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                TAVILY_URL,
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": 5,
                    "include_answer": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("answer", "")
            if answer:
                logger.info(f"Tavily answer ({len(answer)} chars): {answer[:100]}...")
            return answer
    except Exception as e:
        logger.warning(f"Tavily answer fetch failed: {e}")
        return ""

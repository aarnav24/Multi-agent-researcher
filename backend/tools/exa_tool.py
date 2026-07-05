"""Exa.ai search tool — semantic-first, returns clean academic content."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from backend.config import settings
from backend.tools.base import ToolOutput, estimate_domain_authority, sanitize_snippet

logger = logging.getLogger(__name__)

EXA_URL = "https://api.exa.ai/search"


async def exa_search(
    query: str,
    max_results: int = 5,
) -> list[ToolOutput]:
    """Search using Exa.ai (semantic search). Returns list of ToolOutput."""
    if not settings.exa_api_key:
        logger.warning("Exa API key not configured")
        return []

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            EXA_URL,
            headers={
                "x-api-key": settings.exa_api_key,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "numResults": max_results,
                "useAutoprompt": True,
                "contents": {"text": True},
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
                snippet=sanitize_snippet((r.get("text") or "")[:800]),
                published_date=None,
                domain_authority=estimate_domain_authority(url),
                tool_name="exa",
            )
        )
    return results

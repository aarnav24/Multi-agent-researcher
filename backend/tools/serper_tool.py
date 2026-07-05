"""Serper (Google) search tool — freshness-focused web search."""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.config import settings
from backend.tools.base import ToolOutput, estimate_domain_authority, sanitize_snippet

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"

# Errors that indicate a network/server-side hiccup worth retrying.
# Client errors (4xx except 429) should NOT be retried — they'd just waste time.
_RETRYABLE = (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.PoolTimeout, httpx.RemoteProtocolError, httpx.ReadTimeout)


async def serper_search(
    query: str,
    max_results: int = 5,
) -> list[ToolOutput]:
    """Search using Serper (Google). Returns list of ToolOutput."""
    if not settings.serpapi_api_key:
        logger.warning("Serper API key not configured")
        return []

    # Wrap the call with tenacity — retries connect/read errors with backoff.
    # 3 attempts: initial, after 1s, after 2s.
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=4),
            retry=retry_if_exception_type(_RETRYABLE),
            reraise=True,
        ):
            with attempt:
                async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=5.0)) as client:
                    resp = await client.post(
                        SERPER_URL,
                        headers={"X-API-KEY": settings.serpapi_api_key},
                        json={"q": query, "num": max_results},
                    )
                    resp.raise_for_status()
                    data = resp.json()
    except _RETRYABLE as e:
        logger.warning(f"Serper: network failure after retries for query '{query[:60]}': {e}")
        return []
    except httpx.HTTPStatusError as e:
        # 4xx/5xx — log and return empty, no retry needed
        logger.warning(f"Serper: HTTP {e.response.status_code} for query '{query[:60]}': {e.response.text[:200]}")
        return []
    except Exception as e:
        logger.warning(f"Serper: unexpected error for query '{query[:60]}': {e}")
        return []

    results: list[ToolOutput] = []
    for r in data.get("organic", []):
        url = r.get("link", "")
        results.append(
            ToolOutput(
                url=url,
                title=r.get("title", ""),
                snippet=sanitize_snippet((r.get("snippet") or "")[:800]),
                domain_authority=estimate_domain_authority(url),
                tool_name="serper",
            )
        )
    return results

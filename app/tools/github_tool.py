"""GitHub search tool — repos, code, READMEs."""

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

from app.config import settings
from app.tools.base import ToolOutput, estimate_domain_authority, sanitize_snippet

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com/search/repositories"

# Network/server errors worth retrying. 4xx (except 429) should NOT be retried.
# GitHub API returns 403/429 for rate-limit — we still want to retry 429 with backoff.
_RETRYABLE = (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.PoolTimeout, httpx.RemoteProtocolError, httpx.ReadTimeout)


async def github_search(
    query: str,
    max_results: int = 5,
) -> list[ToolOutput]:
    """Search GitHub repos. Returns list of ToolOutput."""
    if not settings.github_token:
        logger.warning("GitHub token not configured")
        return []

    # Retry on connect/network errors with exponential backoff (3 attempts).
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=4),
            retry=retry_if_exception_type(_RETRYABLE),
            reraise=True,
        ):
            with attempt:
                async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=5.0)) as client:
                    resp = await client.get(
                        GITHUB_API,
                        params={"q": query, "sort": "stars", "order": "desc", "per_page": max_results},
                        headers={
                            "Authorization": f"Bearer {settings.github_token}",
                            "Accept": "application/vnd.github.v3+json",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
    except _RETRYABLE as e:
        logger.warning(f"GitHub: network failure after retries for query '{query[:60]}': {e}")
        return []
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        # 5xx + 429 are retry-worthy; others return immediately.
        if status in (429, 500, 502, 503, 504):
            logger.warning(f"GitHub: HTTP {status} (transient) for query '{query[:60]}'")
            return []
        logger.warning(f"GitHub: HTTP {status} for query '{query[:60]}': {e.response.text[:200]}")
        return []
    except Exception as e:
        logger.warning(f"GitHub: unexpected error for query '{query[:60]}': {e}")
        return []

    results: list[ToolOutput] = []
    for item in data.get("items", []):
        url = item.get("html_url", "")
        results.append(
            ToolOutput(
                url=url,
                title=item.get("full_name", ""),
                snippet=sanitize_snippet((item.get("description") or "")[:800]),
                domain_authority=90.0,
                tool_name="github",
            )
        )
    return results

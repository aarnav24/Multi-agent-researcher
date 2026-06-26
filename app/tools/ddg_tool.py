"""DuckDuckGo search tool — unlimited free fallback.

Uses the `duckduckgo_search` Python package (unofficial wrapper).
No API key required. Unlimited searches.
https://github.com/deedy5/duckduckgo_search
"""

from __future__ import annotations

import logging
from typing import Optional

from app.tools.base import ToolOutput, estimate_domain_authority, sanitize_snippet

logger = logging.getLogger(__name__)


async def ddg_search(
    query: str,
    max_results: int = 5,
    region: str = "us-en",
    time: str = "y",  # past year by default for freshness
) -> list[ToolOutput]:
    """Search using DuckDuckGo. Returns list of ToolOutput.

    No API key needed. Unlimited free searches.
    Runs the sync duckduckgo_search library in a thread executor.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        logger.warning("ddgs package not installed. Run: pip install ddgs")
        return []

    import asyncio

    def _search():
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(
                query,
                max_results=max_results,
                region=region,
                timelimit=time,
            ):
                url = r.get("href", "")
                results.append(
                    ToolOutput(
                        url=url,
                        title=r.get("title", ""),
                        snippet=sanitize_snippet((r.get("body") or "")[:800]),
                        domain_authority=estimate_domain_authority(url),
                        tool_name="ddg",
                    )
                )
        return results

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _search)
    except Exception as e:
        logger.error(f"DuckDuckGo search failed: {e}")
        return []

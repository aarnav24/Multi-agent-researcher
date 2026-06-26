"""ArXiv search tool — academic / scientific papers.

Rate limit handling: ArXiv allows ~1 request/second for free tier.
We truncate long queries and retry with exponential backoff on 429.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Optional

import arxiv
import httpx

from app.tools.base import ToolOutput, estimate_domain_authority, sanitize_snippet

logger = logging.getLogger(__name__)

# ArXiv free tier: ~1 req/sec. Be conservative.
_ARXIV_DELAY_SECONDS = 1.5
_ARXIV_MAX_RETRIES = 3


def _sanitize_arxiv_query(query: str) -> str:
    """Convert a natural-language sub-question into an arXiv-friendly query.

    arXiv's search API works best with short keyword phrases, not long sentences.
    Strip question words, quotes, and special characters.
    """
    # Remove question marks
    query = query.rstrip("?").strip()

    # Remove common question prefixes
    prefixes = [
        "what are ", "what is ", "how do ", "how does ", "how can ",
        "why is ", "why are ", "when did ", "where is ", "which ",
        "who is ", "who are ", "is there ", "are there ", "can ",
        "does ", "do ", "has ", "have ",
    ]
    query_lower = query.lower()
    for prefix in prefixes:
        if query_lower.startswith(prefix):
            query = query[len(prefix):]
            break

    # Remove quotes and parentheses that break arXiv search
    query = query.replace('"', '').replace("(", " ").replace(")", " ")

    # Collapse multiple spaces
    query = re.sub(r'\s+', ' ', query).strip()

    # Truncate to 80 chars max (arXiv search works best with short queries)
    if len(query) > 80:
        query = query[:80].rsplit(' ', 1)[0]

    return query


async def arxiv_search(
    query: str,
    max_results: int = 5,
) -> list[ToolOutput]:
    """Search ArXiv for academic papers. Returns list of ToolOutput.

    Handles rate limits with exponential backoff and query sanitization.
    """
    clean_query = _sanitize_arxiv_query(query)
    if clean_query != query:
        logger.info(f"ArXiv: sanitize query '{query[:60]}...' → '{clean_query[:60]}'")

    for attempt in range(_ARXIV_MAX_RETRIES):
        try:
            # Rate limit: wait between requests
            if attempt > 0:
                wait = _ARXIV_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.info(f"ArXiv: retry {attempt}/{_ARXIV_MAX_RETRIES} after {wait}s")
                await asyncio.sleep(wait)
            else:
                # Small delay even on first request to be polite
                await asyncio.sleep(_ARXIV_DELAY_SECONDS)

            search = arxiv.Search(
                query=clean_query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance,
            )
            client = arxiv.Client()
            results: list[ToolOutput] = []
            for paper in client.results(search):
                url = paper.entry_id or ""
                results.append(
                    ToolOutput(
                        url=url,
                        title=paper.title or "",
                        snippet=sanitize_snippet((paper.summary or "")[:800]),
                        published_date=paper.published.date() if paper.published else None,
                        domain_authority=90.0,
                        tool_name="arxiv",
                    )
                )
            if results:
                logger.info(f"ArXiv: found {len(results)} papers for '{clean_query[:60]}'")
            return results

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(f"ArXiv: rate limited (429), attempt {attempt + 1}/{_ARXIV_MAX_RETRIES}")
                if attempt == _ARXIV_MAX_RETRIES - 1:
                    logger.error("ArXiv: rate limit retries exhausted")
                    return []
                continue
            logger.error(f"ArXiv: HTTP error {e.response.status_code}: {e}")
            return []
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate" in error_str:
                logger.warning(f"ArXiv: rate limited, attempt {attempt + 1}/{_ARXIV_MAX_RETRIES}")
                if attempt == _ARXIV_MAX_RETRIES - 1:
                    logger.error("ArXiv: rate limit retries exhausted")
                    return []
                continue
            logger.error(f"ArXiv search failed: {e}")
            return []

    return []

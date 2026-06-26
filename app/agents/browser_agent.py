"""Browser / Fetcher Worker agent — deep-fetches URLs surfaced by Searchers."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agents.base import BaseAgent
from app.tools.base import sanitize_content
from app.tools.browser_tool import fetch_url

logger = logging.getLogger(__name__)

BROWSER_SYSTEM = """You are a content extraction specialist. You receive the full text of a web page.

Your job:
1. Extract the key information relevant to the research question
2. Identify specific claims, data points, and quotes
3. Note any contradictions with other sources

Output JSON:
{
  "extracted_facts": ["fact1", "fact2"],
  "key_quotes": ["quote1"],
  "relevance": "high|medium|low",
  "summary": "2-3 sentence summary of page content"
}

Output ONLY valid JSON."""


class BrowserAgent(BaseAgent):
    model_tier = "fast"
    system_prompt = BROWSER_SYSTEM

    async def fetch_and_extract(
        self,
        url: str,
        research_question: str,
        max_chars: int = 8000,
    ) -> dict[str, Any]:
        """Fetch a URL and extract relevant information."""
        logger.info(f"Browser: fetching {url}")
        tool_output = await fetch_url(url, max_chars=max_chars)

        if not tool_output.full_content:
            return {
                "extracted_facts": [],
                "key_quotes": [],
                "relevance": "low",
                "summary": "Failed to fetch content",
                "source": tool_output.model_dump(),
            }

        # Defense: sanitize fetched content to prevent prompt injection
        # from malicious pages containing "ignore previous instructions" etc.
        sanitized_content = sanitize_content(tool_output.full_content[:6000])

        prompt = (
            f"Research question: {research_question}\n\n"
            f"Page content from {url}:\n\n{sanitized_content}\n\n"
            f"Extract relevant facts, quotes, and assess relevance."
        )
        response = await self.run(prompt)

        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
            if match:
                parsed = json.loads(match.group(1))
            else:
                parsed = {"extracted_facts": [], "key_quotes": [], "relevance": "medium", "summary": response[:500]}

        parsed["source"] = tool_output.model_dump()
        return parsed

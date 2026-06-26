"""Browser / Fetcher tool — two-tier fetching: fast HTTP first, Playwright fallback.

Separated from Searchers because fetching is slow and benefits from its
own concurrency pool. Handles JS-rendered pages, PDFs, paywalled previews.

Strategy:
  1. Try fast httpx fetch first (no JS, ~0.5-2s)
  2. Fall back to Playwright only if content is too short (JS-heavy page)

This avoids the 30s Playwright penalty for every URL.
"""

from __future__ import annotations

import asyncio
import logging

from app.tools.base import ToolOutput, sanitize_content, estimate_domain_authority

logger = logging.getLogger(__name__)

# Module-level Playwright browser instance (lazy init)
_playwright = None
_browser = None
_browser_context = None  # Reuse a single context across fetches

# Fast-fetch threshold: if httpx gets fewer chars than this, use Playwright
# Lowered from 500 → 300 so more URLs skip the slow Playwright path
_MIN_CONTENT_CHARS = 300

# ── Fast HTTP fetch (httpx) ──────────────────────────────────────────────────

async def _fetch_url_fast(url: str) -> str | None:
    """Try fetching URL with httpx (fast, no JS). Returns content or None."""
    try:
        import httpx
        async with httpx.AsyncClient(
            timeout=10,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                # Try to extract text from HTML
                content_type = resp.headers.get("content-type", "")
                if "text/html" in content_type:
                    from html.parser import HTMLParser

                    class _TextExtractor(HTMLParser):
                        def __init__(self):
                            super().__init__()
                            self._skip = {"script", "style", "nav", "footer", "header"}
                            self._tag_stack: list[str] = []
                            self._parts: list[str] = []
                        def handle_starttag(self, tag, attrs):
                            self._tag_stack.append(tag)
                        def handle_endtag(self, tag):
                            if self._tag_stack and self._tag_stack[-1] == tag:
                                self._tag_stack.pop()
                        def handle_data(self, data):
                            if not any(t in self._tag_stack for t in self._skip):
                                stripped = data.strip()
                                if stripped:
                                    self._parts.append(stripped)

                    extractor = _TextExtractor()
                    extractor.feed(resp.text)
                    return "\n".join(extractor._parts)
                else:
                    # Plain text / other
                    return resp.text
            return None
    except Exception as e:
        logger.debug(f"Fast fetch failed for {url}: {e}")
        return None


def _smart_truncate(text: str, max_chars: int) -> str:
    """Truncate text intelligently: head + tail + middle.

    Instead of just taking the first N chars (which misses conclusions),
    we take:
    - Head: first 40% (introduction, key claims)
    - Tail: last 25% (conclusions, final analysis)
    - Middle: middle 35% (key details, data)

    This captures the most important parts of articles and papers.
    """
    if len(text) <= max_chars:
        return text

    head_len = int(max_chars * 0.40)  # 40% from start
    tail_len = int(max_chars * 0.25)  # 25% from end
    mid_len = max_chars - head_len - tail_len  # 35% from middle

    head = text[:head_len]

    # Middle section: take from the center of the remaining text
    mid_start = (len(text) - mid_len) // 2
    mid = text[mid_start:mid_start + mid_len]

    tail = text[-tail_len:]

    return (
        f"{head}\n\n"
        f"...[middle section]...\n\n"
        f"{mid}\n\n"
        f"...[conclusion]...\n\n"
        f"{tail}"
    )


# ── Playwright fetch (slow, JS-capable) ──────────────────────────────────────

async def _get_browser_context():
    """Get or create a shared Playwright browser context."""
    global _playwright, _browser, _browser_context
    if _browser_context is None:
        from playwright.async_api import async_playwright
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
        _browser_context = await _browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    return _browser_context


async def close_browser():
    """Shutdown Playwright browser."""
    global _playwright, _browser, _browser_context
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()
    _browser = None
    _playwright = None
    _browser_context = None


async def _fetch_url_playwright(url: str, max_chars: int = 8000) -> ToolOutput:
    """Deep-fetch a URL using Playwright. Returns ToolOutput with full_content."""
    try:
        context = await _get_browser_context()
        page = await context.new_page()
        # Use "commit" instead of "domcontentloaded" — don't wait for all resources
        await page.goto(url, wait_until="commit", timeout=30000)

        # Give the page a moment for JS to render text
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass  # Continue even if domcontentloaded times out

        # Extract main text content
        content = await page.evaluate("""() => {
            const selectors = ['article', 'main', '.content', '#content', 'body'];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText && el.innerText.length > 200) {
                    return el.innerText;
                }
            }
            return document.body ? document.body.innerText : '';
        }""")

        title = await page.title()
        await page.close()

        sanitized = sanitize_content(content) if content else ""

        # Smart truncation: head + tail + middle instead of just first N chars
        # Captures introduction, conclusions, and key middle content
        truncated = _smart_truncate(sanitized, max_chars)

        return ToolOutput(
            url=url,
            title=title or url,
            snippet=truncated[:800],
            full_content=truncated,
            domain_authority=estimate_domain_authority(url),
            tool_name="browser",
        )
    except Exception as e:
        logger.error(f"Browser fetch failed for {url}: {e}")
        return ToolOutput(
            url=url,
            title="",
            snippet=f"[Fetch failed: {e}]",
            domain_authority=0.0,
            tool_name="browser",
        )


# ── Unified fetch with fast-first strategy ───────────────────────────────────

async def fetch_url(
    url: str,
    max_chars: int = 8000,
) -> ToolOutput:
    """Fetch a URL using a fast-first strategy.

    1. Try httpx (fast, ~0.5-2s) — works for 80% of pages
    2. Fall back to Playwright if content is too short (needs JS rendering)
    """
    # Try fast fetch first
    fast_content = await _fetch_url_fast(url)
    if fast_content and len(fast_content.strip()) >= _MIN_CONTENT_CHARS:
        logger.info(f"Fast fetch succeeded for {url} ({len(fast_content)} chars)")
        truncated = fast_content[:max_chars]
        return ToolOutput(
            url=url,
            title=url,
            snippet=truncated[:800],
            full_content=truncated,
            domain_authority=estimate_domain_authority(url),
            tool_name="httpx",
        )

    # Fall back to Playwright for JS-heavy pages
    logger.info(f"Fast fetch insufficient ({len(fast_content or '')} chars), using Playwright for {url}")
    return await _fetch_url_playwright(url, max_chars=max_chars)


async def fetch_urls_parallel(urls: list[str], max_chars: int = 8000) -> list[ToolOutput]:
    """Fetch multiple URLs concurrently."""
    tasks = [fetch_url(url, max_chars) for url in urls]
    return await asyncio.gather(*tasks)

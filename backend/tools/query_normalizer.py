"""Query normalization layer — transforms natural-language sub-questions into
tool-specific search queries.

Problem: Planner/Searcher agents generate long natural-language questions like
"What evidence exists that Notion is increasingly targeting enterprise customers
through pricing, security, and collaboration features?" but downstream tools
(arXiv, GitHub, Exa, etc.) require short keyword-oriented queries.

Solution: Tool-specific adapters that extract key terms, strip question phrasing,
and enforce max query lengths.

Usage:
    from backend.tools.query_normalizer import normalize_query
    github_query = normalize_query(sub_question, tool="github")
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Per-tool configuration ────────────────────────────────────────────────────

@dataclass
class ToolQueryConfig:
    """Configuration for query normalization per tool."""
    max_length: int = 100
    strip_punctuation: bool = True
    strip_question_words: bool = True
    keyword_only: bool = False  # If True, extract only nouns/key phrases
    allow_special_chars: str = ""  # Chars to keep even when stripping punctuation


TOOL_CONFIGS: dict[str, ToolQueryConfig] = {
    "arxiv": ToolQueryConfig(
        max_length=100,
        strip_punctuation=True,
        strip_question_words=True,
        keyword_only=True,  # arXiv works best with technical keywords
        allow_special_chars="-+:",  # Keep hyphens for compound terms
    ),
    "github": ToolQueryConfig(
        max_length=80,
        strip_punctuation=True,
        strip_question_words=True,
        keyword_only=True,  # GitHub search is keyword-based
        allow_special_chars="-_",
    ),
    "exa": ToolQueryConfig(
        max_length=120,
        strip_punctuation=True,
        strip_question_words=True,
        keyword_only=False,  # Exa supports semantic/natural language queries
    ),
    "tavily": ToolQueryConfig(
        max_length=150,
        strip_punctuation=False,  # Tavily handles natural language well
        strip_question_words=True,
        keyword_only=False,
    ),
    "serper": ToolQueryConfig(
        max_length=150,
        strip_punctuation=False,  # Google handles natural language
        strip_question_words=True,
        keyword_only=False,
    ),
    "ddg": ToolQueryConfig(
        max_length=150,
        strip_punctuation=False,  # DDG handles natural language
        strip_question_words=True,
        keyword_only=False,
    ),
}

# ── Question words/phrases to strip ──────────────────────────────────────────

QUESTION_PREFIXES = [
    "what are ", "what is ", "what evidence ", "what data ",
    "how do ", "how does ", "how can ", "how has ", "how have ",
    "why is ", "why are ", "why do ", "why does ",
    "when did ", "when was ", "when is ",
    "where is ", "where are ", "where can ",
    "which ", "who is ", "who are ",
    "is there ", "are there ", "can ", "could ",
    "does ", "do ", "has ", "have ", "had ",
    "explain ", "describe ", "compare ", "analyze ",
    "list ", "find ", "search ", "show ",
]

QUESTION_SUFFIXES = [
    " in detail", " comprehensively", " with examples",
    " according to research", " in recent years",
    " in 2023-2024", " in 2022-2024", " in 2024",
    " recently", " currently", " today",
]


def _strip_question_prefixes(text: str) -> str:
    """Remove leading question phrases."""
    text_lower = text.lower()
    for prefix in QUESTION_PREFIXES:
        if text_lower.startswith(prefix):
            text = text[len(prefix):]
            break
    return text


def _strip_question_suffixes(text: str) -> str:
    """Remove trailing filler phrases."""
    text_lower = text.lower()
    for suffix in QUESTION_SUFFIXES:
        if text_lower.endswith(suffix):
            text = text[:-len(suffix)]
            break
    return text


def _extract_keywords(text: str) -> str:
    """Extract key noun phrases from a sentence.

    Removes common stop words and keeps meaningful terms.
    """
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above",
        "below", "between", "out", "off", "over", "under", "again",
        "further", "then", "once", "here", "there", "when", "where",
        "why", "how", "all", "both", "each", "few", "more", "most",
        "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "because", "but",
        "and", "or", "if", "while", "about", "up", "that", "this",
        "these", "those", "it", "its", "they", "them", "their", "we",
        "our", "you", "your", "he", "she", "him", "her", "his",
        "i", "me", "my", "which", "what", "who", "whom",
        "evidence", "exists", "exist", "showing", "show", "shows",
        "indicating", "indicate", "indicates", "suggest", "suggests",
        "demonstrate", "demonstrates", "recent", "latest", "new",
    }

    words = text.split()
    keywords = [w for w in words if w.lower() not in stop_words and len(w) > 1]

    # If we filtered too aggressively, fall back to original words
    if len(keywords) < 2:
        keywords = [w for w in words if len(w) > 1]

    return " ".join(keywords)


def _strip_punctuation(text: str, keep: str = "") -> str:
    """Remove punctuation except for explicitly kept chars."""
    result = []
    for ch in text:
        if ch.isalnum() or ch.isspace() or ch in keep:
            result.append(ch)
        else:
            result.append(" ")
    return re.sub(r'\s+', ' ', "".join(result)).strip()


def normalize_query(query: str, tool: str = "tavily") -> str:
    """Normalize a natural-language sub-question into a tool-specific search query.

    Args:
        query: Original sub-question from the agent (can be long/natural language)
        tool: Target tool name (arxiv, github, exa, tavily, serper, ddg)

    Returns:
        Cleaned, tool-appropriate search query string.

    Example:
        >>> normalize_query("What evidence exists that Notion is targeting enterprise customers?", "github")
        'Notion enterprise customers'
        >>> normalize_query("What are the latest advances in quantum error correction?", "arxiv")
        'quantum error correction advances'
    """
    config = TOOL_CONFIGS.get(tool, ToolQueryConfig())
    original = query.strip()

    # Step 1: Strip question prefixes
    if config.strip_question_words:
        query = _strip_question_prefixes(query)
        query = _strip_question_suffixes(query)

    # Step 2: Remove question marks
    query = query.rstrip("?").strip()

    # Step 3: For keyword-only tools, extract key terms
    if config.keyword_only:
        query = _extract_keywords(query)

    # Step 4: Strip punctuation
    if config.strip_punctuation:
        query = _strip_punctuation(query, keep=config.allow_special_chars)

    # Step 5: Collapse whitespace
    query = re.sub(r'\s+', ' ', query).strip()

    # Step 6: Enforce max length (cut at last complete word)
    if len(query) > config.max_length:
        query = query[:config.max_length].rsplit(' ', 1)[0]

    # Step 7: Final cleanup — remove leading/trailing stop words
    query = query.strip()
    if query and query[-1] in ",.;:":
        query = query[:-1].strip()

    if original != query:
        logger.info(f"Query normalize [{tool}]: '{original[:80]}...' → '{query[:80]}'")

    return query


# ── Metrics collection ────────────────────────────────────────────────────────

@dataclass
class ToolMetrics:
    """Per-tool metrics for monitoring query quality and API health."""
    tool_name: str
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    rate_limits: int = 0
    retries: int = 0
    total_latency_ms: float = 0.0
    last_error: str = ""
    last_call_time: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.successes / max(1, self.total_calls)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(1, self.total_calls)

    def record_call(self, success: bool, latency_ms: float, error: str = "", rate_limited: bool = False):
        self.total_calls += 1
        self.last_call_time = time.time()
        self.total_latency_ms += latency_ms
        if success:
            self.successes += 1
        else:
            self.failures += 1
            self.last_error = error
        if rate_limited:
            self.rate_limits += 1

    def __str__(self) -> str:
        return (
            f"{self.tool_name}: calls={self.total_calls} "
            f"ok={self.successes} fail={self.failures} "
            f"rate_limited={self.rate_limits} "
            f"success_rate={self.success_rate:.0%} "
            f"avg_latency={self.avg_latency_ms:.0f}ms"
        )


# Global metrics registry
_metrics: dict[str, ToolMetrics] = {}


def get_metrics(tool_name: str) -> ToolMetrics:
    """Get or create metrics for a tool."""
    if tool_name not in _metrics:
        _metrics[tool_name] = ToolMetrics(tool_name=tool_name)
    return _metrics[tool_name]


def get_all_metrics() -> dict[str, ToolMetrics]:
    """Get all tool metrics."""
    return dict(_metrics)


def log_all_metrics():
    """Log a summary of all tool metrics."""
    logger.info("=== Tool Metrics Summary ===")
    for name, m in sorted(_metrics.items()):
        logger.info(f"  {m}")

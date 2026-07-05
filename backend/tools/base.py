"""Unified tool output schema + content sanitization for prompt injection prevention."""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class ToolOutput(BaseModel):
    """Every tool returns this same schema regardless of which API produced it."""
    source_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    url: str = ""
    title: str = ""
    snippet: str = ""  # ~200 token summary
    full_content: Optional[str] = None  # fetched on demand by Browser Worker
    published_date: Optional[date] = None
    domain_authority: float = Field(default=0.0, ge=0.0, le=100.0)  # 0–100
    tool_name: str = ""  # "tavily" | "arxiv" | "github" | "serper" | "exa" | "ddg" | "browser" | "pgvector"

    def model_post_init(self, __context):
        """Auto-estimate domain authority from URL if not explicitly set."""
        if self.domain_authority == 0.0 and self.url:
            self.domain_authority = estimate_domain_authority(self.url)


def _strip_injection_patterns(text: str) -> str:
    """Remove common prompt injection patterns from text."""
    text = re.sub(
        r'ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instructions?',
        '[REMOVED-INJECTION]',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'you\s+are\s+now\s+(a|an)\s+',
        '[ROLE-OVERRIDE-REMOVED] ',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'(system|developer|admin)\s*:\s*',
        '[REMOVED-PREFIX] ',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'<\s*/\s*untrusted_content\s*>',
        '',
        text,
        flags=re.IGNORECASE,
    )
    return text


def sanitize_snippet(snippet: str) -> str:
    """Sanitize a search result snippet against prompt injection.

    Lighter than sanitize_content — just strips injection patterns
    without wrapping in <untrusted_content> tags (which would bloat context).
    """
    return _strip_injection_patterns(snippet)


def sanitize_content(content: str) -> str:
    """Wrap fetched web content in <untrusted_content> tags to prevent prompt injection.

    This is the defense against malicious pages that contain
    "ignore previous instructions" type attacks.
    """
    stripped = _strip_injection_patterns(content)
    return f"<untrusted_content>\n{stripped}\n</untrusted_content>"


# ── Domain authority lookup (simplified) ──────────────────────────────────────

HIGH_AUTHORITY_DOMAINS = {
    # Academic / scientific
    "arxiv.org", "nature.com", "science.org", "nih.gov", "ncbi.nlm.nih.gov",
    "pnas.org", "cell.com", "thelancet.com", "nejm.org", "aps.org",
    "iop.org", "acs.org", "rsc.org", "frontiersin.org", "mdpi.com",
    "semanticscholar.org", "inspirehep.net", "biorxiv.org", "medrxiv.org",
    "plos.org", "elifesciences.org", "embopress.org", "jbc.org",
    # Tech / industry research
    "research.google", "research.facebook.com", "microsoft.com/en-us/research",
    "deepmind.google", "openai.com/research", "anthropic.com/research",
    "riverlane.com", "quantinuum.com", "ibm.com/blogs/research",
    "rigetti.com", "ionq.com", "xanadu.ai", "nvidia.com/en-us/research",
    "intel.com/content/www/us/en/research", "amd.com/en/technologies",
    # News / general — tier 1 (most authoritative)
    "reuters.com", "apnews.com", "bbc.com", "economist.com", "wsj.com",
    "ft.com", "nytimes.com", "washingtonpost.com", "theguardian.com",
    # News / general — tier 2
    "wired.com", "technologyreview.com", "scientificamerican.com",
    "physicsworld.com", "phys.org", "newscientist.com", "mit.edu",
    "stanford.edu", "harvard.edu", "caltech.edu", "cam.ac.uk",
    "ox.ac.uk", "imperial.ac.uk",
    # Encyclopedic / reference
    "wikipedia.org", "britannica.com", "scholarpedia.org",
    # Code / developer
    "github.com", "stackoverflow.com", "gitlab.com", "docs.python.org",
    "developer.mozilla.org", "docs.microsoft.com",
    # Government / international
    "who.int", "un.org", "worldbank.org", "imf.org", "oecd.org",
    "nist.gov", "nsf.gov", "energy.gov", "nasa.gov", "noaa.gov",
}

MEDIUM_AUTHORITY_DOMAINS = {
    # Blogs / platforms (can have good content but variable quality)
    "medium.com", "substack.com", "towardsdatascience.com",
    "hackernoon.com", "dev.to", "hashnode.net",
    # Aggregators / portals
    "yahoo.com", "msn.com", "aol.com",
    # Tech news (good but less rigorous than tier-1)
    "techcrunch.com", "theverge.com", "arstechnica.com", "engadget.com",
    "zdnet.com", "cnet.com", "venturebeat.com",
    # Business news
    "bloomberg.com", "forbes.com", "businessinsider.com", "cnbc.com",
    "marketwatch.com",
}

# TLD-based authority boosts (checked when no domain match found)
HIGH_AUTHORITY_TLDS = {".edu", ".gov", ".ac.uk", ".ac.", ".gov.uk"}
MEDIUM_AUTHORITY_TLDS = {".org", ".net"}


def estimate_domain_authority(url: str) -> float:
    """Rough domain authority estimate (0–100).

    Three-tier lookup:
    1. Known high-authority domains → 85
    2. Known medium-authority domains → 60
    3. TLD-based heuristic (.edu/.gov → 75, .org/.net → 55)
    4. HTTPS default → 50, HTTP-only → 30
    """
    url_lower = url.lower()

    # Tier 1: Known high-authority domains
    for domain in HIGH_AUTHORITY_DOMAINS:
        if domain in url_lower:
            return 85.0

    # Tier 2: Known medium-authority domains
    for domain in MEDIUM_AUTHORITY_DOMAINS:
        if domain in url_lower:
            return 60.0

    # Tier 3: TLD-based heuristic
    for tld in HIGH_AUTHORITY_TLDS:
        if tld in url_lower:
            return 75.0
    for tld in MEDIUM_AUTHORITY_TLDS:
        if tld in url_lower:
            return 55.0

    # Tier 4: Protocol-based fallback
    if url_lower.startswith("https"):
        return 50.0
    return 30.0

"""Citation graph — directed graph of claims → sources → original URLs.

Built incrementally as findings arrive. Used by Citation Formatter
to verify every claim has a working source link.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CitationGraph:
    """In-memory directed graph: claim → source → URL."""

    def __init__(self):
        # claim_text -> list of source_ids
        self.claim_to_sources: dict[str, list[str]] = {}
        # source_id -> {url, title, snippet, ...}
        self.sources: dict[str, dict] = {}
        # claim_text -> trust_score
        self.claim_trust: dict[str, int] = {}

    def add_claim(self, claim: str, sources: list[dict], trust_score: int = 0):
        """Add a claim with its supporting sources."""
        source_ids = []
        for src in sources:
            sid = src.get("source_id", "")
            if sid:
                self.sources[sid] = src
                source_ids.append(sid)
        self.claim_to_sources[claim] = source_ids
        self.claim_trust[claim] = trust_score

    def get_sources_for_claim(self, claim: str) -> list[dict]:
        """Get all sources for a claim."""
        sids = self.claim_to_sources.get(claim, [])
        return [self.sources[sid] for sid in sids if sid in self.sources]

    def get_trust(self, claim: str) -> int:
        return self.claim_trust.get(claim, 0)

    def all_claims(self) -> list[str]:
        return list(self.claim_to_sources.keys())

    def all_sources(self) -> list[dict]:
        return list(self.sources.values())

    def to_dict(self) -> dict:
        return {
            "claims": {
                claim: {
                    "sources": self.get_sources_for_claim(claim),
                    "trust_score": self.claim_trust.get(claim, 0),
                }
                for claim in self.claim_to_sources
            },
            "source_count": len(self.sources),
        }

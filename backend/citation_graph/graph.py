"""Citation Graph — high-level API for building and querying the claim→source graph.

Wraps Neo4jAdapter with domain-specific methods for the research pipeline.
Falls back to in-memory storage when Neo4j is disabled, so the same
`CitationGraph` API works in both modes (no Neo4j dependency required).

Nodes are added incrementally as verified claims arrive from the fact-checker.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from backend.citation_graph.neo4j_adapter import Neo4jAdapter

logger = logging.getLogger(__name__)


class CitationGraph:
    """Domain-specific citation graph.

    If the adapter is Neo4j-enabled, data is persisted to Neo4j. Otherwise,
    operations fall back to an in-memory dict store with the same semantics
    for queries (sources, related claims, stats, etc.).
    """

    def __init__(self, adapter: Neo4jAdapter):
        self._adapter = adapter
        self._use_in_memory = not adapter.enabled
        # In-memory fallback stores (keyed by claim_id / source_id / sq_id).
        # Populated whenever a write goes to in-memory instead of Neo4j.
        self._mem_claims: dict[str, dict] = {}
        self._mem_sources: dict[str, dict] = {}
        self._mem_sub_questions: dict[str, str] = {}
        # Edges stored as adjacency lists: source_id -> list of claim_ids
        self._mem_supports: dict[str, set[str]] = {}      # source -> claims
        self._mem_contradicts: dict[str, set[str]] = {}   # source -> claims
        # claim -> supporting source_ids (only the supports side)
        self._mem_claim_supports: dict[str, set[str]] = {}
        # claim -> claims related (related-claims we derive during finalize)
        self._mem_related_pairs: set[tuple[str, str]] = set()
        # claim -> sub_question_id
        self._mem_answers: dict[str, str] = {}
        if self._use_in_memory:
            logger.info("CitationGraph: Neo4j unavailable, using in-memory fallback")

    @property
    def is_in_memory(self) -> bool:
        return self._use_in_memory

    # ── Write operations ──────────────────────────────────────────────────

    async def add_sub_question(self, sq_id: str, question: str) -> bool:
        """Add a SubQuestion node (call during orchestrator)."""
        if self._use_in_memory:
            self._mem_sub_questions[sq_id] = question
            return True
        return await self._adapter.add_sub_question(sq_id, question)

    async def add_verified_claim(
        self,
        claim_text: str,
        trust_score: int,
        trust_label: str,
        fact_check_passed: bool,
        sources: list[dict],
        sub_question_id: str | None = None,
    ) -> str:
        """Add a Claim node with SUPPORTS edges to its sources.

        Args:
            claim_text: The verified claim text.
            trust_score: 0-100 trust score.
            trust_label: HIGH | MODERATE | LOW.
            fact_check_passed: Whether independent fact-check passed.
            sources: List of source dicts with 'url', 'title', 'snippet', etc.
            sub_question_id: Optional ID of the sub-question this claim answers.

        Returns:
            The claim_id of the added claim.
        """
        claim_id = str(uuid.uuid4())

        if self._use_in_memory:
            self._mem_claims[claim_id] = {
                "claim_id": claim_id,
                "text": claim_text,
                "trust_score": trust_score,
                "trust_label": trust_label,
                "fact_check_passed": fact_check_passed,
                "sub_question_id": sub_question_id,
            }
            source_ids = []
            for src in sources:
                source_id = src.get("source_id") or str(uuid.uuid4())
                self._mem_sources[source_id] = {
                    "source_id": source_id,
                    "url": src.get("url", ""),
                    "title": src.get("title", ""),
                    "snippet": src.get("snippet", ""),
                    "domain_authority": src.get("domain_authority", 0.0),
                    "tool_name": src.get("tool_name", ""),
                    "published_date": src.get("published_date"),
                }
                self._mem_supports.setdefault(source_id, set()).add(claim_id)
                source_ids.append(source_id)
            self._mem_claim_supports[claim_id] = set(source_ids)

            if sub_question_id:
                self._mem_sub_questions.setdefault(
                    sub_question_id, f"Sub-question {sub_question_id}"
                )
                self._mem_answers[claim_id] = sub_question_id

            logger.info(f"CitationGraph [mem]: added claim {claim_id[:8]}... with {len(sources)} sources")
            return claim_id

        # Neo4j path
        await self._adapter.add_claim(
            claim_id=claim_id,
            text=claim_text,
            trust_score=trust_score,
            trust_label=trust_label,
            fact_check_passed=fact_check_passed,
            sub_question_id=sub_question_id,
        )

        for src in sources:
            source_id = src.get("source_id") or str(uuid.uuid4())
            await self._adapter.add_source(
                source_id=source_id,
                url=src.get("url", ""),
                title=src.get("title", ""),
                snippet=src.get("snippet", ""),
                domain_authority=src.get("domain_authority", 0.0),
                tool_name=src.get("tool_name", ""),
                published_date=src.get("published_date"),
            )
            await self._adapter.add_supports_edge(
                claim_id=claim_id,
                source_id=source_id,
                weight=float(trust_score),
            )

        if sub_question_id:
            await self._adapter.add_sub_question(sub_question_id, f"Sub-question {sub_question_id}")
            await self._adapter.add_answers_edge(claim_id, sub_question_id)

        logger.info(f"CitationGraph: added claim {claim_id[:8]}... with {len(sources)} sources")
        return claim_id

    async def add_rejected_claim(
        self,
        claim_text: str,
        reason: str,
        contradicting_sources: list[dict],
        sub_question_id: str | None = None,
    ) -> str:
        """Add a rejected claim with CONTRADICTS edges to sources that disprove it."""
        claim_id = str(uuid.uuid4())

        if self._use_in_memory:
            self._mem_claims[claim_id] = {
                "claim_id": claim_id,
                "text": claim_text,
                "trust_score": 0,
                "trust_label": "LOW",
                "fact_check_passed": False,
                "sub_question_id": sub_question_id,
                "rejected": True,
                "reason": reason,
            }
            for src in contradicting_sources:
                source_id = src.get("source_id") or str(uuid.uuid4())
                self._mem_sources[source_id] = {
                    "source_id": source_id,
                    "url": src.get("url", ""),
                    "title": src.get("title", ""),
                    "snippet": src.get("snippet", ""),
                    "domain_authority": src.get("domain_authority", 0.0),
                    "tool_name": src.get("tool_name", ""),
                    "published_date": src.get("published_date"),
                }
                self._mem_contradicts.setdefault(source_id, set()).add(claim_id)

            if sub_question_id:
                self._mem_sub_questions.setdefault(
                    sub_question_id, f"Sub-question {sub_question_id}"
                )
                self._mem_answers[claim_id] = sub_question_id

            logger.info(f"CitationGraph [mem]: added REJECTED claim {claim_id[:8]}... ({len(contradicting_sources)} contradictions)")
            return claim_id

        # Neo4j path
        await self._adapter.add_claim(
            claim_id=claim_id,
            text=claim_text,
            trust_score=0,
            trust_label="LOW",
            fact_check_passed=False,
            sub_question_id=sub_question_id,
        )

        for src in contradicting_sources:
            source_id = src.get("source_id") or str(uuid.uuid4())
            await self._adapter.add_source(
                source_id=source_id,
                url=src.get("url", ""),
                title=src.get("title", ""),
                snippet=src.get("snippet", ""),
                domain_authority=src.get("domain_authority", 0.0),
                tool_name=src.get("tool_name", ""),
                published_date=src.get("published_date"),
            )
            await self._adapter.add_contradicts_edge(
                claim_id=claim_id,
                source_id=source_id,
                weight=0.0,
            )

        if sub_question_id:
            await self._adapter.add_sub_question(sub_question_id, f"Sub-question {sub_question_id}")
            await self._adapter.add_answers_edge(claim_id, sub_question_id)

        logger.info(f"CitationGraph: added REJECTED claim {claim_id[:8]}... ({len(contradicting_sources)} contradictions)")
        return claim_id

    async def add_unverified_source(
        self,
        url: str,
        title: str,
        snippet: str,
        tool_name: str,
        sub_question_id: str | None = None,
    ) -> str:
        """Add a searcher-provided source that hasn't been fact-checked yet.

        These appear in the citation graph as unverified source nodes,
        distinguishable from verified claims by having no SUPPORTS edge
        from a verified claim.
        """
        source_id = str(uuid.uuid4())

        if self._use_in_memory:
            self._mem_sources[source_id] = {
                "source_id": source_id,
                "url": url,
                "title": title,
                "snippet": snippet,
                "tool_name": tool_name,
                "verified": False,
            }
            if sub_question_id:
                self._mem_sub_questions.setdefault(
                    sub_question_id, f"Sub-question {sub_question_id}"
                )
            logger.info(f"CitationGraph [mem]: added unverified source {source_id[:8]}... ({tool_name})")
            return source_id

        # Neo4j path — add source without any claim edge
        from datetime import date
        await self._adapter.add_source(
            source_id=source_id,
            url=url,
            title=title,
            snippet=snippet,
            tool_name=tool_name,
            published_date=date.today().isoformat(),
        )
        if sub_question_id:
            await self._adapter.add_sub_question(sub_question_id, f"Sub-question {sub_question_id}")

        logger.info(f"CitationGraph: added unverified source {source_id[:8]}... ({tool_name})")
        return source_id

    async def finalize(self) -> int:
        """Run after all claims are added. Creates RELATED edges between claims sharing sources."""
        if self._use_in_memory:
            count = 0
            # Build related-claim pairs: two claims are related if they share any source.
            source_to_claims: dict[str, list[str]] = {}
            for source_id, claim_set in self._mem_supports.items():
                if len(claim_set) >= 2:
                    source_to_claims[source_id] = sorted(claim_set)
            found: set[tuple[str, str]] = set()
            for claim_ids in source_to_claims.values():
                for i in range(len(claim_ids)):
                    for j in range(i + 1, len(claim_ids)):
                        a, b = claim_ids[i], claim_ids[j]
                        key = (a, b) if a < b else (b, a)
                        if key not in found:
                            found.add(key)
                            self._mem_related_pairs.add(key)
                            count += 1
            logger.info(f"CitationGraph [mem]: finalized — created {count} RELATED edges")
            return count
        count = await self._adapter.add_related_edges()
        logger.info(f"CitationGraph: finalized — created {count} RELATED edges")
        return count

    # ── Query methods ─────────────────────────────────────────────────────

    async def get_claim_sources(self, claim_id: str) -> list[dict]:
        """Get all sources for a claim."""
        if self._use_in_memory:
            source_ids = self._mem_claim_supports.get(claim_id, set())
            return [self._mem_sources[sid] for sid in source_ids if sid in self._mem_sources]
        return await self._adapter.get_claim_sources(claim_id)

    async def get_source_claims(self, source_id: str) -> list[dict]:
        """Get all claims supported by a source."""
        if self._use_in_memory:
            claim_ids = self._mem_supports.get(source_id, set())
            return [self._mem_claims[cid] for cid in claim_ids if cid in self._mem_claims]
        return await self._adapter.get_source_claims(source_id)

    async def get_related_claims(self, claim_id: str) -> list[dict]:
        """Get claims related to the given claim."""
        if self._use_in_memory:
            result: list[dict] = []
            for a, b in self._mem_related_pairs:
                if a == claim_id and b in self._mem_claims:
                    result.append(self._mem_claims[b])
                elif b == claim_id and a in self._mem_claims:
                    result.append(self._mem_claims[a])
            return result
        return await self._adapter.get_related_claims(claim_id)

    async def get_high_trust_claims(self, min_score: int = 70) -> list[dict]:
        """Get claims with trust >= min_score."""
        if self._use_in_memory:
            return [
                c for c in self._mem_claims.values()
                if c.get("trust_score", 0) >= min_score and not c.get("rejected", False)
            ]
        return await self._adapter.get_high_trust_claims(min_score)

    async def get_stats(self) -> dict:
        """Get graph statistics."""
        if self._use_in_memory:
            return {
                "node_counts": {
                    "Claims": len(self._mem_claims),
                    "Sources": len(self._mem_sources),
                    "SubQuestions": len(self._mem_sub_questions),
                },
                "relationship_counts": {
                    "SUPPORTS": sum(len(v) for v in self._mem_supports.values()),
                    "CONTRADICTS": sum(len(v) for v in self._mem_contradicts.values()),
                    "ANSWERS": len(self._mem_answers),
                    "RELATED": len(self._mem_related_pairs),
                },
            }
        return await self._adapter.get_stats()

    async def get_subgraph(self, claim_id: str, depth: int = 2) -> dict:
        """Get subgraph centered on a claim."""
        if self._use_in_memory:
            nodes: list[dict] = []
            edges: list[dict] = []
            visited: set[str] = {claim_id}

            # Center claim node
            center = self._mem_claims.get(claim_id)
            if center:
                nodes.append({"id": claim_id, "label": "Claim", **center})

            # Hop 1: sources of this claim + claims related to it
            claim_sources = self._mem_claim_supports.get(claim_id, set())
            for sid in claim_sources:
                if sid not in visited:
                    visited.add(sid)
                    src = self._mem_sources.get(sid)
                    if src:
                        nodes.append({"id": sid, "label": "Source", **src})
                    edges.append({"source": claim_id, "target": sid, "type": "SUPPORTS"})

            related = self._mem_claims.get(claim_id) and [
                self._mem_claims.get(other_id)
                for other_id in [
                    b if a == claim_id else a
                    for a, b in self._mem_related_pairs
                    if claim_id in (a, b)
                ]
            ] or []

            for c in related:
                if not c or c["claim_id"] in visited:
                    continue
                visited.add(c["claim_id"])
                nodes.append({"id": c["claim_id"], "label": "Claim", **c})
                edges.append({"source": claim_id, "target": c["claim_id"], "type": "RELATED"})

            return {"nodes": nodes, "edges": edges}
        return await self._adapter.get_subgraph(claim_id, depth)

    async def export(self) -> dict:
        """Export full graph for API response."""
        if self._use_in_memory:
            return {
                "enabled": True,
                "backend": "in_memory",
                "nodes": [
                    {"id": cid, "label": "Claim", **c} for cid, c in self._mem_claims.items()
                ] + [
                    {"id": sid, "label": "Source", **s} for sid, s in self._mem_sources.items()
                ] + [
                    {"id": sqid, "label": "SubQuestion", "question": q}
                    for sqid, q in self._mem_sub_questions.items()
                ],
                "edges": (
                    [
                        {"source": sid, "target": cid, "type": "SUPPORTS"}
                        for sid, cid_set in self._mem_supports.items()
                        for cid in cid_set
                    ]
                    + [
                        {"source": sid, "target": cid, "type": "CONTRADICTS"}
                        for sid, cid_set in self._mem_contradicts.items()
                        for cid in cid_set
                    ]
                    + [
                        {"source": cid, "target": sqid, "type": "ANSWERS"}
                        for cid, sqid in self._mem_answers.items()
                    ]
                    + [
                        {"source": a, "target": b, "type": "RELATED"}
                        for a, b in self._mem_related_pairs
                    ]
                ),
                "stats": await self.get_stats(),
            }
        return await self._adapter.export_all()

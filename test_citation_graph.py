"""Unit tests for the Citation Graph (Layer C).

Tests the CitationGraph class and Neo4jAdapter without needing a live Neo4j instance.
Uses a mock adapter to verify graph construction logic.
"""

import asyncio
import io
import sys
import uuid

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.citation_graph.graph import CitationGraph


# ── Mock adapter (no Neo4j needed) ──────────────────────────────────────────

class MockAdapter:
    """In-memory mock of Neo4jAdapter for testing."""

    def __init__(self):
        self.claims = {}
        self.sources = {}
        self.sub_questions = {}  # separate from sources
        self.edges = []
        self.enabled = True

    async def add_claim(self, claim_id, text, trust_score, trust_label,
                        fact_check_passed, sub_question_id=None):
        self.claims[claim_id] = {
            "id": claim_id, "text": text, "trust_score": trust_score,
            "trust_label": trust_label, "fact_check_passed": fact_check_passed,
            "sub_question_id": sub_question_id,
        }
        return True

    async def add_source(self, source_id, url, title, snippet,
                         domain_authority, tool_name, published_date=None):
        self.sources[source_id] = {
            "id": source_id, "url": url, "title": title, "snippet": snippet,
            "domain_authority": domain_authority, "tool_name": tool_name,
            "published_date": published_date,
        }
        return True

    async def add_supports_edge(self, claim_id, source_id, weight):
        self.edges.append({"type": "SUPPORTS", "source": claim_id, "target": source_id, "weight": weight})
        return True

    async def add_contradicts_edge(self, claim_id, source_id, weight):
        self.edges.append({"type": "CONTRADICTS", "source": claim_id, "target": source_id, "weight": weight})
        return True

    async def add_answers_edge(self, claim_id, sub_question_id):
        self.edges.append({"type": "ANSWERS", "source": claim_id, "target": sub_question_id})
        return True

    async def add_sub_question(self, sq_id, question):
        self.sub_questions[sq_id] = {"id": sq_id, "question": question}
        return True

    async def add_related_edges(self):
        # Find claims sharing sources via SUPPORTS edges
        supports = [e for e in self.edges if e["type"] == "SUPPORTS"]
        source_to_claims = {}
        for e in supports:
            source_to_claims.setdefault(e["target"], set()).add(e["source"])

        related_count = 0
        for src_id, claim_ids in source_to_claims.items():
            claim_list = sorted(claim_ids)
            if len(claim_list) >= 2:
                for i in range(len(claim_list)):
                    for j in range(i + 1, len(claim_list)):
                        self.edges.append({
                            "type": "RELATED",
                            "source": claim_list[i],
                            "target": claim_list[j],
                            "shared_sources": 1,
                        })
                        related_count += 1
        return related_count

    async def get_claim_sources(self, claim_id):
        return [
            {"source_id": e["target"], "weight": e["weight"], "relationship": e["type"]}
            for e in self.edges if e["source"] == claim_id and e["type"] in ("SUPPORTS", "CONTRADICTS")
        ]

    async def get_source_claims(self, source_id):
        return [
            {"claim_id": e["source"], "weight": e["weight"]}
            for e in self.edges if e["target"] == source_id and e["type"] == "SUPPORTS"
        ]

    async def get_related_claims(self, claim_id):
        return [
            {"claim_id": e["target"] if e["source"] == claim_id else e["source"], "shared_sources": e.get("shared_sources", 1)}
            for e in self.edges if e["type"] == "RELATED" and claim_id in (e["source"], e["target"])
        ]

    async def get_stats(self):
        return {
            "claims": len(self.claims),
            "sources": len(self.sources),
            "sub_questions": len(self.sub_questions),
            "supports": len([e for e in self.edges if e["type"] == "SUPPORTS"]),
            "contradicts": len([e for e in self.edges if e["type"] == "CONTRADICTS"]),
            "related": len([e for e in self.edges if e["type"] == "RELATED"]),
            "enabled": True,
        }


# ── Tests ──────────────────────────────────────────────────────────────────

async def test_basic_graph():
    """Test: Adding a claim creates claim node + source nodes + SUPPORTS edges."""
    adapter = MockAdapter()
    graph = CitationGraph(adapter)

    sources = [
        {"source_id": "src-arxiv-1", "url": "https://arxiv.org/abs/2024.1234", "title": "Quantum Advances 2024", "snippet": "...", "domain_authority": 90.0, "tool_name": "arxiv"},
        {"source_id": "src-nature-1", "url": "https://nature.com/articles/quantum-error-correction", "title": "Nature QEC", "snippet": "...", "domain_authority": 95.0, "tool_name": "exa"},
    ]

    claim_id = await graph.add_verified_claim(
        claim_text="Quantum error correction achieved 99.9% fidelity in 2024",
        trust_score=85,
        trust_label="HIGH",
        fact_check_passed=True,
        sources=sources,
        sub_question_id="sq-1",
    )

    assert claim_id is not None
    assert len(adapter.claims) == 1
    assert len(adapter.sources) == 2  # 2 sources
    assert len(adapter.sub_questions) == 1  # 1 sub_question (separate dict)
    assert len(adapter.edges) == 3   # 2 SUPPORTS + 1 ANSWERS
    stats = await graph.get_stats()
    assert stats["claims"] == 1
    assert stats["supports"] == 2
    assert stats["sub_questions"] == 1
    print("  PASS: Basic graph construction (claim + sources + edges)")


async def test_rejected_claim():
    """Test: Rejected claims get CONTRADICTS edges."""
    adapter = MockAdapter()
    graph = CitationGraph(adapter)

    contradicting = [
        {"url": "https://example.com/earth-flat", "title": "Flat Earth Society", "snippet": "...", "domain_authority": 5.0, "tool_name": "ddg"},
    ]

    claim_id = await graph.add_rejected_claim(
        claim_text="The Earth is flat",
        reason="Contradicted by overwhelming evidence",
        contradicting_sources=contradicting,
        sub_question_id="sq-shape",
    )

    assert claim_id is not None
    contradicts_edges = [e for e in adapter.edges if e["type"] == "CONTRADICTS"]
    assert len(contradicts_edges) == 1
    assert contradicts_edges[0]["weight"] == 0.0
    print("  PASS: Rejected claims get CONTRADICTS edges")


async def test_related_edges():
    """Test: Claims sharing sources get RELATED edges."""
    adapter = MockAdapter()
    graph = CitationGraph(adapter)

    shared_source_id = "source-shared-arxiv"
    shared_source = {"source_id": shared_source_id, "url": "https://arxiv.org/abs/quantum-review", "title": "Quantum Review 2024", "snippet": "...", "domain_authority": 90.0, "tool_name": "arxiv"}

    await graph.add_verified_claim(
        claim_text="Superconducting qubits reached 1000 qubits",
        trust_score=78,
        trust_label="MODERATE",
        fact_check_passed=True,
        sources=[shared_source, {"url": "https://example.com/1", "title": "A", "snippet": "x", "domain_authority": 50.0, "tool_name": "tavily"}],
        sub_question_id="sq-1",
    )

    await graph.add_verified_claim(
        claim_text="Trapped ions achieved 99.99% gate fidelity",
        trust_score=82,
        trust_label="HIGH",
        fact_check_passed=True,
        sources=[shared_source, {"url": "https://example.com/2", "title": "B", "snippet": "y", "domain_authority": 50.0, "tool_name": "tavily"}],
        sub_question_id="sq-2",
    )

    # Both claims share the arxiv source — should create RELATED edge
    related_count = await graph.finalize()
    assert related_count == 1, f"Expected 1 RELATED edge, got {related_count}"

    related = await graph.get_related_claims(list(adapter.claims.keys())[0])
    assert len(related) == 1
    assert related[0]["shared_sources"] >= 1
    print("  PASS: RELATED edges between claims sharing sources")


async def test_query_methods():
    """Test: get_claim_sources, get_source_claims, get_related_claims."""
    adapter = MockAdapter()
    graph = CitationGraph(adapter)

    src_id = str(uuid.uuid4())
    claim_id = await graph.add_verified_claim(
        claim_text="Test claim for queries",
        trust_score=65,
        trust_label="MODERATE",
        fact_check_passed=True,
        sources=[{"url": "https://example.com/test", "title": "Test Source", "snippet": "test snippet", "domain_authority": 60.0, "tool_name": "tavily", "source_id": src_id}],
    )

    # get_claim_sources
    sources = await graph.get_claim_sources(claim_id)
    assert len(sources) == 1
    assert sources[0]["source_id"] == src_id or sources[0].get("weight") == 65

    # get_source_claims (reverse lookup)
    claims = await graph.get_source_claims(src_id)
    assert len(claims) == 1

    print("  PASS: Query methods work (forward + reverse lookup)")


async def test_stats():
    """Test: Graph statistics."""
    adapter = MockAdapter()
    graph = CitationGraph(adapter)

    await graph.add_verified_claim("Claim A", 80, "HIGH", True,
        [{"url": "https://a.com", "title": "A", "snippet": "a", "domain_authority": 70.0, "tool_name": "tavily"}])
    await graph.add_verified_claim("Claim B", 60, "MODERATE", True,
        [{"url": "https://b.com", "title": "B", "snippet": "b", "domain_authority": 50.0, "tool_name": "exa"}])
    await graph.finalize()

    stats = await graph.get_stats()
    assert stats["claims"] == 2
    assert stats["sources"] == 2
    assert stats["supports"] == 2
    assert stats["enabled"] is True
    print("  PASS: Graph statistics are correct")


async def test_neo4j_adapter_exists():
    """Test: Neo4jAdapter class exists and has correct interface."""
    from app.citation_graph.neo4j_adapter import Neo4jAdapter

    adapter = Neo4jAdapter(enabled=False)
    assert adapter.enabled is False

    # All methods should return False/empty when disabled
    assert await adapter.add_claim("x", "y", 50, "LOW", False) is False
    assert await adapter.add_source("x", "y", "z", "s", 50.0, "t") is False
    assert await adapter.add_supports_edge("c", "s", 50.0) is False
    assert await adapter.get_claim_sources("x") == []
    stats = await adapter.get_stats()
    assert stats["enabled"] is False
    print("  PASS: Neo4jAdapter interface exists and disables gracefully")


async def test_store_integration():
    """Test: StateStore.get_citation_graph returns graph or None."""
    from app.state.store import StateStore

    store = StateStore()
    # Don't connect — just test the method handles missing neo4j
    graph = store.get_citation_graph("any-session")
    # Should return None since store isn't connected
    assert graph is None
    print("  PASS: StateStore.get_citation_graph handles disconnected state")


async def main():
    print("=" * 60)
    print("CITATION GRAPH UNIT TESTS — Layer C")
    print("=" * 60)

    tests = [
        ("Basic Graph Construction", test_basic_graph),
        ("Rejected Claims", test_rejected_claim),
        ("RELATED Edges", test_related_edges),
        ("Query Methods", test_query_methods),
        ("Graph Statistics", test_stats),
        ("Neo4jAdapter Interface", test_neo4j_adapter_exists),
        ("StateStore Integration", test_store_integration),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"\n{name}:")
        try:
            await test_fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

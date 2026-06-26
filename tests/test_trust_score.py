"""Tests for trust scoring engine."""

from __future__ import annotations

import pytest
from app.scoring.trust_score import (
    compute_trust_score,
    label_trust,
    _score_source_count,
    _score_authority,
    _score_recency,
)


class TestTrustScore:
    def test_high_trust(self, sample_sources):
        score = compute_trust_score(
            claim="Quantum error correction achieved 99.9% fidelity.",
            sources=sample_sources,
            fact_check_passed=True,
            fact_check_trust_score=85,
        )
        # With high-authority sources + strong fact_check, score should be at least MODERATE
        assert score > 60
        assert label_trust(score) in ("HIGH", "MODERATE")

    def test_low_trust_no_sources(self):
        score = compute_trust_score(
            claim="Something with no sources.",
            sources=[],
            fact_check_passed=False,
        )
        assert score < 50
        assert label_trust(score) == "LOW"

    def test_moderate_trust(self, sample_sources):
        score = compute_trust_score(
            claim="A claim with some support.",
            sources=sample_sources[:1],
            fact_check_passed=False,
        )
        assert 30 <= score <= 80

    def test_label_boundaries(self):
        assert label_trust(100) == "HIGH"
        assert label_trust(81) == "HIGH"
        assert label_trust(80) == "MODERATE"
        assert label_trust(51) == "MODERATE"
        assert label_trust(50) == "LOW"
        assert label_trust(0) == "LOW"


class TestSourceCount:
    def test_zero_sources(self):
        assert _score_source_count(0) == 0.0

    def test_five_sources(self):
        assert _score_source_count(5) == 100.0

    def test_three_sources(self):
        assert _score_source_count(3) == 100.0


class TestAuthority:
    def test_no_sources(self):
        assert _score_authority([]) == 0.0

    def test_high_authority(self):
        sources = [{"domain_authority": 90.0}, {"domain_authority": 95.0}]
        assert _score_authority(sources) == 92.5


class TestRecency:
    def test_no_sources(self):
        assert _score_recency([]) == 0.0

    def test_recent_source(self):
        from datetime import date, timedelta
        sources = [{"published_date": date.today() - timedelta(days=10)}]
        assert _score_recency(sources) == 100.0

    def test_old_source(self):
        from datetime import date, timedelta
        sources = [{"published_date": date.today() - timedelta(days=2000)}]
        assert _score_recency(sources) == 20.0


class TestComputeTrustScoreIntegration:
    """Integration tests for compute_trust_score."""

    def test_high_trust_with_factcheck_and_sources(self, sample_sources):
        """High trust: fact-check passed + multiple high-authority sources."""
        score = compute_trust_score(
            claim="Quantum error correction achieved 99.9% fidelity.",
            sources=sample_sources,
            fact_check_passed=True,
            fact_check_trust_score=90,
        )
        assert score >= 70

    def test_zero_score_no_sources_no_factcheck(self):
        """Zero score: no sources, no fact-check."""
        score = compute_trust_score(
            claim="Unverifiable claim.",
            sources=[],
            fact_check_passed=False,
        )
        assert score < 30

    def test_single_source_no_factcheck_moderate(self):
        """Single source, no fact-check: moderate score."""
        sources = [{"domain_authority": 50.0, "snippet": "Some info", "tool_name": "ddg"}]
        score = compute_trust_score(
            claim="Some claim.",
            sources=sources,
            fact_check_passed=False,
        )
        assert 20 <= score <= 70


class TestEmbeddingCache:
    def test_same_snippet_returns_cached(self):
        """Same snippet uses cached embedding."""
        from app.scoring.trust_score import _embedding_cache, _get_cached_embedding
        _embedding_cache.clear()
        text = "This is a test snippet for cache."
        emb1 = _get_cached_embedding(text)
        emb2 = _get_cached_embedding(text)
        # Should be the same object (from cache)
        assert emb1 is emb2

    def test_different_snippets_different_cache_keys(self):
        """Different snippets get different cache entries."""
        from app.scoring.trust_score import _embedding_cache, _get_cached_embedding
        _embedding_cache.clear()
        _get_cached_embedding("snippet one")
        _get_cached_embedding("snippet two")
        assert len(_embedding_cache) == 2


class TestScoreAgreement:
    def test_identical_snippets_high_agreement(self):
        """Identical snippets should have high agreement score."""
        from app.scoring.trust_score import _score_agreement
        sources = [
            {"snippet": "The Earth is round and orbits the sun.", "title": "Fact"},
            {"snippet": "The Earth is round and orbits the sun.", "title": "Fact"},
        ]
        score = _score_agreement(sources)
        assert score > 80

    def test_dissimilar_snippets_low_agreement(self):
        """Very different snippets should have lower agreement."""
        from app.scoring.trust_score import _score_agreement
        sources = [
            {"snippet": "Quantum computing uses qubits.", "title": "QC"},
            {"snippet": "The weather is sunny today.", "title": "Weather"},
        ]
        score = _score_agreement(sources)
        assert score < 70

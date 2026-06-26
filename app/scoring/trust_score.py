"""5-dimension trust scoring engine.

Every substantive claim in the final output gets a 0–100 trust score.
Claims under 50 are explicitly flagged: "Low confidence — sources disagree."

Scoring dimensions:
  1. Source Count      — how many independent sources support this claim
  2. Source Authority  — domain authority of supporting sources
  3. Source Agreement  — do sources actually say the same thing?
  4. Recency           — for time-sensitive claims, are sources recent?
  5. Fact-Checker      — independent verification result
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import date, datetime
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Weights for each dimension (must sum to 1.0)
# Shifted weight away from authority (often unknown) toward agreement + count
WEIGHTS = {
    "source_count": 0.25,
    "source_authority": 0.20,
    "source_agreement": 0.30,
    "recency": 0.10,
    "factcheck": 0.15,
}

# Embedding functions — uses ONNX Runtime (no torch dependency)
from app.utils.embeddings import embed_texts, cosine_similarity

# Embedding cache (max 10k entries)
_embedding_cache: dict[str, np.ndarray] = {}
_EMBEDDING_CACHE_MAX = 10000


def _get_cached_embedding(text: str) -> np.ndarray:
    """Get embedding with caching using ONNX Runtime."""
    cache_key = hashlib.md5(text.encode()).hexdigest()
    if cache_key in _embedding_cache:
        return _embedding_cache[cache_key]
    emb = embed_texts([text])[0]
    if len(_embedding_cache) < _EMBEDDING_CACHE_MAX:
        _embedding_cache[cache_key] = emb
    return emb


def _score_source_count(n_sources: int) -> float:
    """More sources = higher score, diminishing returns after 3."""
    if n_sources == 0:
        return 0.0
    if n_sources >= 3:
        return 100.0
    return min(100.0, (n_sources / 3) * 100)


def _score_authority(sources: list[dict]) -> float:
    """Average domain authority of sources.

    Uses the pre-computed domain_authority from each source (populated by
    estimate_domain_authority at creation time). Sources with recognized
    high-authority domains (arxiv, nature, github, etc.) score 85+. Unknown
    HTTPS domains score 50, HTTP-only score 30.

    The key fix: we no longer collapse all unknowns to 50. The actual
    estimated values are preserved, giving meaningful differentiation.
    """
    if not sources:
        return 0.0
    authorities = [s.get("domain_authority", 0) for s in sources]
    if not authorities:
        return 50.0
    # Use actual estimated values — don't collapse to neutral
    # Filter out only truly unset (0 after model_post_init didn't run)
    valid = [a for a in authorities if a > 0]
    if not valid:
        return 50.0
    return float(np.mean(valid))


def _score_agreement(sources: list[dict]) -> float:
    """Measure how much sources agree using embedding similarity.

    For short snippets (< 40 chars), pads with the title to give the
    embedding model more signal. Uses a calibrated curve that maps:
      sim=0.35 → 65, sim=0.45 → 72, sim=0.55 → 79,
      sim=0.65 → 85, sim=0.75 → 90, sim=0.85 → 95

    This is more forgiving than the previous power-0.4 curve for the
    low-similarity regime typical of diverse search snippets.
    Uses embedding cache to avoid recomputing for identical snippets.
    """
    if len(sources) <= 1:
        return 50.0  # Can't measure agreement with 0-1 sources

    try:
        snippets = []
        for s in sources:
            text = s.get("snippet", "")
            # Pad very short snippets with title for better embedding
            if len(text) < 40:
                title = s.get("title", "")
                if title:
                    text = f"{title}. {text}"
            if text:
                snippets.append(text)

        if len(snippets) <= 1:
            return 50.0

        # Use ONNX-based embeddings (no torch needed)
        embeddings = embed_texts(snippets)

        # Compute pairwise cosine similarities
        similarities = []
        for i in range(len(embeddings)):
            for j in range(i + 1, len(embeddings)):
                sim = cosine_similarity(embeddings[i], embeddings[j])
                similarities.append(sim)

        avg_sim = float(np.mean(similarities)) if similarities else 0.5
        # Calibrated curve: more forgiving for low-sim regime
        if avg_sim >= 0:
            return max(0.0, min(100.0, (avg_sim ** 0.35) * 100))
        return max(0.0, min(100.0, (avg_sim + 1) / 2 * 100))
    except Exception as e:
        logger.warning(f"Agreement scoring failed: {e}")
        return 50.0


def _score_recency(sources: list[dict]) -> float:
    """How recent are the sources? Important for time-sensitive claims."""
    if not sources:
        return 0.0

    now = date.today()
    scores = []
    for s in sources:
        pub = s.get("published_date")
        if pub is None:
            scores.append(60.0)  # Unknown date = slight penalty, not harsh
            continue
        if isinstance(pub, str):
            try:
                pub = date.fromisoformat(pub)
            except ValueError:
                scores.append(50.0)
                continue
        days_old = (now - pub).days
        if days_old <= 30:
            scores.append(100.0)
        elif days_old <= 365:
            scores.append(70.0)
        elif days_old <= 365 * 3:
            scores.append(40.0)
        else:
            scores.append(20.0)

    return float(np.mean(scores)) if scores else 0.0


def _score_factcheck(fact_check_passed: bool, fact_check_trust_score: int = 50) -> float:
    """Fact-Checker verdict — uses the fact-checker's raw trust score.

    If the fact-checker verified the claim, use its trust_score directly (0-100).
    If not verified, cap at 30.
    """
    if fact_check_passed:
        return float(fact_check_trust_score)
    return 30.0


def compute_trust_score(
    claim: str,
    sources: list[dict],
    fact_check_passed: bool = False,
    fact_check_trust_score: int = 50,
) -> int:
    """Compute 0–100 trust score for a claim across 5 dimensions."""
    scores = {
        "source_count": _score_source_count(len(sources)),
        "source_authority": _score_authority(sources),
        "source_agreement": _score_agreement(sources),
        "recency": _score_recency(sources),
        "factcheck": _score_factcheck(fact_check_passed, fact_check_trust_score),
    }

    weighted = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)
    return max(0, min(100, int(round(weighted))))


def label_trust(score: int) -> str:
    """Convert numeric score to display label."""
    if score >= 81:
        return "HIGH"
    elif score >= 51:
        return "MODERATE"
    else:
        return "LOW"

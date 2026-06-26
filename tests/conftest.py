"""Test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_query():
    return "What are the latest advances in quantum error correction?"


@pytest.fixture
def sample_sources():
    return [
        {
            "source_id": "src-1",
            "url": "https://arxiv.org/abs/2401.00001",
            "title": "Quantum Error Correction Advances 2024",
            "snippet": "Recent advances in quantum error correction include surface codes and LDPC codes.",
            "domain_authority": 90.0,
            "tool_name": "arxiv",
        },
        {
            "source_id": "src-2",
            "url": "https://nature.com/articles/qec-2024",
            "title": "Nature: Quantum Error Correction Breakthrough",
            "snippet": "Researchers achieved 99.9% fidelity in quantum error correction experiments.",
            "domain_authority": 95.0,
            "tool_name": "tavily",
        },
    ]


@pytest.fixture
def sample_claim():
    return "Quantum error correction has achieved 99.9% fidelity in recent experiments using surface codes."

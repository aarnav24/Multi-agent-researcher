"""Tests for _LLMTimingTracker per-model breakdown."""

from __future__ import annotations

from backend.agents.base import _LLMTimingTracker


class TestLLMTimingTracker:
    def _make_tracker(self):
        t = _LLMTimingTracker()
        # Avoid loading tiktoken in tests
        t._encoder = False
        return t

    def test_summary_has_models_key(self):
        """summary() includes 'models' breakdown."""
        t = self._make_tracker()
        t.record("reasoning", "OrchestratorAgent", "openai/gpt-oss-120b:free", 2.5, 1000, 500, key_idx=0)
        t.record("reasoning", "SynthesizerAgent", "gemini-3.5-flash", 3.0, 2000, 800, key_idx=1)
        t.record("fast", "SearcherAgent", "nvidia/nemotron-3-nano-30b-a3b:free", 1.0, 500, 200, key_idx=0)

        summary = t.summary()
        assert "models" in summary["reasoning"]
        assert "models" in summary["fast"]

    def test_per_model_stats_correct(self):
        """Per-model stats aggregate correctly."""
        t = self._make_tracker()
        # Two calls to same model
        t.record("reasoning", "OrchestratorAgent", "openai/gpt-oss-120b:free", 2.0, 1000, 500, key_idx=0)
        t.record("reasoning", "OrchestratorAgent", "openai/gpt-oss-120b:free", 3.0, 1500, 600, key_idx=1)
        # One call to different model
        t.record("reasoning", "SynthesizerAgent", "gemini-3.5-flash", 1.5, 800, 400, key_idx=0)

        summary = t.summary()
        models = summary["reasoning"]["models"]

        assert "openai/gpt-oss-120b:free" in models
        assert models["openai/gpt-oss-120b:free"]["count"] == 2
        assert models["openai/gpt-oss-120b:free"]["in_tokens"] == 2500
        assert models["openai/gpt-oss-120b:free"]["out_tokens"] == 1100

        assert "gemini-3.5-flash" in models
        assert models["gemini-3.5-flash"]["count"] == 1

    def test_summary_empty_when_no_calls(self):
        """summary() returns empty dict when no calls recorded."""
        t = self._make_tracker()
        assert t.summary() == {}

    def test_reset_clears_all_data(self):
        """reset() clears all tracking data."""
        t = self._make_tracker()
        t.record("fast", "SearcherAgent", "model-x", 1.0, 100, 50)
        t.reset()
        assert t.summary() == {}

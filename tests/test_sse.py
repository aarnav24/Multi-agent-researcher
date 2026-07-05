"""Tests for SSE streamer — keepalive, stale cleanup."""

from __future__ import annotations

import asyncio
import time
import pytest

from backend.api.sse import SSEStreamer, STALE_STREAM_TIMEOUT


class TestSSEStreamer:
    @pytest.mark.asyncio
    async def test_event_emitted_immediately(self):
        """Emitted events are yielded immediately."""
        streamer = SSEStreamer()
        streamer.emit("test_event", {"key": "value"})

        # Get first chunk from the stream
        chunk = None
        async for c in streamer.stream():
            chunk = c
            break
        assert chunk is not None
        assert "test_event" in chunk
        assert "key" in chunk

    @pytest.mark.asyncio
    async def test_done_event_ends_stream(self):
        """Stream terminates after 'done' event."""
        streamer = SSEStreamer()
        streamer.emit("done", {"message": "complete"})

        chunks = []
        async for c in streamer.stream():
            chunks.append(c)
        assert len(chunks) == 1
        assert "done" in chunks[0]

    def test_is_stale_false_for_new_stream(self):
        """New stream is not stale."""
        streamer = SSEStreamer()
        assert not streamer.is_stale()

    def test_is_stale_true_after_timeout(self):
        """Stream becomes stale after inactivity."""
        streamer = SSEStreamer()
        # Manually set last activity to past
        streamer._last_activity = time.time() - STALE_STREAM_TIMEOUT - 1
        assert streamer.is_stale()

    def test_emit_updates_last_activity(self):
        """emit() updates _last_activity."""
        streamer = SSEStreamer()
        old_activity = streamer._last_activity
        time.sleep(0.01)  # Small delay to ensure time difference
        streamer.emit("event", {})
        assert streamer._last_activity > old_activity

    @pytest.mark.asyncio
    async def test_error_event_ends_stream(self):
        """Stream terminates after 'error' event."""
        streamer = SSEStreamer()
        streamer.emit("error", {"error": "something went wrong"})

        chunks = []
        async for c in streamer.stream():
            chunks.append(c)
        assert len(chunks) == 1
        assert "error" in chunks[0]

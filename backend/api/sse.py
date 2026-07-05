"""SSE streaming helpers — real-time agent activity events."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)

# Stale stream timeout: streams inactive for 10 minutes are cleaned up
STALE_STREAM_TIMEOUT = 600.0


class SSEStreamer:
    """Manages SSE event queues for live agent activity streaming."""

    def __init__(self):
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._last_activity: float = time.time()

    def emit(self, event: str, data: dict[str, Any]) -> None:
        """Emit an SSE event."""
        self._last_activity = time.time()
        payload = {"event": event, "data": data}
        self._queue.put_nowait(payload)

    async def stream(self) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted strings for FastAPI StreamingResponse."""
        while True:
            try:
                payload = await asyncio.wait_for(self._queue.get(), timeout=30.0)
                event = payload["event"]
                data = json.dumps(payload["data"], default=str)
                yield f"event: {event}\ndata: {data}\n\n"

                if event in ("done", "error", "killed"):
                    break
            except asyncio.TimeoutError:
                # Send keepalive comment
                yield ": keepalive\n\n"
            except Exception as e:
                logger.error(f"SSE stream error: {e}")
                break

    def is_stale(self, timeout: float = STALE_STREAM_TIMEOUT) -> bool:
        """Check if this stream has been inactive for longer than timeout."""
        return (time.time() - self._last_activity) > timeout

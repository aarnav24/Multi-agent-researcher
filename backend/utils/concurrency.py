"""Concurrency control — semaphore + kill switches."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from backend.config import settings

logger = logging.getLogger(__name__)

# Global semaphore capping parallel API calls
_semaphore = asyncio.Semaphore(settings.max_concurrent_agents)


@asynccontextmanager
async def agent_slot() -> AsyncGenerator[None, None]:
    """Acquire a concurrency slot for an agent invocation."""
    async with _semaphore:
        yield


def check_kill_switches(state: dict) -> str | None:
    """Check all hard kill switches. Returns reason string if tripped, None if OK."""
    if state.get("agent_count", 0) >= settings.max_agent_invocations:
        return f"agent_limit_reached:{state['agent_count']}"
    if state.get("critic_rounds", 0) >= settings.max_critic_rounds:
        return f"critic_rounds_exhausted:{state['critic_rounds']}"
    return None

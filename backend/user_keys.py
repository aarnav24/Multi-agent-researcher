"""User API key resolution — user keys first, system defaults as fallback.

Priority:
  1. User's key (from Postgres user_api_keys table)
  2. System default (from .env)

This allows users to bring their own API keys and consume their own quota.
Users without keys share the system defaults (current behavior).
"""

from __future__ import annotations

import logging
from backend.config import settings

logger = logging.getLogger(__name__)

# System defaults from .env (fallback)
_SYSTEM_DEFAULTS: dict[str, list[str]] = {
    "openrouter": settings.openrouter_keys,
    "gemini": settings.google_keys,
    "tavily": settings.tavily_keys,
}

# Default models per provider (used when user doesn't specify)
_DEFAULT_MODELS: dict[str, str] = {
    "openrouter": settings.model_reasoning,
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-6",
    "groq": "llama-4-scout-17b-16e-instruct",
    "deepseek": "deepseek-chat",
    "openai": "gpt-4o",
}

# Default base URLs per provider
_DEFAULT_BASE_URLS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "",  # Uses Google AI SDK directly
    "anthropic": "https://api.anthropic.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
}


# ── Module-level cache for user keys (populated at graph setup time) ─────────
# Keyed by (user_id, provider) → list of key dicts.
# This avoids synchronous DB calls from agent code (which runs in async context).
_user_keys_cache: dict[tuple[str, str], list[dict]] = {}


def cache_user_keys(user_id: str, provider: str, keys: list[dict]) -> None:
    """Cache user's keys for a provider. Called at graph setup time (async context)."""
    _user_keys_cache[(user_id, provider)] = keys


def clear_user_keys_cache() -> None:
    """Clear the key cache. Call at the start of each pipeline run."""
    _user_keys_cache.clear()


def get_user_keys(user_id: str | None, provider: str) -> list[dict]:
    """Fetch user's active keys for a provider.

    Returns list of dicts: [{"id": ..., "api_key": ..., "model_name": ..., "base_url": ...}]
    Returns empty list if user has no keys or user_id is None.

    Checks the in-memory cache first (populated at graph setup), then falls back
    to a direct DB query via the global connected store.
    """
    if not user_id:
        return []

    # 1. Check cache (populated by prefetch_user_keys at graph setup)
    cached = _user_keys_cache.get((user_id, provider))
    if cached is not None:
        return cached

    # 2. Fallback: query the global connected store
    try:
        from backend.api.routes import _state_store as store
        if store is None or not store._pg:
            return []
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            # In async context — can't block. Return empty; cache miss means
            # prefetch didn't run, which shouldn't happen in normal flow.
            logger.debug("get_user_keys cache miss in async context, returning empty")
            return []
        except RuntimeError:
            # No running loop — safe to run async code synchronously
            return asyncio.run(store.get_user_keys(user_id, provider))
    except Exception as e:
        logger.warning(f"get_user_keys failed for {user_id}/{provider}: {e}")
        return []


async def prefetch_user_keys(user_id: str | None) -> None:
    """Prefetch all of a user's keys into the cache. Call once at graph setup.

    This runs in async context (inside the graph node), so it can properly
    await the DB call. Subsequent synchronous calls to get_user_keys will
    hit the cache.
    """
    if not user_id:
        return

    try:
        from backend.api.routes import _state_store as store
        if store is None or not store._pg:
            return
        keys = await store.get_user_keys(user_id)
        # Group by provider into the cache
        for key in keys:
            provider = key.get("provider", "openrouter")
            cache_user_keys(user_id, provider, [])
            _user_keys_cache[(user_id, provider)].append(key)
        logger.info(f"Prefetched {len(keys)} keys for user {user_id}")
    except Exception as e:
        logger.warning(f"prefetch_user_keys failed for {user_id}: {e}")


def get_effective_keys(provider: str, user_id: str | None = None) -> list[str]:
    """Get effective API keys: user's first, then system defaults as fallback.

    Args:
        provider: "openrouter" | "gemini" | "anthropic" | "groq" | "deepseek" | "openai"
        user_id: NextAuth user ID (email or UUID), or None for anonymous

    Returns:
        List of API key strings to try in order
    """
    # 1. Try user's keys
    if user_id:
        user_keys = get_user_keys(user_id, provider)
        if user_keys:
            return [k["api_key"] for k in user_keys]

    # 2. Fallback to system defaults
    return _SYSTEM_DEFAULTS.get(provider, [])


def get_effective_model(provider: str, user_id: str | None = None) -> str:
    """Get effective model name: user's preference or system default."""
    # 1. Try user's model
    if user_id:
        user_keys = get_user_keys(user_id, provider)
        if user_keys and user_keys[0].get("model_name"):
            return user_keys[0]["model_name"]

    # 2. Fallback to system default
    return _DEFAULT_MODELS.get(provider, "default")


def get_effective_base_url(provider: str, user_id: str | None = None) -> str:
    """Get effective base URL: user's preference or system default."""
    # 1. Try user's base_url
    if user_id:
        user_keys = get_user_keys(user_id, provider)
        if user_keys and user_keys[0].get("base_url"):
            return user_keys[0]["base_url"]

    # 2. Fallback to system default
    return _DEFAULT_BASE_URLS.get(provider, "")


def get_all_user_keys(user_id: str | None) -> dict[str, list[dict]]:
    """Get all user's keys grouped by provider. Useful for settings UI."""
    if not user_id:
        return {}

    result: dict[str, list[dict]] = {}
    for provider in _DEFAULT_MODELS:
        keys = get_user_keys(user_id, provider)
        if keys:
            result[provider] = keys
    return result

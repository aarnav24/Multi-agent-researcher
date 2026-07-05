"""User API keys management — CRUD endpoints for storing user-provided API keys.

These keys are stored in Postgres and used in priority over system defaults.
Users without keys share the system .env keys (current behavior).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Header

logger = logging.getLogger(__name__)

router = APIRouter()

# ── In-memory cache for user keys (refreshed on each request) ─────────────
# For production, add TTL cache. For now, always read from DB.


async def _get_state_store():
    """Get the global StateStore instance."""
    from backend.api.routes import get_state_store
    return await get_state_store()


@router.get("/user/keys")
async def list_user_keys(authorization: str | None = Header(None)):
    """List all API keys for the authenticated user."""
    user_id = _extract_user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    store = await _get_state_store()
    all_keys = await store.get_user_keys(user_id)

    # Mask API keys for security (show only last 4 chars)
    masked = []
    for key in all_keys:
        masked.append({
            "id": key["id"],
            "provider": key["provider"],
            "model_name": key["model_name"],
            "base_url": key["base_url"],
            "api_key": "..." + key["api_key"][-4:],
            "is_active": key["is_active"],
        })

    return {"keys": masked}


@router.post("/user/keys")
async def add_user_key(body: dict[str, Any], authorization: str | None = Header(None)):
    """Add a new API key for the authenticated user."""
    user_id = _extract_user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    provider = body.get("provider", "").lower()
    api_key = body.get("api_key", "")
    model_name = body.get("model_name", "")
    base_url = body.get("base_url", "")

    if not provider or not api_key:
        raise HTTPException(status_code=400, detail="provider and api_key are required")

    # Validate provider
    valid_providers = {"openrouter", "gemini", "anthropic", "groq", "deepseek", "openai"}
    if provider not in valid_providers:
        raise HTTPException(status_code=400, detail=f"Invalid provider. Must be one of: {valid_providers}")

    store = await _get_state_store()
    key_id = await store.add_user_key(user_id, provider, api_key, model_name, base_url)

    logger.info(f"User {user_id} added {provider} key {key_id}")
    return {"id": key_id, "provider": provider, "message": "Key added successfully"}


@router.delete("/user/keys/{key_id}")
async def delete_user_key(key_id: str, authorization: str | None = Header(None)):
    """Deactivate an API key for the authenticated user."""
    user_id = _extract_user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    store = await _get_state_store()
    success = await store.delete_user_key(key_id, user_id)

    if not success:
        raise HTTPException(status_code=404, detail="Key not found")

    return {"message": "Key deleted successfully"}


@router.post("/user/keys/{key_id}/test")
async def test_user_key(key_id: str, authorization: str | None = Header(None)):
    """Test if an API key is valid by making a simple API call."""
    user_id = _extract_user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    store = await _get_state_store()
    all_keys = store.get_user_keys(user_id)
    key = next((k for k in all_keys if k["id"] == key_id), None)

    if not key:
        raise HTTPException(status_code=404, detail="Key not found")

    # Test the key based on provider
    try:
        if key["provider"] == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(
                model=key["model_name"] or "gemini-2.0-flash",
                api_key=key["api_key"],
                max_retries=0,
            )
            response = await llm.ainvoke("Say 'ok'")
        else:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=key["model_name"] or "gpt-4o",
                api_key=key["api_key"],
                base_url=key["base_url"] or "https://openrouter.ai/api/v1",
                max_retries=0,
                max_tokens=10,
            )
            response = await llm.ainvoke([{"role": "user", "content": "Say 'ok'"}])

        return {"valid": True, "message": "Key is valid"}
    except Exception as e:
        return {"valid": False, "message": f"Key test failed: {str(e)[:100]}"}


def _extract_user_id(authorization: str | None) -> str | None:
    """Extract user ID from Authorization header.

    For now, uses a simple Bearer token format.
    In production, validate the JWT token from NextAuth.

    Format: "Bearer <user_id>"
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.split(" ", 1)[1]

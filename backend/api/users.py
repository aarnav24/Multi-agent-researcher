"""User authentication — signup, login, and account management."""

from __future__ import annotations

import logging
from typing import Any

import bcrypt
from fastapi import APIRouter, HTTPException, Header

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_state_store():
    from backend.api.routes import get_state_store
    return await get_state_store()


@router.post("/auth/signup")
async def signup(body: dict[str, Any]):
    """Create a new user account."""
    store = await _get_state_store()

    username = (body.get("username") or "").strip()
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    name = (body.get("name") or "").strip()

    # Validate
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters")

    # Check if username taken by checking JWT-based user_id (backward compat)
    # or by checking the users table directly
    existing = await store.get_user_by_username(username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    # Hash password
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    try:
        user = await store.create_user(username, email, password_hash, name)
        logger.info(f"New user created: {username} ({user['id']})")
        return {"message": "Account created successfully", "user": user}
    except Exception as e:
        logger.error(f"Signup failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to create account")


@router.post("/auth/login")
async def login(body: dict[str, Any]):
    """Verify credentials and return user info (for non-NextAuth flows)."""
    store = await _get_state_store()

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password required")

    user = await store.verify_user_password(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    return {"message": "Login successful", "user": user}


@router.get("/auth/me")
async def get_current_user(authorization: str | None = Header(None)):
    """Get current user info from user_id in Authorization header."""
    store = await _get_state_store()

    user_id = (authorization or "").replace("Bearer ", "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = await store.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"user": user}

"""Firebase Auth API routes — server-side token verification.

Endpoints:
  POST /api/v1/auth/verify  — verify a Firebase ID token from the frontend, return user info
  GET  /api/v1/auth/me      — get user info from a verified token (via Authorization header)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Header

from backend.auth.firebase import firebase_controller

logger = logging.getLogger(__name__)

router = APIRouter()


class VerifyTokenRequest:
    """Request body for token verification."""

    def __init__(self, id_token: str) -> None:
        self.id_token = id_token


@router.post("/auth/verify")
async def verify_token(body: dict[str, Any]):
    """Verify a Firebase ID token and return the decoded user info.

    Frontend sends the ID token obtained from Firebase Client SDK after sign-in.
    Backend verifies it with the Admin SDK and returns safe user fields.
    """
    id_token = body.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="id_token is required")

    try:
        decoded = firebase_controller.verify_id_token(id_token)
    except Exception as e:
        logger.warning("Firebase token verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from e

    return {
        "uid": decoded.get("uid"),
        "email": decoded.get("email"),
        "name": decoded.get("name"),
        "picture": decoded.get("picture"),
        "email_verified": decoded.get("email_verified"),
        "auth_time": decoded.get("auth_time"),
    }


@router.get("/auth/me")
async def get_current_user(authorization: str | None = Header(None)):
    """Return the current user from a Firebase ID token in the Authorization header.

    Header format: Authorization: Bearer <id_token>
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    id_token = authorization.split(" ", 1)[1]

    try:
        decoded = firebase_controller.verify_id_token(id_token)
    except Exception as e:
        logger.warning("Firebase token verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from e

    return {
        "uid": decoded.get("uid"),
        "email": decoded.get("email"),
        "name": decoded.get("name"),
        "picture": decoded.get("picture"),
        "email_verified": decoded.get("email_verified"),
    }

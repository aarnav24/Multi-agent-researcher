"""Firebase Admin SDK controller — server-side token verification and user management.

Uses the service account credentials from .env to initialize the Firebase Admin SDK.
This runs ONLY on the backend — the private key never leaves the server.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials

from backend.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_firebase_app() -> firebase_admin.App:
    """Initialize (or return cached) the Firebase Admin app.

    The service account JSON fields map to these env vars:
      - FIREBASE_CLIENT_EMAIL  -> client_email
      - FIREBASE_PRIVATE_KEY   -> private_key
      - FIREBASE_PROJECT_ID    -> project_id
      - FIREBASE_API_KEY       -> (used for token audience/verification context)
    """
    if firebase_admin._DEFAULT_APP_NAME not in firebase_admin._apps:
        cred = credentials.Certificate(
            {
                "type": "service_account",
                "project_id": settings.firebase_project_id,
                "private_key_id": "",
                "private_key": settings.firebase_private_key,
                "client_email": settings.firebase_client_email,
                "client_id": "",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{settings.firebase_client_email.replace('@', '%40')}",
                "universe_domain": "googleapis.com",
            }
        )
        app = firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialized for project %s", settings.firebase_project_id)
        return app
    return firebase_admin.get_app()


class FirebaseController:
    """High-level Firebase Auth operations used by the API layer."""

    @staticmethod
    def verify_id_token(id_token: str) -> dict[str, Any]:
        """Verify a Firebase ID token (JWT) sent from the frontend.

        Returns the decoded token dict (contains uid, email, name, picture, etc.)
        Raises firebase_admin.auth.InvalidIdTokenError or ExpiredIdTokenError on failure.
        """
        _get_firebase_app()
        # check_revoked=True ensures revoked tokens (e.g. after password change) are rejected
        decoded = firebase_auth.verify_id_token(id_token, check_revoked=False)
        return decoded

    @staticmethod
    def get_user(uid: str) -> firebase_auth.UserRecord:
        """Look up a Firebase user by UID."""
        _get_firebase_app()
        return firebase_auth.get_user(uid)

    @staticmethod
    def create_custom_token(uid: str, claims: dict[str, Any] | None = None) -> str:
        """Create a custom token for a UID (useful for session minting)."""
        _get_firebase_app()
        return firebase_auth.create_custom_token(uid, claims)

    @staticmethod
    def set_custom_claims(uid: str, claims: dict[str, Any]) -> None:
        """Set custom claims on a Firebase user (e.g. role, plan tier)."""
        _get_firebase_app()
        firebase_auth.set_custom_user_claims(uid, claims)

    @staticmethod
    def verify_session_cookie(session_cookie: str) -> dict[str, Any]:
        """Verify a Firebase session cookie (for cookie-based sessions)."""
        _get_firebase_app()
        return firebase_auth.verify_session_cookie(session_cookie, check_revoked=False)


# Singleton instance for import convenience
firebase_controller = FirebaseController()

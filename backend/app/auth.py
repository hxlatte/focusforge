"""Firebase ID-token verification.

The browser sends `Authorization: Bearer <Firebase ID token>`. The token is
verified server-side with the Firebase Admin SDK; the uid inside the verified
token is the ONLY source of identity for data access. A uid is never accepted
from the request body, query string or path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

log = logging.getLogger("focusforge.auth")
_bearer = HTTPBearer(auto_error=False)

_firebase_ready = False


@dataclass(frozen=True)
class AuthUser:
    uid: str
    email: str | None = None


def _init_firebase() -> None:
    global _firebase_ready
    if _firebase_ready:
        return
    import firebase_admin
    from firebase_admin import credentials

    if not firebase_admin._apps:  # noqa: SLF001
        from .config import get_settings

        # Uses GOOGLE_APPLICATION_CREDENTIALS (service-account JSON).
        firebase_admin.initialize_app(
            credentials.ApplicationDefault(),
            {"projectId": get_settings().project_id},
        )
    _firebase_ready = True


def verify_token(token: str) -> AuthUser:
    """Verify a Firebase ID token. Raises ValueError on any failure."""
    from firebase_admin import auth as fb_auth

    _init_firebase()
    try:
        decoded = fb_auth.verify_id_token(token, check_revoked=False)
    except Exception as exc:  # expired, malformed, wrong project, ...
        raise ValueError(str(exc)) from exc
    return AuthUser(uid=decoded["uid"], email=decoded.get("email"))


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        return verify_token(creds.credentials)
    except ValueError:
        log.info("Rejected invalid ID token")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

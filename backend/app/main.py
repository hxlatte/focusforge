"""FocusForge Intelligence API."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .auth import AuthUser, current_user
from .config import get_settings
from .domain import normalize_sessions
from .repo import FirestoreRepo, Repository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("focusforge.api")

_repo: Repository | None = None


def get_repo() -> Repository:
    """Dependency so tests can swap in InMemoryRepo."""
    global _repo
    if _repo is None:
        _repo = FirestoreRepo()
    return _repo


User = Annotated[AuthUser, Depends(current_user)]
Repo = Annotated[Repository, Depends(get_repo)]


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="FocusForge Intelligence", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/me")
    def me(user: User) -> dict:
        return {"uid": user.uid, "email": user.email}

    @app.get("/v1/data-summary")
    def data_summary(user: User, repo: Repo, tz: str | None = None) -> dict:
        """What data exists for the signed-in user (counts only, no content)."""
        try:
            rows = repo.list(user.uid, "sessions")
        except Exception:
            log.exception("Failed to read sessions")
            raise HTTPException(502, "Could not read your data")
        sessions = normalize_sessions(rows, tz)
        return {
            "sessions_total": len(sessions),
            "sessions_labelled": sum(s.labelled for s in sessions),
            "sessions_completed": sum(s.completed for s in sessions),
            "sessions_abandoned": sum(s.status == "abandoned" for s in sessions),
            "sessions_with_start_time": sum(s.local_start is not None for s in sessions),
            "sessions_with_notes": sum(bool(s.notes) for s in sessions),
            "unusable_rows": len(rows) - len(sessions),
        }

    return app


app = create_app()

"""FocusForge Intelligence API."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware

from .auth import AuthUser, current_user
from .config import get_settings
from .domain import normalize_sessions, safe_zone
from .repo import FirestoreRepo, Repository
from .logs import analyzer as log_analyzer
from .recommend import engine as reco_engine
from .rhythm import engine as rhythm_engine
from .serialize import clean

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("focusforge.api")

_repo: Repository | None = None


def get_repo() -> Repository:
    """Dependency so tests can swap in InMemoryRepo."""
    global _repo
    if _repo is None:
        _repo = FirestoreRepo()
    return _repo


class AnalyzeRequest(BaseModel):
    # IANA zone of the user's device, e.g. "Asia/Kolkata". Needed to turn UTC timestamps
    # into the user's local hour of day.
    tz: str = Field(default="UTC", max_length=64)


User = Annotated[AuthUser, Depends(current_user)]
Repo = Annotated[Repository, Depends(get_repo)]


def _summary(learning: dict) -> dict:
    """Light version stored in analysis/learning. Full topics (with evidence) live in topics/{id}."""
    keep = ("id", "name", "subjects", "status", "needs_revision", "stance_counts", "mentions", "sessions",
            "revisits", "first_seen", "last_seen", "last_signal", "schedule", "recall", "reasons")
    return {**learning, "topics": [{k: t[k] for k in keep if k in t} for t in learning.get("topics", [])]}


def _store_learning(repo: Repository, uid: str, learning: dict) -> None:
    repo.put(uid, "analysis", "learning", _summary(learning))
    new_ids = set()
    for t in learning.get("topics", []):
        repo.put(uid, "topics", t["id"], t)
        new_ids.add(t["id"])
    for old in repo.list(uid, "topics"):          # drop topics that no longer exist after re-analysis
        if old["id"] not in new_ids:
            repo.delete(uid, "topics", old["id"])


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

    @app.post("/v1/analyze")
    def analyze(body: AnalyzeRequest, user: User, repo: Repo) -> dict:
        """Run the engines on the signed-in user's real data and store the result."""
        try:
            tz_ok = str(safe_zone(body.tz)) if body.tz != "UTC" else "UTC"
            if body.tz != "UTC" and tz_ok == "UTC":
                raise HTTPException(422, "Unknown time zone")
            rows = repo.list(user.uid, "sessions")
            tasks = repo.list(user.uid, "tasks")
        except HTTPException:
            raise
        except Exception:
            log.exception("Failed to read user data")
            raise HTTPException(502, "Could not read your data")
        sessions = normalize_sessions(rows, body.tz)
        if any(s.synthetic for s in sessions):
            # Synthetic data is for model testing only and must never reach a real dashboard.
            raise HTTPException(409, "Synthetic data detected; refusing to analyse")
        try:
            rhythm = clean(rhythm_engine.run(sessions, tasks, tz=body.tz))
            repo.put(user.uid, "analysis", "rhythm", rhythm)
        except Exception:
            log.exception("Rhythm analysis failed")
            raise HTTPException(500, "Analysis failed")
        try:
            reviews = repo.list(user.uid, "reviews")
            learning = clean(log_analyzer.analyze(sessions, reviews))
            _store_learning(repo, user.uid, learning)
        except Exception:
            log.exception("Study-log analysis failed")
            raise HTTPException(500, "Analysis failed")
        try:
            reco = reco_engine.run(learning, rhythm, repo.list(user.uid, "recommendations"), sessions)
            for r in reco["recommendations"]:
                repo.put(user.uid, "recommendations", r["id"], clean(r))
            repo.put(user.uid, "analysis", "recommendations_meta",
                     clean({"deferred": reco["deferred"], "evaluation": reco["evaluation"],
                            "generated_at": rhythm["generated_at"]}))
        except Exception:
            log.exception("Recommendation step failed")
            raise HTTPException(500, "Analysis failed")
        return {"rhythm": rhythm, "learning": _summary(learning), "recommendations": reco}

    @app.get("/v1/intelligence")
    def intelligence(user: User, repo: Repo) -> dict:
        """Latest stored results (no recomputation)."""
        try:
            return {"rhythm": repo.get(user.uid, "analysis", "rhythm"),
                    "learning": repo.get(user.uid, "analysis", "learning"),
                    "recommendations": {"items": repo.list(user.uid, "recommendations"),
                                        **(repo.get(user.uid, "analysis", "recommendations_meta") or {})}}
        except Exception:
            log.exception("Failed to read analysis")
            raise HTTPException(502, "Could not read your analysis")

    return app


app = create_app()

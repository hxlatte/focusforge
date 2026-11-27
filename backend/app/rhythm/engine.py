"""Cognitive Rhythm Engine: orchestrates discovery, gating, modelling and insights."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from ..domain import Session
from . import discovery as D
from . import thresholds as T
from .frame import attempts_frame, build_features, sessions_frame, task_rate_by_day
from .insights import build as build_insights
from .model import evaluate, what_if as what_if_grid

ENGINE_VERSION = "1.0"


def _unlocks(c: dict) -> list[str]:
    out = []
    if c["total"] < T.MIN_SESSIONS_ANY:
        out.append(f"Log {T.MIN_SESSIONS_ANY - c['total']} more session(s) to see basic patterns.")
    if c["start_known"] < T.MIN_START_KNOWN:
        out.append(f"{T.MIN_START_KNOWN - c['start_known']} more session(s) with a known start time unlock "
                   f"time-of-day views (Pomodoro sessions record this automatically).")
    if c["labelled_attempts"] < T.MIN_LABELLED_ATTEMPTS or c["abandoned"] < T.MIN_ABANDONED_FOR_RATES:
        out.append(f"Completion patterns need {T.MIN_LABELLED_ATTEMPTS} timer attempts including at least "
                   f"{T.MIN_ABANDONED_FOR_RATES} stopped early (you have {c['labelled_attempts']} and {c['abandoned']}). "
                   f"Stopping a session early is recorded as data, not as failure.")
    if c["labelled_attempts"] < T.MODEL_MIN_LABELLED:
        out.append(f"A personal prediction model needs {T.MODEL_MIN_LABELLED} timer attempts "
                   f"({T.MODEL_MIN_LABELLED - c['labelled_attempts']} to go).")
    return out


def run(sessions: list[Session], tasks: list[dict] | None = None, now: datetime | None = None,
        tz: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    df = sessions_frame(sessions)
    att = attempts_frame(df) if len(df) else df.iloc[0:0]
    counts = {
        "total": int(len(df)),
        "completed": int(df["completed"].sum()) if len(df) else 0,
        "abandoned": int((df["status"] == "abandoned").sum()) if len(df) else 0,
        "start_known": int(df["local_start"].notna().sum()) if len(df) else 0,
        "labelled_attempts": int(len(att)),
        "contains_synthetic": any(s.synthetic for s in sessions),
    }
    counts["abandoned"] = int((att["completed"] == False).sum()) if len(att) else 0  # noqa: E712

    result: dict = {"engine": "cognitive_rhythm", "version": ENGINE_VERSION, "tz": tz,
                    "generated_at": now.isoformat(), "data": counts, "observed": {},
                    "model": {"card": {"state": "insufficient_data"}, "what_if": []}, "insights": []}

    if counts["total"] < T.MIN_SESSIONS_ANY:
        result["status"] = {"stage": "collecting", "message": "Not enough data yet to find patterns. "
                            "Nothing personalised is shown until there is something real to describe.",
                            "next_unlocks": _unlocks(counts)}
        return result

    obs = result["observed"]
    obs["typical_duration"] = D.typical_duration(df)
    if counts["start_known"] >= T.MIN_START_KNOWN:
        obs["heatmap"] = D.heatmap(df)
        obs["period_activity"] = D.period_activity(df)
        obs["weekday_consistency"] = D.weekday_consistency(df)
        obs["clusters"] = D.rhythm_clusters(df)
    rates_ok = counts["labelled_attempts"] >= T.MIN_LABELLED_ATTEMPTS and counts["abandoned"] >= T.MIN_ABANDONED_FOR_RATES
    if rates_ok:
        obs["period_success"] = D.period_success(att)
        obs["abandonment_by_length"] = D.abandonment_by_length(att)
        obs["subject_completion"] = D.subject_completion(att)

    model_out = {"card": {"state": "insufficient_data"}, "model": None}
    grid: list[dict] = []
    if rates_ok:
        X = build_features(att, df, task_rate_by_day(tasks or []))
        y = att["completed"].to_numpy().astype(int)
        model_out = evaluate(X, y)
        if model_out["model"] is not None:
            grid = what_if_grid(model_out["model"], X, att)
    result["model"] = {"card": model_out["card"], "what_if": grid}

    result["insights"] = build_insights(obs, model_out["card"], grid, counts)
    active = model_out["card"].get("state") == "active"
    result["status"] = {
        "stage": "modelled" if active else ("descriptive" if rates_ok or counts["start_known"] >= T.MIN_START_KNOWN
                                            else "collecting"),
        "message": ("Personal model active: it beat the baseline on held-out sessions." if active else
                    "Showing observed patterns from your history. Predictions unlock with more labelled sessions."),
        "next_unlocks": _unlocks(counts),
    }
    return result

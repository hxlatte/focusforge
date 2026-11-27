"""Session records -> pandas frame, plus leak-free features for the completion model."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ..domain import Session
from .thresholds import SHRINKAGE_STRENGTH, period_of


def sessions_frame(sessions: list[Session]) -> pd.DataFrame:
    rows = []
    for s in sessions:
        rows.append({
            "id": s.id, "subject": s.parent_subject.lower(), "type": s.type, "status": s.status,
            "labelled": s.labelled, "planned_min": s.planned_min, "actual_min": s.actual_min,
            "start_utc": s.start_utc, "end_utc": s.logged_at, "local_start": s.local_start,
            "hour": s.hour, "weekday": s.weekday,
            "period": period_of(s.hour) if s.hour is not None else None,
            "local_date": s.local_start.date() if s.local_start else None,
            "completed": s.completed,
        })
    cols = ["id", "subject", "type", "status", "labelled", "planned_min", "actual_min", "start_utc",
            "end_utc", "local_start", "hour", "weekday", "period", "local_date", "completed"]
    return pd.DataFrame(rows, columns=cols)


def attempts_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Labelled focus attempts with a known start: the only rows a completion rate may use.

    Legacy rows are excluded on purpose: only successes were ever stored, so including
    them would inflate every completion rate (survivorship bias). Manual logs are
    excluded because they are not timer attempts and cannot be abandoned.
    """
    a = df[(df["type"] == "pomodoro") & df["labelled"] & df["local_start"].notna()].copy()
    return a.sort_values("start_utc").reset_index(drop=True)


def task_rate_by_day(tasks: list[dict]) -> dict:
    """{date: completion share} from task docs whose `date` is JS toDateString()."""
    per: dict = {}
    for t in tasks:
        try:
            d = datetime.strptime(str(t.get("date", "")), "%a %b %d %Y").date()
        except ValueError:
            continue
        tot, done = per.get(d, (0, 0))
        per[d] = (tot + 1, done + (1 if t.get("completed") else 0))
    return {d: done / tot for d, (tot, done) in per.items() if tot}


FEATURE_GROUPS = {
    "time_of_day": ["hour_sin", "hour_cos"],
    "weekday": ["is_weekend", "wd_sin", "wd_cos"],
    "planned_length": ["planned_min"],
    "subject": ["subject"],
    "recent_history": ["prior_rate", "subject_prior_rate", "load_24h", "hours_since_last",
                       "attempts_today", "prev_day_task_rate"],
}
NUMERIC = [c for g in FEATURE_GROUPS.values() for c in g if c != "subject"]


def build_features(att: pd.DataFrame, everything: pd.DataFrame, task_rates: dict) -> pd.DataFrame:
    """One row per attempt, using ONLY information available when that attempt started.

    Every history feature is computed from rows strictly earlier than the attempt, so the
    label (and anything that happens after the start) can never leak into its own features.
    Vectorised (O(n log n)); `tests/test_rhythm.py` checks it against a literal O(n^2) reference.
    """
    n = len(att)
    if n == 0:
        return pd.DataFrame(columns=["hour_sin", "hour_cos", "is_weekend", "wd_sin", "wd_cos", "planned_min",
                                     "subject", "prior_rate", "subject_prior_rate", "load_24h",
                                     "hours_since_last", "attempts_today", "prev_day_task_rate"])
    S = SHRINKAGE_STRENGTH
    comp = att["completed"].to_numpy().astype(float)
    idx = np.arange(n)
    prior_sum = np.concatenate([[0.0], np.cumsum(comp)[:-1]])                  # outcomes strictly before i
    overall = (prior_sum + S * 0.5) / (idx + S)
    subj = att["subject"].reset_index(drop=True)
    k = subj.groupby(subj).cumcount().to_numpy().astype(float)                 # earlier same-subject attempts
    csum = pd.Series(comp).groupby(subj).cumsum().to_numpy() - comp            # their completed count
    sub_rate = (csum + S * overall) / (k + S)
    day = att["local_date"].reset_index(drop=True)
    same_day = day.groupby(day).cumcount().to_numpy().astype(float)

    # load in the previous 24h / time since the last finished session, from `everything`,
    # counting only sessions that ENDED at or before this attempt's start.
    st = pd.to_datetime(att["start_utc"], utc=True).to_numpy("datetime64[ns]").astype("int64")
    ev = everything[["end_utc", "actual_min"]].copy()
    ev["end_utc"] = pd.to_datetime(ev["end_utc"], utc=True)
    ev = ev.dropna(subset=["end_utc"]).sort_values("end_utc")
    ends = ev["end_utc"].to_numpy("datetime64[ns]").astype("int64")
    mins = np.nan_to_num(ev["actual_min"].to_numpy(dtype=float))
    cs = np.concatenate([[0.0], np.cumsum(mins)])
    day_ns = int(24 * 3600 * 1e9)
    hi = np.searchsorted(ends, st, side="right")                                # ends <= start
    lo = np.searchsorted(ends, st - day_ns, side="left")                        # ends >= start - 24h
    load = cs[hi] - cs[lo]
    last_end = np.where(hi > 0, ends[np.maximum(hi - 1, 0)], 0)
    since = np.where(hi > 0, np.minimum((st - last_end) / 3.6e12, 48.0), 48.0)

    h = att["hour"].to_numpy(dtype=float)
    wd = att["weekday"].to_numpy(dtype=float)
    prev = np.array([task_rates.get(d - timedelta(days=1), np.nan) for d in att["local_date"]], dtype=float)
    return pd.DataFrame({
        "hour_sin": np.sin(2 * np.pi * h / 24), "hour_cos": np.cos(2 * np.pi * h / 24),
        "is_weekend": (wd >= 5).astype(float),
        "wd_sin": np.sin(2 * np.pi * wd / 7), "wd_cos": np.cos(2 * np.pi * wd / 7),
        "planned_min": att["planned_min"].to_numpy(dtype=float), "subject": att["subject"].to_numpy(),
        "prior_rate": overall, "subject_prior_rate": sub_rate, "load_24h": load,
        "hours_since_last": since, "attempts_today": same_day, "prev_day_task_rate": prev,
    })

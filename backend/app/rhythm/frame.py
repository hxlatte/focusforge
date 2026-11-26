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
    """
    out = []
    comp = att["completed"].to_numpy()
    starts = att["start_utc"].tolist()
    ends_all = everything["end_utc"].tolist()
    act_all = everything["actual_min"].to_numpy()
    n = len(att)
    for i in range(n):
        r = att.iloc[i]
        st = starts[i]
        prior_comp = comp[:i]
        overall = (prior_comp.sum() + SHRINKAGE_STRENGTH * 0.5) / (i + SHRINKAGE_STRENGTH) if i else 0.5
        same = [j for j in range(i) if att.at[j, "subject"] == r["subject"]]
        sub_rate = ((comp[same].sum() + SHRINKAGE_STRENGTH * overall) / (len(same) + SHRINKAGE_STRENGTH)
                    if same else overall)
        load = 0.0
        last_end = None
        for e, m in zip(ends_all, act_all):
            if e <= st:
                if st - e <= timedelta(hours=24):
                    load += m
                if last_end is None or e > last_end:
                    last_end = e
        since = min((st - last_end).total_seconds() / 3600, 48.0) if last_end else 48.0
        same_day = sum(1 for j in range(i) if att.at[j, "local_date"] == r["local_date"])
        prev = task_rates.get(r["local_date"] - timedelta(days=1), np.nan)
        h, wd = r["hour"], r["weekday"]
        out.append({
            "hour_sin": np.sin(2 * np.pi * h / 24), "hour_cos": np.cos(2 * np.pi * h / 24),
            "is_weekend": float(wd >= 5),
            "wd_sin": np.sin(2 * np.pi * wd / 7), "wd_cos": np.cos(2 * np.pi * wd / 7),
            "planned_min": float(r["planned_min"]), "subject": r["subject"],
            "prior_rate": overall, "subject_prior_rate": sub_rate, "load_24h": load,
            "hours_since_last": since, "attempts_today": float(same_day), "prev_day_task_rate": prev,
        })
    return pd.DataFrame(out)

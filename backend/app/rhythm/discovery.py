"""Observed productivity patterns. Descriptive statistics only, no prediction.

Two different questions are kept apart:
  * "most active"      = where the minutes are (needs only start times)
  * "most successful"  = where focus attempts are completed (needs labelled attempts,
                         because a completion rate needs abandoned attempts as well)
"""
from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

from . import thresholds as T


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _rate_row(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"n": int(n), "completed": int(k), "rate": round(k / n, 3) if n else None,
            "ci_low": round(lo, 3), "ci_high": round(hi, 3)}


def compare_groups(k1: int, n1: int, k2: int, n2: int) -> dict | None:
    """Is group 1's completion rate reliably different from group 2's? None if too small."""
    if n1 < T.MIN_GROUP_N or n2 < T.MIN_GROUP_N:
        return None
    _, p = fisher_exact([[k1, n1 - k1], [k2, n2 - k2]])
    diff = k1 / n1 - k2 / n2
    return {"diff": round(diff, 3), "p_value": round(float(p), 4),
            "reliable": bool(p < T.FISHER_ALPHA and abs(diff) >= T.MIN_EFFECT)}


def heatmap(df: pd.DataFrame) -> dict:
    """Completed focus minutes by weekday x hour, split across the hours a session spans."""
    known = df[df["local_start"].notna() & df["completed"]]
    grid = np.zeros((7, 24))
    for _, r in known.iterrows():
        t, remaining = r["local_start"], float(r["actual_min"])
        while remaining > 1e-9:
            nxt = (t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
            chunk = min(remaining, (nxt - t).total_seconds() / 60)
            grid[t.weekday(), t.hour] += chunk
            remaining -= chunk
            t = nxt
    return {
        # One entry per weekday (Mon=0). Firestore forbids arrays directly inside arrays, so this
        # is a list of {weekday, minutes[24]} maps rather than a 7x24 matrix.
        "rows": [{"weekday": i, "minutes": np.round(grid[i], 1).tolist()} for i in range(7)],
        "sessions_used": int(len(known)),
        "sessions_excluded_no_start": int((~df["local_start"].notna() & df["completed"]).sum()),
    }


def period_activity(df: pd.DataFrame) -> list[dict]:
    known = df[df["local_start"].notna() & df["completed"]]
    tot = float(known["actual_min"].sum()) or 1.0
    out = []
    for p in T.PERIODS:
        sub = known[known["period"] == p]
        out.append({"period": p, "minutes": round(float(sub["actual_min"].sum()), 1),
                    "share": round(float(sub["actual_min"].sum()) / tot, 3), "sessions": int(len(sub))})
    return out


def period_success(att: pd.DataFrame) -> dict:
    rows = []
    for p in T.PERIODS:
        sub = att[att["period"] == p]
        rows.append({"period": p, **_rate_row(int(sub["completed"].sum()), len(sub))})
    eligible = [r for r in rows if r["n"] >= T.MIN_GROUP_N]
    comparison = None
    if len(eligible) >= 2:
        best = max(eligible, key=lambda r: r["rate"])
        rest = att[att["period"] != best["period"]]
        c = compare_groups(best["completed"], best["n"], int(rest["completed"].sum()), len(rest))
        if c:
            comparison = {"period": best["period"], **c, "rest_n": int(len(rest)),
                          "rest_rate": round(float(rest["completed"].mean()), 3)}
    return {"rows": rows, "best_vs_rest": comparison}


def weekday_consistency(df: pd.DataFrame) -> dict | None:
    """Share of each weekday (in the observed span) on which at least one session was completed."""
    d = df[df["completed"]].copy()
    dates = d["end_utc"].dt.tz_convert(d["local_start"].dropna().iloc[0].tzinfo) if d["local_start"].notna().any() \
        else d["end_utc"]
    days = sorted({x.date() for x in dates})
    if not days:
        return None
    first, last = days[0], days[-1]
    weeks = (last - first).days / 7
    if weeks < T.WEEKDAY_MIN_WEEKS:
        return {"available": False, "weeks_observed": round(weeks, 1), "needed_weeks": T.WEEKDAY_MIN_WEEKS}
    studied = set(days)
    per = {i: [0, 0] for i in range(7)}
    cur = first
    while cur <= last:
        per[cur.weekday()][1] += 1
        per[cur.weekday()][0] += cur in studied
        cur += timedelta(days=1)
    rows = [{"weekday": i, "studied_days": a, "days_observed": b, "share": round(a / b, 3) if b else None}
            for i, (a, b) in per.items()]
    return {"available": True, "weeks_observed": round(weeks, 1), "rows": rows}


def typical_duration(df: pd.DataFrame) -> dict:
    done = df[df["completed"]]["actual_min"]
    ab = df[df["status"] == "abandoned"]["actual_min"]
    out = {"completed_n": int(len(done))}
    if len(done):
        out.update(median=round(float(done.median()), 1), q25=round(float(done.quantile(.25)), 1),
                   q75=round(float(done.quantile(.75)), 1))
    out["abandoned_n"] = int(len(ab))
    if len(ab) >= T.MIN_ABANDONED_FOR_RATES:
        out["abandoned_median_min"] = round(float(ab.median()), 1)
    return out


LENGTH_BINS = [(0, 20, "≤20 min"), (20.01, 30, "21–30 min"), (30.01, 45, "31–45 min"), (45.01, 10_000, ">45 min")]


def abandonment_by_length(att: pd.DataFrame) -> dict:
    rows = []
    for lo, hi, label in LENGTH_BINS:
        sub = att[(att["planned_min"] >= lo) & (att["planned_min"] <= hi)]
        if len(sub):
            rows.append({"bin": label, "min": lo, "max": hi, **_rate_row(int(sub["completed"].sum()), len(sub)),
                         "abandon_rate": round(1 - float(sub["completed"].mean()), 3)})
    return {"rows": rows}


def subject_completion(att: pd.DataFrame) -> dict:
    """Per-subject completion, shrunk toward the overall rate so tiny groups don't look extreme."""
    if att.empty:
        return {"rows": [], "overall_rate": None, "hidden_subjects": 0}
    overall = float(att["completed"].mean())
    rows, hidden = [], 0
    for sub, g in att.groupby("subject"):
        n, k = len(g), int(g["completed"].sum())
        if n < T.MIN_SUBJECT_N:
            hidden += 1
            continue
        shrunk = (k + T.SHRINKAGE_STRENGTH * overall) / (n + T.SHRINKAGE_STRENGTH)
        rows.append({"subject": sub, **_rate_row(k, n), "shrunk_rate": round(shrunk, 3),
                     "vs_rest": compare_groups(k, n, int(att["completed"].sum()) - k, len(att) - n)})
    rows.sort(key=lambda r: -r["shrunk_rate"])
    return {"rows": rows, "overall_rate": round(overall, 3), "hidden_subjects": hidden}


def rhythm_clusters(df: pd.DataFrame) -> dict:
    """Exploratory: do sessions fall into distinct (time-of-day, length) groups?"""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    d = df[df["completed"] & df["local_start"].notna()]
    if len(d) < T.CLUSTER_MIN_SESSIONS:
        return {"available": False, "reason": f"needs {T.CLUSTER_MIN_SESSIONS}+ sessions with a start time",
                "n": int(len(d))}
    X = np.column_stack([np.sin(2 * np.pi * d["hour"] / 24), np.cos(2 * np.pi * d["hour"] / 24),
                         np.log1p(d["actual_min"]) / 2])
    best = None
    for k in (2, 3, 4):
        lab = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(X)
        if len(set(lab)) < 2:
            continue
        sc = float(silhouette_score(X, lab))
        if best is None or sc > best[0]:
            best = (sc, k, lab)
    if best is None or best[0] < T.CLUSTER_MIN_SILHOUETTE:
        return {"available": False, "n": int(len(d)),
                "reason": "no clearly separated groups (silhouette below threshold)",
                "silhouette": None if best is None else round(best[0], 3)}
    sc, k, lab = best
    groups = []
    for c in range(k):
        g = d[lab == c]
        groups.append({"n": int(len(g)), "median_start_hour": float(g["hour"].median()),
                       "median_minutes": round(float(g["actual_min"].median()), 1)})
    return {"available": True, "k": k, "silhouette": round(sc, 3), "groups": groups,
            "note": "Exploratory grouping, not a prediction."}

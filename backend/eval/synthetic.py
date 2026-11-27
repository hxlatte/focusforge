"""SYNTHETIC data for controlled model testing ONLY.

Every document carries `synthetic: true`. The API refuses to analyse a user whose data
contains synthetic rows, and nothing under app/ imports this module, so synthetic data
can never reach the real dashboard. It exists to check that the engine can recover a
pattern that was deliberately planted (and does NOT invent one when none was planted).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

TZ = "Asia/Kolkata"
SUBJECTS = ["coding", "math", "reading"]


def generate(seed: int, days: int = 120, planted: bool = True, per_day: float = 2.2,
             start_day: datetime | None = None) -> list[dict]:
    """Return raw session docs (new schema). With planted=True: mornings and short sessions
    are completed more, evenings and 45+ minute sessions less, coding more, math less."""
    rng = np.random.default_rng(seed)
    zone = ZoneInfo(TZ)
    start_day = (start_day or datetime(2026, 1, 5)).replace(tzinfo=zone)
    docs: list[dict] = []
    for d in range(days):
        for _ in range(rng.poisson(per_day)):
            slot = rng.choice(["morning", "afternoon", "evening"], p=[.35, .3, .35])
            hour = {"morning": rng.normal(9, 1.2), "afternoon": rng.normal(14, 1.2), "evening": rng.normal(20, 1.2)}[slot]
            hour = float(np.clip(hour, 5, 23))
            t0 = start_day + timedelta(days=d, hours=hour)
            planned = int(rng.choice([15, 25, 25, 40, 50]))
            subject = str(rng.choice(SUBJECTS))
            logit = 0.6
            if planted:
                logit += {"morning": 1.2, "afternoon": 0.0, "evening": -0.9}[slot]
                logit += -1.6 if planned >= 40 else 0.0
                logit += {"coding": 0.5, "math": -0.5, "reading": 0.0}[subject]
            done = rng.random() < 1 / (1 + np.exp(-logit))
            actual = planted_actual = planned if done else max(1.0, planned * float(rng.uniform(.1, .8)))
            end = t0 + timedelta(minutes=actual)
            docs.append({
                "subject": subject.title(), "type": "pomodoro", "status": "completed" if done else "abandoned",
                "duration": int(round(actual)), "plannedDuration": planned, "actualDuration": float(actual),
                "startedAt": t0.astimezone(timezone.utc).isoformat(), "endedAt": end.astimezone(timezone.utc).isoformat(),
                "date": end.astimezone(timezone.utc).isoformat(), "tz": TZ, "notes": "", "synthetic": True,
            })
    return docs

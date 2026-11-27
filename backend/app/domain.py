"""Normalising raw Firestore documents into typed records.

The frontend wrote sessions as {subject, duration, notes, date, type} and
nothing else. New fields are additive and optional:

    status          'completed' | 'abandoned'   (absent on legacy rows)
    plannedDuration minutes the timer was set to
    actualDuration  minutes actually focused before finishing/stopping
    startedAt       ISO timestamp when the timer started
    endedAt         ISO timestamp when it finished/was stopped
    tz              IANA time zone of the device that recorded it
    confidence      optional 1-4 self-rating after the session

Rules applied here, deliberately conservative:
  * A legacy row has no status. It is treated as completed for descriptive
    statistics, but it is NOT a labelled example for the classifier, because
    abandoned attempts were never recorded (it would be a one-class sample).
  * For manual logs the stored `date` is when the log was typed in, not when
    studying happened, so no start time is derived and hour-of-day analysis
    excludes them.
  * For legacy Pomodoro rows the timer only saved on completion, so
    start ~= date - duration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

_SPLIT_RE = re.compile(r"\s*(?:—|–|\s-\s|:)\s*")


def split_subject(subject: str) -> tuple[str, str | None]:
    """'Mathematics — Integration' -> ('Mathematics', 'Integration')."""
    subject = (subject or "").strip() or "General"
    parts = _SPLIT_RE.split(subject, maxsplit=1)
    parent = parts[0].strip() or "General"
    detail = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    return parent, detail


def parse_ts(value: Any) -> datetime | None:
    """Parse an ISO timestamp (Z or offset). Returns aware UTC, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def safe_zone(name: str | None) -> ZoneInfo | timezone:
    if name:
        try:
            return ZoneInfo(name)
        except Exception:  # unknown tz string
            pass
    return timezone.utc


@dataclass(frozen=True)
class Session:
    id: str
    subject: str
    parent_subject: str
    detail: str | None
    type: str                    # 'pomodoro' | 'manual'
    status: str                  # 'completed' | 'abandoned'
    labelled: bool               # status explicitly recorded (new-style row)
    planned_min: float
    actual_min: float
    notes: str
    logged_at: datetime          # UTC
    start_utc: datetime | None   # None when the start time is unknown
    local_start: datetime | None # start in the user's zone (None if unknown)
    tz_known: bool
    confidence: int | None
    synthetic: bool = False

    @property
    def hour(self) -> int | None:
        return self.local_start.hour if self.local_start else None

    @property
    def weekday(self) -> int | None:  # Monday=0
        return self.local_start.weekday() if self.local_start else None

    @property
    def completed(self) -> bool:
        return self.status == "completed"


def _num(value: Any, default: float) -> float:
    try:
        v = float(value)
        return v if v == v and v > 0 else default
    except (TypeError, ValueError):
        return default


def normalize_session(raw: dict[str, Any], default_tz: str | None = None) -> Session | None:
    """Return a Session, or None if the row is unusable (no valid timestamp)."""
    logged = parse_ts(raw.get("endedAt")) or parse_ts(raw.get("date"))
    if logged is None:
        return None

    subject = str(raw.get("subject") or "General").strip() or "General"
    parent, detail = split_subject(subject)
    stype = raw.get("type") if raw.get("type") in ("pomodoro", "manual") else "manual"

    explicit = raw.get("status") in ("completed", "abandoned")
    status = raw["status"] if explicit else "completed"

    legacy_dur = _num(raw.get("duration"), 25.0)
    planned = _num(raw.get("plannedDuration"), legacy_dur)
    actual = _num(raw.get("actualDuration"), legacy_dur)

    tz_name = raw.get("tz") or default_tz
    tz_known = bool(tz_name) and safe_zone(tz_name) is not timezone.utc or tz_name == "UTC"
    zone = safe_zone(tz_name)

    start = parse_ts(raw.get("startedAt"))
    if start is None and stype == "pomodoro":
        start = logged - timedelta(minutes=actual)
    local = start.astimezone(zone) if (start is not None and tz_known) else None

    conf = raw.get("confidence")
    conf = int(conf) if isinstance(conf, (int, float)) and 1 <= conf <= 4 else None

    return Session(
        id=str(raw.get("id", "")),
        subject=subject,
        parent_subject=parent,
        detail=detail,
        type=stype,
        status=status,
        labelled=explicit,
        planned_min=planned,
        actual_min=actual,
        notes=str(raw.get("notes") or "").strip(),
        logged_at=logged,
        start_utc=start,
        local_start=local,
        tz_known=tz_known,
        confidence=conf,
        synthetic=bool(raw.get("synthetic", False)),
    )


def normalize_sessions(rows: list[dict[str, Any]], default_tz: str | None = None) -> list[Session]:
    out = [s for r in rows if (s := normalize_session(r, default_tz)) is not None]
    out.sort(key=lambda s: s.logged_at)
    return out

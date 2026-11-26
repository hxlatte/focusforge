"""Unified recommendation layer.

Combines the two engines without merging them:
  Study-Log Analyzer   -> WHAT to revise (topic, why it was flagged, due date)
  Cognitive Rhythm     -> WHEN and for HOW LONG (only if its own evidence supports it)

A transparent rule combiner, not a model: every clause in a recommendation is filled from a
named field of an engine's output and is listed under `why` with its source. If the rhythm
engine has nothing reliable to say, the recommendation says nothing about timing instead of
guessing. Wording is associative ("completed more often"), never causal.

Recommendations are PROPOSALS. Nothing is created for the user until they accept one.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..domain import Session, parse_ts, safe_zone
from ..rhythm.thresholds import PERIODS

MAX_ACTIVE = 5
DEFAULT_MINUTES = 25
DISMISS_COOLDOWN_DAYS = 7
OPEN = ("proposed", "accepted")
_PERIOD_END = {"morning": 12, "afternoon": 17, "evening": 22, "night": 24}
_PERIOD_START = {"morning": 5, "afternoon": 12, "evening": 17, "night": 22}


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _duration(rhythm: dict) -> tuple[int, list[dict]]:
    """Session length: from the user's own completed sessions, capped where long sessions are stopped early."""
    why: list[dict] = []
    ins = {i["id"]: i for i in rhythm.get("insights", [])}
    td = (rhythm.get("observed") or {}).get("typical_duration") or {}
    minutes = DEFAULT_MINUTES
    if td.get("completed_n", 0) >= 5 and td.get("median"):
        minutes = int(min(50, max(15, 5 * round(td["median"] / 5))))
        why.append({"source": "rhythm", "ref": "typical_focus_duration",
                    "text": f"Your completed sessions typically last about {round(td['median'])} minutes."})
    else:
        why.append({"source": "default", "ref": None,
                    "text": f"No reliable session-length pattern yet, so the standard {DEFAULT_MINUTES}-minute length is used."})
    cap = ins.get("long_sessions_abandoned")
    if cap:
        lim = int(cap["action"]["max_planned_min"])
        if minutes > lim:
            minutes = max(15, lim)
        ev = cap["evidence"]
        why.append({"source": "rhythm", "ref": "long_sessions_abandoned",
                    "text": f"You stopped {_pct(ev['abandon_rate'])} of sessions planned for {ev['bin']} early "
                            f"({ev['n'] - ev['completed']}/{ev['n']}), so a shorter session is suggested."})
    return minutes, why


def _period(rhythm: dict) -> tuple[str | None, list[dict], str | None]:
    """Best supported time of day, with the strength of the evidence behind it."""
    ins = {i["id"]: i for i in rhythm.get("insights", [])}
    if "best_period_completion" in ins:
        i = ins["best_period_completion"]; ev = i["evidence"]
        return ev["period"], [{"source": "rhythm", "ref": "best_period_completion", "kind": "observed",
                               "text": f"Sessions you started in the {ev['period']} were completed {_pct(ev['rate'])} of the time "
                                       f"({ev['completed']}/{ev['n']}) versus {_pct(ev['rest_rate'])} at other times."}], "observed"
    if "model_best_slot" in ins:
        a = ins["model_best_slot"]["action"]
        return a["period"], [{"source": "rhythm", "ref": "model_best_slot", "kind": "predicted",
                              "text": f"Your personal model estimates sessions in the {a['period']} are most likely to be completed. "
                                      f"This is a model estimate, not something observed."}], "predicted"
    if "most_active_period" in ins:
        ev = ins["most_active_period"]["evidence"]
        if ev["sessions"] >= 8:
            return ev["period"], [{"source": "rhythm", "ref": "most_active_period", "kind": "observed",
                                   "text": f"You do most of your studying in the {ev['period']} ({ev['sessions']} sessions). "
                                           f"That shows when you tend to study, not when it works best."}], "weak"
    return None, [], None


def _when(period: str | None, due: datetime | None, now: datetime, tz: str) -> tuple[str, str | None]:
    """(ISO date, spoken phrase)."""
    zone = safe_zone(tz)
    local = now.astimezone(zone)
    day = local.date()
    if period and local.hour >= _PERIOD_END[period] - 1:
        day += timedelta(days=1)
    elif not period and local.hour >= 21:
        day += timedelta(days=1)
    if due:
        due_day = due.astimezone(zone).date()
        if due_day > day:
            day = due_day
    today = local.date()
    word = "today" if day == today else "tomorrow" if day == today + timedelta(days=1) else day.strftime("on %a %b %d")
    return day.isoformat(), (f"{word} {period}" if period else word)


def _topic_why(t: dict) -> list[dict]:
    out = [{"source": "study_log", "ref": t["id"], "text": r} for r in t.get("reasons", [])]
    c = t.get("stance_counts", {})
    if c.get("struggling", 0) + c.get("revise", 0) >= 2 and not any("times in the last" in o["text"] for o in out):
        out.append({"source": "study_log", "ref": t["id"],
                    "text": f"You flagged difficulty or revision on this topic {c['struggling'] + c['revise']} times."})
    s = t.get("schedule") or {}
    if s.get("basis") == "fsrs":
        out.append({"source": "study_log", "ref": t["id"],
                    "text": f"Spaced-repetition scheduling (from your recall ratings) puts this topic's review at "
                            f"{s['due'][:10]}; estimated recall now is about {_pct(s['retrievability_now'])}."})
    elif s.get("basis") == "initial_estimate":
        out.append({"source": "study_log", "ref": t["id"],
                    "text": "No recall rating yet, so this date is an estimate from your reflection, not a measured forgetting curve."})
    return out


def _adherence(rec: dict, sessions: list[Session], now: datetime) -> str:
    """Did the user study this topic after accepting? Matched on the topic name in subject or notes."""
    acc = parse_ts(rec.get("statusUpdatedAt"))
    name = rec["topic"].lower()
    if acc is None:
        return "pending"
    for s in sessions:
        if s.logged_at >= acc and (name in s.subject.lower() or name in s.notes.lower()):
            return "followed"
    sug = parse_ts(rec.get("suggested_date") + "T23:59:59+00:00") if rec.get("suggested_date") else None
    return "missed" if sug and now > sug + timedelta(days=1) else "pending"


def run(learning: dict, rhythm: dict, existing: list[dict], sessions: list[Session],
        now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    tz = (rhythm or {}).get("tz") or "UTC"
    prev = {r["id"]: r for r in existing}
    topics = {t["id"]: t for t in (learning or {}).get("topics", [])}
    candidates = [t for t in topics.values() if t.get("needs_revision")]

    def rank(t):
        s = t.get("schedule") or {}
        c = t.get("stance_counts", {})
        return (-(s.get("overdue_days") or 0), -(c.get("struggling", 0) * 2 + c.get("revise", 0)), t["name"])
    candidates.sort(key=rank)

    minutes, dur_why = _duration(rhythm or {})
    period, per_why, period_kind = _period(rhythm or {})
    out: list[dict] = []
    for t in candidates:
        rid = f"rev-{t['id']}"
        old = prev.get(rid)
        status, status_at = "proposed", None
        if old:
            status, status_at = old.get("status", "proposed"), old.get("statusUpdatedAt")
            last_neg = max((e["when"] for e in (topics[t["id"]].get("evidence") or []) if e["stance"] in ("struggling", "revise")),
                           default=None) if topics[t["id"]].get("evidence") else t.get("last_seen")
            at = parse_ts(status_at)
            if status == "completed" and at and parse_ts(t.get("last_seen")) and parse_ts(t["last_seen"]) > at \
                    and t.get("last_signal") in ("struggling", "revise"):
                status, status_at = "proposed", None            # new difficulty after completing: propose again
            elif status == "dismissed" and at and now - at < timedelta(days=DISMISS_COOLDOWN_DAYS):
                pass                                            # respect the dismissal
            elif status == "dismissed":
                status, status_at = "proposed", None
        due = parse_ts((t.get("schedule") or {}).get("due"))
        date, phrase = _when(period, due, now, tz)
        contributors = ["study_log"] + (["rhythm"] if (period or any(w["source"] == "rhythm" for w in dur_why)) else [])
        why = _topic_why(t) + per_why + dur_why
        timing_clause = ""
        if per_why and period_kind in ("observed", "predicted"):
            timing_clause = f" {phrase.capitalize()} fits your history better" if period_kind == "observed" \
                else f" {phrase.capitalize()} is what your model estimates is most likely to work"
        summary = (f"{t['name']} needs revision. We suggest a {minutes}-minute revision session {phrase}."
                   + ("" if not per_why else f"{timing_clause}: see why below."))
        rec = {
            "id": rid, "kind": "revision", "topic_id": t["id"], "topic": t["name"],
            "title": f"Revise {t['name']}", "summary": summary,
            "action": {"type": "revision_session", "minutes": minutes, "period": period, "date": date},
            "suggested_date": date, "why": why, "contributors": contributors,
            "timing_basis": period_kind,        # observed | predicted | weak | None
            "caveats": ["Recommendations are proposals based on your own history; they describe association, not cause."]
                       + ([] if period_kind else ["No reliable time-of-day pattern yet, so no time is suggested."]),
            "status": status, "statusUpdatedAt": status_at, "created_at": (old or {}).get("created_at") or now.isoformat(),
        }
        if status == "accepted":
            rec["adherence"] = _adherence(rec, sessions, now)
        out.append(rec)

    active = [r for r in out if r["status"] in OPEN]
    shown = active[:MAX_ACTIVE] + [r for r in out if r["status"] not in OPEN]
    deferred = max(0, len(active) - MAX_ACTIVE)

    # Keep history of resolved recommendations whose topic is no longer flagged.
    kept_ids = {r["id"] for r in shown}
    for old in existing:
        if old["id"] not in kept_ids and old.get("status") in ("accepted", "completed", "dismissed"):
            shown.append(old)
    return {"recommendations": shown, "deferred": deferred, "evaluation": evaluate(shown)}


def evaluate(recs: list[dict]) -> dict:
    """Counters only. Whether recommendations help needs far more use than one person's history;
    this just records what happened so it can be judged later."""
    c = {s: sum(r.get("status") == s for r in recs) for s in ("proposed", "accepted", "dismissed", "completed")}
    resolved = c["accepted"] + c["completed"] + c["dismissed"]
    acc = c["accepted"] + c["completed"]
    adh = [r.get("adherence") for r in recs if r.get("status") == "accepted"]
    return {**c, "total": len(recs),
            "acceptance_rate": round(acc / resolved, 3) if resolved >= 5 else None,
            "completion_rate_among_accepted": round(c["completed"] / acc, 3) if acc >= 5 else None,
            "adherence": {"followed": adh.count("followed"), "missed": adh.count("missed"), "pending": adh.count("pending")},
            "note": "Rates appear only after 5+ responses. They record what you did with recommendations; they do not "
                    "show that following them improves anything."}

"""Revision scheduling.

Rated topics are scheduled by FSRS (the open-source reference implementation, `fsrs`,
default parameters, not personalised). A recall rating is the only thing that moves a
topic's FSRS state: writing "I understood X" is not evidence of retention.

Topics with revision signals but no rating yet get a fixed initial estimate, labelled as
such. Nothing here claims mastery.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fsrs import Card, Rating, Scheduler

DESIRED_RETENTION = 0.90
INITIAL_DAYS = {"struggling": 1, "revise": 2}   # fixed first-pass estimates, not predictions


def _scheduler() -> Scheduler:
    # No sub-day learning steps: topic reviews are day-scale.
    return Scheduler(desired_retention=DESIRED_RETENTION, learning_steps=(), relearning_steps=(),
                     enable_fuzzing=False)


def replay(reviews: list[tuple[datetime, int]], now: datetime) -> dict | None:
    """Replay a topic's recall ratings in time order. Deterministic, so nothing but the
    ratings themselves needs to be stored."""
    if not reviews:
        return None
    sch = _scheduler()
    card = Card()
    for at, rating in sorted(reviews, key=lambda r: r[0]):
        card, _ = sch.review_card(card, Rating(int(rating)), at)
    due = card.due if card.due.tzinfo else card.due.replace(tzinfo=timezone.utc)
    return {
        "basis": "fsrs", "due": due.isoformat(), "stability_days": round(card.stability, 2),
        "difficulty": round(card.difficulty, 2),
        "retrievability_now": round(sch.get_card_retrievability(card, now), 3),
        "reviews": len(reviews), "last_rating": int(sorted(reviews, key=lambda r: r[0])[-1][1]),
        "last_review": sorted(reviews, key=lambda r: r[0])[-1][0].isoformat(),
        "overdue_days": max(0.0, round((now - due).total_seconds() / 86400, 1)),
    }


def initial_estimate(last_signal_stance: str, last_signal_at: datetime, now: datetime) -> dict:
    days = INITIAL_DAYS.get(last_signal_stance, 2)
    due = last_signal_at + timedelta(days=days)
    return {"basis": "initial_estimate", "due": due.isoformat(), "reviews": 0,
            "overdue_days": max(0.0, round((now - due).total_seconds() / 86400, 1)),
            "note": "Estimate from your reflection only. Rate your recall to start spaced-repetition scheduling."}

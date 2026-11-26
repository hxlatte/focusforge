"""Study-Log Analyzer: reflections -> topics, learning history, clusters, revision schedule."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from ..domain import Session, parse_ts
from . import schedule as SCH
from . import topics as T
from .embedder import Embedder, get_embedder
from .extract import Observation, Reflection, extract

ENGINE_VERSION = "1.0"
MIN_NOTES_FOR_TOPICS = 1
MIN_DIFFICULTY_FOR_CLUSTERS = 4
CLUSTER_DISTANCE = {True: 0.45, False: 0.70}   # cosine distance cut-off: semantic vs lexical embedder
RECENT_DAYS = 45
EVIDENCE_PER_TOPIC = 8
NEGATIVE = ("struggling", "revise")
POSITIVE = ("confident", "understood")


def _week(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def cluster_difficulties(obs: list[Observation], emb: Embedder) -> list[dict]:
    """Group difficulty statements that are about related things.

    Uses the full clause (not just the topic phrase) so wording like "tree recursion is
    confusing" and "struggling with recursive functions" land together when the
    embedder is semantic. With the lexical fallback only surface similarity is captured.
    """
    from sklearn.cluster import AgglomerativeClustering

    items = [o for o in obs if o.stance in NEGATIVE]
    if len(items) < MIN_DIFFICULTY_FOR_CLUSTERS:
        return []
    # Semantic model: embed the whole clause (context helps). Lexical fallback: topic phrase only,
    # because filler words in a clause add n-gram noise that hides shared word stems.
    texts = [o.topic + " . " + o.clause if emb.semantic else o.topic for o in items]
    X = emb.encode(texts)
    lab = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                  distance_threshold=CLUSTER_DISTANCE[emb.semantic]).fit_predict(X)
    out = []
    for c in sorted(set(lab)):
        idx = [i for i, l in enumerate(lab) if l == c]
        if len(idx) < 2:
            continue
        members = [items[i] for i in idx]
        label = Counter(m.topic for m in members).most_common(1)[0][0]
        out.append({"id": f"c{c}", "label": T.display(label), "size": len(members),
                    "sessions": len({m.session_id for m in members}),
                    "topics": sorted({T.display(m.topic) for m in members}),
                    "members": [{"session_id": m.session_id, "when": m.when, "clause": m.clause, "sentence": m.sentence}
                                for m in members][:12]})
    out.sort(key=lambda d: (-d["sessions"], -d["size"]))
    return out


def analyze(sessions: list[Session], reviews: list[dict[str, Any]] | None = None, now: datetime | None = None,
            embedder: Embedder | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    emb = embedder or get_embedder()
    reflections: list[Reflection] = [r for s in sessions if (r := extract(s)) is not None]
    obs: list[Observation] = [o for r in reflections for o in r.observations]
    noted = sum(1 for s in sessions if s.notes)

    result: dict[str, Any] = {
        "engine": "study_log", "version": ENGINE_VERSION, "generated_at": now.isoformat(),
        "embedder": {"name": emb.name, "semantic": emb.semantic},
        "data": {"sessions_with_notes": noted, "reflections_parsed": len(reflections),
                 "observations": len(obs), "unlinked_signals": sum(r.unlinked for r in reflections)},
        "topics": [], "clusters": [], "groups": [], "trend": [], "revision_schedule": [],
    }
    if not obs:
        result["status"] = {
            "stage": "collecting",
            "message": ("No study reflections yet." if not noted else
                        "Your notes did not mention anything this analyzer could attribute to a topic."),
            "next_unlocks": ["Write a short reflection after a session (what you covered, what was unclear). "
                             "Topics, difficulties and revision reminders are built from your own words."]}
        return result

    # ---- canonical topics --------------------------------------------------------------
    canon = T.canonicalise(Counter(o.topic for o in obs))
    by_topic: dict[str, list[Observation]] = defaultdict(list)
    for o in obs:
        by_topic[canon[o.topic]].append(o)

    rated: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
    for r in reviews or []:
        at, tid, rating = parse_ts(r.get("at")), r.get("topicId"), r.get("rating")
        if at and tid and rating in (1, 2, 3, 4):
            rated[tid].append((at, int(rating)))

    topics_out = []
    for name, items in by_topic.items():
        tid = T.slug(name)
        items.sort(key=lambda o: o.when)
        counts = Counter(o.stance for o in items)
        sess = {o.session_id for o in items}
        last = items[-1]
        signal_items = [o for o in items if o.stance != "mention"]
        last_neg = next((o for o in reversed(items) if o.stance in NEGATIVE), None)
        last_pos = next((o for o in reversed(items) if o.stance in POSITIVE), None)
        last_rev = next((o for o in reversed(items) if o.stance == "revised"), None)
        recent_neg = [o for o in items if o.stance in NEGATIVE
                      and parse_ts(o.when) and now - parse_ts(o.when) <= timedelta(days=RECENT_DAYS)]

        review_list = rated.get(tid, [])
        sched = SCH.replay(review_list, now)
        reasons: list[str] = []
        if sched:
            needs = parse_ts(sched["due"]) <= now or sched["last_rating"] <= 2
            reasons.append(f"Your last recall rating was {sched['last_rating']}/4"
                           + (" and it is due for review." if parse_ts(sched["due"]) <= now else "."))
            status = "due_for_review" if needs else "scheduled"
        else:
            neg_after_pos = last_neg and (not last_pos or last_neg.when >= last_pos.when)
            needs = bool(neg_after_pos or len(recent_neg) >= 2 and not (last_pos and last_pos.when > recent_neg[-1].when))
            if neg_after_pos:
                reasons.append(f"Your most recent reflection on this topic ({_fmt(last_neg.when)}) said: "
                               f"“{last_neg.sentence}”")
            if len(recent_neg) >= 2:
                reasons.append(f"You flagged difficulty or revision {len(recent_neg)} times in the last {RECENT_DAYS} days.")
            if needs and last_neg:
                sched = SCH.initial_estimate(last_neg.stance, parse_ts(last_neg.when), now)
            status = ("needs_revision" if needs else
                      "reported_confident" if last_pos and last_pos.stance == "confident" else
                      "reported_understood" if last_pos else "mentioned")
        if last_rev and last_neg and last_rev.when > last_neg.when and not sched:
            reasons.append("You noted revising it after the last difficulty; no recall rating yet.")

        weekly: dict[str, Counter] = defaultdict(Counter)
        for o in items:
            weekly[_week(parse_ts(o.when))][o.stance] += 1
        topics_out.append({
            "id": tid, "name": T.display(name),
            "subjects": sorted({o.parent_subject for o in items}),
            "first_seen": items[0].when, "last_seen": last.when,
            "mentions": len(items), "sessions": len(sess), "revisits": max(0, len(sess) - 1),
            "stance_counts": {k: counts.get(k, 0) for k in
                              ("struggling", "revise", "confident", "understood", "revised", "mention")},
            "last_signal": signal_items[-1].stance if signal_items else "mention",
            "status": status, "needs_revision": bool(needs), "reasons": reasons,
            "schedule": sched,
            "recall": {"ratings": len(review_list), "last": review_list and sorted(review_list)[-1][1] or None},
            "evidence": [{"session_id": o.session_id, "when": o.when, "stance": o.stance, "cue": o.cue,
                          "sentence": o.sentence, "inherited": o.inherited}
                         for o in reversed(signal_items or items)][:EVIDENCE_PER_TOPIC],
            "weekly": [{"week": w, **{k: c.get(k, 0) for k in ("struggling", "revise", "confident", "understood")}}
                       for w, c in sorted(weekly.items())],
        })

    topics_out.sort(key=lambda t: (not t["needs_revision"], -t["stance_counts"]["struggling"], -t["mentions"], t["name"]))
    result["topics"] = topics_out
    result["clusters"] = cluster_difficulties(obs, emb)

    groups: dict[str, list[str]] = defaultdict(list)
    for t in topics_out:
        for s in t["subjects"] or ["General"]:
            groups[s].append(t["id"])
    result["groups"] = [{"subject": s, "topic_ids": ids} for s, ids in sorted(groups.items())]

    wk: dict[str, Counter] = defaultdict(Counter)
    for o in obs:
        wk[_week(parse_ts(o.when))][o.stance] += 1
    for w, c in sorted(wk.items()):
        pos, neg = c["confident"] + c["understood"], c["struggling"] + c["revise"]
        result["trend"].append({"week": w, "struggling": c["struggling"], "revise": c["revise"],
                                "confident": c["confident"], "understood": c["understood"],
                                "difficulty_share": round(neg / (pos + neg), 3) if pos + neg else None})

    sched_rows = [{"topic_id": t["id"], "name": t["name"], **t["schedule"], "status": t["status"]}
                  for t in topics_out if t["schedule"] and (t["needs_revision"] or t["schedule"]["basis"] == "fsrs")]
    sched_rows.sort(key=lambda r: r["due"])
    result["revision_schedule"] = sched_rows
    n_rev = sum(t["needs_revision"] for t in topics_out)
    result["status"] = {
        "stage": "active",
        "message": f"{len(topics_out)} topics found in {len(reflections)} reflections; {n_rev} flagged for revision.",
        "next_unlocks": ([] if any(t["recall"]["ratings"] for t in topics_out) else
                         ["Rate your recall when you revisit a topic (1–4). Only ratings start spaced-repetition scheduling; "
                          "until then dates are estimates from your reflections."]),
        "caveat": "Topics and difficulties are read from your wording and can be wrong. Open the evidence to check.",
    }
    return result


def _fmt(iso: str) -> str:
    d = parse_ts(iso)
    return d.strftime("%b %d") if d else iso

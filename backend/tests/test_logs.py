from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthUser, current_user
from app.domain import normalize_sessions
from app.logs import schedule as SCH
from app.logs.analyzer import analyze
from app.logs.embedder import TfidfEmbedder
from app.main import app, get_repo
from app.repo import InMemoryRepo

NOW = datetime(2026, 11, 26, tzinfo=timezone.utc)
EMB = TfidfEmbedder()


def sess(notes, subject="Focus Session"):
    docs = [{"id": f"s{i}", "subject": subject, "duration": 30, "type": "manual",
             "date": f"2026-11-{10 + i:02d}T10:00:00Z", "notes": n} for i, n in enumerate(notes)]
    return normalize_sessions(docs, "UTC")


def by_name(res):
    return {t["name"]: t for t in res["topics"]}


def test_spec_example_end_to_end():
    r = analyze(sess(["I studied neural networks today. I understood the basic architecture, but I am still "
                      "confused about backpropagation. I need to revise gradient descent."]), [], NOW, EMB)
    t = by_name(r)
    assert t["Neural Network"]["status"] == "mentioned"
    assert t["Architecture"]["status"] == "reported_understood"
    assert t["Backpropagation"]["status"] == "needs_revision" and t["Backpropagation"]["stance_counts"]["struggling"] == 1
    assert t["Gradient Descent"]["status"] == "needs_revision" and t["Gradient Descent"]["stance_counts"]["revise"] == 1
    # the evidence is the user's own sentence, so the insight can be inspected
    assert "backpropagation" in t["Backpropagation"]["evidence"][0]["sentence"].lower()
    assert t["Backpropagation"]["schedule"]["basis"] == "initial_estimate"   # no rating yet: not claimed as FSRS


def test_four_stances_are_distinguished():
    r = analyze(sess(["I understood vectors. Confident about matrices. Confused about tensors. Need to revise eigenvalues."]), [], NOW, EMB)
    got = {t["name"]: t["last_signal"] for t in r["topics"]}
    assert got == {"Vector": "understood", "Matrix": "confident", "Tensor": "struggling", "Eigenvalue": "revise"}


def test_negation_and_not_hard():
    r = analyze(sess(["I don't fully understand recursion. Pointers are not hard."]), [], NOW, EMB)
    got = {t["name"]: t["last_signal"] for t in r["topics"]}
    assert got["Recursion"] == "struggling" and got["Pointer"] == "understood"


def test_later_confidence_clears_flag_but_is_not_mastery():
    r = analyze(sess(["Confused about recursion.", "Recursion makes sense now."]), [], NOW, EMB)
    t = by_name(r)["Recursion"]
    assert not t["needs_revision"] and t["status"] == "reported_confident"      # self-report, not verified
    assert t["recall"]["ratings"] == 0 and t["schedule"] is None


def test_abbreviation_merges_into_one_topic():
    r = analyze(sess(["Confused about backpropagation.", "Backprop still confusing."]), [], NOW, EMB)
    assert [t["name"] for t in r["topics"]] == ["Backpropagation"]
    assert r["topics"][0]["stance_counts"]["struggling"] == 2 and r["topics"][0]["revisits"] == 1


def test_related_difficulties_cluster_and_unrelated_do_not():
    notes = ["I don't understand recursion.", "Tree recursion is confusing.", "I am struggling with recursive functions.",
             "Pointers are really hard for me.", "Confused about pointer arithmetic.", "SQL joins are tricky."]
    r = analyze(sess(notes), [], NOW, EMB)
    labels = {tuple(sorted(c["topics"])) for c in r["clusters"]}
    assert any({"Recursion", "Tree Recursion"} <= set(c) for c in labels)
    assert not any("Sql Join" in c and "Recursion" in c for c in labels)
    assert r["embedder"]["semantic"] is False            # fallback is disclosed, never passed off as semantic


def test_cold_start_without_notes():
    r = analyze(sess([""]), [], NOW, EMB)
    assert r["status"]["stage"] == "collecting" and r["topics"] == []


def test_fsrs_replay_is_deterministic_and_rating_driven():
    revs = [(datetime(2026, 11, 1, tzinfo=timezone.utc), 3), (datetime(2026, 11, 5, tzinfo=timezone.utc), 3)]
    a, b = SCH.replay(revs, NOW), SCH.replay(list(reversed(revs)), NOW)
    assert a == b and a["basis"] == "fsrs" and a["stability_days"] > 0
    fail = SCH.replay(revs + [(datetime(2026, 11, 20, tzinfo=timezone.utc), 1)], NOW)
    assert fail["stability_days"] < a["stability_days"]          # forgetting shortens the interval
    assert SCH.replay([], NOW) is None


def test_recall_ratings_move_topic_to_fsrs_schedule():
    s = sess(["Confused about recursion."])
    reviews = [{"topicId": "recursion", "rating": 3, "at": "2026-11-12T10:00:00Z"}]
    t = by_name(analyze(s, reviews, NOW, EMB))["Recursion"]
    assert t["schedule"]["basis"] == "fsrs" and t["recall"]["ratings"] == 1


def test_api_stores_topics_and_isolates_users():
    repo = InMemoryRepo()
    repo.seed("alice", "sessions", {"a": {"subject": "ML", "duration": 30, "type": "manual", "date": "2026-11-20T10:00:00Z",
                                          "notes": "Confused about backpropagation."}})
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[current_user] = lambda: AuthUser("alice")
    try:
        c = TestClient(app)
        body = c.post("/v1/analyze", json={"tz": "UTC"}).json()
        assert body["learning"]["topics"][0]["id"] == "backpropagation"
        assert "evidence" not in body["learning"]["topics"][0]                  # summary only in the analysis doc
        full = repo.get("alice", "topics", "backpropagation")
        assert full["evidence"][0]["sentence"].startswith("Confused")            # evidence lives in topics/{id}
        assert repo.list("bob", "topics") == []
        repo.seed("alice", "sessions", {"a": {"subject": "ML", "duration": 30, "type": "manual",
                                              "date": "2026-11-20T10:00:00Z", "notes": "Confident about vectors."}})
        c.post("/v1/analyze", json={"tz": "UTC"})
        assert {t["id"] for t in repo.list("alice", "topics")} == {"vector"}      # stale topic removed
    finally:
        app.dependency_overrides.clear()


def test_markup_in_notes_never_becomes_a_topic():
    r = analyze(sess(["<img src=x onerror=alert(1)> confused about <b>sorting</b>."]), [], NOW, EMB)
    assert [t["name"] for t in r["topics"]] == ["Sorting"]


def _stances(note):
    from app.domain import normalize_session
    from app.logs.extract import extract
    r = extract(normalize_session({"id": "x", "subject": "Study", "duration": 25, "notes": note,
                                   "date": "2026-11-20T10:00:00Z", "type": "manual"}))
    return [(o.topic, o.stance) for o in r.observations] if r else []


def test_negated_need_is_not_a_revise_request():
    assert ("integration", "revise") not in _stances("No need to revise integration, it's clear now.")
    assert ("recursion", "revise") in _stances("Need to revise recursion.")


def test_adverbs_and_idioms_do_not_become_topics():
    topics = {t for t, _ in _stances("Not confused anymore about recursion.")
              + _stances("No longer confused by pointers.") + _stances("I can't wrap my head around backpropagation")}
    assert not topics & {"anymore", "longer", "head"}


def test_topic_ids_do_not_collide():
    from app.logs.topics import slug
    ids = [slug(x) for x in ["c++", "c#", "c", "gradient descent", "गणित", "भौतिकी", "x" * 80, "x" * 81]]
    assert len(set(ids)) == len(ids)
    assert slug("gradient descent") == "gradient-descent"        # ordinary topics stay readable
    assert slug("c++") == "c-plus-plus"

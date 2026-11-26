from datetime import datetime, timezone

from app.domain import normalize_sessions
from app.logs.analyzer import analyze
from app.logs.embedder import TfidfEmbedder
from app.recommend import engine as R
from app.rhythm import engine as rhythm_engine
from app.serialize import clean
from eval.synthetic import generate

NOW = datetime(2026, 11, 26, 4, 0, tzinfo=timezone.utc)      # 09:30 in Asia/Kolkata


def learning_for(notes, subject="ML"):
    docs = [{"id": f"n{i}", "subject": subject, "duration": 30, "type": "manual",
             "date": f"2026-11-{15 + i:02d}T10:00:00Z", "notes": n} for i, n in enumerate(notes)]
    s = normalize_sessions(docs, "UTC")
    return clean(analyze(s, [], NOW, TfidfEmbedder())), s


def rhythm_planted():
    s = normalize_sessions([{**d, "id": str(i)} for i, d in enumerate(generate(7, days=150))], "Asia/Kolkata")
    return clean(rhythm_engine.run(s, tz="Asia/Kolkata"))


def rhythm_cold():
    return clean(rhythm_engine.run([], tz="Asia/Kolkata"))


def test_both_engines_contribute_when_rhythm_is_reliable():
    learning, s = learning_for(["Still confused about backpropagation."])
    out = R.run(learning, rhythm_planted(), [], s, NOW)
    rec = out["recommendations"][0]
    assert rec["topic"] == "Backpropagation" and set(rec["contributors"]) == {"study_log", "rhythm"}
    assert rec["action"]["period"] == "morning" and rec["timing_basis"] in ("observed", "predicted")
    assert {w["source"] for w in rec["why"]} >= {"study_log", "rhythm"}
    assert rec["action"]["minutes"] <= 40            # capped where long sessions are abandoned in the planted data


def test_no_timing_claims_without_rhythm_evidence():
    learning, s = learning_for(["Still confused about backpropagation."])
    rec = R.run(learning, rhythm_cold(), [], s, NOW)["recommendations"][0]
    assert rec["action"]["period"] is None and rec["timing_basis"] is None
    assert rec["contributors"] == ["study_log"]
    assert not any(w["source"] == "rhythm" for w in rec["why"])
    assert any("No reliable time-of-day" in c for c in rec["caveats"])
    assert any(w["source"] == "default" for w in rec["why"])       # length default is disclosed as a default


def test_every_why_item_names_its_source_and_no_causal_language():
    learning, s = learning_for(["Still confused about backpropagation."])
    rec = R.run(learning, rhythm_planted(), [], s, NOW)["recommendations"][0]
    assert all(w["source"] in ("study_log", "rhythm", "default") and w["text"] for w in rec["why"])
    blob = (rec["summary"] + " ".join(w["text"] for w in rec["why"])).lower()
    for banned in ("because you", "causes", "caused", "makes you", "guarantee", "will improve"):
        assert banned not in blob


def test_nothing_is_proposed_when_nothing_needs_revision():
    learning, s = learning_for(["Confident about vectors."])
    assert R.run(learning, rhythm_planted(), [], s, NOW)["recommendations"] == []


def test_responses_survive_reanalysis_and_dismissals_cool_down():
    learning, s = learning_for(["Still confused about backpropagation."])
    first = R.run(learning, rhythm_planted(), [], s, NOW)["recommendations"][0]
    dismissed = {**first, "status": "dismissed", "statusUpdatedAt": "2026-11-25T00:00:00+00:00"}
    again = R.run(learning, rhythm_planted(), [dismissed], s, NOW)["recommendations"][0]
    assert again["status"] == "dismissed"                          # inside the 7-day cool-down
    later = datetime(2026, 12, 10, tzinfo=timezone.utc)
    assert R.run(learning, rhythm_planted(), [dismissed], s, later)["recommendations"][0]["status"] == "proposed"
    accepted = {**first, "status": "accepted", "statusUpdatedAt": "2026-11-25T00:00:00+00:00"}
    assert R.run(learning, rhythm_planted(), [accepted], s, NOW)["recommendations"][0]["status"] == "accepted"


def test_adherence_follows_actual_study_of_the_topic():
    learning, s = learning_for(["Still confused about backpropagation."])
    rec = R.run(learning, rhythm_planted(), [], s, NOW)["recommendations"][0]
    accepted = {**rec, "status": "accepted", "statusUpdatedAt": "2026-11-16T00:00:00+00:00"}   # accepted after the reflection
    out = R.run(learning, rhythm_planted(), [accepted], s, NOW)["recommendations"][0]
    assert out["adherence"] in ("pending", "missed")                # nothing studied since acceptance
    s2 = normalize_sessions([{"id": "z", "subject": "ML — Backpropagation", "duration": 25, "type": "manual",
                              "date": "2026-11-20T10:00:00Z", "notes": ""}], "UTC")
    assert R.run(learning, rhythm_planted(), [accepted], s + s2, NOW)["recommendations"][0]["adherence"] == "followed"


def test_active_proposals_are_capped():
    notes = [f"Confused about topic{chr(97 + i)}x." for i in range(9)]
    learning, s = learning_for(notes)
    out = R.run(learning, rhythm_cold(), [], s, NOW)
    assert len([r for r in out["recommendations"] if r["status"] == "proposed"]) == R.MAX_ACTIVE
    assert out["deferred"] == 9 - R.MAX_ACTIVE


def test_evaluation_counters_do_not_overclaim():
    ev = R.evaluate([{"status": "accepted"}, {"status": "dismissed"}])
    assert ev["acceptance_rate"] is None and "do not show" in ev["note"]

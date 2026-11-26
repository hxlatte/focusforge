import numpy as np
import pandas as pd
import pytest

from app.domain import normalize_sessions
from app.rhythm import engine, thresholds as T
from app.rhythm.frame import attempts_frame, build_features, sessions_frame
from app.rhythm.model import _forward_splits
from eval.synthetic import generate


def sess(docs):
    return normalize_sessions([{**d, "id": f"d{i}"} for i, d in enumerate(docs)], "Asia/Kolkata")


def test_cold_start_shows_nothing_personal():
    r = engine.run(sess(generate(1, days=1, per_day=2)[:3]))
    assert r["status"]["stage"] == "collecting"
    assert r["insights"] == [] and r["observed"] == {}
    assert r["status"]["next_unlocks"]


def test_legacy_only_data_makes_no_completion_claims():
    # legacy rows: no status/labels, only successes were ever stored
    docs = [{"subject": "Maths", "duration": 25, "type": "pomodoro", "notes": "",
             "date": f"2026-11-{10 + i % 10:02d}T0{4 + i % 4}:30:00Z"} for i in range(30)]
    r = engine.run(sess(docs), tz="Asia/Kolkata")
    assert r["data"]["labelled_attempts"] == 0
    assert "period_success" not in r["observed"] and "subject_completion" not in r["observed"]
    assert r["model"]["card"]["state"] == "insufficient_data"
    assert not any(i["id"].startswith(("best_period", "long_", "subject_", "model_")) for i in r["insights"])
    assert r["status"]["stage"] == "descriptive"


def test_planted_pattern_is_recovered_and_model_is_earned():
    r = engine.run(sess(generate(7, days=150, planted=True)), tz="Asia/Kolkata")
    ids = {i["id"]: i for i in r["insights"]}
    assert r["model"]["card"]["state"] == "active", r["model"]["card"].get("reason")
    assert r["model"]["card"]["metrics"]["auc"] > 0.6
    assert r["model"]["card"]["logloss_gain_vs_baseline"] > 0
    assert ids["best_period_completion"]["evidence"]["period"] == "morning"
    assert ids["long_sessions_abandoned"]["evidence"]["bin"] in (">45 min", "31–45 min")
    assert r["model"]["what_if"]


def test_what_if_never_extrapolates_to_unsupported_cells():
    r = engine.run(sess(generate(7, days=150)), tz="Asia/Kolkata")
    for c in r["model"]["what_if"]:
        assert (c["probability"] is None) == (not c["supported"])


def test_null_data_rarely_produces_claims():
    """No pattern planted -> reliable-difference insights and an active model should be rare."""
    claims = active = 0
    seeds = range(30)
    for s in seeds:
        r = engine.run(sess(generate(100 + s, days=100, planted=False)), tz="Asia/Kolkata")
        claims += any(i["id"] in ("best_period_completion", "long_sessions_abandoned") or i["id"].startswith("subject_")
                      for i in r["insights"])
        active += r["model"]["card"].get("state") == "active"
    assert active / len(seeds) <= 0.15, f"model falsely active in {active}/{len(seeds)}"
    assert claims / len(seeds) <= 0.35, f"false pattern claims in {claims}/{len(seeds)}"


def test_features_do_not_leak_future_or_own_label():
    docs = generate(3, days=60)
    df = sessions_frame(sess(docs))
    att = attempts_frame(df)
    X = build_features(att, df, {})
    i = len(att) // 2
    # flip this attempt's own label and every later label: its own features must not change
    att2 = att.copy()
    att2.loc[i:, "completed"] = ~att2.loc[i:, "completed"]
    df2 = df.copy()
    X2 = build_features(att2, df2, {})
    pd.testing.assert_series_equal(X.iloc[i], X2.iloc[i], check_names=False)
    # ...and earlier rows are unaffected too
    pd.testing.assert_frame_equal(X.iloc[: i + 1], X2.iloc[: i + 1])
    # but a LATER row does depend on earlier labels (history features are live)
    assert not X.iloc[-1].equals(X2.iloc[-1])


def test_forward_splits_only_train_on_the_past():
    for tr, te in _forward_splits(100, 5):
        assert tr.max() < te.min() and len(te) > 0


def test_thresholds_gate_the_model():
    docs = generate(5, days=12, planted=True)            # small history
    r = engine.run(sess(docs), tz="Asia/Kolkata")
    assert r["model"]["card"]["state"] == "insufficient_data"
    assert "Needs at least" in r["model"]["card"]["reason"]

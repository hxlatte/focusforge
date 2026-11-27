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


def _reference_features(att, everything, task_rates):
    """Literal O(n^2) definition used only to check the vectorised implementation."""
    from datetime import timedelta
    import numpy as np
    import pandas as pd
    from app.rhythm.thresholds import SHRINKAGE_STRENGTH as S
    comp = att["completed"].to_numpy(); out = []
    for i in range(len(att)):
        r = att.iloc[i]; st = r["start_utc"]
        overall = (comp[:i].sum() + S * 0.5) / (i + S) if i else 0.5
        same = [j for j in range(i) if att.at[j, "subject"] == r["subject"]]
        sub = (comp[same].sum() + S * overall) / (len(same) + S) if same else overall
        load, last = 0.0, None
        for e, m in zip(everything["end_utc"], everything["actual_min"]):
            if e <= st:
                if st - e <= timedelta(hours=24):
                    load += m
                if last is None or e > last:
                    last = e
        since = min((st - last).total_seconds() / 3600, 48.0) if last else 48.0
        today = sum(1 for j in range(i) if att.at[j, "local_date"] == r["local_date"])
        out.append([overall, sub, load, since, today])
    return pd.DataFrame(out, columns=["prior_rate", "subject_prior_rate", "load_24h", "hours_since_last",
                                      "attempts_today"])


def test_vectorised_features_match_literal_definition():
    import numpy as np
    from datetime import datetime, timedelta, timezone
    from app.domain import normalize_sessions
    from app.rhythm.frame import attempts_frame, build_features, sessions_frame
    rng = np.random.default_rng(3)
    t0 = datetime(2026, 1, 1, 8, tzinfo=timezone.utc); rows = []
    for i in range(120):
        t = t0 + timedelta(hours=float(rng.integers(3, 30)) * (i + 1) / 3)
        ok = rng.random() < 0.65
        rows.append({"id": f"s{i}", "subject": ["A — x", "B", "A — y"][i % 3], "type": "pomodoro", "duration": 25,
                     "status": "completed" if ok else "abandoned", "plannedDuration": 25,
                     "actualDuration": 25 if ok else 7, "startedAt": t.isoformat(),
                     "endedAt": (t + timedelta(minutes=25 if ok else 7)).isoformat(),
                     "date": (t + timedelta(minutes=25 if ok else 7)).isoformat(), "tz": "UTC", "notes": ""})
    df = sessions_frame(normalize_sessions(rows, "UTC")); att = attempts_frame(df)
    got = build_features(att, df, {}); ref = _reference_features(att, df, {})
    for c in ref.columns:
        assert np.allclose(got[c].to_numpy(float), ref[c].to_numpy(float), atol=1e-9), c

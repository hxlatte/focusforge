"""Session-completion model, trained per user, evaluated on later sessions only.

Honest-by-construction rules:
  * Only labelled timer attempts (see frame.attempts_frame) are used.
  * Features exist at session start (see frame.build_features): no leakage.
  * Evaluation is forward-chaining: train on the past, test on the next block.
  * The model must beat the base-rate baseline on held-out data to be shown at all.
  * Simple model first (regularised logistic regression). Gradient boosting is only
    tried once there is enough data to justify it.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from . import thresholds as T
from .frame import FEATURE_GROUPS, NUMERIC

CLIP = 1e-3


def _pipe(kind: str, subject_cols: list[str], numeric: list[str]) -> Pipeline:
    pre = ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median", add_indicator=True)),
                          ("sc", StandardScaler())]), numeric),
        *([("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=3, sparse_output=False), subject_cols)]
          if subject_cols else []),
    ], sparse_threshold=0)
    if kind == "gbm":
        clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150,
                                             min_samples_leaf=10, random_state=0)
    else:
        clf = LogisticRegression(C=0.5, max_iter=2000)
    return Pipeline([("pre", pre), ("clf", clf)])


def _cols(drop_group: str | None):
    groups = {g: c for g, c in FEATURE_GROUPS.items() if g != drop_group}
    numeric = [c for g, cols in groups.items() for c in cols if c != "subject"]
    subject = ["subject"] if "subject" in groups else []
    return numeric, subject


def _forward_splits(n: int, k: int):
    """Chunk the time-ordered rows; fold j trains on chunks[:j+1] and tests on chunk j+1."""
    edges = np.linspace(0, n, k + 2).astype(int)
    for j in range(k):
        yield np.arange(0, edges[j + 1]), np.arange(edges[j + 1], edges[j + 2])


def _clip(p):
    return np.clip(p, CLIP, 1 - CLIP)


def cross_validate(X: pd.DataFrame, y: np.ndarray, kind: str, drop_group: str | None = None) -> dict:
    n = len(y)
    k = max(1, min(5, n // 8))
    numeric, subject = _cols(drop_group)
    preds, base, ys = [], [], []
    folds = 0
    for tr, te in _forward_splits(n, k):
        if len(np.unique(y[tr])) < 2 or len(te) == 0:
            continue
        m = _pipe(kind, subject, numeric)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m.fit(X.iloc[tr], y[tr])
        preds.append(m.predict_proba(X.iloc[te])[:, 1])
        base.append(np.full(len(te), (y[tr].sum() + 1) / (len(tr) + 2)))   # Laplace-smoothed base rate
        ys.append(y[te])
        folds += 1
    if not folds:
        return {"folds": 0}
    p, b, t = _clip(np.concatenate(preds)), _clip(np.concatenate(base)), np.concatenate(ys)
    out = {"folds": folds, "test_n": int(len(t)),
           "logloss": float(log_loss(t, p, labels=[0, 1])), "baseline_logloss": float(log_loss(t, b, labels=[0, 1])),
           "brier": float(brier_score_loss(t, p)), "baseline_brier": float(brier_score_loss(t, b))}
    out["auc"] = float(roc_auc_score(t, p)) if len(np.unique(t)) == 2 else None
    return out


def evaluate(X: pd.DataFrame, y: np.ndarray) -> dict:
    """Run the gate. Returns a model card (always) and a fitted model (only if it earns display)."""
    n = len(y)
    pos, neg = int(y.sum()), int(n - y.sum())
    card = {"n_labelled": n, "completed": pos, "abandoned": neg,
            "requirements": {"labelled_attempts": T.MODEL_MIN_LABELLED, "minority_class": T.MODEL_MIN_MINORITY}}
    if n < T.MODEL_MIN_LABELLED or min(pos, neg) < T.MODEL_MIN_MINORITY:
        card["state"] = "insufficient_data"
        card["reason"] = (f"Needs at least {T.MODEL_MIN_LABELLED} labelled focus attempts with at least "
                          f"{T.MODEL_MIN_MINORITY} completed and {T.MODEL_MIN_MINORITY} abandoned; "
                          f"you have {n} ({pos} completed, {neg} abandoned).")
        return {"card": card, "model": None}

    kinds = ["logistic"] + (["gbm"] if n >= T.GBM_MIN_LABELLED else [])
    results = {k: cross_validate(X, y, k) for k in kinds}
    results = {k: r for k, r in results.items() if r.get("folds", 0) >= 1}
    if not results:
        card["state"] = "insufficient_data"
        card["reason"] = "Not enough variation across time-ordered blocks to evaluate a model."
        return {"card": card, "model": None}
    best_kind = min(results, key=lambda k: results[k]["logloss"])
    cv = results[best_kind]
    gain = cv["baseline_logloss"] - cv["logloss"]
    card.update(model=best_kind, candidates={k: {m: (round(v, 4) if isinstance(v, float) else v)
                                                 for m, v in r.items()} for k, r in results.items()},
                evaluation="forward-chaining (train on the past, test on the next block)",
                metrics={m: (round(v, 4) if isinstance(v, float) else v) for m, v in cv.items()},
                logloss_gain_vs_baseline=round(gain, 4))
    ok = (cv["folds"] >= T.MODEL_MIN_FOLDS and gain >= T.MODEL_MIN_LOGLOSS_GAIN
          and cv["auc"] is not None and cv["auc"] >= T.MODEL_MIN_AUC)
    if not ok:
        card["state"] = "not_better_than_baseline"
        card["reason"] = ("On held-out later sessions the model did not beat simply using your overall completion "
                          "rate, so no personalised prediction is shown. This is a result, not an error: it "
                          "usually means the pattern is not strong or there is not yet enough history.")
        return {"card": card, "model": None}

    numeric, subject = _cols(None)
    final = _pipe(best_kind, subject, numeric)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        final.fit(X, y)
    # Drop-one-group importance: how much worse does held-out log-loss get without a feature group?
    importance = []
    for g in FEATURE_GROUPS:
        r = cross_validate(X, y, best_kind, drop_group=g)
        if r.get("folds"):
            importance.append({"group": g, "logloss_increase_without": round(r["logloss"] - cv["logloss"], 4)})
    importance.sort(key=lambda d: -d["logloss_increase_without"])
    card["state"] = "active"
    card["feature_group_importance"] = importance
    card["limitations"] = ("Trained on your own history only. Estimates describe association with your past "
                           "behaviour, not cause, and can be wrong when your routine changes.")
    return {"card": card, "model": final}


def what_if(model, X_hist: pd.DataFrame, att: pd.DataFrame) -> list[dict]:
    """Model estimates for (period x planned length) cells that the user's data actually covers."""
    if model is None or att.empty:
        return []
    subjects = att["subject"].value_counts()
    subject = subjects.index[0]
    lo, hi = att["planned_min"].min(), att["planned_min"].max()
    lengths = sorted({int(x) for x in att["planned_min"].round()} | {15, 25, 40, 50})
    lengths = [x for x in lengths if lo - 1e-9 <= x <= hi + 1e-9][:6]
    base = X_hist.iloc[-1].copy()
    rep = {"morning": 9, "afternoon": 14, "evening": 19, "night": 23}
    out = []
    for period, hour in rep.items():
        support = int((att["period"] == period).sum())
        for L in lengths:
            row = base.copy()
            row["hour_sin"], row["hour_cos"] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
            row["planned_min"], row["subject"] = float(L), subject
            sup_len = int(((att["planned_min"] - L).abs() <= 5).sum())
            supported = support >= T.MIN_GROUP_N and sup_len >= T.MIN_GROUP_N
            p = float(model.predict_proba(pd.DataFrame([row]))[:, 1][0]) if supported else None
            out.append({"period": period, "planned_min": L, "subject": subject,
                        "probability": None if p is None else round(p, 3),
                        "supported": supported, "support_period_n": support, "support_length_n": sup_len})
    return out

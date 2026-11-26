"""Evaluate the Cognitive Rhythm Engine on SYNTHETIC users with known ground truth.

    python -m eval.run_rhythm_eval            # writes eval/results/rhythm_synthetic.json

This measures the engine, not real users: with planted patterns can it recover them, and
with no pattern does it stay quiet? It says nothing about how well it will do on a real
person's history. Real-user evaluation needs real labelled sessions (see docs).
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from app.domain import normalize_sessions  # noqa: E402
from app.rhythm import engine  # noqa: E402
from eval.synthetic import generate  # noqa: E402

SEEDS = 20
SIZES = [20, 40, 70, 100, 150]          # days of history (~2.2 attempts/day)


def run(seed: int, days: int, planted: bool) -> dict:
    docs = generate(seed, days=days, planted=planted)
    s = normalize_sessions([{**d, "id": str(i)} for i, d in enumerate(docs)], "Asia/Kolkata")
    r = engine.run(s, tz="Asia/Kolkata")
    ids = {i["id"]: i for i in r["insights"]}
    card = r["model"]["card"]
    return {
        "n_attempts": r["data"]["labelled_attempts"],
        "model_state": card.get("state"),
        "auc": (card.get("metrics") or {}).get("auc"),
        "gain": card.get("logloss_gain_vs_baseline"),
        "found_morning": ids.get("best_period_completion", {}).get("evidence", {}).get("period") == "morning",
        "found_long_abandon": "long_sessions_abandoned" in ids,
        "false_period_or_length_claim": any(k in ids for k in ("best_period_completion", "long_sessions_abandoned")),
        "false_subject_claim": any(k.startswith("subject_") for k in ids),
    }


def main() -> None:
    out = {"seeds_per_cell": SEEDS, "note": "SYNTHETIC users, planted ground truth", "cells": []}
    for planted in (True, False):
        for days in SIZES:
            rows = [run(1000 * (planted + 1) + s, days, planted) for s in range(SEEDS)]
            active = [r for r in rows if r["model_state"] == "active"]
            cell = {
                "planted": planted, "days": days,
                "median_attempts": float(np.median([r["n_attempts"] for r in rows])),
                "model_active_rate": round(len(active) / SEEDS, 2),
                "mean_auc_when_active": round(float(np.mean([r["auc"] for r in active])), 3) if active else None,
                "mean_logloss_gain_when_active": round(float(np.mean([r["gain"] for r in active])), 4) if active else None,
            }
            if planted:
                cell["recovered_morning_effect_rate"] = round(sum(r["found_morning"] for r in rows) / SEEDS, 2)
                cell["recovered_long_session_effect_rate"] = round(sum(r["found_long_abandon"] for r in rows) / SEEDS, 2)
            else:
                cell["false_period_or_length_claim_rate"] = round(sum(r["false_period_or_length_claim"] for r in rows) / SEEDS, 2)
                cell["false_subject_claim_rate"] = round(sum(r["false_subject_claim"] for r in rows) / SEEDS, 2)
            out["cells"].append(cell)
            print(json.dumps(cell))
    path = Path(__file__).parent / "results"
    path.mkdir(exist_ok=True)
    (path / "rhythm_synthetic.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

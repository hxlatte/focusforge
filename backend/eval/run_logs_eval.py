"""Evaluate the Study-Log Analyzer against hand-labelled reflections.

    python -m eval.run_logs_eval --split dev
    python -m eval.run_logs_eval --split test
    python -m eval.run_logs_eval --split test --embedder semantic   # needs sentence-transformers

Reports (topic, stance) precision/recall/F1 and clustering pair-F1. Labels were written by the
same author as the analyzer, so this is a regression baseline, not independent accuracy.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from app.domain import normalize_sessions  # noqa: E402
from app.logs import analyzer as A  # noqa: E402
from app.logs import topics as T  # noqa: E402
from app.logs.embedder import TfidfEmbedder, get_embedder  # noqa: E402
from app.logs.extract import extract  # noqa: E402

GOLD = json.loads((Path(__file__).parent / "labelled_logs.json").read_text())


def norm(topic: str) -> str:
    return T.merge_key(" ".join(T.lemma(t) for t in topic.lower().replace("'s", "").split()))


def sessions_from(notes: list[str]):
    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    docs = [{"id": f"s{i}", "subject": "Focus Session", "duration": 25, "type": "manual", "notes": n,
             "date": (base + timedelta(days=i)).isoformat()} for i, n in enumerate(notes)]
    return normalize_sessions(docs, "UTC")


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "tp": tp, "fp": fp, "fn": fn}


def eval_extraction(split: str, verbose: bool = False) -> dict:
    items = GOLD[split]
    sessions = sessions_from([i["note"] for i in items])
    tot = {"pair": [0, 0, 0], "judgement": [0, 0, 0], "topic": [0, 0, 0]}
    misses = []
    for s, item in zip(sessions, items):
        refl = extract(s)
        pred = {(norm(o.topic), o.stance) for o in (refl.observations if refl else [])}
        gold = {(norm(t), st) for t, st in item["gold"]}
        views = {
            "pair": (pred, gold),
            "judgement": ({p for p in pred if p[1] != "mention"}, {g for g in gold if g[1] != "mention"}),
            "topic": ({p[0] for p in pred}, {g[0] for g in gold}),
        }
        for k, (p, g) in views.items():
            tot[k][0] += len(p & g); tot[k][1] += len(p - g); tot[k][2] += len(g - p)
        if pred != gold:
            misses.append({"note": item["note"], "missed": sorted(gold - pred), "extra": sorted(pred - gold)})
    out = {k: prf(*v) for k, v in tot.items()}
    # stance accuracy where the topic was found
    ok = n = 0
    for s, item in zip(sessions, items):
        refl = extract(s)
        pm = {}
        for o in (refl.observations if refl else []):
            pm.setdefault(norm(o.topic), set()).add(o.stance)
        for t, st in item["gold"]:
            if norm(t) in pm:
                n += 1; ok += st in pm[norm(t)]
    out["stance_accuracy_given_topic_found"] = round(ok / n, 3) if n else None
    out["n_notes"] = len(items)
    if verbose:
        out["misses"] = misses
    return out


def eval_clusters(emb) -> dict:
    groups = GOLD["clusters"]["groups"]
    stmts = [(g, s) for g, ss in groups.items() for s in ss]
    sessions = sessions_from([s for _, s in stmts])
    # one difficulty observation per statement -> map back by session id
    from app.logs.extract import extract as ex
    obs, owner = [], {}
    for s, (g, _) in zip(sessions, stmts):
        r = ex(s)
        for o in (r.observations if r else []):
            if o.stance in A.NEGATIVE:
                obs.append(o); owner[o.session_id] = g
                break
    clusters = A.cluster_difficulties(obs, emb)
    pred_pairs, sid_cluster = set(), {}
    for c in clusters:
        ids = sorted({m["session_id"] for m in c["members"]})
        for a, b in itertools.combinations(ids, 2):
            pred_pairs.add((a, b))
    ids = sorted(owner)
    gold_pairs = {(a, b) for a, b in itertools.combinations(ids, 2) if owner[a] == owner[b]}
    tp = len(pred_pairs & gold_pairs)
    return {"embedder": emb.name, "statements": len(ids), "clusters_found": len(clusters),
            **prf(tp, len(pred_pairs - gold_pairs), len(gold_pairs - pred_pairs))}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--embedder", choices=["tfidf", "semantic"], default="tfidf")
    ap.add_argument("--misses", action="store_true")
    a = ap.parse_args()
    emb = TfidfEmbedder() if a.embedder == "tfidf" else get_embedder()
    res = {"split": a.split, "extraction": eval_extraction(a.split, a.misses), "clustering": eval_clusters(emb)}
    print(json.dumps(res, indent=2, ensure_ascii=False))

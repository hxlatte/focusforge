"""Embedder selection/fallback paths. The real all-MiniLM-L6-v2 weights are NOT downloaded
here: a stand-in `sentence_transformers` module checks OUR integration code (loading,
normalisation, shape, fallback). Semantic quality is verified by eval/run_logs_eval.py
--embedder semantic on a machine that can download the model."""
import sys
import types

import numpy as np
import pytest

from app.logs import embedder as E
from app.logs.analyzer import analyze, cluster_difficulties
from app.logs.embedder import SentenceTransformerEmbedder, TfidfEmbedder, get_embedder


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(E, "_cached", None)
    monkeypatch.delenv("FOCUSFORGE_EMBEDDER", raising=False)
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)


def fake_module(monkeypatch, ctor=None, encode=None):
    class ST:
        def __init__(self, name):
            if ctor:
                raise ctor
            self.name = name

        def encode(self, texts, **kw):
            if encode:
                raise encode
            rng = np.random.default_rng(len(texts))
            return rng.normal(size=(len(texts), 8)) * 3   # un-normalised on purpose
    mod = types.ModuleType("sentence_transformers")
    mod.SentenceTransformer = ST
    monkeypatch.setitem(sys.modules, "sentence_transformers", mod)


def test_semantic_path_loads_and_normalises(monkeypatch):
    fake_module(monkeypatch)
    e = get_embedder()
    assert isinstance(e, SentenceTransformerEmbedder) and e.semantic
    X = e.encode(["a", "b", "c"])
    assert X.shape == (3, 8)
    assert np.allclose(np.linalg.norm(X, axis=1), 1.0)
    assert e.encode([]).shape[0] == 0


def test_missing_package_falls_back(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)   # import -> ImportError
    e = get_embedder()
    assert isinstance(e, TfidfEmbedder) and not e.semantic


def test_download_failure_falls_back(monkeypatch):
    fake_module(monkeypatch, ctor=OSError("offline: cannot reach huggingface.co"))
    assert isinstance(get_embedder(), TfidfEmbedder)


def test_env_forces_fallback(monkeypatch):
    fake_module(monkeypatch)
    monkeypatch.setenv("FOCUSFORGE_EMBEDDER", "tfidf")
    assert isinstance(get_embedder(), TfidfEmbedder)


def _obs():
    from app.logs.extract import Observation
    base = dict(stance="struggling", session_id="s", when="2026-11-01", sentence="x",
                parent_subject="CS", cue="confusing")
    topics = ["tree recursion", "recursive functions", "recursion base case", "binary trees"]
    out = []
    for i, t in enumerate(topics):
        d = dict(base)
        d.update(topic=t, clause=f"{t} is confusing", session_id=f"s{i}")
        try:
            out.append(Observation(**d))
        except TypeError:
            pytest.skip("Observation signature changed")
    return out


def test_runtime_encode_failure_falls_back_and_reports_it(monkeypatch):
    fake_module(monkeypatch, encode=RuntimeError("CUDA OOM"))
    emb = get_embedder()
    assert emb.semantic
    used = []
    clusters = cluster_difficulties(_obs(), emb, used)
    assert used and not used[0].semantic
    assert isinstance(clusters, list)

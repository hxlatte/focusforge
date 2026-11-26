"""Text embedders behind one interface.

Preferred: a Sentence-Transformers model (semantic; run locally on CPU).
Fallback:  character n-gram TF-IDF (lexical only; "recursion" ~ "recursive" works,
           "recursion" ~ "self-calling functions" does not).

The analyzer reports which one it used, so a lexical fallback is never passed off as
semantic understanding. Set FOCUSFORGE_EMBEDDER=tfidf to force the fallback.
"""
from __future__ import annotations

import logging
import os
from typing import Protocol

import numpy as np

log = logging.getLogger("focusforge.embedder")
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class Embedder(Protocol):
    name: str
    semantic: bool

    def encode(self, texts: list[str]) -> np.ndarray: ...


def _unit(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1
    return m / n


class TfidfEmbedder:
    """Fit on whatever texts it is asked to encode (corpora here are small)."""
    name = "tfidf-char-ngrams (lexical fallback)"
    semantic = False

    def encode(self, texts: list[str]) -> np.ndarray:
        from sklearn.feature_extraction.text import TfidfVectorizer

        if not texts:
            return np.zeros((0, 1))
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1)
        return _unit(vec.fit_transform(texts).toarray())


class SentenceTransformerEmbedder:
    semantic = True

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        from sentence_transformers import SentenceTransformer

        self.name = model_name
        self._model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1))
        return _unit(np.asarray(self._model.encode(texts, show_progress_bar=False, convert_to_numpy=True)))


_cached: Embedder | None = None


def get_embedder(force_fallback: bool = False) -> Embedder:
    global _cached
    if force_fallback or os.environ.get("FOCUSFORGE_EMBEDDER", "").lower() == "tfidf":
        return TfidfEmbedder()
    if _cached is None:
        try:
            _cached = SentenceTransformerEmbedder()
        except Exception as exc:  # package missing, or model cannot be downloaded
            log.warning("Sentence-Transformers unavailable (%s); using TF-IDF fallback", exc)
            _cached = TfidfEmbedder()
    return _cached

"""Sentence and clause splitting for study reflections."""
from __future__ import annotations

import re
from dataclasses import dataclass

_SENT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_CLAUSE_RE = re.compile(
    r"\s*(?:;|:\s|,?\s+\b(but|however|although|though|while|whereas|yet|except)\b|"
    r"[,]\s+(?=(?:and\s+)?(?:i|i'm|i’m|i've|but|need|needs|should|will|must|want|still|now)\b))\s*",
    re.I,
)


@dataclass
class Clause:
    sentence_idx: int
    sentence: str      # the full original sentence (shown as evidence)
    text: str          # this clause only
    lead: str          # connector that introduced it ('but', 'however', '' ...)


def split_clauses(note: str) -> list[Clause]:
    out: list[Clause] = []
    sentences = [s.strip() for s in _SENT_RE.split(note or "") if s and s.strip()]
    for si, sent in enumerate(sentences):
        parts = _CLAUSE_RE.split(sent)
        # re.split with one capture group yields [text, connector, text, connector, ...]
        text0, rest = parts[0], parts[1:]
        chunks = [("", text0)]
        for i in range(0, len(rest) - 1, 2):
            chunks.append(((rest[i] or "").lower(), rest[i + 1]))
        for lead, t in chunks:
            t = (t or "").strip(" ,.;:!?-")
            if t:
                out.append(Clause(si, sent, t, lead))
    return out

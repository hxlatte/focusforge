"""Topic phrases from a clause, and canonical topic identity across reflections."""
from __future__ import annotations

import re
from collections import Counter

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

from . import stance as S

_FILLER = set("""
today yesterday tonight tomorrow morning evening afternoon session sessions chapter chapters lecture lectures class
classes topic topics concept concepts thing things stuff part parts bit lot lots time times hour hours minute minutes
day days week weeks well really still also just quite very pretty much more again now then later basic basics
basically general generally overall main whole entire little new next some any many other another
same different bunch finally memorize memorise memorizing memorising work works feeling feelings feels tutorial tutorials flashcard flashcards mostly idea ideas way ways notes note exercise exercises example examples video videos book books page
pages assignment homework revision review lesson course material materials subject subjects section sections
feel felt think thought know knew see saw get got make made making going went looked tried try trying working worked
start started finish finished complete completed do does did done like want wanted need needed needs plan planning
able understanding understand understood better best good great bad fine okay ok sure maybe probably actually
already always never ever often sometimes usually mostly fully completely totally mostly slightly somewhat
enough completely mainly especially particularly exactly specifically properly clearly deeply
""".split())
_STOP = (set(ENGLISH_STOP_WORDS) - {"first", "second", "third"}) | {"i'm", "i’m", "i've", "i’ve", "it's", "it’s", "don't", "didn't", "can't", "isn't", "wasn't",
                                    "im", "ive", "dont", "cant", "also", "etc", "eg", "ie", "vs"}
_PRONOUN = {"it", "this", "that", "these", "those", "them", "they", "one", "ones"}
_KEEP_S = ("ss", "us", "is", "as", "ics", "ous", "ness")
_NO_STRIP = {"series", "species", "lens", "bias", "atlas", "chaos", "canvas", "alias", "status", "analysis", "basis", "axis"}
_TOKEN = re.compile(r"[a-z][a-z0-9+#\-']*")


_IRREGULAR = {"matrices": "matrix", "indices": "index", "vertices": "vertex", "analyses": "analysis",
              "hypotheses": "hypothesis", "theses": "thesis", "criteria": "criterion", "phenomena": "phenomenon",
              "bases": "basis", "axes": "axis", "appendices": "appendix", "equations": "equation"}


def lemma(tok: str) -> str:
    tok = tok.strip("'-")
    if tok in _IRREGULAR:
        return _IRREGULAR[tok]
    if tok in _NO_STRIP or len(tok) <= 3:
        return tok
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith("sses"):
        return tok[:-2]
    if tok.endswith("s") and not tok.endswith(_KEEP_S):
        return tok[:-1]
    return tok


def _cue_spans(clause: str) -> list[tuple[int, int]]:
    spans = []
    low = re.sub(r"(?<=\w)[’']s\b", "", clause.lower())
    for _, rx in S._CUES:  # noqa: SLF001  (reuse the same lexicon so cue words never leak into topics)
        spans += [(m.start(), m.end()) for m in rx.finditer(low)]
    return spans


def phrases(clause: str) -> tuple[list[str], bool]:
    """Topic phrases in a clause (lemmatised, lowercase) and whether it contains a bare pronoun."""
    low = re.sub(r"(?<=\w)[’']s\b", "", clause.lower())
    keep = [True] * len(low)
    for a, b in _cue_spans(clause):
        for i in range(a, b):
            keep[i] = False
    masked = "".join(c if k else " " for c, k in zip(low, keep))
    has_pronoun = False
    runs: list[list[str]] = [[]]
    for m in re.finditer(r"[^\s,;:()\"]+|[,;:()\"]", masked):
        w = m.group(0)
        if w in {",", ";", ":", "(", ")", '"'}:
            runs.append([])
            continue
        tokens = _TOKEN.findall(w)
        if not tokens:
            runs.append([])
            continue
        for t in tokens:
            if t in _PRONOUN:
                has_pronoun = True
                runs.append([])
            elif t in _STOP or t in _FILLER:
                runs.append([])
            else:
                runs[-1].append(lemma(t))
    out = []
    for r in runs:
        if not r:
            continue
        if len(r) > 4:                       # a long run is almost never a topic name
            continue
        out.append(" ".join(r))
    return out, has_pronoun


def merge_key(p: str) -> str:
    return re.sub(r"[\s\-]+", "", p)


def canonicalise(surface_counts: Counter) -> dict[str, str]:
    """Map every surface phrase to a canonical phrase.

    Conservative, explainable merging only: identical after removing spaces/hyphens
    ("back propagation" = "backpropagation"), or a clear abbreviation/prefix
    ("backprop" -> "backpropagation"). Looser "these are related" grouping is done
    separately by embedding clustering and never silently merges topics.
    """
    items = sorted(surface_counts, key=lambda p: (-surface_counts[p], -len(p), p))
    canon: dict[str, str] = {}
    reps: list[str] = []
    for p in items:
        k = merge_key(p)
        target = None
        for r in reps:
            rk = merge_key(r)
            short, long_ = sorted((k, rk), key=len)
            if k == rk or (len(short) >= 5 and long_.startswith(short) and len(short) / len(long_) >= 0.5
                           and len(p.split()) == len(r.split())):
                target = r
                break
        if target is None:
            reps.append(p)
            target = p
        canon[p] = target
    return canon


def display(p: str) -> str:
    return " ".join(w if w.isupper() else w.capitalize() for w in p.split())


def slug(p: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", p.lower()).strip("-")[:60] or "topic"

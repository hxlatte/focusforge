"""Learning-stance detection for one clause.

Stances (a clause can carry several):
  struggling  - confused, stuck, "don't understand", "not clear" ...
  revise      - wants/needs to revisit ("need to revise X")
  confident   - "confident", "got it", "makes sense now" ...
  understood  - "understood X", "I get how ..."
  revised     - revision already done ("reviewed X")
  mention     - studied/covered X, no judgement

This is a cue lexicon with negation handling, NOT generic sentiment analysis: "I'm
excited but still confused about X" is struggling with X, and "this is not hard" is
understood. It is precise on the phrasing it knows and silent on phrasing it does not;
the labelled evaluation in eval/ reports how often that silence costs recall.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_NEG = r"(?:not|n't|n’t|never|no longer|hardly|barely|cannot|cant|without)"
_AUX = r"(?:don'?t|don’t|do not|didn'?t|didn’t|did not|can'?t|can’t|cannot|couldn'?t|could not|won'?t|wouldn'?t|doesn'?t|does not|haven'?t|have not|still not|not)"

# (stance, regex). Order does not matter; spans are collected then resolved.
_CUES: list[tuple[str, re.Pattern]] = [(s, re.compile(p, re.I)) for s, p in [
    ("struggling", rf"\b{_AUX}\s+(?:\w+\s+){{0,2}}?(?:understand|get|grasp|follow|see|remember|figure|wrap|know|got)\b"),
    ("struggling", rf"\b(?:not|n't|never)\s+(?:\w+\s+){{0,2}}?(?:clear|sure|confident|comfortable|getting|understanding|solid)\b"),
    ("struggling", r"\b(?:confus\w*|struggl\w*|stuck|unclear|unsure|tricky|tough|overwhelm\w*|lost|baffl\w*|puzzl\w*)\b"),
    ("struggling", r"\b(?:hard|difficult\w*|challenging)\b(?!\s+(?:work|worker))"),
    ("struggling", r"\b(?:makes? no sense|doesn'?t make sense|does not make sense|mixed up|mix(?:es|ed|ing)? (?:me )?up|hard time|no idea|trouble|forgot\w*|blank)\b"),
    ("revise", r"\b(?:need|needs|needed|have|has|got|want|wants|should|must|will|plan|planning|going|gonna|ought|try|trying)\s+(?:to\s+)?(?:\w+\s+){0,2}?(?:revise|revisit|review|re-?read|re-?study|redo|practi[cs]e|go over|brush up|work on|study)\b(?:\s+\w+){0,3}?(?:\s+(?:again|more))?"),
    ("revise", r"\b(?:to|will|should|must)\s+(?:revise|revisit|review|re-?read|re-?study|brush up)\b"),
    ("revise", r"\b(?:revise|revisit)\b(?!d)"),
    ("revise", r"\b(?:come back to|look (?:at|into) (?:it |this |that )?again|go back to|more practice|study (?:it |this |that )?(?:more|again))\b"),
    ("confident", r"\b(?:confident|comfortable|nailed|mastered|solid|easy|easier|straightforward|no problem|clicked|good grasp|got it|get it now|gets it)\b"),
    ("confident", r"\b(?:makes?|made) sense now\b|\bclear now\b|\bfully (?:understand|get)\b|\bunderstand \w+ (?:well|fully|completely)\b"),
    ("understood", r"\b(?:understood|understand|understands|understanding|grasp(?:ed)?|figured out|made sense|makes sense|make sense|know how|get how|get why|get the|get that|clear)\b"),
    ("revised", r"\b(?:revised|reviewed|revisited|re-?read|redid|went over|went through|brushed up)\b"),
    ("mention", r"\b(?:studied|studying|covered|covering|learned|learnt|read|reading|watched|watching|practi[cs]ed|worked on|worked through|working on|started|finished|completed|did)\b"),
]]

# a cue is flipped to struggling when negated right before it (positive cues only)
_NEG_BEFORE = re.compile(rf"{_NEG}\s+(?:\w+\s+){{0,2}}$", re.I)
# negated difficulty cue -> understood ("not hard", "wasn't confusing")
_NEG_DIFF = re.compile(rf"(?:{_NEG}|wasn'?t|isn'?t|aren'?t|weren'?t)\s+(?:that |too |very |really |so )?$", re.I)
_PERSIST = re.compile(r"\b(?:still|again|keep|keeps|always|repeatedly|yet)\b", re.I)


@dataclass
class Signal:
    stance: str
    cue: str           # matched words, shown as evidence
    persistent: bool = False


_NEG_NEED = re.compile(r"\b(?:no|not|never|n't|nothing)\s+(?:longer\s+)?(?:need\w*\s+)?(?:to\s+)?$")
_RANK = ["struggling", "revise", "confident", "understood", "revised", "mention"]


def detect(clause: str, lead: str = "", prev_stances: set[str] | None = None) -> list[Signal]:
    """Signals for one clause. `prev_stances` = stances of the previous clause (for 'but not X')."""
    text = clause.lower()
    raw: list[tuple[str, int, int, str]] = []
    for stance, rx in _CUES:
        for m in rx.finditer(text):
            raw.append((stance, m.start(), m.end(), m.group(0)))

    out: dict[str, Signal] = {}
    persist = bool(_PERSIST.search(text))
    struggle_spans = [(a, b) for st, a, b, _ in raw if st == "struggling"]

    confident_spans = [(a, b) for st, a, b, _ in raw if st == "confident"]
    for stance, a, b, cue in raw:
        before = text[:a]
        if stance == "struggling":
            if _NEG_DIFF.search(before) and not re.match(rf"\s*{_AUX}", cue):   # "not hard" -> understood
                out.setdefault("understood", Signal("understood", f"{before.split()[-1] if before.split() else ''} {cue}".strip()))
                continue
            out.setdefault("struggling", Signal("struggling", cue, persist))
        elif stance in ("confident", "understood"):
            if any(sa <= a < sb or sa < b <= sb for sa, sb in struggle_spans):
                continue                                    # inside "don't understand" etc.
            if stance == "understood" and any(ca <= a < cb or ca < b <= cb for ca, cb in confident_spans):
                continue                                    # "makes sense now" is confident, not also understood
            if _NEG_BEFORE.search(before):
                out.setdefault("struggling", Signal("struggling", f"not … {cue}", persist))
            else:
                out.setdefault(stance, Signal(stance, cue))
        elif stance == "revised":
            if _NEG_BEFORE.search(before):
                out.setdefault("revise", Signal("revise", f"not yet … {cue}"))
            else:
                out.setdefault("revised", Signal("revised", cue))
        elif stance == "revise":
            if _NEG_NEED.search(before[-24:]):               # "no need to revise X" is not a revise request
                continue
            out.setdefault("revise", Signal("revise", cue))
        elif stance == "mention":
            out.setdefault("mention", Signal("mention", cue))

    # "I understood A but not B": a bare negation leading a clause after a positive clause
    if not (out.keys() - {"mention"}) and lead in ("but", "however", "though", "yet", "although", "except") \
            and re.match(rf"\s*{_NEG}\b", text) and prev_stances and prev_stances & {"understood", "confident"}:
        out["struggling"] = Signal("struggling", "but not")

    # specific stances make a bare 'mention' redundant
    if len(out) > 1:
        out.pop("mention", None)
    # understood/confident alongside struggling in one clause: keep the struggle (conservative)
    if "struggling" in out:
        out.pop("understood", None)
        out.pop("confident", None)
    return [out[s] for s in _RANK if s in out]

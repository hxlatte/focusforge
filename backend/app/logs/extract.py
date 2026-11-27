"""Reflection text -> observations (topic, stance, evidence)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain import Session
from . import stance as S
from . import topics as T
from .text import split_clauses

GENERIC_SUBJECTS = {"general", "focus session", "study", "session", "misc", "other"}


@dataclass
class Observation:
    session_id: str
    when: str                 # ISO of the session
    parent_subject: str
    topic: str                # surface phrase (lemmatised, lowercase)
    stance: str
    cue: str
    sentence: str             # full original sentence, shown as evidence
    clause: str
    inherited: str | None = None     # 'pronoun' | 'context' | 'subject' when the topic was not named in the clause
    persistent: bool = False


@dataclass
class Reflection:
    session_id: str
    when: str
    subject: str
    main_topic: str | None
    observations: list[Observation] = field(default_factory=list)
    unlinked: int = 0         # stance signals with no topic that could be identified


def _expand(clauses):
    """Split "A was easy, B make sense" at the comma when both halves carry their own stance.
    Lists like "A, B and C are confusing" stay together (only one part has a cue)."""
    from .text import Clause
    out = []
    for c in clauses:
        if "," not in c.text:
            out.append(c)
            continue
        groups: list[list[str]] = [[]]
        have: list[bool] = [False]
        for part in [p.strip() for p in c.text.split(",") if p.strip()]:
            has = any(s.stance != "mention" for s in S.detect(part))
            if has and have[-1]:
                groups.append([part]); have.append(True)
            else:
                groups[-1].append(part); have[-1] = have[-1] or has
        for gi, g in enumerate(groups):
            out.append(Clause(c.sentence_idx, c.sentence, ", ".join(g), c.lead if gi == 0 else ""))
    return out


def extract(session: Session) -> Reflection | None:
    if not session.notes:
        return None
    parent = session.parent_subject
    detail = T.lemma(session.detail.lower()) if session.detail else None
    refl = Reflection(session.id, session.logged_at.isoformat(), parent, None)
    prev_stances: set[str] = set()
    prev_topics: list[str] = []
    prev_idx = -99
    # Notes are plain text; if someone pastes markup, drop the tags so they never become 'topics'.
    plain = re.sub(r"<[^>]*>", " ", session.notes)
    for c in _expand(split_clauses(plain)):
        sigs = S.detect(c.text, c.lead, prev_stances)
        ph, has_pron = T.phrases(c.text)
        stances = [s for s in sigs]
        prev_stances = {s.stance for s in sigs}
        if not stances:
            if ph:
                prev_topics, prev_idx = ph, c.sentence_idx
            continue
        inherited = None
        topics = ph
        if not topics:
            # A stance with no topic of its own ("Got it now.", "Pretty solid.") refers to what was
            # just discussed: the previous clause or the previous sentence, never further back.
            if prev_topics and c.sentence_idx - prev_idx <= 1:
                topics, inherited = prev_topics[-1:], ("pronoun" if has_pron else "context")
            elif detail:
                topics, inherited = [detail], "subject"
        if not topics:
            refl.unlinked += sum(1 for s in stances if s.stance != "mention")
            continue
        for sig in stances:
            for t in topics:
                refl.observations.append(Observation(session.id, refl.when, parent, t, sig.stance, sig.cue,
                                                     c.sentence, c.text, inherited, sig.persistent))
        if ph:
            prev_topics, prev_idx = ph, c.sentence_idx
        if refl.main_topic is None and any(s.stance == "mention" for s in stances) and ph:
            refl.main_topic = ph[0]
    if refl.main_topic is None and parent.lower() not in GENERIC_SUBJECTS:
        refl.main_topic = T.lemma(parent.lower()) if " " not in parent else parent.lower()
    return refl

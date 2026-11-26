"""Turn statistics into plain-language insights. Nothing here is hardcoded advice:
each sentence is only emitted when the data behind it passes its support check, and the
numbers in the sentence are the numbers in `evidence`.

Wording rules: 'observed' insights describe what happened in the user's own history;
'predicted' insights come from the model and say so. Neither claims cause.
"""
from __future__ import annotations

from . import thresholds as T

DAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _conf(n: int, reliable: bool = False) -> str:
    if n >= 40 and reliable:
        return "good"
    if n >= 15 or reliable:
        return "moderate"
    return "low"


def build(obs: dict, model_card: dict, what_if: list[dict], counts: dict) -> list[dict]:
    out: list[dict] = []

    # 1. Where the minutes are (observed, needs start times only)
    act = obs.get("period_activity") or []
    if counts["start_known"] >= T.MIN_START_KNOWN and act:
        top = max(act, key=lambda r: r["minutes"])
        if top["minutes"] > 0:
            out.append({"id": "most_active_period", "kind": "observed", "component": "rhythm",
                        "title": f"Most of your focus time is in the {top['period']}",
                        "text": (f"{_pct(top['share'])} of your recorded focus minutes ({round(top['minutes'])} min "
                                 f"across {top['sessions']} sessions) started in the {top['period']}. This shows when "
                                 f"you study, not when you study best."),
                        "evidence": top, "confidence": _conf(top["sessions"])})

    # 2. Best time of day for completing attempts (observed, needs labels)
    ps = obs.get("period_success") or {}
    cmp_ = ps.get("best_vs_rest")
    if cmp_:
        row = next(r for r in ps["rows"] if r["period"] == cmp_["period"])
        if cmp_["reliable"] and cmp_["diff"] > 0:
            out.append({"id": "best_period_completion", "kind": "observed", "component": "rhythm",
                        "title": f"You finish more sessions that start in the {cmp_['period']}",
                        "text": (f"Focus attempts started in the {cmp_['period']} were completed "
                                 f"{_pct(row['rate'])} of the time ({row['completed']}/{row['n']}), versus "
                                 f"{_pct(cmp_['rest_rate'])} at other times ({cmp_['rest_n']} attempts). "
                                 f"Observed in your history; it may reflect what you study then, not the time itself."),
                        "evidence": {**row, **cmp_}, "confidence": _conf(row["n"], True),
                        "action": {"period": cmp_["period"]}})
        else:
            out.append({"id": "no_reliable_period_difference", "kind": "observed", "component": "rhythm",
                        "title": "No reliable time-of-day difference yet",
                        "text": ("Completion rates differ a little between times of day, but not by enough, given how "
                                 "many attempts you have, to call it a pattern."),
                        "evidence": cmp_, "confidence": "low"})

    # 3. Session length vs abandonment
    rows = (obs.get("abandonment_by_length") or {}).get("rows") or []
    cand = [r for r in rows if r["n"] >= T.MIN_GROUP_N]
    if len(cand) >= 2 and rows:
        worst = max(cand, key=lambda r: r["abandon_rate"])
        k_all = sum(r["completed"] for r in rows)
        n_all = sum(r["n"] for r in rows)
        from .discovery import compare_groups
        c = compare_groups(worst["completed"], worst["n"], k_all - worst["completed"], n_all - worst["n"])
        if c and c["reliable"] and c["diff"] < 0:
            out.append({"id": "long_sessions_abandoned", "kind": "observed", "component": "rhythm",
                        "title": f"Sessions planned for {worst['bin']} are stopped early more often",
                        "text": (f"You stopped {_pct(worst['abandon_rate'])} of sessions planned for {worst['bin']} "
                                 f"({worst['n'] - worst['completed']}/{worst['n']}), compared with "
                                 f"{_pct(1 - (k_all - worst['completed']) / (n_all - worst['n']))} of other lengths."),
                        "evidence": {**worst, **c}, "confidence": _conf(worst["n"], True),
                        "action": {"max_planned_min": max(10, int(worst["min"]))}})

    td = obs.get("typical_duration") or {}
    if td.get("completed_n", 0) >= 5 and "median" in td:
        out.append({"id": "typical_focus_duration", "kind": "observed", "component": "rhythm",
                    "title": f"Typical completed session: {round(td['median'])} min",
                    "text": (f"Half of your completed sessions last between {round(td['q25'])} and {round(td['q75'])} "
                             f"minutes (median {round(td['median'])}, {td['completed_n']} sessions)."
                             + (f" When you stop early it is typically after about {round(td['abandoned_median_min'])} min."
                                if "abandoned_median_min" in td else "")),
                    "evidence": td, "confidence": _conf(td["completed_n"])})

    # 4. Subjects that differ reliably from the rest
    for r in (obs.get("subject_completion") or {}).get("rows", []):
        v = r.get("vs_rest")
        if v and v["reliable"]:
            hi = v["diff"] > 0
            out.append({"id": f"subject_{r['subject']}", "kind": "observed", "component": "rhythm",
                        "title": f"{r['subject'].title()} sessions are {'completed more' if hi else 'stopped early more'} often",
                        "text": (f"{r['completed']}/{r['n']} {r['subject']} attempts were completed "
                                 f"({_pct(r['rate'])}) versus {_pct(obs['subject_completion']['overall_rate'])} overall."),
                        "evidence": r, "confidence": _conf(r["n"], True)})

    # 5. Weekday consistency
    wc = obs.get("weekday_consistency")
    if wc and wc.get("available"):
        ranked = sorted((r for r in wc["rows"] if r["days_observed"] >= 2), key=lambda r: -r["share"])
        if ranked and ranked[0]["share"] > ranked[-1]["share"]:
            b, w = ranked[0], ranked[-1]
            out.append({"id": "weekday_consistency", "kind": "observed", "component": "rhythm",
                        "title": f"{DAYS[b['weekday']]} are your most consistent days",
                        "text": (f"You studied on {b['studied_days']} of {b['days_observed']} {DAYS[b['weekday']]} "
                                 f"({_pct(b['share'])}) over {wc['weeks_observed']} weeks, versus "
                                 f"{w['studied_days']} of {w['days_observed']} {DAYS[w['weekday']]}."),
                        "evidence": {"best": b, "worst": w}, "confidence": _conf(b["days_observed"])})

    # 6. Model-based (clearly labelled as a prediction)
    if model_card.get("state") == "active":
        cells = [c for c in what_if if c["supported"] and c["probability"] is not None]
        if len(cells) >= 2:
            best, worst = max(cells, key=lambda c: c["probability"]), min(cells, key=lambda c: c["probability"])
            if best["probability"] - worst["probability"] >= 0.10:
                out.append({"id": "model_best_slot", "kind": "predicted", "component": "rhythm",
                            "title": "Model estimate: your best slot",
                            "text": (f"Estimated completion probability is highest for a {best['planned_min']}-minute "
                                     f"{best['subject']} session in the {best['period']} "
                                     f"({_pct(best['probability'])}), and lowest for {worst['planned_min']} minutes in the "
                                     f"{worst['period']} ({_pct(worst['probability'])}). This is a model estimate from your "
                                     f"past sessions, not a guarantee."),
                            "evidence": {"best": best, "worst": worst,
                                         "held_out": model_card.get("metrics")},
                            "confidence": "moderate",
                            "action": {"period": best["period"], "planned_min": best["planned_min"]}})
    return out

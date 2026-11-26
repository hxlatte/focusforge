"""Every data-sufficiency threshold in one place, so the cold-start behaviour is auditable.

These are deliberately conservative defaults, not tuned values. They exist to stop
the engine from presenting noise as a personal pattern.
"""
MIN_SESSIONS_ANY = 5          # below this: "collecting data" only
MIN_START_KNOWN = 8           # sessions with a known start time before any time-of-day view
MIN_LABELLED_ATTEMPTS = 10    # labelled focus attempts before completion-rate statistics
MIN_ABANDONED_FOR_RATES = 2   # need some abandoned attempts, otherwise a rate says nothing
MIN_GROUP_N = 8               # per-group minimum when two groups are compared
MIN_SUBJECT_N = 5             # per-subject minimum to report a subject completion rate
FISHER_ALPHA = 0.10           # a difference is called "reliable" only below this p-value
MIN_EFFECT = 0.15             # ...and only if the rates differ by at least 15 points

MODEL_MIN_LABELLED = 40       # labelled attempts before a model is even trained
MODEL_MIN_MINORITY = 10       # ...and at least this many of each outcome
GBM_MIN_LABELLED = 200        # gradient boosting is only tried above this size
MODEL_MIN_LOGLOSS_GAIN = 0.01 # model must beat the base-rate baseline by this much (log-loss)
MODEL_MIN_AUC = 0.60          # ...and reach this AUC on held-out later sessions
MODEL_MIN_FOLDS = 3           # ...across at least this many forward-chaining folds

CLUSTER_MIN_SESSIONS = 40
CLUSTER_MIN_SILHOUETTE = 0.25
WEEKDAY_MIN_WEEKS = 3         # weeks of history before "most consistent days"
SHRINKAGE_STRENGTH = 5.0      # pseudo-observations pulling small groups toward the overall rate

PERIODS = {                   # local start hour -> period
    "morning": range(5, 12),
    "afternoon": range(12, 17),
    "evening": range(17, 22),
    "night": list(range(22, 24)) + list(range(0, 5)),
}


def period_of(hour: int) -> str:
    for name, hours in PERIODS.items():
        if hour in hours:
            return name
    return "night"

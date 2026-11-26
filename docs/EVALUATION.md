# Evaluation report

Everything below was produced by code in this repository. Nothing here was run on a real user's
history: none was available. Numbers on synthetic or author-labelled data are labelled as such,
and the limits of each are stated next to the numbers.

## 1. Cognitive Rhythm Engine

**Method.** Labelled timer attempts only; features available at session start only (history
features are computed from strictly earlier rows; unit-tested for leakage); forward-chaining
evaluation (train on the past, test on the next block); baseline = Laplace-smoothed base rate;
regularised logistic regression (gradient boosting only above 200 attempts). A model is
displayed only if, on held-out later sessions, it beats the baseline by ≥ 0.01 log-loss with
AUC ≥ 0.60 over ≥ 3 folds.

**Synthetic study** (`python -m eval.run_rhythm_eval`, 20 simulated users per cell, ~2.2 attempts/day).
"Planted" users have a built-in morning advantage and a penalty for 40+ minute sessions; "null"
users have no pattern.

| History | Median attempts | Planted: model shown | Morning effect found | Long-session effect found | Null: model falsely shown | Null: false period/length claim | Null: false subject claim |
|---|---|---|---|---|---|---|---|
| 20 d | 44 | 15% | 65% | 30% | 0% | 10% | 10% |
| 40 d | 90 | 30% | 85% | 85% | 0% | 20% | 10% |
| 70 d | 157 | 55% | 100% | 100% | 0% | 25% | 10% |
| 100 d | 224 | 85% | 100% | 100% | 0% | 0% | 0% |
| 150 d | 334 | 100% | 100% | 100% | 0% | 10% | 0% |

When the model was shown, held-out AUC averaged 0.72–0.76 (planted effect, so this is a property of the
simulation, not a prediction of real-world accuracy).

**What this supports:** the gate works: the model was never shown on pattern-free data (0 of 100 runs),
and planted effects are found reliably from roughly 70 days of regular use.
**What it does not support:** any claim about real people. **Known weakness:** the descriptive
"reliable difference" insights (p < 0.10 and ≥ 15-point gap) produced a false claim in 0–25% of
pattern-free runs. Several comparisons are made per user and no multiple-comparison correction is
applied. The dashboard labels these "Observed" with a confidence level and the p-value; tighten
`FISHER_ALPHA` / add a correction if you prefer fewer false alarms at the cost of recall.

**Limits with small histories:** below ~40 attempts no model is trained. 20 days of use gives a
usable model in only ~15% of planted cases.

## 2. Study-Log Analyzer

**Method.** Rule-based clause extraction: cue lexicon with negation handling for four stances
(struggling / wants to revise / confident / understood, plus "revised" and "studied"), noun-phrase
topics, conservative canonicalisation, embedding clustering of difficulty statements. Deliberately
not generic sentiment analysis.

**Labelled set** (`eval/labelled_logs.json`). **Written by the same author as the analyzer**, so these
are regression numbers, not independent accuracy. 29 development notes were used while building;
30 test notes were written before the first run and scored once, with the rules frozen.

| Split | (topic, stance) P / R / F1 | Topic only F1 | Stance accuracy when topic found |
|---|---|---|---|
| Development (tuned on, optimistic) | 0.98 / 0.98 / 0.98 | 0.98 | 1.00 |
| **Test (frozen, scored once)** | **0.67 / 0.80 / 0.73** | 0.78 | 0.93 |

The 0.98 → 0.73 gap is overfitting to the development notes. Use the test row. Failure modes seen on
the test split (see `eval/results/logs_test_frozen.json`): idioms ("wrap my head around" leaks "head" as a
topic), implicit struggle ("way over my head", "shaky", "trips me up"), coordinated multi-word terms
("supply and demand" split in two), "sorted out my confusion" read as struggling, and a pronoun/plural
referent ("both feel solid") resolving to one topic only. Two general fixes were made after the test
run (irregular plurals such as *matrices*, markup stripping); the test split was not re-scored afterwards.
For a real accuracy figure, label some of your own reflections in the same JSON format and run
`python -m eval.run_logs_eval --split test`.

**Clustering** (19 hand-grouped difficulty statements, 5 groups, pairwise scoring):
lexical fallback embedder P 1.00 / R 0.52 / F1 0.68. It groups statements that share word stems
("recursion" with "tree recursion") and misses paraphrases. **The semantic embedder
(Sentence-Transformers) was not run:** its weights could not be downloaded in the build
environment. Run `python -m eval.run_logs_eval --split test --embedder semantic` on your machine and
record the result here.

**Revision scheduling.** Uses the open-source `fsrs` reference implementation with default
(non-personalised) parameters, driven only by explicit 1–4 recall ratings; replay is deterministic and
tested. Topics flagged from reflections alone get a fixed estimate (1 or 2 days) labelled as an
estimate. **Not validated:** whether the schedule predicts real recall requires recall ratings over time.
No mastery claim is made from writing alone.

## 3. Unified recommender

A transparent rule combiner, not a learned model. Tests verify: every sentence traces to a named
source; no timing is suggested without supporting rhythm evidence; responses survive re-analysis
(dismissals cool down 7 days); accepting is the only path to a task; wording avoids causal claims.

**No effectiveness result exists.** The system records acceptance, completion and "did you study that
topic after accepting" (`adherence`) and shows rates only after 5+ responses. Comparing recommendations
against a baseline (for example oldest-topic-first with no timing) needs real use over weeks; one
person's history cannot establish it. Any simulation would assume its own conclusion, so none is reported.

## 4. Integration checks actually run

* Backend suite (40 tests): auth scoping, user isolation, Firestore-safe output (no nested arrays/NaN), cold start, leakage, gating, scheduler, recommender rules.
* `tests/frontend/capture.test.mjs`: abandonment, pause handling, ≥1-min threshold, reflection saving, no `undefined` written to Firestore (runs the real `app.js` with Firebase stubbed).
* `tests/frontend/ix_ui_test.py`: 20 browser checks on the dashboard (Chrome): rendering, accept/dismiss/rate writes, XSS escaping, offline state, mobile overflow.

**Not run (no access from the build environment):** real Firebase sign-in and token verification, the deployed
Firestore rules (validated for syntax by inspection only; use the Firebase emulator or console Rules Playground),
and any real user's data.

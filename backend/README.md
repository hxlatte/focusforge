# FocusForge Intelligence backend

FastAPI service that runs the **Cognitive Rhythm Engine**, the **Study-Log Analyzer** and the
**unified recommender** on a signed-in user's own Firestore data. The existing frontend stays
vanilla JS; it calls this service with the user's Firebase ID token.

```
Browser (index.html, app.js, intelligence.js)
   │  Authorization: Bearer <Firebase ID token>
   ▼
FastAPI  ── verifies the token ── uid comes ONLY from the verified token
   ├─ app/rhythm/     Cognitive Rhythm Engine   (when / how you study best)
   ├─ app/logs/       Study-Log Analyzer        (what you study / struggle with)
   ├─ app/recommend/  Unified recommendations   (combines both, transparent rules)
   ▼
Firestore (Admin SDK, every path is users/{uid}/…)
```

## Run it locally

Requirements: Python 3.10+.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 1. Firebase console → Project settings → Service accounts → Generate new private key.
#    Save it as backend/service-account.json  (git-ignored; never commit or share it).
cp .env.example .env                                      # then check the three values in it

# 2. Run
uvicorn app.main:app --port 8000
```

Then serve the frontend as you already do (Live Server on port 5504 is allowed by default) and
open **Intelligence** in the nav. The first visit runs an analysis; **Re-analyse** runs it again.
To point the page at another backend URL: `localStorage.setItem('ff_api_base', 'http://host:port')`.

**Deploy the updated Firestore rules** before using the new features (recall ratings and
recommendation responses are written from the browser):

```bash
firebase deploy --only firestore:rules
```

The first run downloads the sentence-embedding model (`all-MiniLM-L6-v2`, ~90 MB) from Hugging
Face. If it cannot be loaded the analyzer falls back to a lexical TF-IDF embedder and the dashboard
says so. Force the fallback with `FOCUSFORGE_EMBEDDER=tfidf`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest                          # backend: 40 tests, ~60 s
node ../tests/frontend/capture.test.mjs   # timer / abandonment / reflection capture in app.js
python -m eval.run_rhythm_eval            # synthetic recovery + false-alarm study (~6 min)
python -m eval.run_logs_eval --split dev  # labelled reflection extraction (add --embedder semantic)
```

Browser test of the dashboard (needs Playwright + Chrome; see the header of `tests/frontend/ix_ui_test.py`).

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/v1/me` | verified uid/email |
| GET | `/v1/data-summary?tz=` | counts only: what data exists |
| POST | `/v1/analyze` `{tz}` | run all engines on the user's real data, store results |
| GET | `/v1/intelligence` | latest stored results (no recomputation) |

`/v1/analyze` returns 409 if any row carries `synthetic: true`: synthetic data can never reach a user dashboard.

## Firestore

Reused: `users/{uid}/sessions` (extended, additive), `tasks`. New:

| Collection | Written by | Contents |
|---|---|---|
| `analysis/rhythm`, `analysis/learning`, `analysis/recommendations_meta` | backend | latest engine output |
| `topics/{id}` | backend | topic history, stance counts, evidence sentences, schedule |
| `recommendations/{id}` | backend creates; user may change only `status`, `statusUpdatedAt` | proposals |
| `reviews/{id}` | user (rating 1–4) | recall ratings; the only input that drives FSRS |

New optional session fields: `status` (`completed`/`abandoned`), `plannedDuration`, `actualDuration`,
`startedAt`, `endedAt`, `tz`, `confidence` (1–4). Existing documents are untouched; rows without
`status` are treated as completed for descriptive statistics but are **not** used to train the
completion model (only successes were ever stored, so they would bias every rate upward).
Abandoned attempts are kept out of `State.sessions` in the app so existing totals and streaks do not change.

## Cold start (all thresholds in `app/rhythm/thresholds.py`)

| Labelled timer attempts | What is shown |
|---|---|
| < 5 sessions | "collecting data", nothing personalised |
| sessions with a start time ≥ 8 | heatmap, most-active periods, typical duration (observed) |
| ≥ 10 attempts incl. ≥ 2 stopped early | completion rates with 95% intervals, reliable-difference insights |
| ≥ 40 attempts, ≥ 10 of each outcome | a model is trained and **shown only if it beats the base-rate baseline on later, held-out sessions** |

## Security

* ID tokens are verified server-side; every query is scoped to `users/{token uid}`.
* No credentials in frontend code. `service-account*.json` and `.env` are git-ignored.
* The Admin SDK bypasses Firestore rules, so isolation on the backend comes from the uid scoping in `app/repo.py` (tested).
* All user-originated text is HTML-escaped in the dashboard; notes are stripped of markup before analysis.
* **Not yet verified against live Firebase:** real ID-token verification and the deployed rules were not run in this build environment (no credentials). Do a sign-in → Re-analyse pass on your machine.

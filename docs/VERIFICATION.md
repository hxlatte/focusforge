# Pre-PR verification: `feature/intelligence`

Status: **Real Firebase integration has NOT been verified.** Everything below marked "verified" was run
against stubs, an in-memory repository, locally signed tokens or a headless browser with Firestore
replaced by a stub. Nothing has touched your Firebase project. The checklist at the end is how you verify it.

## What was run

| Area | How | Result |
|---|---|---|
| Backend unit/API tests | `cd backend && python -m pytest` | 63 pass |
| ID-token verification | real `firebase_admin` verifier, locally generated signing key, only the certificate download replaced | valid accepted; expired, wrong audience, wrong issuer, missing/empty sub, wrong key, unknown kid, future iat, garbage, tampered payload, `alg: none`, HS256 key-confusion all rejected; uid only ever comes from the verified token |
| Existing-app regression | `node tests/frontend/regression_compare.mjs` (main vs branch, same data) | all zero-argument aggregates identical (sessions, tasks, streaks, garden, growth stages) even with 8 abandoned attempts present; legacy write keys identical, only `status` and `tz` added |
| Timer / capture | `node tests/frontend/capture.test.mjs` | pass |
| Dashboard in Chrome | `tests/frontend/ix_ui_test.py` (20 checks) and `ix_states_test.py` (29 checks plus 424 field mutations x 3 tabs) | pass |
| Embedder paths | `backend/tests/test_embedder_paths.py` with a stand-in `sentence_transformers` | selection, normalisation, missing package, load failure, env override, run-time failure all behave; real model NOT run |
| Firestore rules | **written, not executed**: `tests/rules/rules.test.mjs` (emulator download is blocked in the sandbox) | unknown until you run it |

## Defects found and fixed in this pass

1. **Cross-account cache leak (privacy).** The dashboard cache was not tied to a user; signing out and in as someone else
   in the same tab could show the previous user's analysis, and an in-flight request could land in the wrong account.
   Cache is now keyed to the uid, cleared on change, and late responses are discarded.
2. **Topic id collisions.** `c++` and `c#` both became `c`; non-Latin topics all became `topic`. Ids now spell out symbols
   and add a short hash when text would be lost.
3. **Performance.** Feature building was O(n^2): 1,000 attempts took 11 s and 2,500 took 68 s per request. Now vectorised
   (0.6 s / 0.9 s), checked against the literal definition in a test.
4. **Negated revise.** "No need to revise X" produced a *revise* recommendation. Fixed.
5. **Spurious topics** from "anymore", "no longer", "wrap my head around". Fixed.
6. **Dashboard partial output.** 130 of 424 simulated partial/malformed payloads crashed a section or printed
   `undefined`/`NaN`. Each section now degrades independently to a notice; missing numbers show a dash.
7. **Semantic embedder run-time failure** would have returned a 500. Now falls back to lexical clustering and the result
   says which embedder was really used. `--embedder semantic` in the eval now refuses to run on the fallback.
8. **Stale timer attempt** after changing the pomodoro length mid-pause, or logging out mid-attempt, could attach an old
   start time to the next session. Both paths now clear the attempt.
9. **Nav bar** overflowed 100 px earlier than before because of the extra link (769-900 px). Now no worse than main.

## Remaining issues

### Critical (resolve before opening the PR)
- **C1. Nothing has run against a real Firebase project.** Rules deployment, ID-token verification against Google's
  certificates, Admin SDK Firestore reads/writes, and the Auth authorised-domains setting are all untested.
  Use the checklist. This stays critical until the checklist passes.

### Major
- **M1. Abandoned attempts are only recorded when the user presses Reset or switches mode.** Closing the tab, a crash, or
  navigating away mid-attempt records nothing, so completion rates are biased upward. The UI wording says "of attempts
  recorded". Recording on `pagehide` is unreliable with Firestore; a local-storage journal flushed at next load would fix it.
- **M2. Semantic clustering threshold (cosine distance 0.45) is unvalidated.** MiniLM has never been run on the labelled
  set. It may over-merge unrelated difficulties. Run `python -m eval.run_logs_eval --split test --embedder semantic`
  and compare with the lexical numbers (pair-F1 0.68, precision 1.0, recall 0.52) before trusting semantic labels.
- **M3. No multiple-comparison correction** on the descriptive "best period / subject" claims; the synthetic study shows
  false descriptive claims on null data in roughly 0-25% of cases. They are worded as observations, but a stricter
  gate (Benjamini-Hochberg or a permutation test over the max difference) would be better.
- **M4. Rating orphaning.** Recall ratings are keyed by topic id. If a later analysis canonicalises a topic to a different
  name, earlier ratings no longer match and are silently ignored by the scheduler.
- **M5. Study-log extraction accuracy is author-labelled.** Honest held-out figure: P/R/F1 0.67/0.80/0.73 (see
  EVALUATION.md). Duplicate topics (acronyms, synonyms) and some wrong difficulty labels remain, see below.
- **M6. Recommender effectiveness is unmeasured.** Only counters (accepted, completed, dismissed) are recorded.

### Minor
- Acronym/full-name duplicates ("BST" vs "binary search tree"); "stop" from "hard to stop procrastinating"; "question" from
  "questions about X"; clause after "but" lost when it uses an unlisted positive cue ("was fine").
- `check_revoked=False`: a revoked-but-unexpired token (up to 1 h) is still accepted.
- The backend needs service-account credentials even to verify tokens (firebase_admin builds its client first).
- No rate limit on `/v1/analyze`; local use only.
- `prev_day_task_rate` uses current task completion state, which can include completion that happened after the attempt.
- Rhythm CV pools predictions across folds and picks the better of two models on the same folds (small optimism).
- What-if grid reuses the most recent attempt's history features as context.
- Rules allow extra fields and long strings in the user's own `reviews`; harmless to others.
- Export now includes abandoned attempts in `sessions` (behaviour change, additive).
- Pre-existing, not changed: "Clear data" only clears local state; mobile nav is hidden below 769 px.
- Default API base is `http://127.0.0.1:8000`; a deployed site needs `window.FF_API_BASE` and an HTTPS backend.

## Local testing checklist (your Firebase project)

Use a spare test account (and a second one for isolation checks). Take note of your current Progress/Garden numbers on
`main` first so you can compare.

**A. Setup**
1. `git checkout feature/intelligence` (do not merge). Confirm `firebaseConfig.projectId` in `app.js` equals the
   `FIREBASE_PROJECT_ID` you will give the backend.
2. Firebase console > Authentication > Settings > Authorised domains: `localhost` and `127.0.0.1` are listed.
3. Firebase console > Project settings > Service accounts > Generate new private key. Save it **outside the repo**.
4. `cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && cp .env.example .env`;
   set `FIREBASE_PROJECT_ID` and `GOOGLE_APPLICATION_CREDENTIALS=/abs/path/key.json`.
5. `uvicorn app.main:app --port 8000` and, from the repo root, `python3 -m http.server 5504 --bind 127.0.0.1`.
   Open `http://127.0.0.1:5504`. `curl localhost:8000/health` returns `{"status":"ok"}`.

**B. Rules (before relying on the app)**
6. Run the emulator tests: `cd tests/rules && npm i && npm test` (needs Java). Every test must pass.
7. Deploy: `firebase deploy --only firestore:rules`. This changes the live project's rules. They only add collections
   and require a valid `status` when one is written, so the existing app's writes (no status) are still allowed; check this
   in step 15. If you prefer, test against a separate throwaway Firebase project first.
8. In the browser console as account B, with `const m = await import('https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js')`:
   each of these must reject with `permission-denied`:
   `m.getDocs(m.collection(FocusForge.db,'users','<A-uid>','sessions'))`, the same for `reviews` and `recommendations`,
   `m.setDoc(m.doc(FocusForge.db,'users','<B-uid>','analysis','x'),{a:1})`,
   a `reviews` write with `rating: 7`, and a `recommendations` update that also changes `title`.

**C. Token auth**
9. `curl -i localhost:8000/v1/me` returns 401. In the console: `await FocusForge.auth.currentUser.getIdToken()`, then
   `curl -H "Authorization: Bearer <token>" localhost:8000/v1/me` returns your uid (compare with the console).
10. Change one character of the token: 401. Account B's token returns B's uid and B's counts only.
11. An hour-old token returns 401 (the dashboard then shows a sign-in message and Retry).

**D. Data capture and regression of existing features**
12. Sign up, sign in, Google sign-in, sign out, sign in again.
13. Add / complete / delete a task; garden updates; theme toggle; settings persist after reload; Export downloads JSON.
14. Complete a pomodoro: Firestore `sessions/{id}` has `status: completed`, `plannedDuration`, `startedAt`, `endedAt`, `tz`.
    Start one, wait over a minute, press Reset: a document with `status: abandoned` appears, and your Progress totals do **not** change.
15. Progress, streak and Garden numbers match what `main` showed for the same data. Log a manual session with the optional
    start time and rating; add a reflection in the completion dialog.
16. Change the pomodoro length while a timer is paused, then finish a session: its `startedAt` is the new start, not the old one.

**E. Intelligence**
17. Open Intelligence with little data: it should say what is missing, not show numbers. No demo data anywhere.
18. After some reflections, Re-analyse. Firestore gains `analysis/rhythm`, `analysis/learning`, `analysis/recommendations_meta`,
    `topics/*`, `recommendations/*`. Open a topic and check the evidence sentences are yours.
19. Accept a recommendation: exactly one task appears for the stated day and the recommendation becomes `accepted`.
    Dismiss another: no task. Rate a topic 1-4: a `reviews` document appears and the schedule changes.
20. Stop uvicorn: the dashboard shows setup help, not a blank page. Start it and press Retry.
21. Account switch in the same tab: the second account never sees the first account's topics.

**F. Semantic embedder**
22. `pip install sentence-transformers`, then `python -m eval.run_logs_eval --split test --embedder semantic`. It must say
    `sentence-transformers/all-MiniLM-L6-v2` (it refuses to run on the fallback). Compare cluster precision/recall with the lexical numbers.
23. After a Re-analyse the saved learning result shows `embedder.semantic: true`. With `FOCUSFORGE_EMBEDDER=tfidf`, or offline on a
    fresh machine, it shows the lexical fallback label. The first semantic analysis is slow while the model loads.

Only when every step passes should real Firebase integration be called verified.

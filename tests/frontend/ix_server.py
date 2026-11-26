"""Local UI-test server for the Intelligence dashboard.

Runs the REAL FastAPI app and engines against an in-memory repository seeded with generated
sessions and reflections, with auth stubbed to a fixed test user. This is a fixture for
checking that the dashboard renders and behaves; it is not user data and never touches
Firebase. (The seeded rows deliberately omit the `synthetic` flag so the API will analyse
them, which is exactly why this lives under tests/ and is never part of the app.)
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import uvicorn  # noqa: E402

from app.auth import AuthUser, current_user  # noqa: E402
from app.main import app, get_repo  # noqa: E402
from app.repo import InMemoryRepo  # noqa: E402
from eval.synthetic import generate  # noqa: E402

NOTES = [
    "I studied neural networks today. I understood the basic architecture, but I am still confused about backpropagation. I need to revise gradient descent.",
    "Tree recursion is confusing.", "I don't understand recursion.", "I am struggling with recursive functions.",
    "Pointers are really hard for me. Need to go over pointer arithmetic again.",
    "Backprop still confusing. Gradient descent makes sense now.",
    "Confident about binary search trees. SQL joins are tricky.",
    "<img src=x onerror=window.__xss=1> confused about <b>sorting</b>.",
    "Revised database normalization. Understand it well now.",
]


def build() -> InMemoryRepo:
    repo = InMemoryRepo()
    start = datetime.now() - timedelta(days=100)
    docs = generate(11, days=100, planted=True, start_day=start)
    sessions, ni = {}, 0
    for i, d in enumerate(docs):
        d.pop("synthetic", None)
        if d["status"] == "completed" and i % 9 == 0 and ni < len(NOTES) * 2:
            d["notes"] = NOTES[ni % len(NOTES)]
            ni += 1
        sessions[f"s{i}"] = d
    # place the reflections near the end so topics are recent
    notes_docs = [k for k, v in sessions.items() if v["notes"]]
    for k in notes_docs[:-len(NOTES)]:
        sessions[k]["notes"] = ""
    for j, k in enumerate(notes_docs[-len(NOTES):]):
        sessions[k]["notes"] = NOTES[j]
    repo.seed("demo", "sessions", sessions)
    return repo


repo = build()


@app.get("/__test/topic/{tid}")
def _test_topic(tid: str):
    """Test-only: lets the browser stub of Firestore getDoc() return the stored topic evidence."""
    from fastapi import HTTPException
    doc = repo.get("demo", "topics", tid)
    if doc is None:
        raise HTTPException(404)
    return doc

app.dependency_overrides[get_repo] = lambda: repo
app.dependency_overrides[current_user] = lambda: AuthUser("demo", "demo@example.com")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")

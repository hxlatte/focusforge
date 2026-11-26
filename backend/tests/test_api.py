import pytest
from fastapi.testclient import TestClient

from app.auth import AuthUser, current_user
from app.main import app, get_repo
from app.repo import InMemoryRepo


@pytest.fixture()
def env():
    repo = InMemoryRepo()
    repo.seed("alice", "sessions", {
        "s1": {"subject": "Maths — Integration", "duration": 25, "notes": "hard",
               "date": "2026-11-20T10:00:00Z", "type": "pomodoro"},
        "s2": {"subject": "Maths", "duration": 30, "notes": "",
               "date": "not-a-date", "type": "manual"},
        "s3": {"subject": "CS", "duration": 25, "plannedDuration": 25, "actualDuration": 9,
               "status": "abandoned", "startedAt": "2026-11-21T09:00:00Z",
               "endedAt": "2026-11-21T09:09:00Z", "tz": "Asia/Kolkata", "type": "pomodoro",
               "date": "2026-11-21T09:09:00Z"},
    })
    repo.seed("bob", "sessions", {
        "b1": {"subject": "Secret", "duration": 50, "date": "2026-11-20T10:00:00Z", "type": "manual"},
    })
    app.dependency_overrides[get_repo] = lambda: repo
    yield repo
    app.dependency_overrides.clear()


def as_user(uid):
    app.dependency_overrides[current_user] = lambda: AuthUser(uid=uid, email=f"{uid}@x.com")


def test_health_is_public():
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_requires_token():
    c = TestClient(app)
    assert c.get("/v1/me").status_code == 401
    assert c.get("/v1/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_summary_counts_and_isolation(env):
    as_user("alice")
    r = TestClient(app).get("/v1/data-summary", params={"tz": "Asia/Kolkata"}).json()
    assert r["sessions_total"] == 2          # s2 has an unusable timestamp
    assert r["unusable_rows"] == 1
    assert r["sessions_labelled"] == 1        # only s3 has an explicit status
    assert r["sessions_abandoned"] == 1
    assert r["sessions_with_notes"] == 1
    as_user("bob")
    assert TestClient(app).get("/v1/data-summary").json()["sessions_total"] == 1


def test_repo_scopes_by_uid_and_blocks_collections(env):
    assert env.get("alice", "sessions", "b1") is None
    with pytest.raises(PermissionError):
        env.put("alice", "sessions", "x", {})       # sessions are read-only to backend
    with pytest.raises(PermissionError):
        env.list("alice", "users")
    with pytest.raises(ValueError):
        env.get("alice", "analysis", "../bob")

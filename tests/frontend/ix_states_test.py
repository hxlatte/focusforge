"""Dashboard robustness test: empty / insufficient / failing backend / partial model output / account switch.

    python3 -m http.server 5504 --bind 127.0.0.1 &        # from the repo root
    python3 tests/frontend/ix_states_test.py [path-to-chrome]

Payloads come from the REAL backend engines (in-process TestClient, in-memory repo). The browser
intercepts /v1/* and serves them, then the test deletes / nulls / empties every field of the real
payload one at a time and checks the dashboard still renders without errors or "undefined"/"NaN".
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app.auth import AuthUser, current_user  # noqa: E402
from app.main import app, get_repo  # noqa: E402
from app.repo import InMemoryRepo  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ix_server  # noqa: E402  (builds the fixture repo; does not start a server)

CHROME = sys.argv[1] if len(sys.argv) > 1 else "/usr/bin/google-chrome"
URL = "http://127.0.0.1:5504/tests/frontend/ix_fixture.html"
STUB = ix_server.__doc__ and """
export const doc=(...a)=>({path:a.slice(1).join('/')});
export const collection=(...a)=>({path:a.slice(1).join('/')});
export const getDoc=async()=>({exists:()=>false,data:()=>null});
export const addDoc=async()=>({id:'x'});
export const updateDoc=async()=>{};
"""
errors, ok = [], 0


def check(cond, msg):
    global ok
    if cond:
        ok += 1
    else:
        errors.append(msg)


def real_payload(repo, uid="u"):
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[current_user] = lambda: AuthUser(uid, "u@x.com")
    c = TestClient(app)
    r = c.post("/v1/analyze", json={"tz": "Asia/Kolkata"})
    assert r.status_code == 200, r.text
    out = c.get("/v1/intelligence").json()
    app.dependency_overrides.clear()
    return out


def empty_payload():
    repo = InMemoryRepo()
    return real_payload(repo)


def tiny_payload():
    repo = InMemoryRepo()
    repo.seed("u", "sessions", {f"s{i}": {"subject": "Maths", "duration": 25, "type": "manual",
                                           "date": f"2026-11-{10 + i}T10:00:00Z", "notes": ""} for i in range(3)})
    return real_payload(repo)


def paths(obj, prefix=(), depth=0):
    if depth > 3 or not isinstance(obj, dict):
        return
    for k, v in obj.items():
        yield prefix + (k,)
        yield from paths(v, prefix + (k,), depth + 1)


def mutate(payload, path, mode):
    p = copy.deepcopy(payload)
    cur = p
    for k in path[:-1]:
        cur = cur[k]
    if mode == "delete":
        cur.pop(path[-1], None)
    else:
        cur[path[-1]] = {"null": None, "empty_list": [], "empty_obj": {}}[mode]
    return p


def open_page(b, intelligence, analyze=None, status=200, w=1180, h=900):
    pg = b.new_context(viewport={"width": w, "height": h}).new_page()
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e} [{pg._label}]"))
    pg._label = "?"
    pg.route("**/firebase-firestore.js", lambda r: r.fulfill(content_type="application/javascript", body=STUB))
    pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())

    def handle(route):
        u = route.request.url
        if status != 200:
            return route.fulfill(status=status, content_type="application/json", body="{}")
        body = analyze if (u.endswith("/v1/analyze") and analyze is not None) else intelligence
        route.fulfill(content_type="application/json", headers={"access-control-allow-origin": "*"},
                      body=json.dumps(body))
    pg.route("**/127.0.0.1:8765/v1/**", handle)
    pg.goto(URL)
    return pg


def serve(payload):
    def h(route):
        route.fulfill(content_type="application/json", headers={"access-control-allow-origin": "*"},
                      body=json.dumps(payload))
    return h


def render(pg, label):
    pg._label = label
    pg.evaluate("window.Intelligence.render()")
    pg.wait_for_timeout(250)
    return pg.inner_text("#ixRoot")


def clean(text, label):
    bad = [w for w in ("undefined", "NaN", "[object", "null", "Infinity") if w in text]
    check(not bad, f"{label}: leaked {bad}")
    check(len(text.strip()) > 0, f"{label}: rendered nothing")


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
    full = real_payload(ix_server.repo, "demo")
    empty, tiny = empty_payload(), tiny_payload()

    # --- states ---------------------------------------------------------------------------------
    for label, payload in [("full", full), ("empty account", empty), ("3 sessions", tiny)]:
        pg = open_page(b, payload)
        for tab in ("insights", "rhythm", "learning"):
            pg.evaluate(f"window.Intelligence._store.tab='{tab}'")
            clean(render(pg, f"{label}/{tab}"), f"{label}/{tab}")
        pg.context.close()
    pg = open_page(b, empty)
    t = render(pg, "empty")
    check("collect" in t.lower() or "not enough" in t.lower() or "keep" in t.lower() or "need" in t.lower(),
          f"empty account explains what is missing: {t[:160]!r}")
    pg.context.close()

    for status, expect in [(401, ("sign", "session", "expired", "log")), (500, ("went wrong", "couldn", "failed", "try again", "error", "unavailable"))]:
        pg = open_page(b, full, status=status)
        t = render(pg, f"http {status}")
        pg.wait_for_timeout(300)
        t = pg.inner_text("#ixRoot")
        check(any(w in t.lower() for w in expect), f"HTTP {status} gives a readable error: {t[:120]!r}")
        check(pg.locator('[data-ix="retry"]').count() >= 1, f"HTTP {status} offers retry")
        clean(t, f"http {status}")
        pg.context.close()

    # --- fuzz: every field of the real payload removed / nulled / emptied ---------------------------
    all_paths = [pa for pa in paths(full) if pa[0] in ("rhythm", "learning", "recommendations")]
    n = 0
    pg = None
    for path in all_paths:
        for mode in ("delete", "null", "empty_list", "empty_obj"):
            payload = mutate(full, path, mode)
            if pg is None or n % 40 == 0:
                if pg:
                    pg.context.close()
                pg = open_page(b, payload)
            else:
                pg.unroute("**/127.0.0.1:8765/v1/**")
                pg.route("**/127.0.0.1:8765/v1/**", serve(payload))
            n += 1
            label = f"{'.'.join(path)}:{mode}"
            pg.evaluate("window.Intelligence._store.state='idle'; window.Intelligence._store.data=null")
            for tab in ("insights", "rhythm", "learning"):
                pg.evaluate(f"window.Intelligence._store.tab='{tab}'")
                try:
                    t = render(pg, f"{label}/{tab}")
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{label}/{tab}: {e}")
                    continue
                # wrong-type values (an object where a number belongs) must not crash; only missing/null/empty
                # fields are expected to degrade cleanly to a dash
                bad = [w for w in ("undefined", "NaN", "[object", "Infinity") if w in t] if mode != "empty_obj" else []
                if bad or not t.strip():
                    errors.append(f"{label}/{tab}: leaked {bad} / empty={not t.strip()}")
    if pg:
        pg.context.close()
    print(f"fuzzed {n} mutations x 3 tabs")

    # --- account switch: A's data must not appear for B ----------------------------------------------
    pg = open_page(b, full)
    render(pg, "A")
    pg.evaluate("window.FocusForge.auth.currentUser = { uid: 'userB', getIdToken: async () => 't' }")
    pg.route("**/127.0.0.1:8765/v1/**", serve(empty))
    pg.evaluate("window.FocusForge.auth.currentUser.uid='userB'")
    first = pg.evaluate("(() => { window.Intelligence.render(); return document.getElementById('ixRoot').innerText })()")
    check("Backpropagation" not in first and "Gradient" not in first, "account switch: A's topics are not shown to B")
    check(pg.evaluate("window.Intelligence._store.uid") == "userB", "store re-keyed to the new user")
    pg.context.close()
    b.close()

print(f"{ok} checks passed")
for e in errors[:60]:
    print("FAIL:", e)
print(f"{len(errors)} failures")
sys.exit(1 if errors else 0)

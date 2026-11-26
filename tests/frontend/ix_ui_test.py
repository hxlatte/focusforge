"""Browser test for the Intelligence dashboard (needs: pip install playwright, and Chrome).

    python3 tests/frontend/ix_server.py &                      # API on :8765 (fixture data, stub auth)
    python3 -m http.server 5504 --bind 127.0.0.1 &             # static files from the repo root
    python3 tests/frontend/ix_ui_test.py [path-to-chrome]

Firestore is replaced by a tiny stub that records writes, so this checks the UI and its
request/response handling, not Firestore security rules.
"""
import sys
from playwright.sync_api import sync_playwright

CHROME = sys.argv[1] if len(sys.argv) > 1 else "/usr/bin/google-chrome"
URL = "http://127.0.0.1:5504/tests/frontend/ix_fixture.html"
STUB = """
export const doc=(...a)=>({path:a.slice(1).join('/')});
export const collection=(...a)=>({path:a.slice(1).join('/')});
export const getDoc=async(ref)=>{const id=ref.path.split('/').pop();const r=await fetch('http://127.0.0.1:8765/__test/topic/'+id);const d=r.ok?await r.json():null;return {exists:()=>!!d,data:()=>d}};
export const addDoc=async(c,d)=>{(window.__writes=window.__writes||[]).push({op:'add',path:c.path,d});return {id:'x'}};
export const updateDoc=async(r,d)=>{(window.__writes=window.__writes||[]).push({op:'update',path:r.path,d});};
"""
errors, ok = [], 0


def check(cond, msg):
    global ok
    if cond:
        ok += 1
    else:
        errors.append(msg)


def open_page(b, w=1180, h=900, theme="light", block_api=False):
    pg = b.new_context(viewport={"width": w, "height": h}).new_page()
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.route("**/firebase-firestore.js", lambda r: r.fulfill(content_type="application/javascript", body=STUB))
    pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
    if block_api:
        pg.route("**/127.0.0.1:8765/v1/**", lambda r: r.abort())
    pg.goto(URL)
    pg.evaluate(f"document.documentElement.setAttribute('data-theme','{theme}')")
    pg.evaluate("window.Intelligence.render()")
    return pg


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])

    pg = open_page(b)
    pg.wait_for_selector(".ix-rec", timeout=90000)
    check("FocusForge Intelligence" in pg.inner_text(".ix-title"), "title")
    check("Understand your rhythm" in pg.inner_text(".ix-sub"), "subtitle")
    check(pg.locator(".ix-metric").count() == 4, "4 overview metrics")
    check(pg.locator(".ix-rec").count() >= 1, "recommendations render")

    pg.click(".ix-why summary >> nth=0")
    why = pg.inner_text(".ix-why[open]")
    check("Study log" in why and "Rhythm" in why, "why lists both contributing components")

    n_tasks = pg.evaluate("window.__tasks.length")
    check(n_tasks == 0, "no task exists before the user accepts")
    pg.click('[data-ix="accept"] >> nth=0')
    pg.wait_for_timeout(300)
    check(pg.evaluate("window.__tasks.length") == 1 and pg.evaluate("window.__tasks[0].text").startswith("Revise"), "accept creates exactly one task")
    w = pg.evaluate("window.__writes")
    check(any(x["op"] == "update" and "recommendations/" in x["path"] and x["d"]["status"] == "accepted" for x in w), "accept writes status=accepted")
    check(all(set(x["d"]) <= {"status", "statusUpdatedAt"} for x in w if "recommendations/" in x["path"]), "only allowed keys written to recommendations")
    pg.click('[data-ix="dismiss"] >> nth=1'); pg.wait_for_timeout(300)
    check(pg.evaluate("window.__tasks.length") == 1, "dismiss creates no task")
    check(pg.locator(".ix-rec.done").count() == 1, "dismissed card is visually resolved")

    pg.click('[data-ix="tab"][data-id="rhythm"]'); pg.wait_for_timeout(200)
    check(pg.locator(".ix-hm-cell").count() == 7 * 24, "heatmap has 168 cells")
    check(pg.locator(".ix-grid").count() == 1 and "Model estimate" in pg.inner_text(".ix-block >> nth=5"), "model grid labelled as an estimate")
    check("Predicted" in pg.inner_text("#ixRoot") and "Observed" in pg.inner_text("#ixRoot"), "observed vs predicted both labelled")

    pg.click('[data-ix="tab"][data-id="learning"]'); pg.wait_for_timeout(200)
    names = [t.strip() for t in pg.locator(".ix-chip").all_inner_texts()]
    check(not any(n.lower().startswith(("b ", "img")) for n in names), f"markup did not become topics: {names}")
    pg.click('.ix-chip:has-text("Backpropagation") >> nth=0'); pg.wait_for_timeout(600)
    panel = pg.inner_text(".ix-panel")
    check("your own words" in panel.lower() and "confus" in panel.lower(), "evidence shows the user's own sentences")
    pg.click('[data-ix="rate"][data-r="3"]'); pg.wait_for_timeout(300)
    check(any(x["op"] == "add" and x["path"].endswith("/reviews") and x["d"]["rating"] == 3 and x["d"]["topicId"] == "backpropagation"
              for x in pg.evaluate("window.__writes")), "recall rating written to reviews")
    check(pg.evaluate("window.__xss") is None and pg.locator("#ixRoot img").count() == 0, "no script/markup injected from reflections")

    pg2 = open_page(b, block_api=True)
    pg2.wait_for_selector(".ix-empty", timeout=30000)
    t = pg2.inner_text(".ix-empty")
    check("isn’t running" in t and "uvicorn" in t, "unreachable backend shows setup instructions")

    pg3 = open_page(b, 390, 844, "dark")
    pg3.wait_for_selector(".ix-rec", timeout=90000)
    check(not pg3.evaluate("document.documentElement.scrollWidth > window.innerWidth"), "no horizontal overflow on mobile (dark)")
    pg3.screenshot(path="/tmp/shots/mobile_dark.png", full_page=True)
    b.close()

print(f"{ok} checks passed")
for e in errors:
    print("FAIL:", e)
sys.exit(1 if errors else 0)

// Behaviour test for the Timer/Sessions/UI data-capture code in app.js.
// Run: node tests/frontend/capture.test.mjs   (needs Node 18+, no dependencies)
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url));
let src = fs.readFileSync(path.join(here, '../../app.js'), 'utf8');
src = src.replace(/^import .*$/gm, '')                       // Firebase CDN imports are stubbed below
         .replace("document.addEventListener('DOMContentLoaded'", "(()=>{})||document.addEventListener('DOMContentLoaded'")
         + '\nwindow.__State = State;\n';
const tmp = path.join(os.tmpdir(), `focusforge_app_${process.pid}.mjs`);
fs.writeFileSync(tmp, src);
const writes = [];
const els = new Proxy({}, { get: (t, id) => (t[id] ??= {
  value: '', textContent: '', style: {}, dataset: {},
  classList: { add(){}, remove(){}, toggle(){}, contains: () => false },
  querySelector: () => ({ classList: { toggle(){}, add(){}, remove(){} } }),
  querySelectorAll: () => [], addEventListener(){},
}) });
globalThis.window = globalThis;
globalThis.document = {
  getElementById: id => els[id], querySelectorAll: () => [], addEventListener(){},
  documentElement: { setAttribute(){} },
};
globalThis.scrollTo = () => {};
const fb = {
  initializeApp: () => ({}), getAuth: () => ({}), getFirestore: () => ({}),
  collection: (_d, ...p) => p.join('/'), doc: (_d, ...p) => p.join('/'),
  addDoc: async (col, data) => { writes.push({ op: 'add', col, data }); return { id: 'id' + writes.length }; },
  updateDoc: async (ref, data) => { writes.push({ op: 'update', ref, data }); },
};
// stub the stripped firebase imports as globals
Object.assign(globalThis, fb, { query: x => x, orderBy: () => 0, getDocs: async () => ({ docs: [] }),
  getDoc: async () => ({ exists: () => false }), setDoc: async () => {}, deleteDoc: async () => {},
  where: () => 0, limit: () => 0, signOut: async () => {}, onAuthStateChanged(){}, getRedirectResult: async () => null,
  GoogleAuthProvider: class {}, signInWithPopup: async () => {}, signInWithRedirect: async () => {},
  createUserWithEmailAndPassword: async () => {}, signInWithEmailAndPassword: async () => {} });
await import(tmp);
const { Timer, Sessions, UI } = window; const State = window.__State;
State.user = { uid: 'u1', name: 'T' };

let now = 1_700_000_000_000; const realNow = Date.now; Date.now = () => now;

// 1. abandon after 10 minutes -> recorded as abandoned with ~10 min
Timer.setMode('pomodoro'); Timer.start(); now += 10 * 60000; Timer.reset();
await new Promise(r => setTimeout(r, 5));
let w = writes.at(-1);
assert.equal(w.data.status, 'abandoned'); assert.equal(w.data.plannedDuration, 25);
assert.equal(Math.round(w.data.actualDuration), 10); assert.equal(w.data.type, 'pomodoro');
assert.ok(w.data.startedAt && w.data.tz);
assert.equal(State.abandonedAttempts.length, 1); assert.equal(State.sessions.length, 0);

// 2. accidental tap (<1 min) is NOT recorded
const n = writes.length; Timer.start(); now += 20000; Timer.reset();
await new Promise(r => setTimeout(r, 5)); assert.equal(writes.length, n);

// 3. pause then resume counts wall-clock focus across pauses
Timer.start(); now += 5 * 60000; Timer.stop(); now += 30 * 60000; Timer.start(); now += 5 * 60000; Timer.reset();
await new Promise(r => setTimeout(r, 5));
assert.equal(Math.round(writes.at(-1).data.actualDuration), 10);   // 5+5, pause excluded

// 4. breaks never create abandoned records
const m = writes.length; Timer.setMode('short'); Timer.start(); now += 120000; Timer.reset();
await new Promise(r => setTimeout(r, 5)); assert.equal(writes.length, m);

// 5. completion writes the new fields, keeps legacy fields, and is NOT counted as abandoned
Timer.setMode('pomodoro'); Timer.start(); now += 25 * 60000; State.timer.seconds = 0; Timer.complete();
await new Promise(r => setTimeout(r, 5));
w = writes.at(-1);
assert.equal(w.data.status, 'completed'); assert.equal(w.data.duration, 25);
assert.equal(w.data.plannedDuration, 25); assert.ok(w.data.startedAt && w.data.endedAt);
assert.equal(State.sessions.length, 1);
assert.equal(State.timer.attemptStart, null);

// 6. reflection saved onto the session; empty reflection writes nothing
els.reflectNotes.value = 'Confused about backprop'; UI._reflectConfidence = 2;
els.completionOverlay.classList.contains = () => false;
await UI.hideCompletion();
w = writes.at(-1);
assert.equal(w.op, 'update'); assert.deepEqual(w.data, { notes: 'Confused about backprop', confidence: 2 });
const before = writes.length;
UI.showCompletion('x', 'y', { reflectFor: Promise.resolve({ id: 'zz' }) });
els.reflectNotes.value = ''; UI._reflectConfidence = null;
await UI.hideCompletion(); assert.equal(writes.length, before);

// 7. Firestore never receives undefined values
for (const x of writes) for (const [k, v] of Object.entries(x.data)) assert.notEqual(v, undefined, k);
console.log('FRONTEND HARNESS: all assertions passed', writes.length, 'writes');

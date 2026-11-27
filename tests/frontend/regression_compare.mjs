// Side-by-side regression check of the EXISTING app logic: main vs this branch.
//   git show origin/main:app.js > /tmp/app_main.js
//   node tests/frontend/regression_compare.mjs /tmp/app_main.js ./app.js
// Loads each app.js with Firebase stubbed, feeds identical legacy Firestore data (the branch also gets
// extra 'abandoned' attempt documents, which must not change any existing aggregate), calls every
// zero-argument synchronous function of the existing modules and compares the JSON results.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';

const [mainPath, branchPath] = process.argv.slice(2);
const NOW = Date.UTC(2026, 10, 20, 12, 0, 0);

function iso(daysAgo, hour = 10) { return new Date(NOW - daysAgo * 86400000 + (hour - 12) * 3600000).toISOString(); }
const LEGACY_SESSIONS = Array.from({ length: 40 }, (_, i) => ({
  id: 's' + i, subject: ['Maths — Calculus', 'CS', 'Biology'][i % 3], duration: [25, 30, 50][i % 3],
  notes: i % 4 ? '' : 'confused about limits', date: iso(Math.floor(i / 2), 8 + (i % 10)), type: i % 5 ? 'pomodoro' : 'manual',
}));
const ABANDONED = Array.from({ length: 8 }, (_, i) => ({
  id: 'ab' + i, subject: 'CS', duration: 7, notes: '', date: iso(i, 9), type: 'pomodoro', status: 'abandoned',
  plannedDuration: 25, actualDuration: 7, startedAt: iso(i, 9), endedAt: iso(i, 9), tz: 'UTC',
}));
const TASKS = [{ id: 't1', text: 'a', completed: true, date: new Date(NOW).toDateString() },
               { id: 't2', text: 'b', completed: false, date: new Date(NOW).toDateString() },
               { id: 't3', text: 'c', completed: true, date: new Date(NOW - 86400000).toDateString() }];

async function run(file, withAbandoned) {
  let src = fs.readFileSync(file, 'utf8');
  src = src.replace(/^import .*$/gm, '')
           .replace("document.addEventListener('DOMContentLoaded'", "(()=>{})||document.addEventListener('DOMContentLoaded'")
           + '\nwindow.__State = State;\n';
  const tmp = path.join(os.tmpdir(), `ff_cmp_${process.pid}_${Math.random().toString(36).slice(2)}.mjs`);
  fs.writeFileSync(tmp, src);
  const writes = [];
  const mk = () => new Proxy({}, { get: (t, id) => (t[id] ??= {
    value: '', textContent: '', innerHTML: '', style: {}, dataset: {}, children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => ({ classList: { toggle() {}, add() {}, remove() {} }, style: {} }),
    querySelectorAll: () => [], addEventListener() {}, appendChild() {}, setAttribute() {},
  }) });
  const els = mk();
  const g = globalThis;
  g.window = g; g.document = { getElementById: id => els[id], querySelectorAll: () => [], addEventListener() {},
    documentElement: { setAttribute() {} }, createElement: () => mk()['x'], body: { appendChild() {} } };
  g.scrollTo = () => {}; g.localStorage = { getItem: () => null, setItem() {} };
  const snap = rows => ({ docs: rows.map(r => ({ id: r.id, data: () => { const { id, ...d } = r; return d; } })) });
  Object.assign(g, {
    initializeApp: () => ({}), getAuth: () => ({}), getFirestore: () => ({}),
    collection: (_d, ...p) => p.join('/'), doc: (_d, ...p) => p.join('/'),
    query: x => x, orderBy: () => 0, where: () => 0, limit: () => 0,
    getDocs: async c => String(c).endsWith('sessions') ? snap([...LEGACY_SESSIONS, ...(withAbandoned ? ABANDONED : [])])
                       : String(c).endsWith('tasks') ? snap(TASKS) : snap([]),
    getDoc: async () => ({ exists: () => false }),
    addDoc: async (col, data) => { writes.push({ col, data }); return { id: 'new' + writes.length }; },
    setDoc: async () => {}, updateDoc: async () => {}, deleteDoc: async () => {}, signOut: async () => {},
    onAuthStateChanged() {}, getRedirectResult: async () => null, GoogleAuthProvider: class {},
    signInWithPopup: async () => {}, signInWithRedirect: async () => {},
    createUserWithEmailAndPassword: async () => {}, signInWithEmailAndPassword: async () => {},
  });
  if (!g.__RealDate) g.__RealDate = Date;
  g.Date = class extends g.__RealDate { constructor(...a) { a.length ? super(...a) : super(NOW); } static now() { return NOW; } };
  await import(tmp + '?' + Math.random());
  const State = g.__State; State.user = { uid: 'u1', name: 'T' };
  await g.DB?.loadAll?.call(g.DB) ?? null;
  const out = { counts: { sessions: State.sessions.length, tasks: State.tasks.length } };
  for (const name of ['Sessions', 'Utils', 'TaskManager', 'ConsistencyGarden', 'GrowthStages']) {
    const obj = g[name] ?? eval(`typeof ${name} !== 'undefined' ? ${name} : undefined`);
    if (!obj) { out[name] = 'not exposed'; continue; }
    out[name] = {};
    for (const k of Object.keys(obj)) {
      const f = obj[k];
      if (typeof f !== 'function' || f.length !== 0 || f.constructor.name === 'AsyncFunction') continue;
      try { out[name][k] = JSON.parse(JSON.stringify(f.call(obj) ?? null)); } catch (e) { out[name][k] = 'threw ' + e.message.slice(0, 40); }
    }
  }
  // legacy write shape
  writes.length = 0;
  await g.Sessions.add({ subject: 'Maths', duration: 25, notes: 'n', type: 'pomodoro' });
  await g.TaskManager.add('write essay');
  out.writes = writes.map(w => ({ col: w.col, keys: Object.keys(w.data).sort(), data: w.data }));
  out.afterAdd = State.sessions.length;
  return out;
}

const a = await run(mainPath, false);
const b = await run(branchPath, true);
// existing aggregates identical despite abandoned docs
const strip = o => JSON.parse(JSON.stringify(o, (k, v) => (k === 'data' || k === 'keys' ? undefined : v)));
assert.deepEqual(strip(b), strip(a), 'existing aggregates changed');
// legacy fields written identically; new fields are purely additive
const wa = a.writes[0].data, wb = b.writes[0].data;
for (const k of Object.keys(wa)) assert.deepEqual(wb[k], wa[k], 'legacy field changed: ' + k);
const extra = Object.keys(wb).filter(k => !(k in wa)).sort();
assert.deepEqual(a.writes[1].data, b.writes[1].data, 'task write changed');
console.log('REGRESSION COMPARE: identical aggregates for', Object.keys(a).filter(k => typeof a[k] === 'object').map(k => `${k}(${Object.keys(a[k]).length})`).join(' '));
console.log('session write: legacy keys identical; additive keys:', extra.join(', '));

// Firestore security-rules tests. STATUS: written but not yet executed by the author (the sandbox could not
// download the emulator). Run them yourself:   cd tests/rules && npm i && npx firebase emulators:exec --only firestore --project demo-focusforge "node --test rules.test.mjs"
// (Java 11+ is required by the emulator.) Every `deny` is a user trying to cross an account boundary or forge data.
import { test, before, after, beforeEach } from 'node:test';
import fs from 'node:fs';
import { initializeTestEnvironment, assertFails, assertSucceeds } from '@firebase/rules-unit-testing';
import { doc, getDoc, setDoc, updateDoc, deleteDoc, addDoc, collection, getDocs, collectionGroup, query } from 'firebase/firestore';

let env;
before(async () => {
  env = await initializeTestEnvironment({
    projectId: 'demo-focusforge',
    firestore: { rules: fs.readFileSync(new URL('../../firestore.rules', import.meta.url), 'utf8'), host: '127.0.0.1', port: 8080 },
  });
});
after(async () => env.cleanup());
beforeEach(async () => {
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async ctx => {
    const db = ctx.firestore();
    for (const u of ['alice', 'bob']) {
      await setDoc(doc(db, `users/${u}`), { name: u });
      await setDoc(doc(db, `users/${u}/sessions/s1`), { subject: 'X', duration: 25, date: '2026-11-01T10:00:00Z', type: 'manual' });
      await setDoc(doc(db, `users/${u}/tasks/t1`), { text: 'x', completed: false, date: 'Fri Nov 20 2026' });
      await setDoc(doc(db, `users/${u}/garden/g1`), { pct: 50 });
      await setDoc(doc(db, `users/${u}/analysis/rhythm`), { engine: 'rhythm' });
      await setDoc(doc(db, `users/${u}/topics/t`), { name: 'Recursion' });
      await setDoc(doc(db, `users/${u}/recommendations/r1`), { status: 'proposed', title: 'x', statusUpdatedAt: null });
      await setDoc(doc(db, `users/${u}/reviews/v1`), { topicId: 't', rating: 3, at: '2026-11-01T00:00:00Z' });
    }
  });
});

const as = uid => env.authenticatedContext(uid).firestore();
const COLS = ['sessions', 'tasks', 'garden', 'analysis', 'topics', 'recommendations', 'reviews'];
const DOC = { sessions: 's1', tasks: 't1', garden: 'g1', analysis: 'rhythm', topics: 't', recommendations: 'r1', reviews: 'v1' };

for (const col of COLS) {
  test(`bob cannot read, list, write or delete alice's ${col}`, async () => {
    const bob = as('bob'), ref = doc(bob, `users/alice/${col}/${DOC[col]}`);
    await assertFails(getDoc(ref));
    await assertFails(getDocs(collection(bob, `users/alice/${col}`)));
    await assertFails(setDoc(ref, { hacked: true }));
    await assertFails(updateDoc(ref, { hacked: true }));
    await assertFails(deleteDoc(ref));
    await assertFails(addDoc(collection(bob, `users/alice/${col}`), { rating: 3, topicId: 't', subject: 'x' }));
  });
  test(`unauthenticated users cannot touch ${col}`, async () => {
    const anon = env.unauthenticatedContext().firestore();
    await assertFails(getDoc(doc(anon, `users/alice/${col}/${DOC[col]}`)));
    await assertFails(setDoc(doc(anon, `users/alice/${col}/new`), { rating: 3, topicId: 't' }));
  });
  test(`alice can read her own ${col}`, async () => {
    await assertSucceeds(getDoc(doc(as('alice'), `users/alice/${col}/${DOC[col]}`)));
  });
}

test("bob cannot read alice's profile; each user can use their own", async () => {
  await assertFails(getDoc(doc(as('bob'), 'users/alice')));
  await assertSucceeds(getDoc(doc(as('alice'), 'users/alice')));
  await assertSucceeds(setDoc(doc(as('alice'), 'users/alice'), { name: 'A2' }));
});

test('collection-group queries cannot be used to read across accounts', async () => {
  for (const g of ['sessions', 'reviews', 'recommendations', 'topics'])
    await assertFails(getDocs(query(collectionGroup(as('bob'), g))));
});

test('unknown paths are denied', async () => {
  await assertFails(getDoc(doc(as('alice'), 'secrets/x')));
  await assertFails(setDoc(doc(as('alice'), 'users/alice/other/x'), { a: 1 }));
});

// ---- own-data behaviour -------------------------------------------------------------------------
test('sessions: legacy (no status), completed and abandoned are allowed; other statuses are not', async () => {
  const a = as('alice');
  await assertSucceeds(addDoc(collection(a, 'users/alice/sessions'), { subject: 'x', duration: 25, date: 'd', type: 'manual' }));
  await assertSucceeds(addDoc(collection(a, 'users/alice/sessions'), { subject: 'x', duration: 25, status: 'completed' }));
  await assertSucceeds(addDoc(collection(a, 'users/alice/sessions'), { subject: 'x', duration: 5, status: 'abandoned' }));
  await assertFails(addDoc(collection(a, 'users/alice/sessions'), { subject: 'x', duration: 25, status: 'hacked' }));
  await assertSucceeds(updateDoc(doc(a, 'users/alice/sessions/s1'), { notes: 'reflection', confidence: 2 }));
  await assertSucceeds(deleteDoc(doc(a, 'users/alice/sessions/s1')));
});

test('analysis and topics are server-written only', async () => {
  const a = as('alice');
  await assertFails(setDoc(doc(a, 'users/alice/analysis/rhythm'), { forged: true }));
  await assertFails(setDoc(doc(a, 'users/alice/topics/new'), { name: 'forged' }));
  await assertFails(deleteDoc(doc(a, 'users/alice/topics/t')));
});

test('recommendations: only status/statusUpdatedAt may change, with a valid status; no create or delete', async () => {
  const a = as('alice'), r = doc(a, 'users/alice/recommendations/r1');
  await assertSucceeds(updateDoc(r, { status: 'accepted', statusUpdatedAt: 'now' }));
  await assertFails(updateDoc(r, { status: 'bogus' }));
  await assertFails(updateDoc(r, { status: 'accepted', title: 'rewritten' }));
  await assertFails(updateDoc(r, { title: 'rewritten' }));
  await assertFails(setDoc(doc(a, 'users/alice/recommendations/new'), { status: 'proposed' }));
  await assertFails(deleteDoc(r));
});

test('reviews: create with rating 1-4 and a topicId; immutable afterwards', async () => {
  const a = as('alice'), col = collection(a, 'users/alice/reviews');
  for (const rating of [1, 2, 3, 4]) await assertSucceeds(addDoc(col, { topicId: 't', rating, at: 'x' }));
  await assertFails(addDoc(col, { topicId: 't', rating: 0, at: 'x' }));
  await assertFails(addDoc(col, { topicId: 't', rating: 5, at: 'x' }));
  await assertFails(addDoc(col, { topicId: 't', rating: '3', at: 'x' }));
  await assertFails(addDoc(col, { rating: 3, at: 'x' }));
  await assertFails(addDoc(col, { topicId: 7, rating: 3 }));
  await assertFails(updateDoc(doc(a, 'users/alice/reviews/v1'), { rating: 4 }));
  await assertFails(deleteDoc(doc(a, 'users/alice/reviews/v1')));
});

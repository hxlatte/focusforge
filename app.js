/* =============================================
   FOCUSFORGE — APP.JS
   Modular, clean JavaScript
   Firebase-ready architecture
============================================= */

'use strict';

/* ─── FIREBASE CONFIG PLACEHOLDER ───────────
   Replace with your Firebase project config.
   Instructions:
   1. Go to console.firebase.google.com
   2. Create a project → Add web app
   3. Copy the firebaseConfig object below
   4. Uncomment the Firebase SDK imports
   5. Replace auth/db helpers with real Firebase calls
─────────────────────────────────────────── */
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-app.js";
import { getAuth, createUserWithEmailAndPassword, signInWithEmailAndPassword, signOut, onAuthStateChanged, GoogleAuthProvider, signInWithPopup, signInWithRedirect, getRedirectResult } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js";
import { getFirestore, doc, setDoc, getDoc, updateDoc, collection, addDoc, query, where, getDocs, deleteDoc, orderBy, limit } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";

const firebaseConfig = {
  apiKey: "AIzaSyDFx-k7WXm1bLcjg5uHrTIIRK-Hvu-IYnE",
  authDomain: "focusforge-3a4f7.firebaseapp.com",
  projectId: "focusforge-3a4f7",
  storageBucket: "focusforge-3a4f7.firebasestorage.app",
  messagingSenderId: "619063330554",
  appId: "1:619063330554:web:c6a1b53a5c8aa828a16b43",
  measurementId: "G-T175C74RRP"
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);

/* =============================================
   STATE
============================================= */
const State = {
  user: null,
  sessions: [],       // { id, subject, duration, notes, date, type }
  tasks: [],          // { id, text, completed, date }
  gardenHistory: [],  // { date, pct, stage, taskCount, completedCount }
  settings: {
    pomodoroLength: 25,
    shortBreak: 5,
    longBreak: 15,
    theme: 'light',
  },
  timer: {
    interval: null,
    running: false,
    seconds: 25 * 60,
    mode: 'pomodoro',   // 'pomodoro' | 'short' | 'long'
    pomodorosCompleted: 0,
  },
};

/* =============================================
   DB & FIRESTORE SYNC
   Scopes all data by user.uid
============================================= */
const DB = {
  async saveUser(user) {
    if (!user) return;
    await setDoc(doc(db, 'users', user.uid), {
      name: user.name,
      email: user.email,
      createdAt: user.createdAt || new Date().toISOString(),
      lastLogin: new Date().toISOString(),
    }, { merge: true });
  },

  async loadAll() {
    if (!State.user) return;
    const uid = State.user.uid;

    // Load Sessions
    const sSnap = await getDocs(query(collection(db, 'users', uid, 'sessions'), orderBy('date', 'desc')));
    State.sessions = sSnap.docs.map(d => ({ id: d.id, ...d.data() }));

    // Load Tasks
    const tSnap = await getDocs(collection(db, 'users', uid, 'tasks'));
    State.tasks = tSnap.docs.map(d => ({ id: d.id, ...d.data() }));

    // Load Garden
    const gSnap = await getDocs(query(collection(db, 'users', uid, 'garden'), orderBy('date', 'desc')));
    State.gardenHistory = gSnap.docs.map(d => ({ id: d.id, ...d.data() }));

    // Load Settings
    const uDoc = await getDoc(doc(db, 'users', uid));
    if (uDoc.exists() && uDoc.data().settings) {
      State.settings = { ...State.settings, ...uDoc.data().settings };
    }
  },

  async persistSettings() {
    if (!State.user) return;
    await updateDoc(doc(db, 'users', State.user.uid), {
      settings: State.settings
    });
  }
};

/* ─── AUTH HELPERS (Real Firebase) ── */
const Auth = {
  async signup(name, email, password) {
    const cred = await createUserWithEmailAndPassword(auth, email, password);
    const user = {
      uid: cred.user.uid,
      name,
      email,
      createdAt: new Date().toISOString(),
    };
    State.user = user;
    // Save to Firestore (non-blocking — auth still succeeds if DB fails)
    try {
      await DB.saveUser(user);
      await DB.loadAll();
    } catch (e) {
      console.warn('Firestore write failed after signup (rules may not be published yet):', e.message);
    }
    UI.setAuthNav();
    Nav.go('dashboard');
    return user;
  },

  async login(email, password) {
    const cred = await signInWithEmailAndPassword(auth, email, password);
    State.user = {
      uid: cred.user.uid,
      name: cred.user.displayName || email.split('@')[0],
      email: cred.user.email,
    };
    // Load Firestore data (non-blocking)
    try {
      const uDoc = await getDoc(doc(db, 'users', cred.user.uid));
      if (uDoc.exists()) {
        State.user = { uid: cred.user.uid, ...uDoc.data() };
      }
      await DB.loadAll();
    } catch (e) {
      console.warn('Firestore read failed after login:', e.message);
    }
    UI.setAuthNav();
    Nav.go('dashboard');
    return State.user;
  },

  async googleSignIn() {
    const provider = new GoogleAuthProvider();
    let cred;
    try {
      // Try popup first
      cred = await signInWithPopup(auth, provider);
    } catch (popupErr) {
      // If popup blocked or failed, fall back to redirect
      if (popupErr.code === 'auth/popup-blocked' ||
        popupErr.code === 'auth/popup-closed-by-user' ||
        popupErr.code === 'auth/cancelled-popup-request') {
        await signInWithRedirect(auth, provider);
        return; // Page will redirect and come back
      }
      throw popupErr; // Re-throw other errors
    }

    State.user = {
      uid: cred.user.uid,
      name: cred.user.displayName || 'User',
      email: cred.user.email,
      createdAt: new Date().toISOString(),
    };

    // Save/load Firestore (non-blocking)
    try {
      const uDoc = await getDoc(doc(db, 'users', cred.user.uid));
      if (!uDoc.exists()) {
        await DB.saveUser(State.user);
      } else {
        State.user = { uid: cred.user.uid, ...uDoc.data() };
      }
      await DB.loadAll();
    } catch (e) {
      console.warn('Firestore failed after Google sign-in:', e.message);
    }
    UI.setAuthNav();
    Nav.go('dashboard');
  },

  async logout() {
    await signOut(auth);
    State.user = null;
    State.sessions = [];
    State.tasks = [];
    State.gardenHistory = [];
    UI.setAuthNav();
    Nav.go('home');
  },

  isLoggedIn() { return !!State.user; },

  init() {
    // Handle redirect result (for Google redirect fallback)
    getRedirectResult(auth).then(result => {
      if (result && result.user) {
        State.user = {
          uid: result.user.uid,
          name: result.user.displayName || 'User',
          email: result.user.email,
          createdAt: new Date().toISOString(),
        };
        UI.setAuthNav();
        Nav.go('dashboard');
      }
    }).catch(e => console.warn('Redirect result error:', e.message));

    onAuthStateChanged(auth, async (user) => {
      if (user) {
        // Build basic user from auth (always works)
        State.user = {
          uid: user.uid,
          name: user.displayName || user.email?.split('@')[0] || 'User',
          email: user.email,
        };
        // Try to enrich from Firestore (may fail if rules not set)
        try {
          const uDoc = await getDoc(doc(db, 'users', user.uid));
          if (uDoc.exists()) {
            State.user = { uid: user.uid, ...uDoc.data() };
          }
          await DB.loadAll();
        } catch (e) {
          console.warn('Firestore read failed in auth state change:', e.message);
        }
        UI.setAuthNav();
        if (Nav.currentPage === 'home') Nav.go('dashboard');
        else Nav.go(Nav.currentPage);
      } else {
        State.user = null;
        UI.setAuthNav();
        Nav.go('home');
      }
    });
  }
};

/* ─── SESSION HELPERS ───────────────────── */
const Sessions = {
  async add(session) {
    if (!State.user) return;
    const data = {
      subject: session.subject || 'General',
      duration: Math.max(1, parseInt(session.duration) || 25),
      notes: session.notes || '',
      date: session.date || new Date().toISOString(),
      type: session.type || 'manual',
    };
    const docRef = await addDoc(collection(db, 'users', State.user.uid, 'sessions'), data);
    State.sessions.unshift({ id: docRef.id, ...data });
  },

  async remove(id) {
    if (!State.user) return;
    await deleteDoc(doc(db, 'users', State.user.uid, 'sessions', id));
    State.sessions = State.sessions.filter(s => s.id !== id);
  },

  today() {
    const today = new Date().toDateString();
    return State.sessions.filter(s => new Date(s.date).toDateString() === today);
  },

  totalMinutesToday() {
    return this.today().reduce((acc, s) => acc + s.duration, 0);
  },

  totalMinutesWeek() {
    const now = new Date();
    const weekAgo = new Date(now - 7 * 86400000);
    return State.sessions
      .filter(s => new Date(s.date) >= weekAgo)
      .reduce((acc, s) => acc + s.duration, 0);
  },

  streak() {
    if (!State.sessions.length) return 0;
    const days = new Set(State.sessions.map(s => new Date(s.date).toDateString()));
    let streak = 0;
    const now = new Date();
    for (let i = 0; i < 365; i++) {
      const d = new Date(now - i * 86400000).toDateString();
      if (days.has(d)) streak++;
      else if (i > 0) break;
    }
    return streak;
  },

  last3Days() {
    const result = [];
    for (let i = 2; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const dayStr = d.toDateString();
      const daySessions = State.sessions.filter(s => new Date(s.date).toDateString() === dayStr);
      result.push({
        label: i === 0 ? 'Today' : i === 1 ? 'Yesterday' : d.toLocaleDateString('en', { weekday: 'long' }),
        minutes: daySessions.reduce((a, s) => a + s.duration, 0),
        count: daySessions.length,
      });
    }
    return result;
  },

  weeklyData() {
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    const now = new Date();
    const dayOfWeek = now.getDay(); // 0=Sun
    const startOfWeek = new Date(now - ((dayOfWeek === 0 ? 6 : dayOfWeek - 1) * 86400000));
    startOfWeek.setHours(0, 0, 0, 0);

    return days.map((label, i) => {
      const day = new Date(startOfWeek);
      day.setDate(startOfWeek.getDate() + i);
      const dayStr = day.toDateString();
      const mins = State.sessions
        .filter(s => new Date(s.date).toDateString() === dayStr)
        .reduce((a, s) => a + s.duration, 0);
      const isToday = dayStr === now.toDateString();
      return { label, mins, isToday };
    });
  },

  subjectBreakdown() {
    const map = {};
    State.sessions.forEach(s => {
      const key = s.subject.split('—')[0].trim();
      map[key] = (map[key] || 0) + s.duration;
    });
    const total = Object.values(map).reduce((a, b) => a + b, 0) || 1;
    return Object.entries(map)
      .sort((a, b) => b[1] - a[1])
      .map(([subject, minutes], i) => ({
        subject,
        minutes,
        pct: Math.round((minutes / total) * 100),
        color: COLORS[i % COLORS.length],
      }));
  },
};

/* ─── COLORS FOR SUBJECTS ───────────────── */
const COLORS = [
  'var(--lavender)', 'var(--peach)', 'var(--sage)',
  'var(--rose)', 'var(--blue-pale)', 'var(--accent)',
];

/* ─── UTILS ─────────────────────────────── */
const Utils = {
  fmtMinutes(mins) {
    if (mins < 60) return `${mins}m`;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return m > 0 ? `${h}h ${m}m` : `${h}h`;
  },

  fmtTime(secs) {
    const m = Math.floor(secs / 60).toString().padStart(2, '0');
    const s = (secs % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  },

  fmtDate(iso) {
    return new Date(iso).toLocaleDateString('en', { weekday: 'short', month: 'short', day: 'numeric' });
  },

  getTimeOfDay() {
    const h = new Date().getHours();
    if (h < 12) return 'morning';
    if (h < 17) return 'afternoon';
    return 'evening';
  },

  initials(name) {
    return name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
  },

  toast(msg, duration = 2800) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), duration);
  },
};

/* ─── NAVIGATION ─────────────────────────── */
const Nav = {
  currentPage: 'home',

  init() {
    document.querySelectorAll('[data-page]').forEach(el => {
      el.addEventListener('click', () => this.go(el.dataset.page));
    });
  },

  go(page) {
    if (!Auth.isLoggedIn() && page !== 'home') {
      UI.openAuth();
      return;
    }

    // Hide all pages
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    // Show target
    const target = document.getElementById(`page-${page}`);
    if (target) target.classList.add('active');

    // Update nav links
    document.querySelectorAll('.nav-link').forEach(l => {
      l.classList.toggle('active', l.dataset.page === page);
    });

    this.currentPage = page;

    // Trigger page-specific render
    switch (page) {
      case 'dashboard': Dashboard.render(); break;
      case 'focus': FocusPage.render(); break;
      case 'garden': GardenPage.render(); break;
      case 'progress': ProgressPage.render(); break;
      case 'profile': ProfilePage.render(); break;
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
  },
};

/* ─── AUTH UI ────────────────────────────── */
const UI = {
  openAuth() { document.getElementById('authOverlay').classList.add('open'); },
  closeAuth() { document.getElementById('authOverlay').classList.remove('open'); },
  openLog() { document.getElementById('logOverlay').classList.add('open'); },
  closeLog() { document.getElementById('logOverlay').classList.remove('open'); },

  setAuthNav() {
    const loggedIn = Auth.isLoggedIn();
    const navLoginBtn = document.getElementById('navLoginBtn');
    const navGetStartedBtn = document.getElementById('navGetStartedBtn');

    if (loggedIn) {
      navLoginBtn.textContent = 'My account';
      navLoginBtn.onclick = () => Nav.go('profile');
      navGetStartedBtn.textContent = 'Dashboard';
      navGetStartedBtn.onclick = () => Nav.go('dashboard');
    } else {
      navLoginBtn.textContent = 'Sign in';
      navLoginBtn.onclick = () => this.openAuth();
      navGetStartedBtn.textContent = 'Get started';
      navGetStartedBtn.onclick = () => this.openAuth();
    }
  },

  showCompletion(title, sub) {
    const overlay = document.getElementById('completionOverlay');
    document.getElementById('completionTitle').textContent = title;
    document.getElementById('completionSub').textContent = sub;
    overlay.classList.remove('hidden');
  },

  hideCompletion() {
    document.getElementById('completionOverlay').classList.add('hidden');
  },
};

/* ─── THEME ──────────────────────────────── */
const Theme = {
  apply(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    State.settings.theme = theme;
    // Persist to Firestore if logged in
    if (State.user) {
      DB.persistSettings().catch(e => console.warn('Theme save failed:', e));
    }

    // Sync profile pills
    document.querySelectorAll('.theme-pill').forEach(p => {
      p.classList.toggle('active', p.dataset.themeVal === theme);
    });
  },

  toggle() {
    this.apply(State.settings.theme === 'light' ? 'dark' : 'light');
  },

  init() {
    this.apply(State.settings.theme);
    document.querySelectorAll('.theme-pill').forEach(p => {
      p.addEventListener('click', () => this.apply(p.dataset.themeVal));
    });
  },
};

/* ─── HERO DEMO TIMER ────────────────────── */
const HeroTimer = {
  seconds: 38 * 60 + 24,
  interval: null,

  start() {
    this.interval = setInterval(() => {
      this.seconds++;
      const el = document.getElementById('heroTimer');
      if (el) el.textContent = Utils.fmtTime(this.seconds);
    }, 1000);
  },
};

/* ─── DASHBOARD ──────────────────────────── */
const Dashboard = {
  render() {
    this.renderWelcome();
    this.renderStats();
    this.renderRecentSessions();
    this.renderWeekChart();
    this.renderLast3Days();
    GardenDash.render();
    // Wire dashboard garden button
    document.querySelectorAll('[data-page="garden"]').forEach(el => {
      el.onclick = () => Nav.go('garden');
    });
  },

  renderWelcome() {
    const el = document.getElementById('timeOfDay');
    if (el) el.textContent = Utils.getTimeOfDay();
    const nameEl = document.getElementById('welcomeName');
    if (nameEl && State.user) {
      nameEl.textContent = State.user.name.split(' ')[0];
    }
  },

  renderStats() {
    const todayMins = Sessions.totalMinutesToday();
    const weekMins = Sessions.totalMinutesWeek();
    const streak = Sessions.streak();
    const count = State.sessions.length;

    this._set('statToday', Utils.fmtMinutes(todayMins));
    this._set('statWeek', Utils.fmtMinutes(weekMins));
    this._set('statStreak', streak);
    this._set('statSessions', count);
    this._set('statStreakNote', streak === 1 ? 'day' : 'days');
    this._set('statWeekNote', 'last 7 days');
    this._set('statSessionsNote', 'total');

    const todayTrend = document.getElementById('statTodayTrend');
    if (todayTrend) {
      todayTrend.textContent = todayMins > 0 ? `+${Utils.fmtMinutes(todayMins)}` : '—';
      todayTrend.classList.toggle('positive', todayMins > 0);
    }
  },

  renderRecentSessions() {
    const el = document.getElementById('dashRecentList');
    if (!el) return;

    const recent = State.sessions.slice(0, 6);
    if (!recent.length) {
      el.innerHTML = `<div class="empty-state">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.3"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        <p>No sessions yet.<br/>Start your first focus session.</p>
      </div>`;
      return;
    }

    el.innerHTML = recent.map((s, i) => `
      <div class="session-item">
        <div class="session-pip" style="background:${COLORS[i % COLORS.length]}"></div>
        <div class="session-info">
          <div class="session-name">${s.subject}</div>
          <div class="session-meta">${Utils.fmtDate(s.date)}</div>
        </div>
        <div class="session-dur">${Utils.fmtMinutes(s.duration)}</div>
      </div>
    `).join('');
  },

  renderWeekChart() {
    const barsEl = document.getElementById('weekBars');
    const labelsEl = document.getElementById('weekLabels');
    const subjEl = document.getElementById('weekSubjects');
    if (!barsEl) return;

    const data = Sessions.weeklyData();
    const max = Math.max(...data.map(d => d.mins), 1);

    barsEl.innerHTML = data.map(d => `
      <div class="week-bar-wrap">
        <div class="week-bar ${d.isToday ? 'today' : ''}"
             style="height:${Math.max(4, (d.mins / max) * 100)}%"
             title="${d.label}: ${Utils.fmtMinutes(d.mins)}">
        </div>
      </div>
    `).join('');

    if (labelsEl) {
      labelsEl.innerHTML = data.map(d => `
        <span class="week-lbl ${d.isToday ? 'today' : ''}">${d.label}</span>
      `).join('');
    }

    if (subjEl) {
      const breakdown = Sessions.subjectBreakdown().slice(0, 4);
      if (breakdown.length) {
        subjEl.innerHTML = breakdown.map(b => `
          <div class="ws-item">
            <div class="ws-dot" style="background:${b.color}"></div>
            <div class="ws-label">${b.subject}</div>
            <div class="ws-time">${Utils.fmtMinutes(b.minutes)}</div>
          </div>
        `).join('');
      } else {
        subjEl.innerHTML = '';
      }
    }
  },

  renderLast3Days() {
    const el = document.getElementById('daysGrid');
    if (!el) return;

    const days = Sessions.last3Days();
    const maxMins = Math.max(...days.map(d => d.minutes), 60);

    el.innerHTML = days.map(d => `
      <div class="day-card">
        <div class="day-label">${d.label}</div>
        <div class="day-time">${Utils.fmtMinutes(d.minutes)}</div>
        <div class="day-sessions">${d.count} session${d.count !== 1 ? 's' : ''}</div>
        <div class="day-bar-track">
          <div class="day-bar-fill" style="width:${Math.round((d.minutes / maxMins) * 100)}%"></div>
        </div>
      </div>
    `).join('');
  },

  _set(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  },
};

/* ─── FOCUS TIMER ────────────────────────── */
const Timer = {
  MODES: {
    pomodoro: () => State.settings.pomodoroLength * 60,
    short: () => State.settings.shortBreak * 60,
    long: () => State.settings.longBreak * 60,
  },
  CIRCUMFERENCE: 2 * Math.PI * 96, // r=96 in SVG

  init() {
    this.setMode('pomodoro');
    this.updateDots();
    // Listeners now managed in global attachGlobalEventListeners
  },

  setMode(mode) {
    State.timer.mode = mode;
    State.timer.seconds = this.MODES[mode]?.() ?? 25 * 60;
    State.timer.running = false;
    this.updateDisplay();
    this.updateRing(0);
    this.updatePlayBtn(false);
    document.getElementById('timerPhase').textContent = 'Ready to ' + (mode === 'pomodoro' ? 'focus' : 'rest');
    Fullscreen.updatePhase();
  },

  toggle() {
    if (State.timer.running) this.stop();
    else this.start();
  },

  start() {
    if (State.timer.running) return;
    State.timer.running = true;
    this.updatePlayBtn(true);
    document.getElementById('timerPhase').textContent =
      State.timer.mode === 'pomodoro' ? 'Stay focused...' : 'Rest well...';
    Fullscreen.updatePhase();

    State.timer.interval = setInterval(() => {
      State.timer.seconds--;
      this.updateDisplay();
      const total = this.MODES[State.timer.mode]();
      this.updateRing((total - State.timer.seconds) / total);

      if (State.timer.seconds <= 0) {
        this.complete();
      }
    }, 1000);
  },

  stop() {
    clearInterval(State.timer.interval);
    State.timer.running = false;
    this.updatePlayBtn(false);
  },

  reset() {
    this.stop();
    this.setMode(State.timer.mode);
  },

  complete() {
    this.stop();
    this.updateRing(1);

    if (State.timer.mode === 'pomodoro') {
      State.timer.pomodorosCompleted = (State.timer.pomodorosCompleted % 4) + 1;
      this.updateDots();

      // Auto-log the session
      const subject = document.getElementById('focusSubject')?.value?.trim() || 'Focus Session';
      Sessions.add({
        subject,
        duration: State.settings.pomodoroLength,
        type: 'pomodoro',
        notes: '',
      });

      FocusPage.renderTodaySessions();
      UI.showCompletion('Session complete', `Great work on "${subject}". Take a moment to breathe.`);
    } else {
      UI.showCompletion('Break complete', 'Ready to focus again? Start when you feel settled.');
    }

    // Switch mode
    if (State.timer.mode === 'pomodoro') {
      const nextMode = State.timer.pomodorosCompleted % 4 === 0 ? 'long' : 'short';
      this.setMode(nextMode);
      document.querySelectorAll('.focus-mode-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === nextMode);
      });
    } else {
      this.setMode('pomodoro');
      document.querySelectorAll('.focus-mode-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === 'pomodoro');
      });
    }
  },

  updateDisplay() {
    const t = Utils.fmtTime(State.timer.seconds);
    const disp = document.getElementById('timerDisplay');
    const fsDisp = document.getElementById('fsTime');
    if (disp) disp.textContent = t;
    if (fsDisp) fsDisp.textContent = t;
  },

  updateRing(progress) {
    const ring = document.getElementById('timerRing');
    if (!ring) return;
    const offset = this.CIRCUMFERENCE * (1 - Math.min(progress, 1));
    ring.style.strokeDasharray = this.CIRCUMFERENCE;
    ring.style.strokeDashoffset = offset;
  },

  updatePlayBtn(playing) {
    [document.getElementById('timerPlay'), document.getElementById('fsPlay')].forEach(btn => {
      if (!btn) return;
      btn.querySelector('.play-icon')?.classList.toggle('hidden', playing);
      btn.querySelector('.pause-icon')?.classList.toggle('hidden', !playing);
    });
  },

  updateDots() {
    for (let i = 1; i <= 4; i++) {
      const dot = document.getElementById(`dot${i}`);
      if (!dot) continue;
      dot.classList.remove('active', 'done');
      if (i < State.timer.pomodorosCompleted) dot.classList.add('done');
      if (i === State.timer.pomodorosCompleted || (State.timer.pomodorosCompleted === 0 && i === 1)) {
        dot.classList.add('active');
      }
    }
  },
};

/* ─── FULLSCREEN ─────────────────────────── */
const Fullscreen = {
  open() {
    const el = document.getElementById('fullscreenOverlay');
    el?.classList.remove('hidden');
    this.updatePhase();
    this.updateSubject();
  },

  close() {
    document.getElementById('fullscreenOverlay')?.classList.add('hidden');
  },

  updatePhase() {
    const el = document.getElementById('fsPhase');
    if (!el) return;
    const phases = { pomodoro: 'Focus', short: 'Short Break', long: 'Long Break' };
    el.textContent = phases[State.timer.mode] || 'Focus';
  },

  updateSubject() {
    const subj = document.getElementById('focusSubject')?.value?.trim();
    const el = document.getElementById('fsSubject');
    if (el) el.textContent = subj || '';
  },
};

/* ─── FOCUS PAGE ─────────────────────────── */
const FocusPage = {
  render() {
    this.renderTodaySessions();
    Timer.updateDisplay();
  },

  renderTodaySessions() {
    const el = document.getElementById('focusTodaySessions');
    if (!el) return;
    const today = Sessions.today();
    if (!today.length) {
      el.innerHTML = '<p class="aside-empty">No sessions yet today.</p>';
      return;
    }
    el.innerHTML = today.map(s => `
      <div class="aside-session-item">
        <div style="width:6px;height:6px;border-radius:50%;background:var(--lavender);flex-shrink:0"></div>
        <span>${s.subject}</span>
        <span class="dur">${Utils.fmtMinutes(s.duration)}</span>
      </div>
    `).join('');
  },
};

/* ─── PROGRESS PAGE ──────────────────────── */
const ProgressPage = {
  render() {
    this.renderSummary();
    this.renderWeekChart();
    this.renderSubjectBreakdown();
    this.renderAllLogs();
  },

  renderSummary() {
    const el = document.getElementById('progressSummary');
    if (!el) return;

    const todayMins = Sessions.totalMinutesToday();
    const weekMins = Sessions.totalMinutesWeek();
    const streak = Sessions.streak();

    el.innerHTML = `
      <div class="summary-card">
        <div class="summary-card-label">Today</div>
        <div class="summary-card-val">${Utils.fmtMinutes(todayMins) || '—'}</div>
        <div class="summary-card-sub">${Sessions.today().length} sessions</div>
      </div>
      <div class="summary-card">
        <div class="summary-card-label">This week</div>
        <div class="summary-card-val">${Utils.fmtMinutes(weekMins) || '—'}</div>
        <div class="summary-card-sub">${State.sessions.filter(s => {
      return new Date(s.date) >= new Date(Date.now() - 7 * 86400000);
    }).length} sessions</div>
      </div>
      <div class="summary-card">
        <div class="summary-card-label">Current streak</div>
        <div class="summary-card-val">${streak} day${streak !== 1 ? 's' : ''}</div>
        <div class="summary-card-sub">Keep going</div>
      </div>
    `;
  },

  renderWeekChart() {
    const barsEl = document.getElementById('progressBars');
    const labelsEl = document.getElementById('progressLabels');
    const totalEl = document.getElementById('weekTotal');
    if (!barsEl) return;

    const data = Sessions.weeklyData();
    const max = Math.max(...data.map(d => d.mins), 60);
    const total = data.reduce((a, d) => a + d.mins, 0);

    if (totalEl) totalEl.textContent = `${Utils.fmtMinutes(total)} this week`;

    barsEl.innerHTML = data.map(d => `
      <div class="big-week-bar-wrap">
        <div class="big-week-bar-val">${d.mins > 0 ? Utils.fmtMinutes(d.mins) : ''}</div>
        <div class="big-week-bar ${d.isToday ? 'today' : ''}"
             style="height:${Math.max(4, (d.mins / max) * 100)}%"
             title="${d.label}: ${Utils.fmtMinutes(d.mins)}">
        </div>
      </div>
    `).join('');

    if (labelsEl) {
      labelsEl.innerHTML = data.map(d => `
        <span class="big-week-lbl ${d.isToday ? 'today' : ''}">${d.label}</span>
      `).join('');
    }
  },

  renderSubjectBreakdown() {
    const el = document.getElementById('subjectBlocks');
    if (!el) return;

    const breakdown = Sessions.subjectBreakdown();
    if (!breakdown.length) {
      el.innerHTML = '<p class="aside-empty">No data yet. Start logging sessions.</p>';
      return;
    }

    el.innerHTML = breakdown.map(b => `
      <div class="subject-block">
        <div class="subject-block-header">
          <div class="subject-block-name">${b.subject}</div>
          <div class="subject-block-time">${Utils.fmtMinutes(b.minutes)} · ${b.pct}%</div>
        </div>
        <div class="subject-block-bar">
          <div class="subject-block-fill" style="width:${b.pct}%;background:${b.color}"></div>
        </div>
      </div>
    `).join('');
  },

  renderAllLogs() {
    const el = document.getElementById('allLogList');
    if (!el) return;

    if (!State.sessions.length) {
      el.innerHTML = '<p class="aside-empty">No logs yet.</p>';
      return;
    }

    el.innerHTML = State.sessions.map((s, i) => `
      <div class="log-entry" data-id="${s.id}">
        <div class="log-entry-pip" style="background:${COLORS[i % COLORS.length]}"></div>
        <div class="log-entry-body">
          <div class="log-entry-name">${s.subject}</div>
          <div class="log-entry-meta">${Utils.fmtDate(s.date)} · ${s.type === 'pomodoro' ? 'Pomodoro' : 'Manual log'}</div>
          ${s.notes ? `<div class="log-entry-note">${s.notes}</div>` : ''}
        </div>
        <div class="log-entry-right">
          <div class="log-entry-dur">${Utils.fmtMinutes(s.duration)}</div>
          <button class="log-delete-btn" onclick="ProgressPage.deleteLog('${s.id}')">Remove</button>
        </div>
      </div>
    `).join('');
  },

  deleteLog(id) {
    Sessions.remove(id);
    this.render();
    Dashboard.renderStats();
    Utils.toast('Log removed.');
  },
};

/* ─── PROFILE PAGE ───────────────────────── */
const ProfilePage = {
  render() {
    const user = State.user;
    const nameEl = document.getElementById('profileName');
    const emailEl = document.getElementById('profileEmail');
    const avatarEl = document.getElementById('profileAvatar');
    const statusEl = document.getElementById('profileStatus');
    const sinceEl = document.getElementById('profileSince');
    const authBtn = document.getElementById('profileAuthBtn');
    const logoutBtn = document.getElementById('profileLogout');

    if (user) {
      if (nameEl) nameEl.textContent = user.name;
      if (emailEl) emailEl.textContent = user.email;
      if (avatarEl) avatarEl.textContent = Utils.initials(user.name);
      if (statusEl) statusEl.textContent = 'Active member';
      if (sinceEl) sinceEl.textContent = Utils.fmtDate(user.createdAt);
      authBtn?.classList.add('hidden');
      logoutBtn?.classList.remove('hidden');
    } else {
      if (nameEl) nameEl.textContent = 'Not signed in';
      if (emailEl) emailEl.textContent = 'Sign in to sync your data';
      if (avatarEl) avatarEl.textContent = '—';
      if (statusEl) statusEl.textContent = '—';
      if (sinceEl) sinceEl.textContent = '—';
      authBtn?.classList.remove('hidden');
      logoutBtn?.classList.add('hidden');
    }

    // Stats
    document.getElementById('profileTotalSessions').textContent = State.sessions.length;
    document.getElementById('profileTotalTime').textContent =
      Utils.fmtMinutes(State.sessions.reduce((a, s) => a + s.duration, 0));
    document.getElementById('profileStreak').textContent = Sessions.streak();

    this.renderCalendar();
    this.syncPreferences();
  },

  renderCalendar() {
    const el = document.getElementById('streakCalendar');
    if (!el) return;

    const days = new Set(State.sessions.map(s => new Date(s.date).toDateString()));
    const todayStr = new Date().toDateString();
    const cells = [];

    for (let i = 20; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const dStr = d.toDateString();
      const studied = days.has(dStr);
      const isToday = dStr === todayStr;
      cells.push(`<div class="streak-day ${studied ? 'studied' : ''} ${isToday ? 'today' : ''}" title="${dStr}">${d.getDate()}</div>`);
    }
    el.innerHTML = cells.join('');
  },

  syncPreferences() {
    const pomEl = document.getElementById('pomodoroLength');
    const sbEl = document.getElementById('shortBreakLength');
    const lbEl = document.getElementById('longBreakLength');
    if (pomEl) pomEl.value = State.settings.pomodoroLength;
    if (sbEl) sbEl.value = State.settings.shortBreak;
    if (lbEl) lbEl.value = State.settings.longBreak;
  },
};

/* ─── LOG FORM ───────────────────────────── */
const LogForm = {
  open() {
    document.getElementById('logSubject').value = '';
    document.getElementById('logDuration').value = '';
    document.getElementById('logNotes').value = '';
    UI.openLog();
  },

  save() {
    const subject = document.getElementById('logSubject').value.trim();
    const duration = parseInt(document.getElementById('logDuration').value);
    const notes = document.getElementById('logNotes').value.trim();

    if (!subject) { Utils.toast('Please enter a subject.'); return; }
    if (!duration || duration < 1) { Utils.toast('Enter a valid duration.'); return; }

    Sessions.add({ subject, duration, notes, type: 'manual' });
    UI.closeLog();
    Utils.toast('Session logged.');
    ProgressPage.render();
    Dashboard.renderStats();
    Dashboard.renderRecentSessions();
    Dashboard.renderLast3Days();
  },
};

/* ─── DATA EXPORT ────────────────────────── */
const DataTools = {
  export() {
    const data = { user: State.user, sessions: State.sessions, exportedAt: new Date().toISOString() };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `focusforge_export_${new Date().toISOString().split('T')[0]}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    Utils.toast('Data exported.');
  },

  async clear() {
    if (!confirm('Clear all study data? This cannot be undone.')) return;
    State.sessions = [];
    State.tasks = [];
    State.gardenHistory = [];
    ProgressPage.render();
    Dashboard.render();
    Utils.toast('All data cleared.');
  },
};
/* =============================================
   BOOTSTRAP & EVENT LISTENERS
============================================= */
document.addEventListener('DOMContentLoaded', async () => {

  // 1. Theme (always works)
  Theme.init();

  // 2. Navigation & UI Defaults
  Nav.init();
  Timer.setMode('pomodoro');
  Timer.updateDisplay();
  UI.setAuthNav();
  Nav.go('home');

  // 3. Attach Static Event Listeners
  // (Moving these up so they attach even if Firebase is slow/fails)
  attachGlobalEventListeners();

  // 4. Initialize Firebase & Auth
  try {
    Auth.init();
  } catch (e) {
    console.warn("Firebase Auth failed to initialize:", e);
    Utils.toast("Authentication unavailable. Using offline mode.");
  }

  // 5. Start Passive Components
  HeroTimer.start();
});

function attachGlobalEventListeners() {
  /* ── NAV & HERO ── */
  document.getElementById('navLoginBtn')?.addEventListener('click', () => {
    if (!Auth.isLoggedIn()) UI.openAuth();
    else Nav.go('profile');
  });

  document.getElementById('navGetStartedBtn')?.addEventListener('click', () => {
    if (Auth.isLoggedIn()) Nav.go('dashboard');
    else UI.openAuth();
  });

  document.getElementById('heroGetStarted')?.addEventListener('click', () => {
    if (Auth.isLoggedIn()) Nav.go('dashboard');
    else UI.openAuth();
  });

  document.getElementById('heroLearnMore')?.addEventListener('click', () => {
    document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' });
  });

  document.getElementById('ctaGetStarted')?.addEventListener('click', () => {
    if (Auth.isLoggedIn()) Nav.go('dashboard');
    else UI.openAuth();
  });

  /* ── THEME ── */
  document.getElementById('themeBtn')?.addEventListener('click', () => Theme.toggle());

  /* ── AUTH MODAL ── */
  document.getElementById('authClose')?.addEventListener('click', () => UI.closeAuth());
  document.getElementById('authOverlay')?.addEventListener('click', e => {
    if (e.target === e.currentTarget) UI.closeAuth();
  });

  document.querySelectorAll('.auth-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const isLogin = tab.dataset.tab === 'login';
      document.getElementById('authLogin')?.classList.toggle('hidden', !isLogin);
      document.getElementById('authSignup')?.classList.toggle('hidden', isLogin);
    });
  });

  document.getElementById('loginBtn')?.addEventListener('click', async () => {
    const errEl = document.getElementById('loginError');
    const email = document.getElementById('loginEmail').value;
    const pass = document.getElementById('loginPassword').value;
    if (!email || !pass) { if (errEl) errEl.textContent = 'Enter credentials'; return; }
    try {
      await Auth.login(email, pass);
      UI.closeAuth();
      Utils.toast(`Welcome back!`);
    } catch (e) {
      if (errEl) errEl.textContent = e.message;
    }
  });

  document.getElementById('signupBtn')?.addEventListener('click', async () => {
    const errEl = document.getElementById('signupError');
    const name = document.getElementById('signupName').value;
    const email = document.getElementById('signupEmail').value;
    const pass = document.getElementById('signupPassword').value;
    if (!name || !email || !pass) { if (errEl) errEl.textContent = 'All fields required'; return; }
    try {
      await Auth.signup(name, email, pass);
      UI.closeAuth();
      Utils.toast(`Welcome, ${name.split(' ')[0]}!`);
    } catch (e) {
      if (errEl) errEl.textContent = e.message;
    }
  });

  document.getElementById('googleBtn')?.addEventListener('click', async () => {
    try {
      await Auth.googleSignIn();
      UI.closeAuth();
      Utils.toast(`Welcome!`);
    } catch (e) {
      console.error(e);
      Utils.toast('Google sign-in failed');
    }
  });

  /* ── TIMER & FOCUS ── */
  document.querySelectorAll('.focus-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      Timer.stop();
      Timer.setMode(btn.dataset.mode);
      document.querySelectorAll('.focus-mode-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
  });

  document.getElementById('timerPlay')?.addEventListener('click', () => Timer.toggle());
  document.getElementById('timerReset')?.addEventListener('click', () => Timer.reset());
  document.getElementById('timerFullscreen')?.addEventListener('click', () => Fullscreen.open());
  document.getElementById('fsPlay')?.addEventListener('click', () => Timer.toggle());
  document.getElementById('fsExit')?.addEventListener('click', () => Fullscreen.close());
  document.getElementById('completionClose')?.addEventListener('click', () => UI.hideCompletion());

  document.getElementById('dashStartFocus')?.addEventListener('click', () => Nav.go('focus'));
  document.getElementById('focusSubject')?.addEventListener('input', () => Fullscreen.updateSubject());

  /* ── PROGRESS & LOGS ── */
  document.getElementById('addLogBtn')?.addEventListener('click', () => {
    if (!Auth.isLoggedIn()) { UI.openAuth(); return; }
    LogForm.open();
  });

  document.getElementById('logClose')?.addEventListener('click', () => UI.closeLog());
  document.getElementById('logOverlay')?.addEventListener('click', e => {
    if (e.target === e.currentTarget) UI.closeLog();
  });
  document.getElementById('saveLogBtn')?.addEventListener('click', () => LogForm.save());

  /* ── PROFILE ── */
  document.getElementById('profileAuthBtn')?.addEventListener('click', () => UI.openAuth());

  document.getElementById('profileLogout')?.addEventListener('click', async () => {
    if (!confirm('Sign out of FocusForge?')) return;
    await Auth.logout();
    Utils.toast('Signed out.');
  });

  document.getElementById('exportBtn')?.addEventListener('click', () => DataTools.export());
  document.getElementById('clearDataBtn')?.addEventListener('click', () => DataTools.clear());

  document.getElementById('pomodoroLength')?.addEventListener('change', async e => {
    State.settings.pomodoroLength = parseInt(e.target.value);
    await DB.persistSettings();
    if (State.timer.mode === 'pomodoro' && !State.timer.running) {
      Timer.setMode('pomodoro');
    }
  });
  document.getElementById('shortBreakLength')?.addEventListener('change', async e => {
    State.settings.shortBreak = parseInt(e.target.value);
    await DB.persistSettings();
  });
  document.getElementById('longBreakLength')?.addEventListener('change', async e => {
    State.settings.longBreak = parseInt(e.target.value);
    await DB.persistSettings();
  });

  /* ── GARDEN ── */
  document.getElementById('addTaskBtn')?.addEventListener('click', () => {
    if (!Auth.isLoggedIn()) { UI.openAuth(); return; }
    GardenPage.openAddTask();
  });

  document.getElementById('taskClose')?.addEventListener('click', () => {
    document.getElementById('taskOverlay')?.classList.remove('open');
  });

  document.getElementById('taskOverlay')?.addEventListener('click', e => {
    if (e.target === e.currentTarget) {
      document.getElementById('taskOverlay').classList.remove('open');
    }
  });

  document.getElementById('saveTaskBtn')?.addEventListener('click', () => GardenPage.saveTask());

  document.getElementById('taskInput')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') GardenPage.saveTask();
  });

  document.getElementById('bloomClose')?.addEventListener('click', () => {
    document.getElementById('bloomOverlay')?.classList.add('hidden');
    Nav.go('garden');
  });

  /* ── KEYBOARD SHORTCUTS ── */
  document.addEventListener('keydown', e => {
    const tag = document.activeElement?.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

    if (e.key === ' ' || e.code === 'Space') {
      e.preventDefault();
      if (Nav.currentPage === 'focus') Timer.toggle();
    }
    if (e.key === 'Escape') {
      UI.closeAuth();
      UI.closeLog();
      Fullscreen.close();
      UI.hideCompletion();
    }
    if (e.key === 'r' || e.key === 'R') {
      if (Nav.currentPage === 'focus') Timer.reset();
    }
  });
}

// Window exposures are at the END of the file (after all objects are defined)


/* =============================================
   CONSISTENCY GARDEN FEATURE
   — TaskManager      : CRUD for daily tasks
   — FlowerRenderer   : SVG flower drawing per type
   — ConsistencyGarden: bloom logic, flower grid
   — GardenDash       : dashboard preview card
   Firebase data structure (ready to swap):
     Collection: tasks  → { userId, taskText, completed, date }
     Collection: garden → { userId, date, flowerType, streakDay }
============================================= */

/* ─── FLOWER TYPE SYSTEM ─────────────────── */
const FLOWER_TYPES = {
  blossom: { label: 'Blossom', streakMin: 0, petalColor: '#D4B8CC', petalDark: '#B89AAC', center: '#EED8C0', stem: '#8AB498' },
  fuller: { label: 'Fuller Bloom', streakMin: 3, petalColor: '#C0C8E4', petalDark: '#9AA4CC', center: '#EAE0F4', stem: '#8AB498' },
  layered: { label: 'Layered', streakMin: 7, petalColor: '#B8D4C0', petalDark: '#7AAD88', center: '#FFF0D8', stem: '#5A9068' },
  rare: { label: 'Rare Bloom', streakMin: 30, petalColor: '#E8C8C0', petalDark: '#C8908A', center: '#FFF8E0', stem: '#5A9068' },
};

function getFlowerType(streakDay) {
  if (streakDay >= 30) return 'rare';
  if (streakDay >= 7) return 'layered';
  if (streakDay >= 3) return 'fuller';
  return 'blossom';
}

/* ─── FLOWER SVG RENDERER ────────────────── */
const FlowerRenderer = {

  drawStem(stemColor, h = 40) {
    return `<line x1="28" y1="${58 + h}" x2="28" y2="58" stroke="${stemColor}" stroke-width="2.2" stroke-linecap="round"/>
    <path d="M28 ${38 + h} Q18 ${28 + h} 20 ${18 + h} Q26 ${28 + h} 28 ${38 + h}Z" fill="${stemColor}" opacity="0.7"/>`;
  },

  /* Simple 5-petal blossom */
  blossom(type, size = 56, showStem = true) {
    const t = FLOWER_TYPES[type] || FLOWER_TYPES.blossom;
    const s = size / 56;
    const p = t.petalColor, pd = t.petalDark, c = t.center;
    if (type === 'blossom') {
      return `<svg viewBox="0 0 56 96" width="${size}" height="${size * 96 / 56}" fill="none">
        ${showStem ? `<line x1="28" y1="96" x2="28" y2="58" stroke="${t.stem}" stroke-width="2" stroke-linecap="round"/>
        <path d="M28 80 Q18 70 20 60 Q26 70 28 80Z" fill="${t.stem}" opacity="0.6"/>` : ''}
        <ellipse cx="28" cy="42" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1"/>
        <ellipse cx="28" cy="42" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(72 28 42)"/>
        <ellipse cx="28" cy="42" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(144 28 42)"/>
        <ellipse cx="28" cy="42" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(216 28 42)"/>
        <ellipse cx="28" cy="42" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(288 28 42)"/>
        <circle cx="28" cy="42" r="7" fill="${c}" stroke="${pd}" stroke-width="1"/>
        <circle cx="28" cy="42" r="3.5" fill="${pd}" opacity="0.55"/>
      </svg>`;
    }
    if (type === 'fuller') {
      return `<svg viewBox="0 0 56 96" width="${size}" height="${size * 96 / 56}" fill="none">
        ${showStem ? `<line x1="28" y1="96" x2="28" y2="58" stroke="${t.stem}" stroke-width="2" stroke-linecap="round"/>
        <path d="M28 80 Q16 70 18 60 Q26 72 28 80Z" fill="${t.stem}" opacity="0.6"/>
        <path d="M28 80 Q40 70 38 60 Q30 72 28 80Z" fill="${t.stem}" opacity="0.4"/>` : ''}
        <!-- outer ring -->
        <ellipse cx="28" cy="40" rx="7" ry="12" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.7"/>
        <ellipse cx="28" cy="40" rx="7" ry="12" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.7" transform="rotate(60 28 40)"/>
        <ellipse cx="28" cy="40" rx="7" ry="12" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.7" transform="rotate(120 28 40)"/>
        <ellipse cx="28" cy="40" rx="7" ry="12" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.7" transform="rotate(180 28 40)"/>
        <ellipse cx="28" cy="40" rx="7" ry="12" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.7" transform="rotate(240 28 40)"/>
        <ellipse cx="28" cy="40" rx="7" ry="12" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.7" transform="rotate(300 28 40)"/>
        <!-- inner ring -->
        <ellipse cx="28" cy="40" rx="5" ry="9" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(30 28 40)"/>
        <ellipse cx="28" cy="40" rx="5" ry="9" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(90 28 40)"/>
        <ellipse cx="28" cy="40" rx="5" ry="9" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(150 28 40)"/>
        <ellipse cx="28" cy="40" rx="5" ry="9" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(210 28 40)"/>
        <ellipse cx="28" cy="40" rx="5" ry="9" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(270 28 40)"/>
        <ellipse cx="28" cy="40" rx="5" ry="9" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(330 28 40)"/>
        <circle cx="28" cy="40" r="7.5" fill="${c}" stroke="${pd}" stroke-width="1"/>
        <circle cx="28" cy="40" r="3.5" fill="${pd}" opacity="0.55"/>
      </svg>`;
    }
    if (type === 'layered') {
      return `<svg viewBox="0 0 56 100" width="${size}" height="${size * 100 / 56}" fill="none">
        ${showStem ? `<line x1="28" y1="100" x2="28" y2="60" stroke="${t.stem}" stroke-width="2.2" stroke-linecap="round"/>
        <path d="M28 84 Q16 72 18 62 Q26 74 28 84Z" fill="${t.stem}" opacity="0.7"/>
        <path d="M28 78 Q40 68 38 58 Q30 70 28 78Z" fill="${t.stem}" opacity="0.5"/>` : ''}
        <!-- back petals -->
        <ellipse cx="28" cy="38" rx="9" ry="15" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.5" transform="rotate(36 28 38)"/>
        <ellipse cx="28" cy="38" rx="9" ry="15" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.5" transform="rotate(108 28 38)"/>
        <ellipse cx="28" cy="38" rx="9" ry="15" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.5" transform="rotate(180 28 38)"/>
        <ellipse cx="28" cy="38" rx="9" ry="15" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.5" transform="rotate(252 28 38)"/>
        <ellipse cx="28" cy="38" rx="9" ry="15" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.5" transform="rotate(324 28 38)"/>
        <!-- front petals -->
        <ellipse cx="28" cy="38" rx="7.5" ry="13" fill="${p}" stroke="${pd}" stroke-width="1"/>
        <ellipse cx="28" cy="38" rx="7.5" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(72 28 38)"/>
        <ellipse cx="28" cy="38" rx="7.5" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(144 28 38)"/>
        <ellipse cx="28" cy="38" rx="7.5" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(216 28 38)"/>
        <ellipse cx="28" cy="38" rx="7.5" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(288 28 38)"/>
        <circle cx="28" cy="38" r="8.5" fill="${c}" stroke="${pd}" stroke-width="1.2"/>
        <circle cx="28" cy="38" r="4" fill="${pd}" opacity="0.6"/>
      </svg>`;
    }
    if (type === 'rare') {
      return `<svg viewBox="0 0 56 104" width="${size}" height="${size * 104 / 56}" fill="none">
        ${showStem ? `<line x1="28" y1="104" x2="28" y2="62" stroke="${t.stem}" stroke-width="2.4" stroke-linecap="round"/>
        <path d="M28 88 Q14 76 16 64 Q26 78 28 88Z" fill="${t.stem}" opacity="0.7"/>
        <path d="M28 82 Q42 70 40 60 Q30 74 28 82Z" fill="${t.stem}" opacity="0.5"/>
        <line x1="28" y1="74" x2="18" y2="66" stroke="${t.stem}" stroke-width="1.4" stroke-linecap="round"/>
        <line x1="28" y1="70" x2="38" y2="62" stroke="${t.stem}" stroke-width="1.4" stroke-linecap="round"/>` : ''}
        <!-- outermost ring -->
        <ellipse cx="28" cy="34" rx="10" ry="16" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.35" transform="rotate(0 28 34)"/>
        <ellipse cx="28" cy="34" rx="10" ry="16" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.35" transform="rotate(45 28 34)"/>
        <ellipse cx="28" cy="34" rx="10" ry="16" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.35" transform="rotate(90 28 34)"/>
        <ellipse cx="28" cy="34" rx="10" ry="16" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.35" transform="rotate(135 28 34)"/>
        <ellipse cx="28" cy="34" rx="10" ry="16" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.35" transform="rotate(180 28 34)"/>
        <ellipse cx="28" cy="34" rx="10" ry="16" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.35" transform="rotate(225 28 34)"/>
        <ellipse cx="28" cy="34" rx="10" ry="16" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.35" transform="rotate(270 28 34)"/>
        <ellipse cx="28" cy="34" rx="10" ry="16" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.35" transform="rotate(315 28 34)"/>
        <!-- middle ring -->
        <ellipse cx="28" cy="34" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.7" transform="rotate(22 28 34)"/>
        <ellipse cx="28" cy="34" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.7" transform="rotate(94 28 34)"/>
        <ellipse cx="28" cy="34" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.7" transform="rotate(166 28 34)"/>
        <ellipse cx="28" cy="34" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.7" transform="rotate(238 28 34)"/>
        <ellipse cx="28" cy="34" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" opacity="0.7" transform="rotate(310 28 34)"/>
        <!-- inner ring -->
        <ellipse cx="28" cy="34" rx="6" ry="10" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(0 28 34)"/>
        <ellipse cx="28" cy="34" rx="6" ry="10" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(72 28 34)"/>
        <ellipse cx="28" cy="34" rx="6" ry="10" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(144 28 34)"/>
        <ellipse cx="28" cy="34" rx="6" ry="10" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(216 28 34)"/>
        <ellipse cx="28" cy="34" rx="6" ry="10" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(288 28 34)"/>
        <circle cx="28" cy="34" r="9" fill="${c}" stroke="${pd}" stroke-width="1.4"/>
        <circle cx="28" cy="34" r="4.5" fill="${pd}" opacity="0.7"/>
        <!-- tiny sparkle dots -->
        <circle cx="28" cy="20" r="2" fill="${pd}" opacity="0.5"/>
        <circle cx="38" cy="26" r="1.5" fill="${pd}" opacity="0.4"/>
        <circle cx="18" cy="26" r="1.5" fill="${pd}" opacity="0.4"/>
      </svg>`;
    }
    return '';
  },

  /* Compact version for legend/preview (no stem) */
  compact(type, size = 36) {
    const t = FLOWER_TYPES[type] || FLOWER_TYPES.blossom;
    const p = t.petalColor, pd = t.petalDark, c = t.center;
    return `<svg viewBox="0 0 56 56" width="${size}" height="${size}" fill="none">
      <ellipse cx="28" cy="28" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1"/>
      <ellipse cx="28" cy="28" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(72 28 28)"/>
      <ellipse cx="28" cy="28" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(144 28 28)"/>
      <ellipse cx="28" cy="28" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(216 28 28)"/>
      <ellipse cx="28" cy="28" rx="8" ry="13" fill="${p}" stroke="${pd}" stroke-width="1" transform="rotate(288 28 28)"/>
      <circle cx="28" cy="28" r="7" fill="${c}" stroke="${pd}" stroke-width="1"/>
      <circle cx="28" cy="28" r="3.5" fill="${pd}" opacity="0.55"/>
    </svg>`;
  },
};

/* ─── TASK MANAGER ───────────────────────── */
const TaskManager = {
  todayKey() {
    return new Date().toDateString();
  },

  todayTasks() {
    const today = this.todayKey();
    return State.tasks.filter(t => t.date === today);
  },

  async add(text) {
    if (!text.trim() || !State.user) return;
    const data = {
      text: text.trim(),
      completed: false,
      date: this.todayKey(),
    };
    const docRef = await addDoc(collection(db, 'users', State.user.uid, 'tasks'), data);
    State.tasks.push({ id: docRef.id, ...data });
  },

  async toggle(id) {
    if (!State.user) return;
    const task = State.tasks.find(t => t.id === id);
    if (task) {
      task.completed = !task.completed;
      await updateDoc(doc(db, 'users', State.user.uid, 'tasks', id), {
        completed: task.completed
      });
    }
  },

  async edit(id, newText) {
    if (!State.user || !newText.trim()) return;
    const task = State.tasks.find(t => t.id === id);
    if (task) {
      task.text = newText.trim();
      await updateDoc(doc(db, 'users', State.user.uid, 'tasks', id), {
        text: task.text
      });
    }
  },

  async remove(id) {
    if (!State.user) return;
    await deleteDoc(doc(db, 'users', State.user.uid, 'tasks', id));
    State.tasks = State.tasks.filter(t => t.id !== id);
  },

  completionPct(dateKey) {
    const key = dateKey || this.todayKey();
    const dayTasks = State.tasks.filter(t => t.date === key);
    if (!dayTasks.length) return 0;
    return Math.round((dayTasks.filter(t => t.completed).length / dayTasks.length) * 100);
  },

  goalMet(dateKey) {
    return this.completionPct(dateKey) >= 80;
  },
};

/* ─── CONSISTENCY GARDEN CORE ────────────── */
const ConsistencyGarden = {

  /* Returns all flowers sorted oldest-first */
  allFlowers() {
    return [...State.gardenHistory].sort((a, b) => new Date(a.date) - new Date(b.date));
  },

  /* Check if today already has a flower */
  todayBloomed() {
    const today = new Date().toDateString();
    return State.gardenHistory.some(f => new Date(f.date).toDateString() === today);
  },

  /* Current streak: consecutive days with a flower */
  streak() {
    const flowers = this.allFlowers();
    if (!flowers.length) return 0;
    let streak = 0;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    for (let i = 0; i < 365; i++) {
      const d = new Date(today);
      d.setDate(d.getDate() - i);
      const key = d.toDateString();
      if (flowers.some(f => new Date(f.date).toDateString() === key)) {
        streak++;
      } else {
        if (i === 0) continue; // today not yet bloomed is ok
        break;
      }
    }
    return streak;
  },

  /* Try to add a flower for today. Returns true if newly added. */
  async tryBloom() {
    if (!State.user || this.todayBloomed()) return false;
    // Require 100% completion for bloom
    if (TaskManager.completionPct() < 100) return false;
    const streak = this.streak() + 1;
    const flowerType = getFlowerType(streak);
    const data = {
      date: new Date().toISOString(),
      flowerType,
      streakDay: streak,
    };
    const docRef = await addDoc(collection(db, 'users', State.user.uid, 'garden'), data);
    const entry = { id: docRef.id, ...data };
    State.gardenHistory.push(entry);
    return entry;
  },

  /* Seed demo flowers for first-time visitors (No longer needed with real DB) */
  seedDemoFlowers() {
    // Left empty for now, could be used for initial setup if needed
  },
};

/* ─── GROWTH STAGES ──────────────────────── */
const GrowthStages = {
  STAGES: ['seed', 'sprout', 'bud', 'bloom'],
  EMOJIS: { seed: '', sprout: '', bud: '', bloom: '' },
  LABELS: { seed: 'Seed', sprout: 'Sprout', bud: 'Bud', bloom: 'Full Bloom' },

  current() {
    const tasks = TaskManager.todayTasks();
    if (!tasks.length) return 'seed';
    const pct = TaskManager.completionPct();
    if (pct >= 100) return 'bloom';
    if (pct >= 50) return 'bud';
    if (pct > 0) return 'sprout';
    return 'seed';
  },

  /* Update the growth stage bar UI */
  updateBar() {
    const bar = document.getElementById('growthStageBar');
    if (!bar) return;
    const stage = this.current();
    const stageIndex = this.STAGES.indexOf(stage);
    const stages = bar.querySelectorAll('.growth-stage');
    const connectors = bar.querySelectorAll('.growth-stage-connector');

    stages.forEach((el, i) => {
      el.classList.remove('active', 'completed', 'transitioning');
      if (i < stageIndex) el.classList.add('completed');
      else if (i === stageIndex) {
        el.classList.add('active');
        el.classList.add('transitioning');
        setTimeout(() => el.classList.remove('transitioning'), 500);
      }
    });
    connectors.forEach((el, i) => {
      el.classList.toggle('active', i < stageIndex);
    });
  },

  /* SVG for the flower spot based on growth stage */
  renderSpot(stage) {
    if (stage === 'seed') {
      return `<svg viewBox="0 0 80 80" width="80" height="80" fill="none">
        <circle cx="40" cy="54" r="8" fill="#8B7355" opacity="0.6"/>
        <ellipse cx="40" cy="50" rx="5" ry="3" fill="#A8D5A2" opacity="0.8">
          <animateTransform attributeName="transform" type="scale" values="0.8;1.1;0.8" dur="2s" repeatCount="indefinite"/>
        </ellipse>
      </svg>`;
    }
    if (stage === 'sprout') {
      return `<svg viewBox="0 0 80 100" width="70" height="88" fill="none">
        <line x1="40" y1="80" x2="40" y2="50" stroke="#7CBF73" stroke-width="3" stroke-linecap="round"/>
        <ellipse cx="34" cy="58" rx="8" ry="4" fill="#8AB498" opacity="0.7" transform="rotate(-30 34 58)"/>
        <ellipse cx="46" cy="54" rx="8" ry="4" fill="#8AB498" opacity="0.7" transform="rotate(30 46 54)"/>
      </svg>`;
    }
    if (stage === 'bud') {
      return `<svg viewBox="0 0 80 110" width="65" height="90" fill="none">
        <line x1="40" y1="90" x2="40" y2="45" stroke="#7CBF73" stroke-width="3" stroke-linecap="round"/>
        <ellipse cx="33" cy="65" rx="9" ry="4" fill="#8AB498" opacity="0.7" transform="rotate(-25 33 65)"/>
        <ellipse cx="47" cy="58" rx="9" ry="4" fill="#8AB498" opacity="0.7" transform="rotate(25 47 58)"/>
        <circle cx="40" cy="38" r="12" fill="var(--lavender-soft)" stroke="var(--lavender)" stroke-width="1.5"/>
        <circle cx="40" cy="38" r="5" fill="var(--peach)" opacity="0.7"/>
      </svg>`;
    }
    // bloom — full flower
    return FlowerRenderer.blossom('blossom', 80, false);
  },
};

/* ─── GARDEN PAGE ─────────────────────────── */
const GardenPage = {
  editingId: null,
  _justBloomed: null,
  _prevStage: 'seed',

  render() {
    this.renderTodayCard();
    this.renderTaskList();
    this.renderFlowerGrid();
    this.renderLegend();
    this.updateHeaderStats();
    GrowthStages.updateBar();
  },

  updateHeaderStats() {
    const total = ConsistencyGarden.allFlowers().length;
    const streak = ConsistencyGarden.streak();
    const totalEl = document.getElementById('gardenTotalFlowers');
    const streakEl = document.getElementById('gardenStreakVal');
    if (totalEl) totalEl.textContent = total;
    if (streakEl) streakEl.textContent = streak;
  },

  renderTodayCard() {
    const pct = TaskManager.completionPct();
    const bloomed = ConsistencyGarden.todayBloomed();
    const stage = GrowthStages.current();
    const CIRC = 2 * Math.PI * 34;

    // Ring
    const ring = document.getElementById('gtcRingFill');
    const ringPct = document.getElementById('gtcRingPct');
    if (ring) {
      ring.style.strokeDashoffset = CIRC * (1 - pct / 100);
      ring.classList.toggle('complete', pct >= 100);
    }
    if (ringPct) ringPct.textContent = pct + '%';

    // Flower spot — show growth stage SVG
    const flowerSpot = document.getElementById('gtcFlowerSpot');
    if (flowerSpot) {
      if (bloomed) {
        const streak = ConsistencyGarden.streak();
        const type = getFlowerType(streak);
        flowerSpot.innerHTML = `<div class="bloom-celebrate">
          ${FlowerRenderer.blossom(type, 80, false)}
        </div>`;
      } else {
        const animate = stage !== this._prevStage;
        flowerSpot.innerHTML = `<div style="${animate ? 'animation:stageTransition 0.5s var(--ease-spring)' : ''}">
          ${GrowthStages.renderSpot(stage)}
        </div>`;
        this._prevStage = stage;
      }
    }

    // Text
    const title = document.getElementById('gtcTitle');
    const sub = document.getElementById('gtcSub');
    if (title) title.textContent = bloomed ? "Today's flower bloomed!" : `Today's growth — ${GrowthStages.LABELS[stage]}`;
    if (sub) {
      if (bloomed) {
        sub.textContent = 'Your consistency is growing. Keep it up.';
        sub.className = 'gtc-sub success';
      } else if (pct >= 100) {
        sub.textContent = 'All tasks done! Your flower is blooming...';
        sub.className = 'gtc-sub success';
      } else if (pct > 0) {
        sub.textContent = `${pct}% complete — ${100 - pct}% more to full bloom.`;
        sub.className = 'gtc-sub';
      } else {
        sub.textContent = 'Complete your tasks to grow today\'s flower.';
        sub.className = 'gtc-sub';
      }
    }

    // Update growth stage bar
    GrowthStages.updateBar();
  },

  renderFlowerGrid() {
    const grid = document.getElementById('flowerGrid');
    const meta = document.getElementById('gardenCanvasMeta');
    if (!grid) return;

    const flowers = ConsistencyGarden.allFlowers();
    if (meta) meta.textContent = `${flowers.length} bloom${flowers.length !== 1 ? 's' : ''}`;

    if (!flowers.length) {
      grid.innerHTML = `<div class="flower-grid-empty" id="flowerGridEmpty">
        <svg width="40" height="40" viewBox="0 0 60 60" fill="none">
          <circle cx="30" cy="30" r="26" stroke="var(--border-2)" stroke-width="1.5" stroke-dasharray="5 4"/>
          <circle cx="30" cy="30" r="4" fill="var(--border-2)"/>
        </svg>
        <p>Your garden awaits its first bloom.</p>
        <p class="flower-grid-empty-sub">Complete today's tasks to plant the first flower.</p>
      </div>`;
      return;
    }

    const isNew = this._justBloomed;
    grid.innerHTML = flowers.map((f, i) => {
      const d = new Date(f.date);
      const label = d.toLocaleDateString('en', { month: 'short', day: 'numeric' });
      const isLatest = i === flowers.length - 1 && isNew;
      const delay = Math.min(i * 0.05, 1.2);
      return `<div class="flower-cell${isLatest ? ' new-bloom bloom-celebrate' : ''}"
                   style="animation-delay:${delay}s">
        <div class="flower-svg-wrap">
          ${FlowerRenderer.blossom(f.flowerType, 48, true)}
          <div class="flower-tooltip">${label} · ${FLOWER_TYPES[f.flowerType]?.label || 'Blossom'}</div>
        </div>
        <div class="flower-date-label">${label}</div>
      </div>`;
    }).join('');
    this._justBloomed = null;
  },

  renderLegend() {
    const types = ['blossom', 'fuller', 'layered', 'rare'];
    types.forEach(type => {
      const el = document.getElementById('legend' + type.charAt(0).toUpperCase() + type.slice(1).replace('3', '').replace('7', '').replace('30', ''));
      if (el) el.innerHTML = FlowerRenderer.compact(type, 36);
    });
    // Fix IDs to match legend HTML
    ['Normal', 'Streak3', 'Streak7', 'Streak30'].forEach((suffix, i) => {
      const el = document.getElementById('legend' + suffix);
      if (el) el.innerHTML = FlowerRenderer.compact(types[i], 36);
    });
  },

  renderTaskList() {
    const list = document.getElementById('taskList');
    const meta = document.getElementById('gardenTaskMeta');
    if (!list) return;

    const tasks = TaskManager.todayTasks();
    const done = tasks.filter(t => t.completed).length;
    if (meta) meta.textContent = `${done} of ${tasks.length}`;

    if (!tasks.length) {
      list.innerHTML = `<div class="task-empty">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.3">
          <rect x="3" y="3" width="18" height="18" rx="3"/><polyline points="9 12 11 14 15 10"/>
        </svg>
        <p>No tasks yet. Add your first task for today.</p>
      </div>`;
      return;
    }

    list.innerHTML = tasks.map(t => `
      <div class="task-item ${t.completed ? 'completed' : ''}" data-id="${t.id}">
        <div class="task-checkbox-wrap">
          <input type="checkbox" class="task-checkbox" ${t.completed ? 'checked' : ''}
                 onchange="GardenPage.toggleTask('${t.id}')" aria-label="Mark complete"/>
        </div>
        <div class="task-text-wrap">
          <span class="task-text">${this.escHtml(t.text)}</span>
        </div>
        <div class="task-actions">
          <button class="task-action-btn edit" onclick="GardenPage.openEditTask('${t.id}')" title="Edit">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
              <path d="M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
          </button>
          <button class="task-action-btn delete" onclick="GardenPage.removeTask('${t.id}')" title="Remove">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/>
              <path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>
            </svg>
          </button>
        </div>
      </div>
    `).join('');
  },

  async toggleTask(id) {
    await TaskManager.toggle(id);

    // Update UI immediately
    this.renderTodayCard();
    this.renderTaskList();
    this.updateHeaderStats();
    GardenDash.render();

    // Check for bloom at 100%
    if (TaskManager.completionPct() >= 100 && !ConsistencyGarden.todayBloomed()) {
      try {
        const newBloom = await ConsistencyGarden.tryBloom();
        if (newBloom) {
          this._justBloomed = newBloom;
          this.showBloomCelebration(newBloom);
          this.render();
          GardenDash.render();
        }
      } catch (e) {
        console.warn('Bloom failed:', e.message);
      }
    }
  },

  async removeTask(id) {
    await TaskManager.remove(id);
    this.render();
    GardenDash.render();
    Utils.toast('Task removed.');
  },

  showBloomCelebration(flowerEntry) {
    const overlay = document.getElementById('bloomOverlay');
    const spot = document.getElementById('bloomFlowerSpot');
    const sub = document.getElementById('bloomSub');
    if (!overlay) return;
    if (spot) spot.innerHTML = `<div class="bloom-celebrate">${FlowerRenderer.blossom(flowerEntry.flowerType, 90, false)}</div>`;
    if (sub) {
      const t = FLOWER_TYPES[flowerEntry.flowerType];
      sub.textContent = `A ${t?.label?.toLowerCase() || 'blossom'} has been added to your garden. Day ${flowerEntry.streakDay}.`;
    }
    overlay.classList.remove('hidden');
  },

  openAddTask() {
    this.editingId = null;
    document.getElementById('taskModalTitle').textContent = 'Add a task';
    document.getElementById('saveTaskBtn').textContent = 'Add task';
    document.getElementById('taskInput').value = '';
    document.getElementById('taskEditId').value = '';
    document.getElementById('taskOverlay')?.classList.add('open');
    setTimeout(() => document.getElementById('taskInput')?.focus(), 80);
  },

  openEditTask(id) {
    const task = State.tasks.find(t => t.id === id);
    if (!task) return;
    this.editingId = id;
    document.getElementById('taskModalTitle').textContent = 'Edit task';
    document.getElementById('saveTaskBtn').textContent = 'Save changes';
    document.getElementById('taskInput').value = task.text;
    document.getElementById('taskEditId').value = id;
    document.getElementById('taskOverlay')?.classList.add('open');
    setTimeout(() => document.getElementById('taskInput')?.focus(), 80);
  },

  async saveTask() {
    const input = document.getElementById('taskInput');
    const editId = document.getElementById('taskEditId');
    const text = input?.value?.trim();
    if (!text) { Utils.toast('Please enter a task description.'); return; }

    const id = editId?.value;

    // 1. Close modal IMMEDIATELY
    const overlay = document.getElementById('taskOverlay');
    if (overlay) overlay.classList.remove('open');

    // 2. Clear input
    if (input) input.value = '';
    if (editId) editId.value = '';

    // 3. Perform the operation
    if (id) {
      await TaskManager.edit(id, text);
      Utils.toast('Task updated.');
    } else {
      await TaskManager.add(text);
      Utils.toast('Task added.');
    }

    // 4. Re-render INSTANTLY
    this.renderTaskList();
    this.renderTodayCard();
    this.updateHeaderStats();
    GardenDash.render();

    // 5. Add slide-in animation to newest task
    const list = document.getElementById('taskList');
    if (list && !id) {
      const lastItem = list.querySelector('.task-item:last-child');
      if (lastItem) lastItem.classList.add('new');
    }
  },

  escHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },
};

/* ─── GARDEN DASHBOARD PREVIEW ────────────── */
const GardenDash = {
  render() {
    const pct = TaskManager.completionPct();
    const bloomed = ConsistencyGarden.todayBloomed();
    const streak = ConsistencyGarden.streak();
    const total = ConsistencyGarden.allFlowers().length;
    const today = TaskManager.todayTasks();

    // Progress bar
    const fill = document.getElementById('dgcFill');
    if (fill) fill.style.width = pct + '%';
    const pctEl = document.getElementById('dgcPct');
    if (pctEl) pctEl.textContent = pct + '%';
    const todayPct = document.getElementById('dgcTodayPct');
    if (todayPct) todayPct.textContent = pct + '%';

    // Bloom status
    const dot = document.getElementById('dgcBloomDot');
    const bloomText = document.getElementById('dgcBloomText');
    if (dot) dot.classList.toggle('bloomed', bloomed);
    if (bloomText) {
      bloomText.textContent = bloomed ? 'Flower bloomed today' :
        (pct >= 80 ? 'Ready to bloom — visit your garden' : 'Not yet bloomed today');
    }

    // Stats
    const flowerCount = document.getElementById('dgcFlowerCount');
    const streakCount = document.getElementById('dgcStreakCount');
    if (flowerCount) flowerCount.textContent = total;
    if (streakCount) streakCount.textContent = streak;

    // Title & message
    const title = document.getElementById('dgcTitle');
    const msg = document.getElementById('dgcMessage');
    if (title) title.textContent = bloomed ? 'Your garden bloomed today.' : 'Your garden is growing.';
    if (msg) {
      if (!today.length) {
        msg.textContent = 'Add tasks to begin nurturing your garden.';
      } else if (bloomed) {
        msg.textContent = 'Consistency is building something beautiful.';
      } else if (pct >= 80) {
        msg.textContent = 'Goal reached. Visit your garden to bloom.';
      } else {
        msg.textContent = 'Complete 80% of tasks to earn a new flower.';
      }
    }

    // Mini flower preview
    const preview = document.getElementById('dgcFlowerPreview');
    if (preview) {
      const flowers = ConsistencyGarden.allFlowers();
      const shown = flowers.slice(-9);
      const cells = shown.map((f, i) => `
        <div class="dgc-flower-item" style="animation-delay:${i * 0.06}s">
          ${FlowerRenderer.compact(f.flowerType, 28)}
        </div>`).join('');
      // Pad with placeholders to fill 3×3 grid
      const pads = Math.max(0, 9 - shown.length);
      const placeholders = Array(pads).fill('<div class="dgc-flower-item"><div class="dgc-flower-placeholder"></div></div>').join('');
      preview.innerHTML = cells + placeholders;
    }
  },
};

/* =============================================
   EXPOSE TO WINDOW — MUST BE AFTER ALL DEFINITIONS
   (ES modules scope everything privately; inline onclick
    handlers in dynamically-rendered HTML need these on window)
============================================= */
window.Nav = Nav;
window.Timer = Timer;
window.GardenPage = GardenPage;
window.GardenDash = GardenDash;
window.ProgressPage = ProgressPage;
window.LogForm = LogForm;
window.DataTools = DataTools;
window.TaskManager = TaskManager;
window.ConsistencyGarden = ConsistencyGarden;
window.GrowthStages = GrowthStages;
window.Theme = Theme;
window.UI = UI;
window.Auth = Auth;
window.Sessions = Sessions;
window.Dashboard = Dashboard;
window.FocusPage = FocusPage;
window.ProfilePage = ProfilePage;
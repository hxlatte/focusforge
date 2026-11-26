/* =============================================
   FOCUSFORGE INTELLIGENCE
   Presents the Cognitive Rhythm Engine, the Study-Log Analyzer and the unified
   recommendations. All numbers come from the backend (backend/); this file only
   renders them and records the user's responses (recall ratings, recommendation status).

   Safety notes
   - Every string that originates from user data or the backend is escaped (esc()).
   - The backend is called with the user's Firebase ID token; no secrets live here.
   - Recommendations never create tasks on their own: "Accept" is an explicit click.
============================================= */
'use strict';
import { doc, getDoc, addDoc, updateDoc, collection } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";

const API_BASE = (window.FF_API_BASE || localStorage.getItem('ff_api_base') || 'http://127.0.0.1:8000').replace(/\/$/, '');
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const DAYS_LONG = ['Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays', 'Sundays'];
const PERIOD_LABEL = { morning: 'Morning', afternoon: 'Afternoon', evening: 'Evening', night: 'Night' };
const PERIOD_HOURS = { morning: '5–12', afternoon: '12–17', evening: '17–22', night: '22–5' };
const STANCE_LABEL = { struggling: 'Struggling', revise: 'Wants to revise', confident: 'Confident', understood: 'Understood', revised: 'Revised', mention: 'Studied' };
const SOURCE_LABEL = { study_log: 'Study log', rhythm: 'Rhythm', default: 'Default' };

const FF = () => window.FocusForge;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pct = x => (x == null ? '—' : `${Math.round(x * 100)}%`);
const cap = s => s ? s.charAt(0).toUpperCase() + s.slice(1) : s;

class ApiError extends Error {
  constructor(kind, status) { super(kind); this.kind = kind; this.status = status; }
}

const Store = {
  data: null,            // { rhythm, learning, recommendations }
  state: 'idle',         // idle | loading | analysing | ready | error
  error: null,
  tab: 'insights',
  openTopic: null,
  topicCache: {},
  busy: new Set(),
};

/* ─── API ────────────────────────────────────── */
async function api(path, options = {}) {
  const user = FF().auth.currentUser;
  if (!user) throw new ApiError('signin');
  const token = await user.getIdToken();
  let res;
  try {
    res = await fetch(API_BASE + path, {
      ...options,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
  } catch (e) {
    throw new ApiError('unreachable');
  }
  if (!res.ok) throw new ApiError(res.status === 401 ? 'auth' : 'http', res.status);
  return res.json();
}

const tz = () => FF().Utils.tz();

/* ─── LOADING ────────────────────────────────── */
async function loadStored() {
  Store.state = 'loading'; Store.error = null; paint();
  try {
    const d = await api('/v1/intelligence');
    Store.data = d;
    if (!d.rhythm && !d.learning) return analyse();
    Store.state = 'ready';
  } catch (e) { fail(e); }
  paint();
}

async function analyse() {
  Store.state = 'analysing'; Store.error = null; paint();
  try {
    await api('/v1/analyze', { method: 'POST', body: JSON.stringify({ tz: tz() }) });
    Store.data = await api('/v1/intelligence');   // single source of truth: what is stored
    Store.topicCache = {};
    Store.state = 'ready';
  } catch (e) { fail(e); }
  paint();
}

function fail(e) {
  Store.state = 'error';
  Store.error = e instanceof ApiError ? e : new ApiError('http', 0);
  console.warn('Intelligence request failed:', e);
}

/* ─── SMALL VIEW HELPERS ─────────────────────── */
function rel(iso) {
  if (!iso) return '—';
  const mins = Math.round((Date.now() - new Date(iso)) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  if (mins < 1440) return `${Math.round(mins / 60)} h ago`;
  return `${Math.round(mins / 1440)} d ago`;
}

function dueLabel(iso) {
  if (!iso) return '—';
  const days = Math.round((new Date(iso) - Date.now()) / 86400000);
  if (days < 0) return `Overdue ${-days} d`;
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  return `In ${days} d`;
}

function pill(text, tone = '') { return `<span class="ix-pill ${tone}">${esc(text)}</span>`; }

function stagePill(stage, kind) {
  const map = {
    rhythm: { collecting: ['Collecting data', 'muted'], descriptive: ['Observed patterns', 'info'], modelled: ['Personal model active', 'ok'] },
    learning: { collecting: ['Waiting for reflections', 'muted'], active: ['Reading your reflections', 'ok'] },
  };
  const [t, tone] = (map[kind][stage] || ['—', 'muted']);
  return pill(`${kind === 'rhythm' ? 'Rhythm' : 'Learning'}: ${t}`, tone);
}

function unlocks(list) {
  if (!list || !list.length) return '';
  return `<ul class="ix-unlocks">${list.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
}

function empty(title, body, list) {
  return `<div class="ix-empty"><div class="ix-empty-title">${esc(title)}</div><p>${esc(body)}</p>${unlocks(list)}</div>`;
}

/* Dot-and-interval row: the dot is the observed rate, the bar is its 95% interval,
   the tick marks the overall rate. Wide bars = little data. */
function rateRow(label, row, overall, sub) {
  if (!row || row.rate == null) return '';
  const lo = row.ci_low * 100, hi = row.ci_high * 100;
  return `<div class="ix-rrow" title="${esc(`${row.completed} of ${row.n} completed · 95% interval ${pct(row.ci_low)}–${pct(row.ci_high)}`)}">
    <div class="ix-rlabel">${esc(label)}${sub ? `<small>${esc(sub)}</small>` : ''}</div>
    <div class="ix-track">
      <div class="ix-ci" style="left:${lo}%;width:${Math.max(1, hi - lo)}%"></div>
      ${overall != null ? `<div class="ix-tick" style="left:${overall * 100}%"></div>` : ''}
      <div class="ix-dot" style="left:${row.rate * 100}%"></div>
    </div>
    <div class="ix-rval">${pct(row.rate)}<small>${row.completed}/${row.n}</small></div>
  </div>`;
}

/* ─── HEADER + OVERVIEW ──────────────────────── */
function header(d) {
  const r = d && d.rhythm, l = d && d.learning;
  const last = [r && r.generated_at, l && l.generated_at].filter(Boolean).sort().pop();
  const today = new Date().toLocaleDateString('en', { weekday: 'long', month: 'long', day: 'numeric' });
  return `<header class="ix-head">
    <div>
      <h1 class="ix-title">FocusForge Intelligence</h1>
      <p class="ix-sub">Understand your rhythm. Improve your learning.</p>
    </div>
    <div class="ix-head-side">
      <div class="ix-meta"><span>${esc(today)}</span><span>${last ? `Analysed ${esc(rel(last))}` : 'Not analysed yet'}</span></div>
      <div class="ix-pills">${r ? stagePill(r.status && r.status.stage, 'rhythm') : ''}${l ? stagePill(l.status && l.status.stage, 'learning') : ''}</div>
      <button class="btn btn-ghost btn-sm" data-ix="analyse" ${Store.state === 'analysing' ? 'disabled' : ''}>${Store.state === 'analysing' ? 'Analysing…' : 'Re-analyse'}</button>
    </div>
  </header>`;
}

function bestPeriod(r) {
  if (!r) return null;
  const ins = (r.insights || []).find(i => i.id === 'best_period_completion');
  if (ins) return { value: cap(ins.evidence.period), sub: `${pct(ins.evidence.rate)} of attempts completed` };
  const act = r.observed && r.observed.period_activity;
  if (act && act.length) {
    const top = [...act].sort((a, b) => b.minutes - a.minutes)[0];
    if (top.minutes > 0) return { value: cap(top.period), sub: 'Most active (not yet "best")' };
  }
  return null;
}

function overview(d) {
  const r = d.rhythm, l = d.learning;
  const bp = bestPeriod(r);
  const topics = l && l.topics ? l.topics.length : 0;
  const needs = l && l.topics ? l.topics.filter(t => t.needs_revision).length : 0;
  const m = (label, value, sub) => `<div class="ix-metric"><div class="ix-metric-label">${esc(label)}</div>
    <div class="ix-metric-value">${esc(value)}</div><div class="ix-metric-sub">${esc(sub)}</div></div>`;
  return `<section class="ix-overview" aria-label="Overview">
    ${m('Sessions analysed', r ? String(r.data.total) : '—', r ? `${r.data.labelled_attempts} timer attempts with outcomes` : 'No data yet')}
    ${m('Most productive period', bp ? bp.value : '—', bp ? bp.sub : 'Needs more sessions with a start time')}
    ${m('Topics identified', topics ? String(topics) : '—', topics ? `from ${l.data.reflections_parsed} reflections` : 'Write reflections to see topics')}
    ${m('Need revision', topics ? String(needs) : '—', topics ? (needs ? 'flagged from your own words' : 'nothing flagged') : 'No topics yet')}
  </section>`;
}

/* ─── MY RHYTHM ──────────────────────────────── */
function heatmap(h) {
  if (!h) return '';
  const max = Math.max(1, ...h.rows.flatMap(r => r.minutes));
  const cells = h.rows.map(row => `
    <div class="ix-hm-day">${DAYS[row.weekday]}</div>
    ${row.minutes.map((m, hr) => `<div class="ix-hm-cell" style="--a:${m ? (0.18 + 0.82 * m / max).toFixed(2) : 0}"
      title="${esc(`${DAYS[row.weekday]} ${String(hr).padStart(2, '0')}:00 · ${Math.round(m)} min`)}"></div>`).join('')}`).join('');
  const hours = Array.from({ length: 24 }, (_, i) => `<span>${i % 6 === 0 ? i : ''}</span>`).join('');
  return `<div class="ix-block">
    <div class="ix-block-head"><h3>When you study</h3><span class="ix-note">Completed focus minutes by start time · ${h.sessions_used} sessions${h.sessions_excluded_no_start ? ` · ${h.sessions_excluded_no_start} without a start time left out` : ''}</span></div>
    <div class="ix-hm" role="img" aria-label="Heatmap of focus minutes by weekday and hour">
      ${cells}<div></div><div class="ix-hm-hours">${hours}</div>
    </div>
  </div>`;
}

function periodBlock(obs) {
  const ps = obs.period_success, act = obs.period_activity;
  if (!ps && !act) return '';
  let body = '';
  if (ps) {
    const overall = (() => { const k = ps.rows.reduce((a, r) => a + r.completed, 0), n = ps.rows.reduce((a, r) => a + r.n, 0); return n ? k / n : null; })();
    body += ps.rows.filter(r => r.n > 0).map(r => rateRow(PERIOD_LABEL[r.period], r, overall, `${PERIOD_HOURS[r.period]} h`)).join('');
    body += `<p class="ix-note">Dot = share of timer attempts completed, bar = 95% interval, tick = your overall rate. A wide bar means few attempts, so read it loosely.</p>`;
  } else if (act) {
    const max = Math.max(1, ...act.map(a => a.minutes));
    body += act.map(a => `<div class="ix-rrow"><div class="ix-rlabel">${PERIOD_LABEL[a.period]}<small>${PERIOD_HOURS[a.period]} h</small></div>
      <div class="ix-track"><div class="ix-fill" style="width:${a.minutes / max * 100}%"></div></div>
      <div class="ix-rval">${Math.round(a.minutes)}<small>min</small></div></div>`).join('');
    body += `<p class="ix-note">This shows where your minutes are, not when sessions go best. Completion patterns appear once timer attempts with outcomes (including ones stopped early) have been recorded.</p>`;
  }
  return `<div class="ix-block"><div class="ix-block-head"><h3>${ps ? 'Time of day and completion' : 'Time of day'}</h3></div>${body}</div>`;
}

function durationBlock(obs) {
  const td = obs.typical_duration, ab = obs.abandonment_by_length;
  if (!td || !td.median) return '';
  const scale = Math.max(60, td.q75 * 1.3);
  let html = `<div class="ix-block"><div class="ix-block-head"><h3>Focus duration</h3></div>
    <div class="ix-duration"><div class="ix-big">${Math.round(td.median)}<small> min</small></div>
    <div class="ix-range"><div class="ix-range-bar" style="left:${td.q25 / scale * 100}%;width:${Math.max(2, (td.q75 - td.q25) / scale * 100)}%"></div></div>
    <div class="ix-note">Median completed session · half last ${Math.round(td.q25)}–${Math.round(td.q75)} min · ${td.completed_n} sessions${td.abandoned_median_min ? ` · when you stop early it is after about ${Math.round(td.abandoned_median_min)} min` : ''}</div></div>`;
  if (ab && ab.rows.length) {
    html += `<div class="ix-sub-head">Completion by planned length</div>` + ab.rows.map(r => rateRow(r.bin, r, null)).join('');
  }
  return html + '</div>';
}

function subjectBlock(obs) {
  const sc = obs.subject_completion;
  if (!sc) return '';
  if (!sc.rows.length) return `<div class="ix-block"><div class="ix-block-head"><h3>By subject</h3></div><p class="ix-note">No subject has enough timer attempts yet (5 needed per subject${sc.hidden_subjects ? `; ${sc.hidden_subjects} below that` : ''}).</p></div>`;
  return `<div class="ix-block"><div class="ix-block-head"><h3>By subject</h3><span class="ix-note">Small groups are pulled toward your overall rate</span></div>
    ${sc.rows.map(r => rateRow(cap(r.subject), r, sc.overall_rate, r.vs_rest && r.vs_rest.reliable ? (r.vs_rest.diff > 0 ? 'reliably higher' : 'reliably lower') : '')).join('')}
    ${sc.hidden_subjects ? `<p class="ix-note">${sc.hidden_subjects} subject(s) have too few attempts to show.</p>` : ''}</div>`;
}

function weekdayBlock(obs) {
  const w = obs.weekday_consistency;
  if (!w) return '';
  if (!w.available) return `<div class="ix-block"><div class="ix-block-head"><h3>Consistency by weekday</h3></div><p class="ix-note">Needs ${w.needed_weeks}+ weeks of history (you have ${w.weeks_observed}).</p></div>`;
  return `<div class="ix-block"><div class="ix-block-head"><h3>Consistency by weekday</h3><span class="ix-note">Share of each weekday you studied · ${w.weeks_observed} weeks</span></div>
    <div class="ix-wd">${w.rows.map(r => `<div class="ix-wd-col" title="${esc(`${DAYS_LONG[r.weekday]}: studied on ${r.studied_days} of ${r.days_observed}`)}">
      <div class="ix-wd-bar"><div style="height:${(r.share || 0) * 100}%"></div></div><span>${DAYS[r.weekday]}</span></div>`).join('')}</div></div>`;
}

function modelBlock(r) {
  const c = r.model && r.model.card;
  if (!c) return '';
  let body;
  if (c.state === 'active') {
    const grid = r.model.what_if || [];
    const periods = ['morning', 'afternoon', 'evening', 'night'];
    const lengths = [...new Set(grid.map(g => g.planned_min))].sort((a, b) => a - b);
    const cell = (p, L) => {
      const g = grid.find(x => x.period === p && x.planned_min === L);
      if (!g || !g.supported) return `<td class="ix-na" title="Not enough of your sessions in this slot to estimate">·</td>`;
      return `<td style="--a:${g.probability.toFixed(2)}" title="${esc(`${pct(g.probability)} estimated completion · ${g.support_period_n} attempts in this period`)}">${Math.round(g.probability * 100)}</td>`;
    };
    const subject = grid[0] ? grid[0].subject : '';
    body = `<p class="ix-note"><strong>Model estimate</strong>, not observed. Chance of completing a ${esc(subject)} session, by start period and planned length. Blank cells are slots your history does not cover.</p>
      <table class="ix-grid"><thead><tr><th></th>${lengths.map(L => `<th>${L} min</th>`).join('')}</tr></thead>
      <tbody>${periods.map(p => `<tr><th>${PERIOD_LABEL[p]}</th>${lengths.map(L => cell(p, L)).join('')}</tr>`).join('')}</tbody></table>
      <p class="ix-note">Checked on later sessions it had not seen: AUC ${(c.metrics.auc ?? 0).toFixed(2)}, and it beat a plain base-rate guess by ${c.logloss_gain_vs_baseline.toFixed(3)} log-loss (${c.n_labelled} attempts, ${c.model} model).
      ${c.feature_group_importance && c.feature_group_importance[0] ? ` Most useful signal: ${esc(c.feature_group_importance[0].group.replace(/_/g, ' '))}.` : ''}</p>`;
  } else {
    const need = c.requirements ? c.requirements.labelled_attempts : 40;
    const have = c.n_labelled || 0;
    body = `<p class="ix-note">${esc(c.reason || 'The personal model needs more timer attempts before it can be evaluated.')}</p>
      ${c.state === 'insufficient_data' ? `<div class="ix-progress" role="progressbar" aria-valuemin="0" aria-valuemax="${need}" aria-valuenow="${have}"><div style="width:${Math.min(100, have / need * 100)}%"></div></div><div class="ix-note">${have} of ${need} labelled attempts</div>` : ''}`;
  }
  return `<div class="ix-block"><div class="ix-block-head"><h3>Predicted session completion</h3>${pill(c.state === 'active' ? 'Model' : 'Not available', c.state === 'active' ? 'ok' : 'muted')}</div>${body}</div>`;
}

function insightList(items, title) {
  if (!items || !items.length) return '';
  return `<div class="ix-block"><div class="ix-block-head"><h3>${esc(title)}</h3></div>
    <div class="ix-insights">${items.map(i => `<article class="ix-insight">
      <div class="ix-insight-top">${pill(i.kind === 'predicted' ? 'Predicted' : 'Observed', i.kind === 'predicted' ? 'warn' : 'info')}
        <span class="ix-conf" title="Confidence reflects how much data supports this">${esc(i.confidence)} confidence</span></div>
      <h4>${esc(i.title)}</h4><p>${esc(i.text)}</p>
      ${i.evidence && i.evidence.p_value != null ? `<div class="ix-note">Difference ${Math.round(Math.abs(i.evidence.diff) * 100)} points · p = ${i.evidence.p_value}</div>` : ''}
    </article>`).join('')}</div></div>`;
}

function rhythmTab(d) {
  const r = d.rhythm;
  if (!r) return empty('No rhythm analysis yet', 'Run an analysis to see your patterns.');
  const obs = r.observed || {};
  if (r.status.stage === 'collecting') return empty('Not enough data yet', r.status.message, r.status.next_unlocks);
  return `<div class="ix-stack">
    ${r.status.next_unlocks && r.status.next_unlocks.length ? `<div class="ix-banner"><strong>What unlocks next</strong>${unlocks(r.status.next_unlocks)}</div>` : ''}
    ${heatmap(obs.heatmap)}${periodBlock(obs)}${durationBlock(obs)}${subjectBlock(obs)}${weekdayBlock(obs)}${modelBlock(r)}
    ${insightList(r.insights, 'What your history shows')}
  </div>`;
}

/* ─── MY LEARNING ────────────────────────────── */
function statusDot(t) {
  const tone = t.needs_revision ? 'need' : (t.status === 'reported_confident' || t.status === 'reported_understood') ? 'ok' : 'idle';
  return `<span class="ix-sd ${tone}"></span>`;
}

function topicBoard(l) {
  const byId = Object.fromEntries(l.topics.map(t => [t.id, t]));
  return `<div class="ix-block"><div class="ix-block-head"><h3>Topics from your reflections</h3>
      <span class="ix-note"><span class="ix-sd need"></span>needs revision <span class="ix-sd ok"></span>reported understood or confident <span class="ix-sd idle"></span>mentioned</span></div>
    ${l.groups.map(g => `<div class="ix-group"><div class="ix-group-name">${esc(g.subject)}</div>
      <div class="ix-chips">${g.topic_ids.map(id => byId[id]).filter(Boolean).map(t => `
        <button class="ix-chip ${Store.openTopic === t.id ? 'active' : ''}" data-ix="topic" data-id="${esc(t.id)}">
          ${statusDot(t)}${esc(t.name)}${t.stance_counts.struggling ? `<small>${t.stance_counts.struggling}×</small>` : ''}</button>`).join('')}</div></div>`).join('')}
    <div id="ixTopicPanel">${Store.openTopic ? topicPanel(byId[Store.openTopic]) : ''}</div>
  </div>`;
}

function highlight(sentence, cue) {
  const s = String(sentence || '');
  const c = String(cue || '').replace(/^not … /, '').replace(/^not yet … /, '');
  const i = c ? s.toLowerCase().indexOf(c.toLowerCase()) : -1;
  if (i < 0) return esc(s);
  return esc(s.slice(0, i)) + `<mark>${esc(s.slice(i, i + c.length))}</mark>` + esc(s.slice(i + c.length));
}

function topicPanel(t) {
  if (!t) return '';
  const full = Store.topicCache[t.id];
  const ev = (full && full.evidence) || [];
  const sch = t.schedule;
  const c = t.stance_counts;
  const counts = ['struggling', 'revise', 'confident', 'understood', 'revised'].filter(k => c[k]).map(k => `${c[k]}× ${STANCE_LABEL[k].toLowerCase()}`).join(' · ') || 'Mentioned only';
  return `<div class="ix-panel">
    <div class="ix-panel-head"><div><h4>${esc(t.name)}</h4><div class="ix-note">${t.sessions} session${t.sessions === 1 ? '' : 's'} · ${t.revisits} revisit${t.revisits === 1 ? '' : 's'} · ${esc(counts)}</div></div>
      <button class="ix-x" data-ix="close-topic" aria-label="Close">×</button></div>
    ${(t.reasons || []).map(r => `<p class="ix-reason">${esc(r)}</p>`).join('')}
    ${sch ? `<p class="ix-note">${sch.basis === 'fsrs'
      ? `Spaced repetition: next review ${esc(dueLabel(sch.due).toLowerCase())} · estimated recall now about ${pct(sch.retrievability_now)}`
      : `Estimated revisit ${esc(dueLabel(sch.due).toLowerCase())} — an estimate from your reflection, not a measured forgetting curve`}</p>` : ''}
    <div class="ix-sub-head">Why the system thinks so — your own words</div>
    ${full ? (ev.length ? ev.map(e => `<blockquote class="ix-quote"><div>${highlight(e.sentence, e.cue)}</div>
      <small>${esc(new Date(e.when).toLocaleDateString('en', { month: 'short', day: 'numeric' }))} · read as “${esc(STANCE_LABEL[e.stance] || e.stance)}”${e.inherited ? ' · topic inferred from the previous sentence' : ''}</small></blockquote>`).join('')
        : '<p class="ix-note">No reflections stored for this topic.</p>') : '<p class="ix-note">Loading reflections…</p>'}
    <div class="ix-sub-head">How well do you recall it right now?</div>
    <div class="ix-rate" role="group" aria-label="Recall rating">${[[1, 'Forgot'], [2, 'Hard'], [3, 'Good'], [4, 'Easy']].map(([n, lbl]) =>
      `<button class="ix-rate-btn" data-ix="rate" data-id="${esc(t.id)}" data-r="${n}" ${Store.busy.has('rate') ? 'disabled' : ''}><b>${n}</b>${lbl}</button>`).join('')}</div>
    <p class="ix-note">Ratings are the only thing that moves a topic onto the spaced-repetition schedule. Writing “I understood it” is not treated as proof you remember it.</p>
  </div>`;
}

function clusterBlock(l) {
  if (!l.clusters.length) return '';
  const lexical = l.embedder && !l.embedder.semantic;
  return `<div class="ix-block"><div class="ix-block-head"><h3>Related difficulties</h3></div>
    ${lexical ? `<p class="ix-note">Grouped by word similarity. Install <code>sentence-transformers</code> on the backend to group by meaning.</p>` : ''}
    ${l.clusters.map(c => `<details class="ix-cluster"><summary><span>${esc(c.label)}</span><small>${c.size} statements · ${c.sessions} session${c.sessions === 1 ? '' : 's'}</small></summary>
      ${c.members.map(m => `<blockquote class="ix-quote"><div>${esc(m.sentence)}</div><small>${esc(new Date(m.when).toLocaleDateString('en', { month: 'short', day: 'numeric' }))}</small></blockquote>`).join('')}</details>`).join('')}</div>`;
}

function trendBlock(l) {
  const t = l.trend || [];
  if (t.length < 2) return `<div class="ix-block"><div class="ix-block-head"><h3>Learning trend</h3></div><p class="ix-note">A trend needs reflections from at least two different weeks.</p></div>`;
  const max = Math.max(1, ...t.map(w => w.struggling + w.revise + w.confident + w.understood));
  return `<div class="ix-block"><div class="ix-block-head"><h3>Learning trend</h3><span class="ix-note"><span class="ix-sw warm"></span>difficulty or revision <span class="ix-sw cool"></span>understood or confident</span></div>
    <div class="ix-trend">${t.map(w => {
      const neg = w.struggling + w.revise, pos = w.confident + w.understood;
      return `<div class="ix-trend-col" title="${esc(`${w.week}: ${neg} difficulty/revision, ${pos} understood/confident statements`)}">
        <div class="ix-trend-bar"><div class="warm" style="height:${neg / max * 100}%"></div><div class="cool" style="height:${pos / max * 100}%"></div></div>
        <span>${esc(w.week.slice(-3))}</span></div>`;
    }).join('')}</div><p class="ix-note">Counts statements in your reflections. It shows how you describe your learning, not how much you know.</p></div>`;
}

function scheduleBlock(l) {
  const rows = l.revision_schedule || [];
  if (!rows.length) return `<div class="ix-block"><div class="ix-block-head"><h3>Revision schedule</h3></div><p class="ix-note">Nothing is due. Topics appear here when your reflections flag them or you rate your recall.</p></div>`;
  return `<div class="ix-block"><div class="ix-block-head"><h3>Revision schedule</h3></div>
    <div class="ix-sched">${rows.map(r => `<button class="ix-sched-row" data-ix="topic" data-id="${esc(r.topic_id)}">
      <span class="ix-sched-name">${esc(r.name)}</span>
      <span class="ix-sched-due ${r.overdue_days > 0 ? 'late' : ''}">${esc(dueLabel(r.due))}</span>
      ${pill(r.basis === 'fsrs' ? 'Spaced repetition' : 'Estimate', r.basis === 'fsrs' ? 'ok' : 'muted')}</button>`).join('')}</div></div>`;
}

function learningTab(d) {
  const l = d.learning;
  if (!l) return empty('No learning analysis yet', 'Run an analysis to see your topics.');
  if (l.status.stage === 'collecting') return empty('No topics yet', l.status.message, l.status.next_unlocks);
  return `<div class="ix-stack">
    ${l.status.caveat ? `<div class="ix-banner">${esc(l.status.caveat)}</div>` : ''}
    ${topicBoard(l)}${scheduleBlock(l)}${clusterBlock(l)}${trendBlock(l)}
    ${l.status.next_unlocks && l.status.next_unlocks.length ? `<div class="ix-banner">${unlocks(l.status.next_unlocks)}</div>` : ''}
  </div>`;
}

/* ─── MY INSIGHTS (recommendations) ──────────── */
function recCard(r) {
  const done = r.status === 'completed' || r.status === 'dismissed';
  const actions = r.status === 'proposed'
    ? `<button class="btn btn-primary btn-sm" data-ix="accept" data-id="${esc(r.id)}">Accept &amp; add task</button><button class="btn btn-ghost btn-sm" data-ix="dismiss" data-id="${esc(r.id)}">Dismiss</button>`
    : r.status === 'accepted'
      ? `<button class="btn btn-primary btn-sm" data-ix="complete" data-id="${esc(r.id)}">Mark completed</button><button class="btn btn-ghost btn-sm" data-ix="dismiss" data-id="${esc(r.id)}">Dismiss</button>`
      : `<button class="btn btn-ghost btn-sm" data-ix="reopen" data-id="${esc(r.id)}">Reopen</button>`;
  const statusPill = r.status === 'accepted' ? pill(r.adherence === 'followed' ? 'Accepted · you studied it' : r.adherence === 'missed' ? 'Accepted · not yet studied' : 'Accepted', 'ok')
    : r.status === 'completed' ? pill('Completed', 'ok') : r.status === 'dismissed' ? pill('Dismissed', 'muted') : '';
  return `<article class="ix-rec ${done ? 'done' : ''}">
    <div class="ix-rec-top"><div class="ix-chipset">${(r.contributors || []).map(c => `<span class="ix-src ${esc(c)}">${esc(SOURCE_LABEL[c] || c)}</span>`).join('')}</div>${statusPill}</div>
    <h3>${esc(r.title)}</h3>
    <p class="ix-rec-sum">${esc(r.summary)}</p>
    <details class="ix-why"><summary>Why this recommendation</summary>
      <ul>${(r.why || []).map(w => `<li><span class="ix-src ${esc(w.source)}">${esc(SOURCE_LABEL[w.source] || w.source)}</span>${w.kind === 'predicted' ? '<span class="ix-src pred">Prediction</span>' : ''}${esc(w.text)}</li>`).join('')}</ul>
      ${(r.caveats || []).map(c => `<p class="ix-note">${esc(c)}</p>`).join('')}
    </details>
    <div class="ix-rec-actions">${actions}</div>
  </article>`;
}

function insightsTab(d) {
  const rc = d.recommendations || { items: [] };
  const items = (rc.items || []).slice().sort((a, b) => (a.status === 'proposed' ? 0 : a.status === 'accepted' ? 1 : 2) - (b.status === 'proposed' ? 0 : b.status === 'accepted' ? 1 : 2));
  const ev = rc.evaluation;
  if (!items.length) {
    const hasTopics = d.learning && d.learning.topics && d.learning.topics.length;
    return empty('No recommendations right now',
      hasTopics ? 'None of your topics is currently flagged for revision. Recommendations appear when your reflections or recall ratings point to something worth revisiting.'
        : 'Recommendations combine what you are struggling with (from your reflections) with when you study best. Write a short reflection after a session to get started.');
  }
  return `<div class="ix-stack">
    <p class="ix-lede">Suggestions built from your own sessions and reflections. Nothing is added to your tasks unless you accept it.</p>
    ${items.map(recCard).join('')}
    ${rc.deferred ? `<p class="ix-note">${rc.deferred} more topic(s) need revision; the top ${items.length} are shown to keep this manageable.</p>` : ''}
    ${ev && (ev.accepted + ev.completed + ev.dismissed) ? `<p class="ix-note ix-foot">Your responses so far: ${ev.accepted + ev.completed} accepted, ${ev.completed} completed, ${ev.dismissed} dismissed. ${esc(ev.note)}</p>` : ''}
  </div>`;
}

/* ─── PAGE ───────────────────────────────────── */
function skeleton() {
  return `<div class="ix-skel" aria-busy="true"><div class="ix-skel-row"></div><div class="ix-skel-row short"></div><div class="ix-skel-block"></div><div class="ix-skel-block"></div></div>`;
}

function errorView() {
  const e = Store.error;
  const base = { unreachable: ['Can’t reach the analysis service', `The Intelligence backend isn’t running at ${API_BASE}. Start it with:`], auth: ['Please sign in again', 'Your session expired.'], signin: ['Sign in to see your intelligence', ''], http: ['Something went wrong', 'The analysis could not be completed. Your data is untouched.'] }[e.kind] || ['Something went wrong', ''];
  return `<div class="ix-empty"><div class="ix-empty-title">${esc(base[0])}</div><p>${esc(base[1])}</p>
    ${e.kind === 'unreachable' ? `<pre class="ix-code">cd backend\npip install -r requirements.txt\nuvicorn app.main:app --port 8000</pre>` : ''}
    <button class="btn btn-ghost btn-sm" data-ix="retry">Try again</button></div>`;
}

function paint() {
  const root = document.getElementById('ixRoot');
  if (!root) return;
  const d = Store.data;
  let body;
  if (Store.state === 'loading' || (Store.state === 'analysing' && !d)) body = skeleton();
  else if (Store.state === 'error' && !d) body = errorView();
  else if (!d) body = skeleton();
  else {
    const tabs = [['insights', 'My Insights'], ['rhythm', 'My Rhythm'], ['learning', 'My Learning']];
    const panel = Store.tab === 'insights' ? insightsTab(d) : Store.tab === 'rhythm' ? rhythmTab(d) : learningTab(d);
    body = `${Store.state === 'error' ? `<div class="ix-banner warn">${esc('The last request failed: ' + (Store.error ? Store.error.kind : ''))}. Showing the last saved analysis.</div>` : ''}
      ${overview(d)}
      <div class="ix-tabs" role="tablist">${tabs.map(([id, label]) => `<button role="tab" aria-selected="${Store.tab === id}" class="ix-tab ${Store.tab === id ? 'active' : ''}" data-ix="tab" data-id="${id}">${label}</button>`).join('')}</div>
      <section class="ix-panel-wrap ${Store.state === 'analysing' ? 'dim' : ''}" role="tabpanel">${panel}</section>`;
  }
  root.innerHTML = header(d) + body;
}

/* ─── ACTIONS ────────────────────────────────── */
async function openTopic(id) {
  Store.openTopic = id;
  paint();
  if (!Store.topicCache[id]) {
    try {
      const snap = await getDoc(doc(FF().db, 'users', FF().State.user.uid, 'topics', id));
      Store.topicCache[id] = snap.exists() ? snap.data() : { evidence: [] };
    } catch (e) {
      console.warn('Could not load topic evidence:', e.message);
      Store.topicCache[id] = { evidence: [] };
    }
    if (Store.openTopic === id) paint();
  }
  document.getElementById('ixTopicPanel')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function rate(id, rating) {
  if (Store.busy.has('rate')) return;
  Store.busy.add('rate'); paint();
  try {
    await addDoc(collection(FF().db, 'users', FF().State.user.uid, 'reviews'),
      { topicId: id, rating, at: new Date().toISOString() });
    FF().Utils.toast('Recall rating saved.');
    Store.busy.delete('rate');
    await analyse();                       // reschedules from the new rating
  } catch (e) {
    console.warn('Could not save rating:', e.message);
    FF().Utils.toast('Could not save that rating.');
    Store.busy.delete('rate'); paint();
  }
}

async function setStatus(recId, status) {
  const uid = FF().State.user.uid;
  const at = new Date().toISOString();
  await updateDoc(doc(FF().db, 'users', uid, 'recommendations', recId), { status, statusUpdatedAt: at });
  const rec = Store.data.recommendations.items.find(r => r.id === recId);
  if (rec) { rec.status = status; rec.statusUpdatedAt = at; }
}

async function recAction(kind, id) {
  const rec = Store.data.recommendations.items.find(r => r.id === id);
  if (!rec || Store.busy.has(id)) return;
  Store.busy.add(id);
  try {
    if (kind === 'accept') {
      // The only place a task is created, and only because the user clicked Accept.
      const [y, m, d] = rec.action.date.split('-').map(Number);
      const text = `Revise ${rec.topic} (${rec.action.minutes} min${rec.action.period ? ', ' + rec.action.period : ''})`;
      await window.TaskManager.add(text, new Date(y, m - 1, d).toDateString());
      await setStatus(id, 'accepted');
      FF().Utils.toast('Added to your tasks.');
    } else if (kind === 'complete') { await setStatus(id, 'completed'); FF().Utils.toast('Marked as completed.'); }
    else if (kind === 'dismiss') { await setStatus(id, 'dismissed'); FF().Utils.toast('Dismissed.'); }
    else if (kind === 'reopen') { await setStatus(id, 'proposed'); }
  } catch (e) {
    console.warn('Recommendation update failed:', e.message);
    FF().Utils.toast('Could not update that recommendation.');
  }
  Store.busy.delete(id);
  paint();
}

function onClick(ev) {
  const el = ev.target.closest('[data-ix]');
  if (!el) return;
  const { ix, id, r } = el.dataset;
  if (ix === 'tab') { Store.tab = id; paint(); }
  else if (ix === 'analyse' || ix === 'retry') { Store.data ? analyse() : loadStored(); }
  else if (ix === 'topic') { Store.tab = 'learning'; openTopic(id); }
  else if (ix === 'close-topic') { Store.openTopic = null; paint(); }
  else if (ix === 'rate') rate(id, parseInt(r));
  else if (['accept', 'dismiss', 'complete', 'reopen'].includes(ix)) recAction(ix, id);
}

/* ─── PUBLIC ─────────────────────────────────── */
const Intelligence = {
  _wired: false,
  render() {
    const root = document.getElementById('ixRoot');
    if (!root) return;
    if (!this._wired) { root.addEventListener('click', onClick); this._wired = true; }
    if (Store.state === 'idle' || Store.state === 'error') loadStored();
    else paint();
  },
  _store: Store,   // exposed for tests
};
window.Intelligence = Intelligence;

/* Jobsquirrel WebUI — single master data grid + detail drawer (zero-build) */
const TOKEN = document.body.dataset.sessionToken;
const $ = (s) => document.querySelector(s);
const esc = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const STATUS_HELP = {
  QUEUED: 'In the apply queue — nothing done yet; applied when you run the queue',
  DRAFTING: 'In progress — the ad/keywords are saved but no finished documents yet',
  'NO RESULT': 'A run finished but produced nothing (no ad, no documents, no application) — re-prepare it, or remove it',
  SUBMITTED: 'Application sent — awaiting a reply',
  IN_PROGRESS: 'Application in progress (multi-step form being completed)',
  INTERVIEW: 'Interview held — awaiting the outcome',
  SCHEDULED: 'Interview booked but not happened yet — prepare for it',
  INVITED: 'Interview requested — not booked yet; reply and arrange a time',
  OFFER: 'Offer received',
  REJECTED: 'Rejected / declined by the employer',
  BLOCKED: 'Blocked — CAPTCHA, bot check or a hard wall stopped submission',
  MANUAL: 'Needs you — 2FA/CAPTCHA, or a reply that could not be auto-matched',
  PREPARED: 'Documents generated and gated, but not submitted yet',
  CLOSED: 'Closed / withdrawn / expired — no further action',
};
const QUEUE_HELP = {
  pending: 'Queued to apply (state/queue.tsv)',
  human: 'Handed to you for a human step (state/queue-human.tsv)',
  retry: 'Failed once — queued to retry',
  finished: 'Finished — the runner processed it (moved to queue.done)',
};
const T = (s) => ` title="${esc(s)}"`;
const chip = (s) => `<span class="chip ${esc((s || '').replace(/\s+/g, '_'))}"${T(STATUS_HELP[s] || '')}>${esc(s || '')}</span>`;
const md = (s) => {
  let t = esc(s || '');
  t = t.replace(/```(?:\w+)?\n?([\s\S]*?)```/g, (m, c) => `<pre>${c.replace(/\n$/, '')}</pre>`);
  t = t.replace(/^###### (.*)$/gm, '<h6>$1</h6>').replace(/^##### (.*)$/gm, '<h5>$1</h5>')
    .replace(/^#### (.*)$/gm, '<h4>$1</h4>').replace(/^### (.*)$/gm, '<h3>$1</h3>')
    .replace(/^## (.*)$/gm, '<h2>$1</h2>').replace(/^# (.*)$/gm, '<h1>$1</h1>');
  t = t.replace(/^\s*[-*+] (.*)$/gm, '<li>$1</li>');
  t = t.replace(/(?:^<li>.*<\/li>\n?)+/gm, m => '<ul>' + m + '</ul>');
  t = t.replace(/^&gt;\s?(.*)$/gm, '<blockquote>$1</blockquote>');
  t = t.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/__([^_]+)__/g, '<b>$1</b>');
  t = t.replace(/(^|[^*\w])\*([^*\n]+)\*/g, '$1<i>$2</i>').replace(/(^|[^_\w])_([^_\n]+)_/g, '$1<i>$2</i>');
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  t = t.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  t = t.replace(/^\s*---+\s*$/gm, '<hr>');
  t = t.replace(/^(?!<h\d|<ul|<li|<\/?ul|<pre|<\/?pre|<blockquote|<hr|\s*$)(.+)$/gm, '<p>$1</p>');
  return t;
};
let GRID = [], SORT = { k: 'date', dir: -1 }, D = {}, P = {}, chatOffset = 0, CHAT_TIMER = null, CHAT = { segments: [] }, CUR_PERM = null;
let SPECIAL = '', ACTIVE_METRIC = '', VISIBLE = [];
const PENDING = new Set();
function starting(label, keys) {
  LIVE_RUNNING = true;
  (keys || []).forEach(k => PENDING.add(k));
  const rc = $('#runctl'); if (rc) rc.classList.remove('hide');
  const l = $('#live'); if (l) l.textContent = '● ' + (label || 'working') + ' — starting…';
  document.querySelectorAll('#a-prepare,#a-submit,#a-reconcile,#a-prepare-shown,#a-submit-shown,#a-match,#d-body [data-act]')
    .forEach(b => { b.disabled = true; });
  renderRows();
}
function working(label) {                         // immediate "something is happening" panel
  $('#peras-body').innerHTML = `<span class="muted">${esc(label || 'working…')}</span>`;
  $('#peras').classList.remove('hide');
}
async function busyBtn(el, label, fn) {              // visible "working" state on a button
  const orig = el ? el.textContent : '';
  if (el) { el.disabled = true; el.textContent = label; }
  $('#live').textContent = '● ' + (label || 'working') + ' …';
  try { return await fn(); } finally { if (el) { el.disabled = false; el.textContent = orig; } }
}
function warn(text) {
  return new Promise(res => {
    $('#warn-text').innerHTML = md(text);
    $('#warn').classList.remove('hide');
    $('#warn-ok').onclick = () => { $('#warn').classList.add('hide'); res(true); };
    $('#warn-cancel').onclick = () => { $('#warn').classList.add('hide'); res(false); };
  });
}
const LONG = {
  rebuild: 'Rebuilding the knowledge graph re-indexes **every** source document with the LLM.\n\n' +
    '- It can take **20–30+ minutes** (longer for a big corpus).\n- It uses API tokens/quota.\n' +
    '- It runs in the background — press **⏹ Stop** in the Activity monitor to cancel.\n\nStart the rebuild?',
  update: 'An incremental graph update only processes the new/changed sources, so it is usually much faster ' +
    'than a rebuild — but it still calls the LLM and can take several minutes. Continue?',
  prepareMany: (n) => `Generating documents for **${n}** roles runs the agent once per role, so it can take ` +
    `a while and use API tokens.\n\n- Roughly a few minutes **per role**.\n- Nothing is submitted.\n` +
    `- You can **⏹ Stop** it from the Activity monitor.\n\nContinue?`,
  prepareOne: 'Generating documents for one role runs the agent for a few minutes (GraphRAG + CV + letter + gates). ' +
    'It runs in the background — nothing is submitted. Continue?',
};
window.perasClose = () => $('#peras').classList.add('hide');

async function api(path, body) {
  const o = { headers: {} };
  if (body !== undefined) { o.method = 'POST'; o.headers['Content-Type'] = 'application/json'; o.headers['X-Session'] = TOKEN; o.body = JSON.stringify(body); }
  try { return await (await fetch(path, o)).json(); } catch (e) { return { error: String(e) }; }
}
let _toastTimer = null;
function toast(msg, bad) {
  let t = document.getElementById('toast');
  if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t); }
  t.className = 'toast ' + (bad ? 'bad' : 'ok') + ' show';   // one notification surface, never a stack
  t.textContent = msg;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.classList.remove('show'), 6000);
}

const App = {
  async run(command) {
    if (command === 'submit_queue') {
      const ok = await approve('Run the apply queue — this SUBMITS applications and is irreversible.',
        'POST /api/action/run { "command": "submit_queue", "approval_token": "APPROVE_RUN_QUEUE" }');
      if (!ok) return;
    }
    starting(command);
    const d = await api('/api/action/run', { command, approval_token: command === 'submit_queue' ? 'APPROVE_RUN_QUEUE' : '' });
    toast(d.ok || d.error, !!d.error); if (!d.error) { openDock(true); } else { LIVE_RUNNING = false; liveTick(); }
  },
  cf: async (target) => {
    document.querySelectorAll('#cf-tabs a').forEach(a => a.classList.toggle('on', a.dataset.t === target));
    const d = await api('/api/config?target=' + target); CF = target; $('#cf-text').value = d.content || ''; $('#cf-msg').textContent = '';
  },
  cfSave: async () => { const d = await api('/api/config', { target: CF, content: $('#cf-text').value }); $('#cf-msg').textContent = d.ok || d.error; toast(d.ok || d.error, !!d.error); },
  settings: async (sec) => {
    CF_SEC = sec || CF_SEC || 'accounts';
    document.querySelectorAll('.set-nav a').forEach(a => a.classList.toggle('on', a.dataset.s === CF_SEC));
    const b = $('#set-body'); b.innerHTML = '<span class="muted">loading…</span>';
    if (CF_SEC === 'accounts') return setAccounts(b);
    if (CF_SEC === 'ai') return setAI(b);
    if (CF_SEC === 'kb') return setKB(b);
    if (CF_SEC === 'graph') return setGraph(b);
    if (CF_SEC === 'perms') return setPerms(b);
    return setProfile(b);
  },
  auth: async (kind) => { const d = await api('/api/accounts/auth', { kind }); toast(d.ok || d.error, !!d.error); },
  savePerms: async () => {
    const policy = {}; document.querySelectorAll('#set-body select[data-cat]').forEach(s => policy[s.dataset.cat] = s.value);
    const d = await api('/api/permissions', { policy }); toast(d.error ? d.error : 'permissions saved', !!d.error);
  },
  aiAdd: () => {
    const k = $('#ai-env-k').value.trim(), v = $('#ai-env-v').value;
    if (!k) { toast('name the key first', true); return; }
    const box = $('#ai-env'); if (box.querySelector('span.muted')) box.innerHTML = '';
    const row = document.createElement('div'); row.className = 'row'; row.style.margin = '3px 0';
    row.innerHTML = `<code style="min-width:190px">${esc(k)}</code>
      <input data-env="${esc(k)}" value="${esc(v)}" style="flex:1"><button class="small" onclick="this.parentElement.remove()">✕</button>`;
    box.appendChild(row); $('#ai-env-k').value = ''; $('#ai-env-v').value = '';
  },
  aiDel: (k) => { const el = document.querySelector(`#ai-env input[data-env="${k}"]`); if (el) el.closest('.row').remove(); },
  saveAI: async () => {
    const env = {}; document.querySelectorAll('#ai-env input[data-env]').forEach(i => { if (i.value) env[i.dataset.env] = i.value; });
    const d = await api('/api/agent/config', { agent: $('#ai-agent').value, model: $('#ai-model').value, env });
    toast(d.ok || d.error, !!d.error); if (!d.error) App.settings('ai');
  },
  saveGR: async () => {
    const vars = {}; document.querySelectorAll('#ai-gr input[data-gr]').forEach(i => { if (i.value) vars[i.dataset.gr] = i.value; });
    const d = await api('/api/graphrag/env', { vars });
    toast(d.ok || d.error, !!d.error); if (!d.error) App.settings('ai');
  },
  kbDel: async (path) => { const d = await api('/api/kb/delete', { path }); toast(d.ok || d.error, !!d.error); if (!d.error) App.settings('kb'); },
  kbUpload: async () => {
    const inp = $('#kb-file'), grp = $('#kb-group').value.trim() || 'imported';
    if (!inp.files.length) { toast('choose file(s) first', true); return; }
    const fd = new FormData(); fd.append('group', grp);
    for (const f of inp.files) fd.append('files', f, f.name);
    try {
      const r = await fetch('/api/kb/upload', { method: 'POST', headers: { 'X-Session': TOKEN }, body: fd });
      const d = await r.json(); toast(d.ok || d.error, !!d.error); if (!d.error) App.settings('kb');
    } catch (e) { toast('upload failed: ' + e, true); }
  },
  graphLoad: async () => {
    const kind = $('#g-kind').value, q = $('#g-q').value.trim();
    $('#g-res').innerHTML = '<span class="muted">reading the graph…</span>';
    const d = await api(`/api/graph?kind=${kind}&q=${encodeURIComponent(q)}&limit=300`);
    if (d.error) { $('#g-res').innerHTML = `<span class="muted">${esc(d.error)}</span>`; return; }
    const rows = d.rows || [];
    if (kind === 'entities') $('#g-res').innerHTML = `<div class="muted mini">${rows.length} entities</div><table><tbody>` +
      rows.map(r => `<tr><td><b>${esc(r.title)}</b><div class="muted mini">${esc(r.type)} · degree ${r.degree}</div></td>
        <td class="muted mini">${esc((r.description || '').slice(0, 220))}</td></tr>`).join('') + '</tbody></table>';
    else if (kind === 'relationships') $('#g-res').innerHTML = `<div class="muted mini">${rows.length} relationships</div><table><tbody>` +
      rows.map(r => `<tr><td class="mini"><b>${esc(r.source)}</b> → <b>${esc(r.target)}</b> <span class="muted">w${r.weight}</span></td>
        <td class="muted mini">${esc((r.description || '').slice(0, 200))}</td></tr>`).join('') + '</tbody></table>';
    else if (kind === 'communities') $('#g-res').innerHTML = `<div class="muted mini">${rows.length} communities</div><table><tbody>` +
      rows.map(r => `<tr><td class="mini"><b>${esc(r.title)}</b><div class="muted">level ${r.level} · ${r.size} entities</div></td>
        <td class="muted mini">${esc((r.summary || '').slice(0, 240))}</td></tr>`).join('') + '</tbody></table>';
    else $('#g-res').innerHTML = `<table><tbody>` + rows.map(r =>
      `<tr><td class="mini">${esc(r.title)}</td><td class="muted mini">${r.chars} chars</td></tr>`).join('') + '</tbody></table>';
  },
  chat: async () => {
    const inp = $('#chatmsg'), m = inp.value.trim(); if (!m) return;
    CHAT.running = true; setSpin(true); renderChat();
    const d = await api('/api/chat', { message: m });
    if (d.error) { toast(d.error, true); CHAT.running = false; setSpin(false); renderChat(); return; }  // keep your text
    inp.value = '';
    if (d.queued) toast(`queued — the agent is busy (${d.pending} waiting)`);
    chatOffset = 0; clearInterval(CHAT_TIMER); CHAT_TIMER = setInterval(chatPoll, 1200);
  },
  newChat: async () => {
    const d = await api('/api/chat/new', {});
    if (d.error) { toast(d.error, true); return; }
    clearInterval(CHAT_TIMER); CHAT_TIMER = null;
    CHAT = { segments: [], running: false }; setSpin(false); renderChat(); toast('agent history cleared');
  },
  open: (i) => openDetail(GRID[i]),
  metric: (kind) => {
    if (kind === 'total') { SPECIAL = ''; ACTIVE_METRIC = ''; $('#fstatus').value = ''; $('#fqueue').value = ''; }
    else if (ACTIVE_METRIC === kind) { SPECIAL = ''; ACTIVE_METRIC = ''; $('#fstatus').value = ''; $('#fqueue').value = ''; }
    else {
      ACTIVE_METRIC = kind; SPECIAL = ''; $('#fstatus').value = ''; $('#fqueue').value = '';
      if (kind === 'interviews') $('#fstatus').value = 'INTERVIEW';
      else if (kind === 'offers') $('#fstatus').value = 'OFFER';
      else if (kind === 'human') $('#fqueue').value = 'human';
      else SPECIAL = kind;                                  // in_process / blocked / submissions
    }
    document.querySelectorAll('#metrics .metric').forEach(m => m.classList.toggle('on', m.dataset.metric === ACTIVE_METRIC));
    renderRows();
  },
  prepareRoles: async (keys) => {
    const n = (keys || []).length;
    if (n && !await warn(n > 1 ? LONG.prepareMany(n) : LONG.prepareOne)) return;
    starting('preparing documents', keys); working('Preparing documents for ' + n + ' role(s)…');
    const d = await api('/api/prepare', { keys });
    toast(d.ok || d.error, !!d.error);
    if (!d.error) { openDock(true); } else { PENDING.clear(); $('#peras').classList.add('hide'); }
  },
  prepareThis: (key) => App.prepareRoles([key]),
  prepareShown: () => App.prepareRoles(VISIBLE),
  submitRoles: async (keys) => {
    const n = (keys || []).length;
    if (!n) { toast('no prepared rows to submit — prepare them first', true); return; }
    if (!await approve(`Submit ${n} prepared application(s) — this SENDS them through the employer's site and is irreversible.`,
      `POST /api/submit { "keys": [${n} role key(s)], "approval_token": "APPROVE_RUN_QUEUE" }`)) return;
    starting('submitting applications', keys); working('Submitting ' + n + ' application(s)…');
    const d = await api('/api/submit', { keys, approval_token: 'APPROVE_RUN_QUEUE' });
    toast(d.ok || d.error, !!d.error);
    if (!d.error) { openDock(true); } else { PENDING.clear(); LIVE_RUNNING = false; liveTick(); }
  },
  submitThis: (key) => App.submitRoles([key]),
  submitPrepared: () => App.submitRoles(GRID.filter(r => r.status === 'PREPARED' && VISIBLE.includes(r.key)).map(r => r.key)),
  matchShown: async (el) => busyBtn(el, '⏳ recomputing match…', async () => {
    const d = await api('/api/match/recompute', { keys: VISIBLE });
    toast(d.error ? d.error : 'match recomputed for the rows shown', !!d.error);
    if (!d.error) loadGrid();
  }),
  matchThis: async (key, el) => busyBtn(el, '⏳ recomputing…', async () => {
    const d = await api('/api/match/recompute', { keys: [key] });
    toast(d.error ? d.error : 'match recomputed', !!d.error);
    if (!d.error) { await loadGrid(); if (CUR) openDetail(CUR); }
  }),
  stop: async () => { const d = await api('/api/action/stop', {}); toast(d.ok || d.error, !!d.error); },
  togglePause: async (on) => { const d = await api('/api/action/pause', { on }); toast(d.ok || d.error, !!d.error); },
  queueAct: async (action, company, role) => {
    if (action === 'human') { starting('opening a browser for you'); working('Opening a visible Camoufox browser — pre-filling the form…'); }
    const d = await api('/api/queue/action', { action, company, role });
    toast(d.ok || d.error, !!d.error); if (!d.error) { loadGrid(); if (action !== 'human' && action !== 'delete') openDetail(CUR); } else { LIVE_RUNNING = false; }
  },
  openPage: async (company, role) => { const d = await api('/api/open', { company, role }); toast(d.ok || d.error, !!d.error); },
  addEvidence: (skill, key) => {
    $('#evid-skill').value = skill || ''; $('#evid-source').value = ''; $('#evid-detail').value = '';
    $('#evid').classList.remove('hide'); $('#evid-source').focus();
  },
  saveEvidence: async () => {
    const d = await api('/api/skills/evidence', { skill: $('#evid-skill').value, source: $('#evid-source').value,
      detail: $('#evid-detail').value, key: CUR ? CUR.key : '' });
    if (d.error) { toast(d.error, true); return; }
    $('#evid').classList.add('hide');
    loadGrid();                                       // fit updates immediately
    if (CUR) openDetail(CUR);
    toast('saved — the fit across roles now counts it (no re-prepare needed)');
  },
  updateKB: async () => {
    if (!await warn(LONG.update)) return;
    starting('updating the knowledge graph'); working('Updating the knowledge graph (incremental — only the new source)…');
    const d = await api('/api/action/run', { command: 'kb_update', approval_token: '' });
    toast(d.ok || d.error, !!d.error); if (!d.error) openDock(true); else { LIVE_RUNNING = false; $('#peras').classList.add('hide'); }
  },
  rebuildKB: async () => {
    if (!await warn(LONG.rebuild)) return;
    starting('rebuilding the knowledge graph'); working('Rebuilding the knowledge graph (full re-index — can take 20–30+ min)…');
    const d = await api('/api/kb/rebuild', {}); toast(d.ok || d.error, !!d.error); if (!d.error) openDock(true); else { LIVE_RUNNING = false; $('#peras').classList.add('hide'); }
  },
  saveRow: async () => {
    const d = await api('/api/register/row', { company: CUR.company, role: CUR.role, status: $('#dt-status').value, notes: $('#dt-notes').value, employment: $('#dt-emp') ? $('#dt-emp').value : undefined });
    toast(d.ok || d.error, !!d.error); if (!d.error) { loadGrid(); }
  },
};
let CF = 'cv.json', CUR = null, CF_SEC = 'accounts';

/* ---------- approval ---------- */
function approve(purpose, callText) {
  return new Promise(res => {
    $('#ap-text').textContent = purpose;
    $('#ap-cmd').textContent = callText;
    $('#ap-check').checked = false; $('#ap-confirm').disabled = true; $('#approve').classList.remove('hide');
    $('#ap-confirm').onclick = () => { $('#approve').classList.add('hide'); res(true); };
    $('#ap-cancel').onclick = () => { $('#approve').classList.add('hide'); res(false); };
    $('#ap-check').onchange = () => { $('#ap-confirm').disabled = !$('#ap-check').checked; };
  });
}

/* ---------- grid ---------- */
let GRID_TIMER = null, LIVE_RUNNING = false, IDLE_TICKS = 0, WAS_BUSY = false, DTAB = 0;
async function loadGrid() {
  const sc = document.querySelector('.scroll'), y = sc ? sc.scrollTop : 0;
  const [g, s] = await Promise.all([api('/api/grid'), api('/api/state')]);
  GRID = Array.isArray(g) ? g : [];
  $('#metrics').innerHTML =
    `<span class="metric hero" data-metric="in_process"${T('Applications still live: submitted + in progress + interviews + offers — click to filter')}><b>${s.kpis.in_process}</b>in process</span>` +
    `<span class="metric" data-metric="interviews"${T('Applications that reached at least one interview — click to filter')}><b>${s.kpis.interviews}</b>interviews</span>` +
    `<span class="metric" data-metric="blocked"${T('Blocked or manual — click to filter')}><b>${s.kpis.blocked}</b>blocked</span>` +
    `<span class="metric" data-metric="human"${T('Roles waiting on you — click to filter')}><b>${s.kpis.human}</b>human</span>` +
    `<span class="metric" data-metric="offers"${T('Offers received — click to filter')}><b>${s.kpis.offers}</b>offers</span>` +
    `<span class="metric" data-metric="total"${T('All rows — click to clear filters')}><b>${s.kpis.total}</b>total</span>` +
    `<span class="metric" data-metric="submissions"${T('Submissions with recorded provenance — click to filter')}><b>${s.kpis.submissions}</b>submissions</span>`;
  document.querySelectorAll('#metrics .metric').forEach(m => m.onclick = () => App.metric(m.dataset.metric));
  renderRows();
  if (sc) sc.scrollTop = y;
}
async function gridTick() {                 // keep the grid live (faster while a run is active)
  await loadGrid();
  setTimeout(gridTick, LIVE_RUNNING ? 3000 : 8000);
}
function renderRows() {
  const q = $('#q').value.toLowerCase(), st = $('#fstatus').value, qq = $('#fqueue').value;
  const ft = $('#ftype') ? $('#ftype').value : '';
  const cy = String(new Date().getFullYear());
  const shortDate = (d) => { const [y, m, dd] = d.split('-'); return y === cy ? `${m}-${dd}` : `${y.slice(2)}-${m}-${dd}`; };
  const disp = (r) => r.label || r.status;               // INTERVIEW rows show SCHEDULED when an interview is still ahead
  const statusMatch = (r) => !st || (st === 'INTERVIEW' ? ['INTERVIEW', 'SCHEDULED', 'INVITED'].includes(disp(r)) : disp(r) === st);
  const typeMatch = (r) => !ft || (ft === '__none' ? !r.employment : (r.employment || '') === ft);
  let rows = GRID.filter(r => statusMatch(r) && typeMatch(r) && (!qq || r.queue === qq) &&
    (!q || (r.company + ' ' + r.role + ' ' + (r.ats || '')).toLowerCase().includes(q)));
  if (SPECIAL === 'in_process') rows = rows.filter(r => ['SUBMITTED', 'IN_PROGRESS', 'INTERVIEW', 'OFFER'].includes(r.status));
  else if (SPECIAL === 'blocked') rows = rows.filter(r => ['BLOCKED', 'MANUAL'].includes(r.status));
  else if (SPECIAL === 'applied') rows = rows.filter(r => r.applied);
  VISIBLE = rows.map(r => r.key);
  const k = SORT.k;
  const rank = (r) => r.running ? 0 : (r.status === 'QUEUED' ? 1 : 2);   // in-flight + queued float to the top
  rows = rows.slice().sort((a, b) => {
    const ra = rank(a), rb = rank(b);
    if (ra !== rb) return ra - rb;
    const av = a[k] || '', bv = b[k] || '';
    return av < bv ? -SORT.dir : av > bv ? SORT.dir : 0;
  });
  $('#count').textContent = `${rows.length} / ${GRID.length} rows`;
  const mbadge = (r) => r.match == null ? '<span class="muted"' + T('No score — this role has no saved job ad (ATS keywords) and/or no CV to compare') + '>—</span>'
    : `<span class="badge ${r.match >= 70 ? 'good' : r.match >= 40 ? 'mid' : 'bad'}"${T("CV-to-job fit: this % of the ad's ATS keywords are covered by the tailored CV")}>${r.match}%</span>`
      + (r.alignment === 'FAIL' ? ' <span class="badge bad"' + T('Pre-submit alignment gate FAILED for this role — open the row to see why') + '>✗</span>' : '');
  $('#rows').innerHTML = rows.map((r) => {
    const i = GRID.indexOf(r);
    return `<tr class="click" onclick="App.open(${i})">` +
      `<td class="muted"${T(r.date ? 'Register row last updated ' + r.date : 'Not dated yet — queued, not applied')}>${r.date ? esc(shortDate(r.date)) : '—'}</td>` +
      `<td${T(r.company + '  ·  employer / recruiter')}>${(r.running || PENDING.has(r.key)) ? '<span class="spin" title="Being worked on now">🥜</span> ' : ''}${esc(r.company)}</td>` +
      `<td${T(r.role + (r.employment ? '  ·  ' + r.employment : '') + '  ·  job title')}>${esc(r.role)}${r.employment && r.employment !== 'full-time' ? ` <span class="etag">${esc(r.employment)}</span>` : ''}</td>` +
      `<td class="muted"${T(r.ats ? 'Submitted through ' + r.ats + ' (the employer’s applicant-tracking system)' : 'No ATS recorded')}>${esc(r.ats)}</td>` +
      `<td>${chip(r.label || r.status)}${r.hint ? `<div class="mini muted whycell"${T(r.hint)}>${esc(r.hint.slice(0, 66))}</div>` : ''}</td><td>${mbadge(r)}</td>` +
      `<td${T(QUEUE_HELP[r.queue] || 'Not in any queue')}>${['pending', 'human', 'retry'].includes(r.queue)
        ? `<span class="badge ${r.queue === 'human' ? 'bad' : r.queue === 'retry' ? 'mid' : 'good'}">${esc(r.queue)}</span>`
        : `<span class="muted">—</span>`}</td>` +
      `<td${T(r.applied ? 'Provenance recorded — exact CV, letter and SHA-256 hashes on file' : 'No submission recorded (not applied, or not reconciled yet)')}>${r.applied ? '✓' : '<span class="muted">—</span>'}</td>` +
      `<td${T(r.spec ? 'A saved job description exists — open the row for the ad, ATS keywords and grounded context' : 'No saved job description')}>${r.spec ? '✓' : '<span class="muted">—</span>'}</td></tr>`;
  }).join('') || '<tr><td colspan=9 class="muted">no matching rows</td></tr>';
}
document.querySelectorAll('#grid th[data-s]').forEach(th => th.onclick = () => { const k = th.dataset.s; SORT = { k, dir: SORT.k === k ? -SORT.dir : 1 }; renderRows(); });

/* ---------- detail drawer ---------- */
async function openDetail(r) {
  if (!r) return;
  CUR = r; D = {}; P = {};
  setPanel('detail', { open: true });
  $('#d-title').textContent = `${r.company} — ${r.role}`;
  const tabs = ['Summary', 'Provenance', 'Job spec', 'ATS', 'Grounding', 'Documents'];
  $('#dtabs').innerHTML = tabs.map((t, i) => `<a class="${i === DTAB ? 'on' : ''}" onclick="dt(${i})">${t}</a>`).join('');
  $('#d-body').innerHTML = '<span class="muted">loading…</span>';
  const jobs = [api(`/api/provenance?company=${encodeURIComponent(r.company)}&role=${encodeURIComponent(r.role)}`)];
  if (r.spec) jobs.push(api('/api/roles/' + encodeURIComponent(r.key)));
  const [p, d] = await Promise.all(jobs); P = p || {}; D = d || {};
  dt(DTAB);
}
window.dt = (i) => {
  const r = CUR, map = [summary, prov, spec, ats, grounding, tailored];
  DTAB = i;
  document.querySelectorAll('#dtabs a').forEach((a, n) => a.classList.toggle('on', n === i));
  $('#d-body').innerHTML = map[i](r) || '<span class="muted">—</span>';
};
const sec = (s, raw) => s ? (raw ? `<pre class="doc">${esc(s)}</pre>` : `<div class="doc md">${md(s)}</div>`) : '<span class="muted">(nothing yet)</span>';
const vbtn = (f, t) => f ? ` <button class="mini" onclick='viewDoc(${JSON.stringify(f)},"${t}")'>view</button>` : '';
function summary(r) {
  const m = (D.match) || {};
  const reg = ['QUEUED', 'PREPARED', 'SUBMITTED', 'IN_PROGRESS', 'INTERVIEW', 'OFFER', 'REJECTED', 'BLOCKED', 'MANUAL', 'CLOSED'];
  const known = reg.includes(r.status);
  const notes = (r.notes || '').trim();
  const hist = notes ? notes.split(/\s*\|\s*/).filter(Boolean).map(x => `<li>${md(x)}</li>`).join('') : '';
  return `<div class="statebox">
      <div class="row">${chip(r.label || r.status)}${r.hint ? `<span class="statehint">${esc(r.hint)}</span>` : ''}</div>
      <div class="stages">${(() => {
        const st = r.stages || {};
        const cell = (k, label) => `<span class="stage ${st[k] ? 'on' : ''}" title="${st[k] ? 'done' : 'not yet'}">${st[k] ? '✓' : '○'} ${label}</span>`;
        return cell('ad', 'Ad saved') + cell('keywords', 'Keywords') + cell('grounding', 'Grounded') + cell('documents', 'Documents') + cell('applied', 'Applied');
      })()}</div>
      <div class="state-meta mini muted">ATS: ${esc(r.ats || '—')}${r.employment ? ' · type: ' + esc(r.employment) : ''} · Queue: ${esc(r.queue || 'not queued')}${r.date ? ' · updated ' + esc(r.date) : ''}${r.interview_at ? ' · interview ' + esc(r.interview_at) : ''} · <span class="mono">${esc(r.key)}</span></div>
      ${r.running ? '<div class="working"><span class="spin">🥜</span> being worked on right now</div>' : ''}
    </div>` +
    `<div class="row" style="margin:6px 0 10px"><span class="muted">Set status</span>
      <select id="dt-status"><option value="">— keep as ${esc(r.label || r.status || 'is')} —</option>` +
      reg.map(x => `<option ${x === r.status ? 'selected' : ''}>${x}</option>`).join('') + '</select>' +
      `<span class="muted">Type</span><select id="dt-emp">` +
      ['', 'full-time', 'part-time', 'contract', 'consultant', 'freelance', 'internship', 'temporary']
        .map(x => `<option value="${x}" ${x === (r.employment || '') ? 'selected' : ''}>${x || '— unknown —'}</option>`).join('') + '</select>' +
      `<button onclick="App.saveRow()">Save</button>
      <button data-act onclick='App.prepareThis(${JSON.stringify(r.key)})'>Prepare this role</button>
      ${r.status === 'PREPARED' ? `<button class="risky" data-act onclick='App.submitThis(${JSON.stringify(r.key)})' title="Submit this application now with the documents already prepared — sends it, needs approval">🚀 Submit this application</button>` : ''}
      <button data-act onclick='App.matchThis(${JSON.stringify(r.key)}, this)'>Recompute match</button></div>` +
    `<div class="row">${m.alignment ? `<span class="badge ${m.alignment === 'PASS' ? 'good' : 'bad'}">alignment ${m.alignment}</span>` : ''}` +
    `${m.coverage != null ? `<span class="badge ${m.coverage >= 70 ? 'good' : 'mid'}">coverage ${m.coverage}%</span>` : ''}${known ? '' : '<span class="muted mini">(runner-derived state)</span>'}</div>` +
    (m.missing && m.missing.length ? `<div class="muted mini" style="margin-top:8px">missing skills — click one to add where you have it:
      <div style="margin-top:4px">${m.missing.map(x => {
        const ev = (m.evidenced || []).some(e => e.toLowerCase() === x.toLowerCase());
        return `<a class="missk${ev ? ' evidenced' : ''}" title="${ev ? 'you have recorded evidence — re-prepare this role to apply it (grounding already includes it)' : 'click to record where you have this skill'}" onclick='App.addEvidence(${JSON.stringify(x)},${JSON.stringify(r.key)})'>${ev ? '✓ ' : ''}${esc(x)}</a>`;
      }).join('')}</div></div>
      ${(m.evidenced || []).length ? `<div class="row" style="margin-top:6px"><span class="muted mini">${m.evidenced.length} skill(s) have evidence — re-prepare this role to fold them into the CV (grounding includes them now).</span>
        <button class="small" onclick='App.prepareThis(${JSON.stringify(r.key)})'>↻ Re-prepare with the new evidence</button></div>` : ''}` : '') +
    `<div class="why" style="margin-top:12px"><div class="why-h"><span class="muted mini">WHY / HISTORY</span></div>
      ${hist ? `<ul class="hist">${hist}</ul>` : '<div class="muted">no notes recorded for this row</div>'}
      ${P.evidence ? `<div class="muted mini" style="margin-top:6px">submission evidence: ${esc(String(P.evidence).slice(0, 240))}</div>` : ''}</div>` +
    `<div class="muted mini" style="margin:12px 0 4px">your notes (editable)</div><textarea id="dt-notes" style="min-height:12vh">${esc(r.notes || '')}</textarea>` +
    `<div class="row" style="margin-top:8px"><button onclick="App.saveRow()">Save notes</button></div>` +
    (['BLOCKED', 'MANUAL'].includes(r.status) ? `<div class="why resolve">
      <div class="why-h"><span class="muted mini">GET PAST THE BLOCK</span></div>
      ${r.url ? `<a class="mini" href="${esc(r.url)}" target="_blank">${esc(r.url.slice(0, 70))}</a>` : '<span class="muted mini">no apply URL recorded</span>'}
      <div class="row" style="margin-top:8px">
        <button class="risky" onclick='App.queueAct("human",${JSON.stringify(r.company)},${JSON.stringify(r.role)})' title="Opens a VISIBLE browser, pre-fills everything (identity, EEO answers, your prepared CV and cover letter), then waits for you to solve the CAPTCHA/2FA and press Submit">🖐 Autofill &amp; finish</button>
        <button onclick='App.queueAct("retry",${JSON.stringify(r.company)},${JSON.stringify(r.role)})' title="Re-queue this role for another automated attempt">↻ Retry</button>
        <button onclick='App.queueAct("unblock",${JSON.stringify(r.company)},${JSON.stringify(r.role)})' title="Clear the blocked status and re-queue">✓ Unblock</button>
        ${r.url ? `<button onclick='App.openPage(${JSON.stringify(r.company)},${JSON.stringify(r.role)})' title="Open the apply page in your own browser">🌐 Open page</button>` : ''}
      </div></div>` : '');
}
function prov(r) {
  const st = ((r && r.status) || '').toUpperCase();
  if (!Object.keys(P).length) {
    if (['SUBMITTED', 'IN_PROGRESS', 'INTERVIEW', 'OFFER'].includes(st))
      return `<span class="muted">This row is <b>${esc(st)}</b> but has no provenance entry — it predates the ledger, or was recorded by hand. Provenance is written automatically by <code>record_submission.py</code>; backfill an old one with <code>--inferred</code>.</span>`;
    return `<span class="muted">No submission recorded for this role${st ? ' (status ' + esc(st) + ')' : ''}. The provenance ledger is written by <code>record_submission.py</code> the moment an application is sent, so rows that were never applied to are empty by design.</span>`;
  }
  const sha = (s) => s ? `<span class="sha" title="copy" onclick='navigator.clipboard.writeText(${JSON.stringify(s)})'>${esc(s.slice(0, 16))}…</span>` : '—';
  return `<table><tbody>` +
    `<tr><td class="muted">CV</td><td>${esc(P.cv_file || '—')} ${sha(P.cv_sha256)}${vbtn(P.cv_file, 'CV')}</td></tr>` +
    `<tr><td class="muted">letter</td><td>${esc(P.letter_file || '—')} ${sha(P.letter_sha256)}${vbtn(P.letter_file, 'Cover letter')}</td></tr>` +
    `<tr><td class="muted">confidence</td><td>${chip((P.confidence || '').toUpperCase())}</td></tr>` +
    `<tr><td class="muted">evidence</td><td class="md">${P.evidence ? md(P.evidence) : '—'}</td></tr>` +
    `<tr><td class="muted">recorded</td><td class="mini muted">${esc(P.date || '—')}</td></tr>` +
    `<tr><td class="muted">snapshot</td><td class="mini mono">${esc(P.snapshot_dir || '—')}</td></tr>` +
    `<tr><td class="muted">screenshots</td><td class="mini mono">${(P.screenshots || []).map(esc).join('<br>') || '—'}</td></tr></tbody></table>`;
}
const spec = () => sec(D.jd), ats = () => sec(D.ats, true), kb = () => sec(D.kb);
function tailored() {
  const d = D.docs || {};
  if (!d.cv && !d.cv_pdf && !d.letter && !d.letter_pdf) {
    return '<span class="muted">No rendered documents yet — run Prepare (review).</span>';
  }
  const raw = (p) => '/raw?path=' + encodeURIComponent(p);
  setTimeout(async () => {
    const el = $('#tpre'); if (!el) return;
    if (d.cv_pdf) {                                       // embedded PDF viewer (the real rendered CV)
      el.innerHTML = `<embed src="${raw(d.cv_pdf)}#view=FitH" type="application/pdf"
        style="width:100%;height:74vh;border:1px solid var(--line);border-radius:8px">`;
      return;
    }
    if (d.cv) {
      const f = await api('/api/file?path=' + encodeURIComponent(d.cv));
      el.innerHTML = (f && f.kind === 'docx') ? `<div class="md">${f.html}</div>`
        : `<span class="muted">${esc((f && f.error) || 'could not render')}</span>`;
      return;
    }
    el.innerHTML = '<span class="muted">no CV file for this role</span>';
  }, 0);
  return `<div class="row" style="margin-bottom:8px">
      ${d.cv_pdf ? `<button onclick='viewDoc(${JSON.stringify(d.cv_pdf)},"CV (PDF)")'>Open CV PDF</button>` : ''}
      ${d.cv ? `<button onclick='viewDoc(${JSON.stringify(d.cv)},"CV (Word)")'>CV (Word)</button>` : ''}
      ${d.letter_pdf ? `<button onclick='viewDoc(${JSON.stringify(d.letter_pdf)},"Cover letter (PDF)")'>Open cover letter PDF</button>` : ''}
      ${d.letter ? `<button onclick='viewDoc(${JSON.stringify(d.letter)},"Cover letter (Word)")'>Cover letter (Word)</button>` : ''}
      ${d.cv_pdf ? `<a class="mini" style="align-self:center" href="${raw(d.cv_pdf)}" target="_blank">open in a tab ↗</a>` : ''}</div>` +
    `<div class="muted mini" style="margin-bottom:4px">CV${d.cv_pdf ? ' (PDF)' : ''}</div><div id="tpre">loading…</div>` +
    `<details style="margin-top:12px"><summary class="muted mini">content pack (JSON)</summary>` +
    `<pre class="doc">${esc((D.tailored_cv || '') + (D.letter ? '\n\n---\n' + D.letter : ''))}</pre></details>`;
}
function grounding(r) {
  setTimeout(async () => {
    const el = $('#grd'); if (!el) return;
    const d = await api('/api/grounding?key=' + encodeURIComponent(r.key || ''));
    if (d.error) { el.innerHTML = `<span class="muted">${esc(d.error)}</span>`; return; }
    el.innerHTML =
      `<p class="muted">How the knowledge graph was used for this role: the grounding pack cites
        <b>${d.cited_entities || 0}</b> entities and <b>${d.cited_sources || 0}</b> source documents.</p>` +
      ((d.entities || []).length ? `<h4>Entities cited</h4><table><tbody>${d.entities.map(e =>
        `<tr><td><b>${esc(e.title)}</b> <span class="muted mini">${esc(e.type)}</span></td>
          <td class="muted mini">${esc(e.description || '')}</td></tr>`).join('')}</tbody></table>` : '') +
      ((d.documents || []).length ? `<h4>Source documents</h4><ul class="mini">${d.documents.map(x =>
        `<li>${esc(x.title)} <span class="muted">(${x.chars} chars)</span></li>`).join('')}</ul>` : '') +
      `<h4>Context pack</h4><div class="md">${md(d.pack || '(none — this role has no grounding pack)')}</div>`;
  }, 0);
  return '<div id="grd"><span class="muted">loading grounding…</span></div>';
}

window.docClose = () => $('#docv').classList.add('hide');
window.viewDoc = async (rel, title) => {
  if (!rel) return;
  $('#docv-title').textContent = title || String(rel).split('/').pop();
  $('#docv-raw').href = '/raw?path=' + encodeURIComponent(rel);
  $('#docv-body').innerHTML = '<span class="muted">loading…</span>';
  $('#docv').classList.remove('hide');
  const d = await api('/api/file?path=' + encodeURIComponent(rel));
  if (!d || d.error) { $('#docv-body').innerHTML = `<span class="muted">${esc((d && d.error) || 'not found')}</span>`; return; }
  if (d.kind === 'docx') $('#docv-body').innerHTML = `<div class="md">${d.html}</div>`;
  else if (d.kind === 'text') $('#docv-body').innerHTML = `<pre class="doc">${esc(d.text)}</pre>`;
  else if (d.kind === 'pdf') $('#docv-body').innerHTML = `<embed src="${d.url}" type="application/pdf" style="width:100%;height:76vh">`;
  else if (d.kind === 'image') $('#docv-body').innerHTML = `<img src="${d.url}" style="max-width:100%">`;
  else $('#docv-body').innerHTML = `<a href="${d.url}" target="_blank">open ${esc(d.name)}</a>`;
};

/* ---------- live strip + agent dock ---------- */
async function liveTick() {
  const d = await api('/api/live');
  const a = d.action || {};
  let s = a.running ? '● ' + a.name + ' …' : (d.active ? '● running' : '○ idle');
  (d.running || []).forEach(r => s += '  ▶ ' + r);
  const t = (d.tail || []).slice(-1)[0];
  if (t) s += '   ' + t.t;
  $('#live').textContent = s;
  const busy = !!a.running || d.active;
  LIVE_RUNNING = busy || LIVE_RUNNING;                 // stay optimistic until confirmed idle
  document.querySelectorAll('#a-prepare,#a-submit,#a-reconcile,#a-prepare-shown,#a-submit-shown,#a-match,#d-body [data-act]')
    .forEach(b => { b.disabled = LIVE_RUNNING; });
  const rc = $('#runctl'); if (rc) { rc.classList.toggle('hide', !LIVE_RUNNING); $('#btn-pause').textContent = d.paused ? '▶ Resume' : '⏸ Pause'; }
  if (LIVE_RUNNING && !busy) $('#live').textContent = '● starting… (the run takes a few minutes — see the monitor)';
  if (busy) { IDLE_TICKS = 0; WAS_BUSY = true; } else if (LIVE_RUNNING && ++IDLE_TICKS >= 3) {
    LIVE_RUNNING = false;
    if (WAS_BUSY) {                                    // a run just finished — refresh everything
      WAS_BUSY = false;
      loadGrid();
      if (CUR && !$('#detail').hidden) openDetail(CUR);
      toast('run finished — updated the grid and this role');
    }
    PENDING.clear(); $('#peras').classList.add('hide'); renderRows();
  }
  if (!$('#peras').classList.contains('hide')) {         // background-run monitor
    const sm = a.summary || {};
    let h = `<div class="act-h">${a.running ? '●' : '✓'} ${esc(a.name || 'working…')} <span class="muted">${a.running ? 'running…' : 'finished'}</span></div>`;
    if (sm.headline) h += `<div class="act-sum">${esc(sm.headline)}</div>`;
    if ((sm.notable || []).length) h += '<ul class="act-list">' + sm.notable.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>';
    h += (d.running || []).length ? `<div class="act-h" style="margin-top:6px">▶ ${(d.running || []).map(esc).join(' · ')}</div>` : '';
    (d.tail || []).slice(-6).forEach(x => h += `<div class="mini muted">${esc(x.t)}</div>`);
    $('#peras-body').innerHTML = h;
  }
  const sm = a.summary || {};
  $('#act-sum').textContent = a.name ? ((a.running ? '● ' : '✓ ') + a.name) : (d.active ? 'runner active' : 'idle');
  if (document.body.dataset.act === 'open') {
    let h = '';
    if (a.name && (a.running || (a.log || []).length)) {
      h += `<div class="act-h">${a.running ? '●' : '✓'} ${esc(a.name)} <span class="muted">${a.running ? 'running…' : 'done'}</span></div>`;
      if (sm.headline) h += `<div class="act-sum">${esc(sm.headline)}</div>`;
      if ((sm.notable || []).length) h += '<ul class="act-list">' + sm.notable.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>';
      const total = (a.log || []).length;
      if (total > (sm.notable || []).length) h += `<details class="act-raw"><summary>full output · ${total} lines</summary><pre>${esc((a.log || []).join('\n'))}</pre></details>`;
      h += '<div class="act-sep"></div>';
    }
    h += d.active ? '● runner active' : '○ runner idle';
    (d.running || []).forEach(r => h += `\n▶ ${esc(r)}`);
    (d.tail || []).forEach(x => h += x.k === 'phase' ? `\n[p] ${esc(x.t)}` : `\n    ${esc(x.t)}`);
    $('#liveterm').innerHTML = h;
  }
  setTimeout(liveTick, 2500);
  permTick();
}
/* the embedded agent asks before doing something risky (agent_access.py -> here) */
async function permTick() {
  if (CUR_PERM) return;
  const d = await api('/api/agent/pending');
  const q = (d && d.pending) || [];
  if (!q.length) return;
  CUR_PERM = q[0];
  $('#perm-text').textContent = `${CUR_PERM.category}: ${CUR_PERM.detail}`;
  $('#perm-always').textContent = `Always allow ${CUR_PERM.category}`;
  $('#perm').classList.remove('hide');
}
async function permAnswer(decision, remember) {
  if (!CUR_PERM) return;
  const id = CUR_PERM.id; CUR_PERM = null; $('#perm').classList.add('hide');
  await api('/api/agent/decide', { id, decision, remember: !!remember });
  permTick();
}

/* ---------- shared dockable panels (edges) ---------- */
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const EDGE_SIZE = {
  left: parseInt(localStorage.getItem('edge.left') || '380', 10),
  right: parseInt(localStorage.getItem('edge.right') || '380', 10),
  top: parseInt(localStorage.getItem('edge.top') || '300', 10),
  bottom: parseInt(localStorage.getItem('edge.bottom') || '300', 10),
};
const PANELS = {
  agent: { pos: localStorage.getItem('agent.pos') || 'left', open: localStorage.getItem('agent.open') === '1', tab: '#agent-tab' },
  detail: { pos: localStorage.getItem('detail.pos') || 'right', open: false, tab: '#detail-tab' },
};
let actSize = parseInt(localStorage.getItem('dock.act') || '180', 10);
const panelOf = (k) => document.querySelector(`.panel[data-panel="${k}"]`);
const isVert = (edge) => edge === 'left' || edge === 'right';

function applyEdgeSizes() {
  const r = document.documentElement.style;
  r.setProperty('--edge-left', EDGE_SIZE.left + 'px');
  r.setProperty('--edge-right', EDGE_SIZE.right + 'px');
  r.setProperty('--edge-top', EDGE_SIZE.top + 'px');
  r.setProperty('--edge-bottom', EDGE_SIZE.bottom + 'px');
  r.setProperty('--act-size', actSize + 'px');
}
function layoutPanels() {
  for (const k in PANELS) {
    const el = panelOf(k), p = PANELS[k];
    el.hidden = !p.open;
    const cont = document.querySelector(`.edge-panels[data-edge="${p.pos}"]`);
    if (el.parentElement !== cont) cont.appendChild(el);
  }
  document.querySelectorAll('.edge-panels').forEach(reflowEdge);
  document.querySelectorAll('.edge').forEach(edge =>
    edge.classList.toggle('has', !!edge.querySelector('.panel:not([hidden])')));
  applyEdgeSizes();
  // pullout tabs (offset when both sit on the same edge)
  const openEdges = {};
  for (const k in PANELS) {
    const t = document.querySelector(PANELS[k].tab); if (!t) continue;
    t.hidden = PANELS[k].open; t.dataset.edge = PANELS[k].pos;
    t.classList.toggle('stacked', !!openEdges[PANELS[k].pos]); openEdges[PANELS[k].pos] = true;
  }
}
function reflowEdge(cont) {
  cont.querySelectorAll('.split-panel').forEach(s => s.remove());
  const panels = [...cont.querySelectorAll('.panel')].filter(p => !p.hidden);
  for (let i = 0; i < panels.length - 1; i++) {
    const s = document.createElement('div'); s.className = 'splitter split-panel'; s.dataset.edge = cont.dataset.edge;
    s.title = 'Drag to resize';
    cont.insertBefore(s, panels[i + 1]);
    initPanelSplit(s, panels[i]);
  }
}
function initPanelSplit(split, first) {
  split.addEventListener('pointerdown', e => {
    e.preventDefault(); split.classList.add('drag'); split.setPointerCapture(e.pointerId);
    const vert = isVert(split.dataset.edge), start = vert ? e.clientY : e.clientX;
    const base = vert ? first.getBoundingClientRect().height : first.getBoundingClientRect().width;
    const move = ev => {
      const d = (vert ? ev.clientY : ev.clientX) - start;
      first.style.flex = `0 0 ${clamp(base + d, 90, 100000)}px`;
    };
    const up = () => { split.classList.remove('drag'); split.removeEventListener('pointermove', move); split.removeEventListener('pointerup', up); };
    split.addEventListener('pointermove', move); split.addEventListener('pointerup', up);
  });
}
function initEdgeSplit(split) {
  split.addEventListener('pointerdown', e => {
    e.preventDefault(); split.classList.add('drag'); split.setPointerCapture(e.pointerId);
    const edge = split.dataset.edge, vert = isVert(edge), start = vert ? e.clientX : e.clientY, base = EDGE_SIZE[edge];
    const move = ev => {
      const d = (vert ? ev.clientX : ev.clientY) - start;
      let v = (edge === 'left' || edge === 'top') ? base + d : base - d;
      v = clamp(v, 220, (vert ? window.innerWidth : window.innerHeight) - 240);
      EDGE_SIZE[edge] = v; localStorage.setItem('edge.' + edge, v); applyEdgeSizes();
    };
    const up = () => { split.classList.remove('drag'); split.removeEventListener('pointermove', move); split.removeEventListener('pointerup', up); };
    split.addEventListener('pointermove', move); split.addEventListener('pointerup', up);
  });
}
function setPanel(key, props) {
  Object.assign(PANELS[key], props);
  localStorage.setItem(key + '.pos', PANELS[key].pos);
  localStorage.setItem(key + '.open', PANELS[key].open ? '1' : '0');
  layoutPanels();
}
function openDock(v) { setPanel('agent', { open: v }); if (v) api('/api/agent').then(d => $('#agent-name').textContent = d.agent || '?'); }
function zoneAt(x, y) {
  const w = window.innerWidth, h = window.innerHeight, top = 56;
  const dl = x, dr = w - x, dt = y - top, db = h - y;
  const min = Math.min(dl, dr, dt, db);
  if (min > Math.min(w, h) * 0.30) return null;      // dragged into the middle → no move
  if (min === dl) return 'left';
  if (min === dr) return 'right';
  if (min === dt) return 'top';
  return 'bottom';
}
function setZone(z) { document.querySelectorAll('.dockzone').forEach(e => e.classList.toggle('on', e.id === 'zone-' + z)); }
function initDockDrag(handle) {
  handle.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const key = handle.dataset.panel; if (!key) return;
    e.preventDefault(); handle.setPointerCapture(e.pointerId);
    document.body.classList.add('dock-dragging'); let zone = null; setZone(null);
    const move = ev => { zone = zoneAt(ev.clientX, ev.clientY); setZone(zone); };
    const up = () => {
      handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', up); handle.removeEventListener('pointercancel', up);
      document.body.classList.remove('dock-dragging'); setZone(null);
      if (zone && zone !== PANELS[key].pos) setPanel(key, { pos: zone, open: true });
    };
    handle.addEventListener('pointermove', move); handle.addEventListener('pointerup', up); handle.addEventListener('pointercancel', up);
  });
}
function initActSplit() {
  const el = $('#split-inner'); if (!el) return;
  el.addEventListener('pointerdown', e => {
    e.preventDefault(); el.classList.add('drag'); el.setPointerCapture(e.pointerId);
    const vert = isVert(PANELS.agent.pos), x0 = e.clientX, y0 = e.clientY, base = actSize;
    const panes = el.parentElement, span = vert ? panes.clientHeight : panes.clientWidth;
    const move = ev => {
      const d = vert ? (ev.clientY - y0) : (ev.clientX - x0);
      actSize = clamp(base - d, 90, Math.max(140, span - 150));
      localStorage.setItem('dock.act', actSize); applyEdgeSizes();
    };
    const up = () => { el.classList.remove('drag'); el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', up); };
    el.addEventListener('pointermove', move); el.addEventListener('pointerup', up);
  });
}
function initPanels() {
  // migrate pre-v6 keys so upgrading doesn't reset the panel layout
  if (localStorage.getItem('agent.open') === null && localStorage.getItem('dock.open') !== null)
    localStorage.setItem('agent.open', localStorage.getItem('dock.open'));
  if (localStorage.getItem('agent.pos') === null && localStorage.getItem('dock.pos') !== null)
    localStorage.setItem('agent.pos', localStorage.getItem('dock.pos'));
  document.body.dataset.act = localStorage.getItem('dock.actOpen') === '1' ? 'open' : 'closed';
  document.querySelectorAll('.dock-drag').forEach(initDockDrag);
  document.querySelectorAll('.edge-split').forEach(initEdgeSplit);
  initActSplit();
  $('#agent-tab').onclick = () => openDock(true);
  $('#detail-tab').onclick = () => setPanel('detail', { open: true });
  document.querySelectorAll('.panel-close').forEach(b => b.onclick = () => {
    if (b.dataset.panel === 'detail') setPanel('detail', { open: false });
    else openDock(false);
  });
  layoutPanels();
}
async function chatPoll() {
  const d = await api('/api/chat/stream?since=' + chatOffset);
  if (d.segments) { CHAT = d; renderChat(); }
  chatOffset = d.offset || chatOffset;
  setSpin(!!d.running);
  const active = d.running || (d.pending || 0) > 0;      // keep polling while a turn runs OR messages wait
  if (active && !CHAT_TIMER) CHAT_TIMER = setInterval(chatPoll, 1200);
  else if (!active && CHAT_TIMER) { clearInterval(CHAT_TIMER); CHAT_TIMER = null; renderChat(); }
}
function toolBlock(s) {
  const tag = (s.tool && s.tool !== 'bash') ? esc(s.tool) + ' · ' : '$ ';
  return `<details class="c-tool" data-k="t:${esc(s.cmd).slice(0, 90)}"><summary><code>${tag}${esc(s.cmd)}</code></summary>${s.body ? `<pre>${esc(s.body)}</pre>` : ''}</details>`;
}
function collapseCode(html) {
  return html.replace(/<pre>([\s\S]*?)<\/pre>/g, (m, c) => ((c.match(/\n/g) || []).length >= 2)
    ? `<details class="c-code" data-k="c:${esc(c).slice(0, 80)}"><summary>code</summary><pre>${c}</pre></details>` : m);
}
function setSpin(v) {
  const s = $('#chat-spin'); if (s) s.classList.toggle('hide', !v);   // the single "agent working" indicator
}
function openKeys(el) { return new Set([...el.querySelectorAll('details[open]')].map(d => d.getAttribute('data-k')).filter(Boolean)); }
function renderChat() {
  const el = $('#chat'), segs = (CHAT && CHAT.segments) || [];
  if (!segs.length && !CHAT.running) { el.innerHTML = '<span class="muted">ask the agent anything…</span>'; return; }
  const keys = openKeys(el);                                  // keep expanded steps open across re-renders
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  let h = '', i = 0;
  while (i < segs.length) {
    const s = segs[i];
    if (s.t === 'tool') {                       // collapse runs of tool calls into one group
      const grp = [];
      while (i < segs.length && segs[i].t === 'tool') { grp.push(segs[i]); i++; }
      h += grp.length === 1 ? toolBlock(grp[0])
        : `<details class="c-tools" data-k="g:${esc(grp.map(x => x.cmd).join('|')).slice(0, 90)}"><summary>🔧 ${grp.length} steps</summary>${grp.map(toolBlock).join('')}</details>`;
      continue;
    }
    if (s.t === 'user') h += `<div class="c-user"><div class="md">${md(s.body)}</div></div>`;
    else if (s.t === 'status') h += `<div class="c-status">${esc(s.body)}</div>`;
    else h += `<div class="md">${collapseCode(md(s.body))}</div>`;
    i++;
  }
  if (CHAT.running) h += `<div class="working"><span class="muted">▮ working…</span></div>`;
  el.innerHTML = h;
  el.querySelectorAll('details[data-k]').forEach(d => { if (keys.has(d.getAttribute('data-k'))) d.open = true; });
  if (nearBottom || CHAT.running) el.scrollTop = el.scrollHeight;
}

/* ---------- settings sections ---------- */
const fmtSize = (n) => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : n > 1024 ? (n / 1024).toFixed(0) + ' KB' : n + ' B';
async function setAccounts(b) {
  const d = await api('/api/accounts');
  b.innerHTML = `<p class="muted">Connect your accounts. Authorisation opens in your browser - finish it there, then re-check.
      Per-site logins: <b>${d.sites}</b> stored.</p>
    <div class="row" style="margin:8px 0"><button onclick="App.auth('gmail')">Authorise Gmail (read-only)</button>
      <button onclick="App.auth('calendar')">Authorise Calendar</button>
      <button onclick="viewDoc('docs/ACCOUNT-SETUP.md','Account setup guide')">Open setup guide</button>
      <button onclick="App.settings('accounts')">Re-check</button></div>
    <pre class="doc">${esc(d.text || '(no output)')}</pre>`;
}
async function setKB(b) {
  const d = await api('/api/kb');
  let list = '';
  for (const [g, files] of Object.entries(d.sources || {})) {
    if (!files.length) continue;
    const p = `kb/sources/${g === '(root)' ? '' : g + '/'}${f.name}`;
    list += `<div class="kb-group"><b>${esc(g)}</b> <span class="muted mini">${files.length} file(s)</span><ul>` +
      files.map(f => `<li><span class="mini">${esc(f.name)}</span> <span class="muted mini">${fmtSize(f.size)}</span>
        <button class="small" title="delete" onclick='App.kbDel(${JSON.stringify(p)})'>✕</button></li>`).join('') +
      '</ul></div>';
  }
  const s = d.stats || {};
  b.innerHTML = `<p class="muted">Documents in <code>kb/sources/</code> feed the GraphRAG knowledge graph. Add documents, then rebuild the index.</p>
    <div class="row" style="margin:8px 0"><input id="kb-group" placeholder="group (personal, contracts…)" style="max-width:230px">
      <input type="file" id="kb-file" multiple><button onclick="App.kbUpload()">Upload</button>
      <button class="risky" onclick="App.rebuildKB()" title="Full re-index of the knowledge graph — can take 20–30+ minutes">Rebuild graph (slow)</button></div>
    <div class="kb-list">${list || '<span class="muted">no source documents yet</span>'}</div>
    <h4 style="margin:14px 0 4px">Index</h4>
    <div class="muted mini">${s.index ? `${s.entities} entities · ${s.relationships} relationships · ${s.communities} communities · ${s.documents} documents` : 'not built yet'}</div>
    <pre class="doc" style="margin-top:8px">${esc(d.check || '')}</pre>`;
}
async function setGraph(b) {
  const d = await api('/api/graph?kind=stats');
  b.innerHTML = `<p class="muted">The knowledge graph built from your documents (GraphRAG index in <code>kb/graphrag/</code>).
      ${d.entities ? `<b>${d.entities}</b> entities · <b>${d.relationships}</b> relationships · <b>${d.communities}</b> communities` : ''}</p>
    <div class="row" style="margin:8px 0">
      <select id="g-kind" onchange="App.graphLoad()">
        <option value="entities">Entities</option><option value="relationships">Relationships</option>
        <option value="communities">Communities</option><option value="documents">Documents</option></select>
      <input id="g-q" placeholder="search the graph…" style="flex:1" onkeydown="if(event.key==='Enter')App.graphLoad()">
      <button onclick="App.graphLoad()">Search</button></div>
    <div id="g-res" class="g-res"><span class="muted">loading…</span></div>`;
  App.graphLoad();
}
async function setPerms(b) {
  const d = await api('/api/permissions');
  const cats = Object.keys(d.defaults || {});
  const help = { read_repo: 'read files in this repo', read_external: 'read files outside the repo',
    write_repo: 'write files in this repo', write_external: 'write files outside the repo',
    bash: 'run shell commands', web: 'fetch web pages', task: 'launch subagents' };
  b.innerHTML = `<p class="muted">What the embedded agent may do <b>without asking</b>. <b>ask</b> shows you a
      prompt (Allow once / Always allow / Deny) the moment the agent tries it — the agent waits for your answer.</p>
    <table><tbody>${cats.map(c => `<tr><td><code>${esc(c)}</code><div class="muted mini">${esc(help[c] || '')}</div></td>
      <td><select data-cat="${esc(c)}">${['allow', 'ask', 'deny'].map(v =>
        `<option value="${v}" ${(d.policy[c] === v) ? 'selected' : ''}>${v}</option>`).join('')}</select></td></tr>`).join('')}</tbody></table>
    <div class="row" style="margin-top:10px"><button onclick="App.savePerms()">Save</button>
      <span class="muted mini">Applies to every agent (opencode, Claude Code, any <code>AGENT=</code>).</span></div>`;
}
async function setAI(b) {
  const [a, g] = await Promise.all([api('/api/agent/config'), api('/api/graphrag/env')]);
  const detected = (a.detected || []);
  const envRows = (a.env_keys || []).map(k =>
    `<div class="row" style="margin:3px 0"><code style="min-width:190px">${esc(k)}</code>
      <input data-env="${esc(k)}" placeholder="${esc(a.env[k])} (blank = keep)" style="flex:1">
      <button class="small" onclick="App.aiDel('${esc(k)}')" title="remove">✕</button></div>`).join('');
  const grRows = (g.keys || []).map(k =>
    `<div class="row" style="margin:3px 0"><code style="min-width:190px">${esc(k)}</code>
      <input data-gr="${esc(k)}" placeholder="${esc(g.vars[k])} (blank = keep)" style="flex:1"></div>`).join('');
  b.innerHTML = `<p class="muted">Which LLM/agent runs the pipeline. Token values are stored outside the repo
      (<code>${esc(a.config_path)}</code>, 0600) and shown masked.</p>
    <div class="row" style="margin:6px 0"><b>Detected:</b>
      ${detected.length ? detected.map(x => `<span class="pill">${esc(x)}</span>`).join(' ')
        : '<span class="muted">none on PATH</span>'}
      <span class="muted">· in use: <b>${esc(a.which || '?')}</b></span></div>
    ${detected.length ? '' : `<div class="muted mini" style="margin-bottom:8px">Install one, then set the command below:
      <code>npm i -g opencode-ai</code> (opencode) or <code>npm i -g @anthropic-ai/claude-code</code> (Claude Code),
      or set a custom command.</div>`}
    <div class="row" style="margin-top:8px"><span class="muted">Agent</span>
      <input id="ai-agent" value="${esc(a.agent)}" placeholder="auto (opencode, else claude)" style="flex:1">
      <span class="muted">Model</span><input id="ai-model" value="${esc(a.model)}" placeholder="agent default" style="flex:1"></div>
    <h4 style="margin:14px 0 4px">API keys / env</h4>
    <div id="ai-env">${envRows || '<span class="muted mini">none set</span>'}</div>
    <div class="row" style="margin-top:6px">
      <input id="ai-env-k" list="ai-known" placeholder="KEY name" style="max-width:220px">
      <datalist id="ai-known">${(a.known_keys || []).map(k => `<option>${esc(k)}</option>`).join('')}</datalist>
      <input id="ai-env-v" placeholder="value" style="flex:1"><button onclick="App.aiAdd()">＋ Add</button></div>
    <div class="row" style="margin-top:10px"><button onclick="App.saveAI()">Save agent config</button></div>
    <h4 style="margin:18px 0 4px">GraphRAG LLM (<code>kb/graphrag/.env</code>)</h4>
    <div id="ai-gr">${grRows || '<span class="muted mini">no .env yet</span>'}</div>
    <div class="row" style="margin-top:8px"><button onclick="App.saveGR()">Save GraphRAG env</button>
      <span class="muted mini">Used by the knowledge graph (same OPENCODE_API_KEY works for both).</span></div>`;
}
function setProfile(b) {
  b.innerHTML = `<p class="muted">Your ground-truth CV, role-family templates and rules. JSON is validated before saving; a <code>.bak</code> is kept.</p>
    <div class="row"><div class="tabs2" id="cf-tabs" style="margin:0;border:0">
      <a data-t="cv.json" onclick="App.cf('cv.json')">cv.json</a>
      <a data-t="archetypes.json" onclick="App.cf('archetypes.json')">archetypes.json</a>
      <a data-t="profile.md" onclick="App.cf('profile.md')">profile.md</a></div>
      <span style="flex:1"></span><button onclick="App.cfSave()">Save</button>
      <button onclick="App.run('build_archetypes')">Regenerate archetype CVs</button></div>
    <textarea id="cf-text" spellcheck="false"></textarea>
    <div id="cf-msg" class="muted"></div>`;
  App.cf(CF);
}

/* ---------- wiring ---------- */
$('#a-prepare').onclick = () => App.run('prepare');
$('#a-submit').onclick = () => App.run('submit_queue');
$('#a-reconcile').onclick = () => App.run('reconcile');
$('#a-config').onclick = () => { $('#cfg').classList.remove('hide'); App.settings(CF_SEC); };
window.cfgClose = () => $('#cfg').classList.add('hide');
window.legendClose = () => $('#legend-modal').classList.add('hide');
$('#legend').onclick = () => {
  $('#legend-status').innerHTML = Object.entries(STATUS_HELP).map(([k, v]) => `<dt>${chip(k)}</dt><dd>${esc(v)}</dd>`).join('');
  $('#legend-queue').innerHTML = Object.entries(QUEUE_HELP).map(([k, v]) => `<dt><code>${esc(k)}</code></dt><dd>${esc(v)}</dd>`).join('');
  $('#legend-modal').classList.remove('hide');
};
$('#a-drawer').onclick = () => openDock(!PANELS.agent.open);
$('#updpill').onclick = () => updateDialog();
$('#btn-stop').onclick = () => App.stop();
window.evidClose = () => $('#evid').classList.add('hide');
$('#evid-save').onclick = () => App.saveEvidence();
$('#peras-stop').onclick = () => App.stop();
$('#btn-pause').onclick = () => App.togglePause($('#btn-pause').textContent.includes('Pause'));
$('#perm-once').onclick = () => permAnswer('allow', false);
$('#perm-always').onclick = () => permAnswer('allow', true);
$('#perm-deny').onclick = () => permAnswer('deny', false);
$('#act-toggle').onclick = () => {
  const open = document.body.dataset.act !== 'open';
  document.body.dataset.act = open ? 'open' : 'closed';
  localStorage.setItem('dock.actOpen', open ? '1' : '0');
  if (open) liveTick();
};
$('#chat-send').onclick = () => App.chat();
$('#chat-new').onclick = () => App.newChat();
$('#q').oninput = renderRows;
$('#fstatus').onchange = () => { SPECIAL = ''; ACTIVE_METRIC = ''; document.querySelectorAll('#metrics .metric').forEach(m => m.classList.remove('on')); renderRows(); };
$('#fqueue').onchange = () => { SPECIAL = ''; ACTIVE_METRIC = ''; document.querySelectorAll('#metrics .metric').forEach(m => m.classList.remove('on')); renderRows(); };
$('#ftype').onchange = () => renderRows();
$('#a-prepare-shown').onclick = () => App.prepareShown();
$('#a-submit-shown').onclick = () => App.submitPrepared();
$('#a-match').onclick = () => App.matchShown($('#a-match'));
$('#export').onclick = () => {
  const cs = ['date', 'company', 'role', 'employment', 'ats', 'status', 'match', 'queue', 'applied', 'spec', 'key'];
  const body = GRID.map(r => cs.map(c => JSON.stringify(r[c] == null ? '' : r[c])).join(',')).join('\n');
  const url = URL.createObjectURL(new Blob([cs.join(',') + '\n' + body], { type: 'text/csv' }));
  const a = document.createElement('a'); a.href = url; a.download = 'jobsquirrel.csv'; a.click(); URL.revokeObjectURL(url);
};
window.App = App;
async function healthPill() { const s = await api('/api/health'); const h = $('#health');
  h.textContent = 'health: ' + (s.v || '?'); h.className = 'pill ' + (s.v || 'unknown'); h.title = s.detail || ''; setTimeout(healthPill, 60000); }
/* ---------- software updates ---------- */
let UPD = {};
async function updateCheck(refresh) {
  const d = await api('/api/update' + (refresh ? '?refresh=1' : ''));
  UPD = d || {};
  if ($('#ver')) $('#ver').textContent = d.current || '?';
  const pill = $('#updpill');
  if (pill) { pill.classList.toggle('hide', !d.available); if (d.available) pill.textContent = `⬆ ${d.latest}`; }
  setTimeout(updateCheck, 6 * 3600 * 1000);                        // re-check every 6h
}
window.updClose = () => $('#upd').classList.add('hide');
function updateDialog() {
  if (!UPD.available) { updateCheck(true); return; }
  $('#upd-title').textContent = `Update available: ${UPD.latest}`;
  $('#upd-lead').textContent = `You are on v${UPD.current}. ${UPD.name || ''}`;
  $('#upd-notes').innerHTML = md(UPD.notes || '');
  $('#upd-link').href = UPD.url || '#';
  $('#upd').classList.remove('hide');
}
$('#upd-go').onclick = async () => {
  const ok = await approve(`Update Jobsquirrel to ${UPD.latest} (runs git pull; restart after)`, 'APPROVE_UPDATE', 'update');
  if (!ok) return;
  $('#upd').classList.add('hide');
  const d = await api('/api/update/apply', { approval_token: 'APPROVE_UPDATE' });
  toast(d.ok || d.error, !!d.error); if (!d.error) openDock(true);
};
initPanels(); loadGrid(); gridTick(); liveTick(); healthPill(); chatPoll(); updateCheck();

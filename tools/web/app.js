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
/* Lifecycle buckets: the primary way to read the grid, no fine filtering needed.
   Each row lands in exactly one bucket, by urgency: done > needs > ongoing > pipeline. */
const BUCKETS = [
  { k: 'active', label: 'Active', hint: 'Everything not finished: needs you + prepared + ongoing + to apply' },
  { k: 'focus', label: 'Focus', hint: 'Roles that pay at least your target and fit at least 70%; also shows high-fit roles with no pay figure' },
  { k: 'needs', label: 'Needs you', hint: 'Replies, interviews to book, assessments, offers or manual steps' },
  { k: 'prepared', label: 'Prepared', hint: 'Documents generated and gated — review or submit' },
  { k: 'ongoing', label: 'Ongoing', hint: 'Submitted, in progress or interviewing — waiting on the employer' },
  { k: 'pipeline', label: 'To apply', hint: 'Queued, drafting, blocked or with no result yet' },
  { k: 'done', label: 'Done', hint: 'Rejected or closed — finished, no action' },
  { k: 'all', label: 'All', hint: 'Every row, including finished ones' },
];
const BUCKET_GROUPS = [
  { k: 'needs', title: 'Needs you', desc: 'reply, book a time, complete an assessment, or clear a manual step' },
  { k: 'prepared', title: 'Prepared', desc: 'documents ready — review or submit' },
  { k: 'ongoing', title: 'Ongoing', desc: 'waiting on the employer' },
  { k: 'pipeline', title: 'To apply', desc: 'queued, drafting, or blocked before applying' },
  { k: 'done', title: 'Done', desc: 'rejected or closed — no action' },
];
const FOCUS_GROUPS = [
  { k: 'focus_pay', title: 'Pays well + fits', desc: 'known pay at or above your target · strong fit', test: r => r.focus },
  { k: 'focus_unknown', title: 'High fit, pay not stated', desc: 'strong fit — check the ad or set a salary', test: r => r.focus_unknown },
];
const NEEDS_STATUS = new Set(['MANUAL', 'OFFER']);
function bucketOf(r) {
  const s = r.status, lb = r.label || s;
  if (s === 'CLOSED' || s === 'REJECTED') return 'done';
  if (r.action || NEEDS_STATUS.has(s) || lb === 'INVITED' || r.queue === 'human') return 'needs';
  if (['SUBMITTED', 'IN_PROGRESS', 'INTERVIEW'].includes(s)) return 'ongoing';
  if (s === 'PREPARED') return 'prepared';
  return 'pipeline';
}
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
let GRID = [], SORT = { k: 'date', dir: -1 }, D = {}, P = {}, chatOffset = 0, CHAT_TIMER = null, CHAT = { segments: [] }, CUR_PERM = null, PERM_BUSY = false, DRAFT_SENDING = false;
let BUILD = '', LIVE_TASKS = [];
let BUCKET = 'active', VISIBLE = [], VIEW = [];
let COLLAPSED = { ongoing: true, pipeline: true, done: true, prepared: false, focus_unknown: true };   // default to the actionable top of the list
let BUCKET_BEFORE_SEARCH = null;
const PENDING = new Set();
const NUT = '<span class="spin" title="working…">🥜</span> ';
function starting(label, keys) {
  LIVE_RUNNING = true;
  (keys || []).forEach(k => PENDING.add(k));
  const rc = $('#runctl'); if (rc) rc.classList.remove('hide');
  const l = $('#live'); if (l) l.innerHTML = NUT + esc('● ' + (label || 'working') + ' — starting…');
  ACT = { name: label || 'working', running: true, summary: {}, log: [] };
  ACT_SIG = ''; ACT_IGNORE = LAST_ACT_NAME;
  CHAT_STICK = true;
  renderChat();
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
  const o = { headers: { 'X-Session': TOKEN } };
  if (body !== undefined) { o.method = 'POST'; o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(body); }
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

const CHAT_HIST_KEY = 'agent.history';
let HIST = { open: false, items: [], sel: 0 };

function chatHistory() {
  try {
    const a = JSON.parse(localStorage.getItem(CHAT_HIST_KEY) || '[]');
    return Array.isArray(a) ? a.filter(x => typeof x === 'string' && x.trim()) : [];
  } catch (e) { return []; }
}

function rememberChat(m) {
  const h = chatHistory().filter(x => x !== m);
  h.unshift(m);
  try { localStorage.setItem(CHAT_HIST_KEY, JSON.stringify(h.slice(0, 100))); } catch (e) {}
}

function histClose() {
  HIST.open = false; HIST.items = [];
  const el = document.getElementById('chat-hist');
  if (el) { el.classList.add('hide'); el.innerHTML = ''; }
}

function histRender() {
  const el = document.getElementById('chat-hist');
  if (!el) return;
  el.innerHTML = HIST.items.length
    ? HIST.items.map((t, i) => `<div class="ch-item${i === HIST.sel ? ' sel' : ''}" role="option" data-i="${i}" title="${esc(t)}">${esc(t)}</div>`).join('')
    : '<div class="ch-empty muted">no earlier prompts</div>';
  el.classList.remove('hide');
  const sel = el.querySelector('.ch-item.sel');
  if (sel) sel.scrollIntoView({ block: 'nearest' });
}

function histOpen(filter) {
  const f = (filter || '').trim().toLowerCase();
  const all = chatHistory();
  const recent = (f ? all.filter(x => x.toLowerCase().includes(f)) : all).slice(0, 50);
  // Render oldest first so that pressing Up walks back in time; start on the
  // newest (bottom).
  HIST.items = recent.reverse();
  HIST.sel = HIST.items.length - 1;
  HIST.open = true;
  histRender();
}

function chatKey(e) {
  const inp = e.target;
  if (e.key === 'ArrowUp') {
    if (HIST.open) { HIST.sel = Math.max(0, HIST.sel - 1); histRender(); }
    else histOpen(inp.value);
    e.preventDefault(); return;
  }
  if (!HIST.open) {
    if (e.key === 'Enter') { e.preventDefault(); App.chat(); }
    return;
  }
  if (e.key === 'ArrowDown') { e.preventDefault(); HIST.sel = Math.min(HIST.items.length - 1, HIST.sel + 1); histRender(); return; }
  if (e.key === 'Escape') { e.preventDefault(); histClose(); return; }
  if (e.key === 'Enter') {
    e.preventDefault();
    const pick = HIST.items[HIST.sel];
    if (pick) { inp.value = pick; inp.setSelectionRange(pick.length, pick.length); }
    histClose();
    return;
  }
  if (e.key === 'Tab') histClose();
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
    if (CF_SEC === 'secrets') return setSecrets(b);
    if (CF_SEC === 'ai') return setAI(b);
    if (CF_SEC === 'kb') return setKB(b);
    if (CF_SEC === 'graph') return setGraph(b);
    if (CF_SEC === 'perms') return setPerms(b);
    if (CF_SEC === 'data') return setData(b);
    return setProfile(b);
  },
  auth: async (kind) => { const d = await api('/api/accounts/auth', { kind }); toast(d.ok || d.error, !!d.error); },
  secretSave: async (section, name, value, user) => {
    const v = section === 'accounts' ? { password: value, username: user || '' } : value;
    const d = await api('/api/secrets', { section, name, value: v });
    toast(d.ok || d.error, !!d.error);
    if (!d.error) App.settings('secrets');
  },
  secretAdd: async (section) => {
    if (section === 'accounts') {
      const host = ($('#add-accounts-host') || {}).value || '';
      const user = ($('#add-accounts-user') || {}).value || '';
      const pass = ($('#add-accounts-pass') || {}).value || '';
      if (!host.trim() || !pass) return toast('host and password are required', true);
      return App.secretSave('accounts', host.trim(), pass, user.trim());
    }
    if (section === 'custom') {
      const sec = (($('#add-custom-section') || {}).value || 'custom').trim().toLowerCase();
      const name = (($('#add-custom-name') || {}).value || '').trim();
      const val = ($('#add-custom-value') || {}).value || '';
      if (!name || !val) return toast('name and value are required', true);
      return App.secretSave(sec || 'custom', name, val);
    }
    const name = (($('#add-' + section + '-name') || {}).value || '').trim();
    const val = ($('#add-' + section + '-value') || {}).value || '';
    if (!name || !val) return toast('name and value are required', true);
    return App.secretSave(section, name, val);
  },
  secretEdit: (btn) => {
    const row = btn.closest('[data-sec]'); if (!row) return;
    const inp = row.querySelector('[data-new]');
    if (!inp) return;
    if (inp.style.display === 'none') {
      inp.style.display = ''; inp.focus(); btn.textContent = 'Save'; return;
    }
    if (!inp.value) return toast('type a new value first', true);
    App.secretSave(row.dataset.sec, row.dataset.name, inp.value, row.dataset.user || '');
  },
  secretDel: async (btn) => {
    const row = btn.closest('[data-sec]'); if (!row) return;
    if (!window.confirm(`Delete ${row.dataset.name} from the secrets store?`)) return;
    const d = await api('/api/secrets/delete', { section: row.dataset.sec, name: row.dataset.name });
    toast(d.ok || d.error, !!d.error);
    if (!d.error) App.settings('secrets');
  },
  secretMigrate: async () => {
    const d = await api('/api/secrets/migrate', {});
    toast(d.error ? d.error : 'existing secrets imported', !!d.error);
    if (!d.error) App.settings('secrets');
  },
  secretEncrypt: async () => {
    const d = await api('/api/secrets/encrypt', {});
    toast(d.ok || d.error, !!d.error);
    if (!d.error) App.settings('secrets');
  },
  backupDownload: async () => {
    const docs = $('#bk-docs') && $('#bk-docs').checked ? '1' : '0';
    toast('building the backup…');
    try {
      const r = await fetch('/api/backup?documents=' + docs, { headers: { 'X-Session': TOKEN } });
      if (!r.ok) { const e = await r.json().catch(() => ({})); return toast(e.error || 'backup failed', true); }
      const blob = await r.blob();
      const cd = r.headers.get('Content-Disposition') || '';
      const m = /filename="([^"]+)"/.exec(cd);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = m ? m[1] : 'jobsquirrel-backup.zip';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
      toast('backup downloaded');
      App.settings('data');
    } catch (e) { toast(String(e), true); }
  },
  backupRestore: async () => {
    const f = $('#bk-file').files[0];
    const confirm = $('#bk-confirm').value.trim();
    if (!f) return toast('choose a backup .zip first', true);
    if (confirm.toUpperCase() !== 'RESTORE') return toast('type RESTORE to confirm', true);
    if (!window.confirm('Restore ' + f.name + ' over the current system?\n\n' +
      'This replaces config/, state/, documents/ and kb/sources/ with what is in the backup.\n' +
      'A safety backup of the current system is written to backups/ first.')) return;
    const fd = new FormData(); fd.append('file', f); fd.append('confirm', confirm);
    toast('restoring…');
    const r = await fetch('/api/backup/restore', { method: 'POST', headers: { 'X-Session': TOKEN }, body: fd });
    const d = await r.json().catch(() => ({ error: 'restore failed' }));
    toast(d.ok || d.error, !!d.error);
    if (d.reload) setTimeout(() => location.reload(), 1200);
  },
  clearData: async (scope) => {
    const confirm = $('#cl-confirm').value.trim();
    if (confirm.toUpperCase() !== 'CLEAR') return toast('type CLEAR to confirm', true);
    const what = scope === 'full'
      ? 'every application, every document AND the knowledge-graph index (a rebuild takes 20–30 minutes)'
      : 'the register, queues, drafts, saved job ads and every generated document';
    if (!window.confirm('Delete ' + what + '?\n\nConfig and kb/sources/ are kept.\n' +
      'A safety backup is written to backups/ first, but this cannot be undone from the UI.')) return;
    const d = await api('/api/backup/clear', { scope, confirm });
    toast(d.ok || d.error, !!d.error);
    if (d.reload) setTimeout(() => location.reload(), 1200);
  },
  googleSave: async () => {
    const d = await api('/api/google', { config_dir: $('#g-dir').value, credentials: $('#g-cred').value,
      token: $('#g-token').value, client_id: $('#g-id').value, client_secret: $('#g-secret').value });
    toast(d.ok || d.error, !!d.error);
  },
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
      <input data-env="${esc(k)}" value="${esc(v)}" style="flex:1" onchange="App.saveAI()">
      <button class="small" onclick="App.aiDel('${esc(k)}')" title="remove">✕</button>`;
    box.appendChild(row); $('#ai-env-k').value = ''; $('#ai-env-v').value = '';
    App.saveAI();
  },
  aiDel: (k) => {
    const el = document.querySelector(`#ai-env input[data-env="${k}"]`);
    if (el) el.closest('.row').remove();
    App.saveAI({ envExtra: { [k]: '' } });
  },
  useOpenRouter: async () => {
    const key = ($('#ai-or-key') && $('#ai-or-key').value || '').trim();
    const env = key ? { OPENROUTER_API_KEY: key } : {};
    const pick = ($('#ai-model-sel') && $('#ai-model-sel').value || '').trim();
    const model = pick && pick.includes('/') && !/^(opencode|opencode-go|claude)/.test(pick)
      ? pick : 'deepseek/deepseek-v4.1-flash';
    const d = await api('/api/agent/config', { agent: 'openrouter', model,
      models: { openrouter: model }, env });
    toast(d.ok || d.error, !!d.error);
    if (!d.error) App.settings('ai');
  },
  useLocal: async () => {
    const url = (($('#ai-local-url') && $('#ai-local-url').value.trim()) || 'http://127.0.0.1:8080/v1').replace(/\/$/, '');
    const key = ($('#ai-local-key') && $('#ai-local-key').value.trim()) || '';
    const env = { LOCAL_LLM_BASE_URL: url };
    if (key) env.LOCAL_LLM_API_KEY = key;
    let d = await api('/api/agent/config', { agent: 'local', model: '', models: {}, env });
    if (d.error) return toast(d.error, true);
    const m = await api('/api/agent/models?agent=local');
    const model = ((m && m.models) || [])[0] || 'lfm3-1.7b-heretic';
    d = await api('/api/agent/config', { agent: 'local', model, models: { local: model }, env });
    toast(d.ok || d.error, !!d.error);
    if (!d.error) { loadChatModel(); App.settings('ai'); }
  },
  aiStatus: (msg, bad) => {
    const el = $('#ai-msg');
    if (el) { el.textContent = msg; el.className = 'muted mini' + (bad ? ' bad' : ''); }
    if (bad) toast(msg, true);
  },
  aiFillModels: async (a) => {
    const sel = $('#ai-model-sel'); if (!sel) return;
    const seq = ++AI_MODEL_SEQ;
    const who = (a && (a.which || a.agent)) || '';
    let m = { models: [], source: '' };
    try { m = await api('/api/agent/models?agent=' + encodeURIComponent(who)); } catch (e) { return; }
    if (seq !== AI_MODEL_SEQ) return;
    const cur = (a && a.model) || '';
    const list = m.models || [];
    sel.innerHTML = modelOptionsHTML(m.groups || [], cur, list);
    const custom = $('#ai-model-custom');
    if (custom) custom.value = (cur && !list.includes(cur)) ? cur : '';
    sel.title = m.source ? `models from ${m.source}` : 'type a model id instead';
  },
  saveAI: async (opts = {}) => {
    const has = (k) => Object.prototype.hasOwnProperty.call(opts, k);
    const env = Object.assign({}, opts.envExtra || {});
    document.querySelectorAll('#ai-env input[data-env]').forEach(i => { if (i.value) env[i.dataset.env] = i.value; });
    const orKey = ($('#ai-or-key') && $('#ai-or-key').value || '').trim();
    if (orKey) env.OPENROUTER_API_KEY = orKey;
    const localUrl = ($('#ai-local-url') && $('#ai-local-url').value.trim() || '');
    if (localUrl) env.LOCAL_LLM_BASE_URL = localUrl.replace(/\/$/, '');
    const localKey = ($('#ai-local-key') && $('#ai-local-key').value.trim() || '');
    if (localKey) env.LOCAL_LLM_API_KEY = localKey;
    let agent = has('agent') ? String(opts.agent || '').trim() : (($('#ai-agent') && $('#ai-agent').value) || '').trim();
    if (agent === '__custom__') agent = ($('#ai-agent-custom') && $('#ai-agent-custom').value.trim()) || '';
    let model = has('model') ? String(opts.model || '').trim()
      : ((($('#ai-model-custom') && $('#ai-model-custom').value.trim()) || ($('#ai-model-sel') && $('#ai-model-sel').value) || '').trim());
    if (!agent) model = '';
    const models = agent && model ? { [agent]: model } : {};
    const d = await api('/api/agent/config', { agent, model, models, env });
    if (d.error) { App.aiStatus(d.error, true); return d; }
    const saved = d.config || {};
    const iu = $('#ai-inuse'); if (iu) iu.textContent = saved.agent || agent || 'auto';
    const top = $('#chat-model');
    if (top) {
      top.dataset.agent = saved.agent || agent || '';
      top.dataset.configured = saved.agent || agent || '';
      const target = saved.model || model;
      if (target) {
        let opt = Array.from(top.options).find(o => o.value === target);
        if (!opt) { opt = document.createElement('option'); opt.value = target; opt.textContent = target; top.appendChild(opt); }
        top.value = target;
      }
    }
    App.aiStatus('saved');
    loadChatModel(true);
    return d;
  },
  saveGR: async () => {
    const vars = {}; document.querySelectorAll('#ai-gr input[data-gr]').forEach(i => { if (i.value) vars[i.dataset.gr] = i.value; });
    const d = await api('/api/graphrag/env', { vars });
    if (d.error) return App.aiStatus(d.error, true);
    App.aiStatus('GraphRAG saved');
  },
  saveGmailReview: async () => {
    const el = $('#gmail-review-enabled'), model = $('#gmail-review-model'), auto = $('#gmail-review-auto');
    const d = await api('/api/gmail/review/config', {
      enabled: !!(el && el.checked), use_model: !!(model && model.checked),
      auto_model: !!(auto && auto.checked)
    });
    toast(d.ok || d.error, !!d.error);
    if (!d.error) loadGmailReview();
  },
  kbDel: async (path) => {
    const d = await api('/api/kb/delete', { path });
    toast(d.ok || d.error, !!d.error);
    if (!d.error) {
      const page = $('#knowledge');
      if (page && !page.classList.contains('hide')) App.kgSide('sources');
      else App.settings('kb');
    }
  },
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
  openKnowledge: async () => {
    const page = $('#knowledge'); if (!page) return;
    const cfg = $('#cfg'); if (cfg) cfg.classList.add('hide');
    page.classList.remove('hide');
    document.body.classList.add('knowledge-open');
    try { history.replaceState(null, '', '#knowledge'); } catch (e) {}
    const d = await api('/api/graph?kind=stats');
    const st = $('#kg-stats');
    if (st) st.textContent = d && d.entities
      ? `${d.entities} entities · ${d.relationships} relationships · ${d.communities} communities`
      : 'Index not built yet';
    if (d && d.entities) App.graphTypes();
    else if ($('#kg-side-body')) {
      $('#kg-side-body').className = 'kg-side-body muted mini';
      $('#kg-side-body').textContent = 'No graph index yet. Add documents and rebuild the graph.';
    }
  },
  closeKnowledge: () => {
    kgStop();
    const page = $('#knowledge'); if (page) page.classList.add('hide');
    document.body.classList.remove('knowledge-open');
    try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {}
  },
  graphTypes: async () => {
    const msg = $('#kg-msg'); if (msg) msg.textContent = 'reading topics…';
    const d = await api('/api/graph/types?limit=24');
    if (!d || d.error) { if (msg) msg.textContent = (d && d.error) || 'could not read the topics'; return; }
    await kgRender(d);
    KG.crumbs = [];
    KG.parent = null;
    KG.total = d.total || d.nodes.length;
    KG.type = null;
    kgCrumbs([], null);
    App.graphHideResults();
    const gall = $('#kg-all'); if (gall) gall.style.display = 'none';
    if (msg) msg.textContent = `${d.nodes.length} topics · ${d.links.length} links between topics`;
  },
  graphTypeEntities: async (type) => {
    const msg = $('#kg-msg'); if (msg) msg.textContent = 'reading entities…';
    const d = await api('/api/graph/type?type=' + encodeURIComponent(type) + '&limit=90');
    if (!d || d.error) { if (msg) msg.textContent = (d && d.error) || 'could not read that topic'; return; }
    await kgRender(d);
    KG.crumbs = [];
    KG.parent = null;
    KG.type = d.type;
    kgCrumbs([], d.label);
    App.graphHideResults();
    const gall = $('#kg-all'); if (gall) gall.style.display = 'none';
    if (msg) msg.textContent = `${d.nodes.length} of ${d.total} entities · ${d.links.length} relationships`;
  },
  openSource: async (name) => {
    const d = await api('/api/kb/find?name=' + encodeURIComponent(name));
    if (!d || d.error) { toast(d && d.error ? d.error : 'source not found', true); return; }
    viewDoc(d.path, name);
  },
  openSourcePath: (path, name) => viewDoc(path, name),
  kgSide: async (tab) => {
    document.querySelectorAll('.kg-side-tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === tab));
    const body = $('#kg-side-body'); if (!body) return;
    if (tab === 'details') {
      if (KG && KG.selected) kgSelect(KG.selected);
      else kgClear();
      return;
    }
    if (tab === 'classes') {
      body.className = 'kg-side-body';
      body.innerHTML = '<span class="muted mini">reading ontology…</span>';
      const d = await api('/api/graph/ontology');
      if (!d || d.error) { body.innerHTML = `<span class="bad mini">${esc((d && d.error) || 'could not read the ontology')}</span>`; return; }
      const classes = d.classes || [];
      body.innerHTML = `<p class="muted mini">A small, explicit vocabulary for the candidate's record. Every graph entity is mapped to one class; the application layer will reuse the same classes for job requirements and evidence.</p>
        <div class="kg-class-list">` + classes.map(c => `<div class="kg-class-row${c.count ? '' : ' empty'}">
          <i style="background:${c.color}"></i><b>${esc(c.label)}</b><span class="muted mini">${c.count}</span>
          ${c.count ? `<button class="small" data-id="${esc(c.id)}" onclick="App.graphTypeEntities(this.dataset.id)">Open</button>` : ''}
          <div class="muted mini kg-class-desc">${esc(c.description || '')}</div></div>`).join('') + '</div>' +
        `<h4 style="margin:12px 0 2px">Relations</h4><div class="kg-rel-list">` +
        (d.relations || []).map(r => `<div class="kg-rel"><b>${esc(r.label)}</b><span class="muted mini">${esc(r.description || '')}</span></div>`).join('') +
        `</div><p class="muted mini" style="margin-top:8px">${esc(d.note || '')}</p>`;
      return;
    }
    if (tab === 'roles') {
      body.className = 'kg-side-body';
      body.innerHTML = '<span class="muted mini">reading roles…</span>';
      const rows = await api('/api/grid');
      if (!Array.isArray(rows)) { body.innerHTML = '<span class="bad mini">could not read the register</span>'; return; }
      const rank = { PREPARED: 0, QUEUED: 1, INTERVIEW: 2, MANUAL: 3, BLOCKED: 4, IN_PROGRESS: 5, SUBMITTED: 6 };
      const active = rows.filter(r => Object.prototype.hasOwnProperty.call(rank, r.status))
        .sort((a, b) => (rank[a.status] - rank[b.status]) || ((b.match || 0) - (a.match || 0)));
      body.innerHTML = `<p class="muted mini">Open a role to work on the application in the job drawer, or prepare a queued role. The same evidence graph backs these documents.</p>` +
        (active.length ? active.slice(0, 40).map(r => `<div class="kg-role">
          <b>${esc(r.role)}</b><span class="muted mini">${esc(r.company)}</span>
          <div class="muted mini">${esc(r.status)}${r.match != null ? ` · match ${r.match}%` : ''}${r.action ? ' · action' : ''}</div>
          <div class="row" style="margin-top:4px">
            <button class="small" data-id="${esc(r.key)}" onclick="App.openRoleFromKnowledge(this.dataset.id)">Open</button>
            ${r.status === 'QUEUED' ? `<button class="small" data-id="${esc(r.key)}" onclick="App.prepareFromKnowledge(this.dataset.id)">Prepare</button>` : ''}
          </div></div>`).join('') :
          '<span class="muted mini">No roles in the register yet.</span>');
      return;
    }
    if (tab === 'sources') {
      body.className = 'kg-side-body';
      body.innerHTML = '<span class="muted mini">reading sources…</span>';
      const d = await api('/api/kb');
      if (!d || d.error) { body.innerHTML = `<span class="bad mini">${esc((d && d.error) || 'could not read sources')}</span>`; return; }
      const groups = d.sources || {};
      let list = '';
      for (const [g, files] of Object.entries(groups)) {
        if (!files || !files.length) continue;
        list += `<div class="kg-doc-group"><b>${esc(g)}</b><span class="muted mini">${files.length}</span>` +
          files.map(f => {
            const path = `kb/sources/${g === '(root)' ? '' : g + '/'}${f.name}`;
            return `<div class="kg-doc-row"><button class="kg-doc" data-path="${esc(path)}" data-name="${esc(f.name)}"
              onclick="App.openSourcePath(this.dataset.path, this.dataset.name)">${esc(f.name)}</button>
              <span class="muted mini">${fmtSize(f.size)}</span>
              <button class="small" data-path="${esc(path)}" onclick="App.kbDel(this.dataset.path)" title="delete">✕</button></div>`;
          }).join('') + '</div>';
      }
      const s = d.stats || {};
      body.innerHTML = `<p class="muted mini">Documents in <code>kb/sources/</code> feed the graph. Delete a file here, or add more below; rebuild the index afterwards to fold changes into the graph.</p>
        <div class="row" style="margin:6px 0"><input id="kg-kb-group" placeholder="group" style="max-width:110px">
          <input type="file" id="kg-kb-file" multiple><button onclick="App.kgUpload()">Upload</button></div>
        <div class="kg-doc-list">${list || '<span class="muted mini">no source documents yet</span>'}</div>
        <div class="row" style="margin-top:8px"><button class="risky" onclick="App.rebuildKB()">Rebuild graph</button>
          <span class="muted mini">${s.index ? `${s.entities} entities · ${s.relationships} relationships · ${s.documents} documents` : 'index not built'}</span></div>
        <pre class="doc kg-check">${esc((d.check || '').slice(-1600))}</pre>`;
      return;
    }
    body.className = 'kg-side-body';
    body.innerHTML = `<p class="muted mini">Add a fact or skill to the knowledge base. It is written as a source document, attributed to the employer or project you name, and becomes available to the next rebuild.</p>
      <input id="kg-fact-skill" placeholder="Skill or fact" style="width:100%;margin:4px 0">
      <input id="kg-fact-source" placeholder="Source (employer, project, certification…)" style="width:100%;margin:4px 0">
      <textarea id="kg-fact-detail" placeholder="Detail / evidence — what did you do, at what scale, with what result?" style="width:100%;height:78px;margin:4px 0"></textarea>
      <div class="row"><button onclick="App.addFact()">Add fact</button>
        <button class="small" onclick="App.kgSide('sources')">Manage documents</button></div>
      <p class="muted mini" style="margin-top:8px">A fact is a knowledge-base source, not a graph edit. Rebuild the graph when you want the new evidence in the index and in future CVs.</p>`;
  },
  addFact: async () => {
    const skill = (($('#kg-fact-skill') || {}).value || '').trim();
    const source = (($('#kg-fact-source') || {}).value || '').trim();
    const detail = (($('#kg-fact-detail') || {}).value || '').trim();
    if (!skill) { toast('name the skill or fact first', true); return; }
    const d = await api('/api/skills/evidence', { skill, source, detail });
    toast(d.error ? d.error : 'fact added — rebuild the graph to index it', !!d.error);
    if (!d.error) { $('#kg-fact-skill').value = ''; $('#kg-fact-source').value = ''; $('#kg-fact-detail').value = ''; }
  },
  kgUpload: async () => {
    const inp = $('#kg-kb-file'), grp = ($('#kg-kb-group') || {}).value || 'imported';
    if (!inp || !inp.files.length) { toast('choose file(s) first', true); return; }
    const fd = new FormData(); fd.append('group', grp);
    for (const f of inp.files) fd.append('files', f, f.name);
    try {
      const r = await fetch('/api/kb/upload', { method: 'POST', headers: { 'X-Session': TOKEN }, body: fd });
      const d = await r.json(); toast(d.ok || d.error, !!d.error);
      if (!d.error) App.kgSide('sources');
    } catch (e) { toast('upload failed: ' + e, true); }
  },
  openRoleFromKnowledge: async (key) => {
    const rows = await api('/api/grid');
    const r = Array.isArray(rows) ? rows.find(x => x.key === key) : null;
    if (!r) { toast('role not found', true); return; }
    App.closeKnowledge();
    openDetail(r);
  },
  prepareFromKnowledge: (key) => {
    App.closeKnowledge();
    App.prepareThis(key);
  },
  graphOverview: async (parent, limit) => {
    const msg = $('#kg-msg'); if (msg) msg.textContent = 'reading communities…';
    const n = limit || 16;
    const url = '/api/graph/overview?limit=' + n + (parent != null ? '&parent=' + encodeURIComponent(parent) : '');
    const d = await api(url);
    if (!d || d.error) { if (msg) msg.textContent = (d && d.error) || 'could not read the graph'; return; }
    await kgRender(d);
    KG.crumbs = d.breadcrumb || [];
    KG.parent = d.parent;
    KG.total = d.total || d.nodes.length;
    KG.limit = n;
    kgCrumbs(KG.crumbs, null);
    App.graphHideResults();
    const q = $('#kg-q'); if (q) q.value = '';
    const all = $('#kg-all'); if (all) all.style.display = (d.mode === 'communities' && KG.total > d.nodes.length) ? '' : 'none';
    if (msg) msg.textContent = d.mode === 'communities'
      ? `${d.nodes.length} of ${KG.total} communities · ${d.links.length} links`
      : `${d.nodes.length} entities · ${d.links.length} relationships`;
  },
  graphAll: () => App.graphOverview(KG ? KG.parent : null, 60),
  graphCommunity: async (id) => {
    const msg = $('#kg-msg'); if (msg) msg.textContent = 'reading community…';
    const d = await api('/api/graph/community?id=' + encodeURIComponent(id) + '&limit=90');
    if (!d || d.error) { if (msg) msg.textContent = (d && d.error) || 'could not read the community'; return; }
    await kgRender(d);
    KG.crumbs = d.breadcrumb || [];
    KG.parent = d.parent;
    KG.total = d.total || d.nodes.length;
    kgCrumbs(KG.crumbs, null);
    App.graphHideResults();
    const gall = $('#kg-all');
    if (gall) gall.style.display = (d.mode === 'communities' && KG.total > d.nodes.length) ? '' : 'none';
    if (msg) msg.textContent = d.mode === 'communities'
      ? `${d.nodes.length} sub-communities · ${d.links.length} links`
      : `${d.nodes.length} entities · ${d.links.length} relationships`;
  },
  graphEgo: async (q) => {
    const msg = $('#kg-msg'); if (msg) msg.textContent = 'building the neighbourhood…';
    const d = await api('/api/graph/ego?q=' + encodeURIComponent(q) + '&limit=50');
    if (!d || d.error) { if (msg) msg.textContent = (d && d.error) || 'could not build that view'; return; }
    await kgRender(d);
    KG.crumbs = d.breadcrumb || [];
    kgCrumbs(KG.crumbs, d.center || q);
    App.graphHideResults();
    const gall = $('#kg-all'); if (gall) gall.style.display = 'none';
    if (msg) msg.textContent = `${d.nodes.length} entities · ${d.links.length} relationships · ego network`;
  },
  graphSearch: async (q) => {
    q = (q || '').trim();
    if (!q) return App.graphTop();
    const box = $('#kg-results');
    if (!box) return;
    box.classList.remove('hide');
    box.innerHTML = '<span class="muted mini">searching…</span>';
    const d = await api('/api/graph/search?q=' + encodeURIComponent(q));
    if (!d || d.error) { box.innerHTML = `<span class="muted mini">${esc((d && d.error) || 'search failed')}</span>`; return; }
    const cs = d.communities || [], es = d.entities || [];
    if (!cs.length && !es.length) {
      box.innerHTML = `<div class="kg-res-head">No matches for “${esc(q)}” <button class="small" onclick="App.graphHideResults()">✕</button></div>`;
      return;
    }
    box.innerHTML = `<div class="kg-res-head">“${esc(q)}” · ${cs.length} communities · ${es.length} entities
        <button class="small" onclick="App.graphHideResults()">✕</button></div>` +
      (cs.length ? `<div class="kg-res-group"><b>Communities</b>` + cs.map(c =>
        `<button class="kg-res-item" data-id="${c.community}" onclick="App.graphCommunity(this.dataset.id)">
          <b>${esc(c.title)}</b><span class="muted mini">level ${c.level} · ${c.size} entities</span></button>`).join('') + '</div>' : '') +
      (es.length ? `<div class="kg-res-group"><b>Entities</b>` + es.map(e =>
        `<button class="kg-res-item" data-id="${esc(e.title)}" onclick="App.graphEgo(this.dataset.id)">
          <b>${esc(e.title)}</b><span class="muted mini">${esc(e.type)}${e.community_title ? ' · ' + esc(e.community_title) : ''}</span></button>`).join('') + '</div>' : '');
  },
  graphHideResults: () => { const b = $('#kg-results'); if (b) b.classList.add('hide'); },
  graphTop: () => App.graphOverview(null),
  graphBack: () => {
    if (!KG) return App.graphTypes();
    if (KG.view === 'types' || KG.view === 'type') return App.graphTypes();
    const crumbs = KG.crumbs || [];
    if (KG.mode === 'ego' && crumbs.length) return App.graphCommunity(crumbs[crumbs.length - 1].community);
    if (crumbs.length > 1) return App.graphOverview(crumbs[crumbs.length - 2].community);
    return App.graphOverview(null);
  },
  graphSelect: (id) => { if (KG && KG.byId.has(id)) kgSelect(id); else App.graphEgo(id); },
  graphFit: () => { if (window.__kg3d) window.__kg3d.fit(); },
  graphType: (type) => {
    if (!KG) return;
    if (KG.hidden.has(type)) KG.hidden.delete(type); else KG.hidden.add(type);
    kgVisibility();
  },
  chat: async () => {
    const inp = $('#chatmsg'), m = inp.value.trim(); if (!m) return;
    ACT = null; ACT_SIG = '';
    CHAT.running = true; CHAT_STICK = true; setSpin(true); renderChat();
    const d = await api('/api/chat', { message: m });
    if (d.error) { toast(d.error, true); CHAT.running = false; setSpin(false); renderChat(); return; }  // keep your text
    rememberChat(m);
    inp.value = '';
    if (d.queued) toast(`queued — the agent is busy (${d.pending} waiting)`);
    chatOffset = 0; clearInterval(CHAT_TIMER); CHAT_TIMER = setInterval(chatPoll, 1200);
  },
  chatStop: async () => {
    const d = await api('/api/chat/stop', {});
    toast(d.ok || d.error, !!d.error);
    CHAT.running = false; setSpin(false); chatPoll();
  },
  newChat: async () => {
    const d = await api('/api/chat/new', {});
    if (d.error) { toast(d.error, true); return; }
    clearInterval(CHAT_TIMER); CHAT_TIMER = null;
    ACT = null; ACT_SIG = '';
    CHAT = { segments: [], running: false }; setSpin(false); renderChat(); toast('agent history cleared');
  },
  open: (i) => openDetail(GRID[i]),
  showTaskLogFor: (company, role) => openTaskLog(taskLogName(company, role), `${company} — ${role}`),
  bucket: (kind) => {
    BUCKET = BUCKETS.some(b => b.k === kind) ? kind : 'active';
    BUCKET_BEFORE_SEARCH = null;
    renderBuckets();
    renderRows();
  },
  focusGroup: (which) => {
    BUCKET = 'focus';
    BUCKET_BEFORE_SEARCH = null;
    COLLAPSED.focus_pay = which === 'unknown';
    COLLAPSED.focus_unknown = which !== 'unknown';
    renderBuckets();
    renderRows();
  },
  clearFilters: () => {
    ['fstatus', 'fqueue', 'ftype', 'fpay', 'ffit', 'fwork'].forEach(id => { const el = $('#' + id); if (el) el.value = ''; });
    const fa = $('#faction'); if (fa) fa.checked = false;
    const q = $('#q'); if (q) q.value = '';
    const f = $('#filters'); if (f) f.open = false;
    BUCKET_BEFORE_SEARCH = null;
    BUCKET = 'active'; renderBuckets(); renderRows();
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
  submitPrepared: () => App.submitRoles(GRID.filter(r => r.status === 'PREPARED' && VIEW.includes(r.key)).map(r => r.key)),
  matchShown: async (el) => busyBtn(el, '⏳ recomputing match…', async () => {
    const d = await api('/api/match/recompute', { keys: VIEW });
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
    const d = await api('/api/register/row', {
      company: CUR.company, role: CUR.role, key: CUR.key,
      status: $('#dt-status').value, notes: $('#dt-notes').value,
      employment: $('#dt-emp') ? $('#dt-emp').value : undefined,
      work_model: $('#dt-work') ? $('#dt-work').value : undefined,
      salary: $('#dt-salary') ? $('#dt-salary').value : undefined
    });
    toast(d.ok || d.error, !!d.error); if (!d.error) { loadGrid(); }
  },
  saveAction: async () => {
    const v = ($('#dt-action') && $('#dt-action').value || '').trim();
    if (!v) return App.clearAction();
    const d = await api('/api/register/row', { company: CUR.company, role: CUR.role, action: v });
    toast(d.ok || d.error, !!d.error);
    if (!d.error) { CUR.action = v; if (DTAB === 0) dt(0); loadGrid(); }
  },
  clearAction: async () => {
    const d = await api('/api/register/row', { company: CUR.company, role: CUR.role, action: '' });
    toast(d.ok || d.error, !!d.error);
    if (!d.error) { CUR.action = ''; if (DTAB === 0) dt(0); loadGrid(); }
  },
  loadDrafts: async () => {
    if (!CUR) return;
    const d = await api(`/api/drafts?company=${encodeURIComponent(CUR.company)}&role=${encodeURIComponent(CUR.role)}`);
    const el = $('#dt-draft-list'); if (!el) return;
    const items = ((d && d.drafts) || []).filter(x => !x.sent_at);
    el.innerHTML = items.length ? items.map(x => {
      return `<div class="draftrow"><div class="row"><b>${esc(x.subject || '(no subject)')}</b><span style="flex:1"></span>
        <button class="mini" onclick='App.draftEdit(${JSON.stringify(x.path)})'>Edit</button>
        <button class="mini" onclick='App.draftSend(${JSON.stringify(x.path)})' title="Send this saved draft — one approval dialog">Send…</button>
        <button class="mini" onclick='App.draftDelete(${JSON.stringify(x.path)})'>Delete</button></div>
        <div class="muted mini">${esc(x.to || 'no recipient')} · updated ${esc((x.modified || '').slice(0, 16))}</div></div>`;
    }).join('') : '<span class="muted">no open drafts — sent replies are archived in state/drafts/sent.json.</span>';
  },
  draftNew: () => { DRAFT = null; openDraft({}); },
  draftEdit: async (path) => {
    const d = await api('/api/draft?path=' + encodeURIComponent(path));
    if (d.error) return toast(d.error, true);
    DRAFT = d.draft; openDraft(d.draft);
  },
  draftSend: async (path) => {
    if (!CUR || !path) return;
    if (DRAFT_SENDING) { toast('this draft is already sending — use the open approval dialog', true); return; }
    DRAFT_SENDING = true;
    try {
      toast('sending — approve the prompt when it appears');
      const s = await api('/api/draft/send', { path, clear_action: true });
      if (s.error) {
        if (/session/i.test(s.error)) return location.reload();
        return toast(s.error, true);
      }
      toast(s.ok || 'sent');
      await App.loadDrafts();
      await loadGrid();
      if (CUR && !$('#detail').hidden) openDetail(CUR);
    } finally {
      DRAFT_SENDING = false;
    }
  },
  draftSave: async (send) => {
    if (!CUR) return;
    if (send && DRAFT_SENDING) { toast('this draft is already sending — use the open approval dialog', true); return; }
    if (send) { DRAFT_SENDING = true; const sb = $('#dr-send'); if (sb) sb.disabled = true; }
    try {
      const payload = { path: DRAFT && DRAFT.path || '', company: CUR.company, role: CUR.role,
        to: $('#dr-to').value, cc: $('#dr-cc').value, subject: $('#dr-subject').value,
        attachments: $('#dr-attach').value, body: $('#dr-body').value };
      const d = await api('/api/draft/save', payload);
      if (d.error) { if (/session/i.test(d.error)) return location.reload(); return toast(d.error, true); }
      DRAFT = d.draft;
      if (!send) { toast('draft saved'); App.loadDrafts(); return; }
      if (!(d.draft.to || '').trim()) return toast('add a recipient before sending', true);
      if (!$('#dr-subject').value.trim()) return toast('add a subject before sending', true);
      toast('sending — approve the prompt when it appears');
      draftClose();                                  // the approval dialog must not sit behind the draft
      const s = await api('/api/draft/send', { path: DRAFT.path, clear_action: $('#dr-clear').checked });
      if (s.error) {
        if (/session/i.test(s.error)) return location.reload();
        toast(s.error, true);
        const showErr = () => { const e = $('#draft-error'); if (e) { e.textContent = 'Send failed: ' + s.error; e.classList.remove('hide'); } };
        showErr();
        if (DRAFT && DRAFT.path) App.draftEdit(DRAFT.path).then(showErr);
        return;
      }
      draftClose(); toast(s.ok || 'sent'); await App.loadDrafts(); await loadGrid();
      if (CUR && !$('#detail').hidden) openDetail(CUR);
    } finally {
      if (send) { DRAFT_SENDING = false; const sb = $('#dr-send'); if (sb) sb.disabled = false; }
    }
  },
  draftDelete: async (path) => {
    if (!confirm('Delete this draft?')) return;
    const d = await api('/api/draft/delete', { path });
    toast(d.ok || d.error, !!d.error); if (!d.error) App.loadDrafts();
  },
  roleChatLoad: async () => {
    if (!CUR) return;
    const d = await api('/api/role-chat?key=' + encodeURIComponent(CUR.key));
    ROLE_DATA = d || { segments: [], running: false, pending: 0 };
    const el = $('#rc-log'); if (!el) return;
    const stick = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    el.innerHTML = (d.segments && d.segments.length) ? roleSegsHTML(d.segments, d.running)
      : '<span class="muted">Ask anything about this role — e.g. “what should I say back?”, “what will they probe?”, “draft a follow-up”.</span>';
    if (stick) el.scrollTop = el.scrollHeight;
    const st = $('#rc-stop'); if (st) st.classList.toggle('hide', !d.running);
  },
  roleChatSend: async () => {
    if (!CUR) return;
    const inp = $('#rc-in'), m = (inp.value || '').trim(); if (!m) return;
    inp.value = '';
    await api('/api/role-chat', { key: CUR.key, company: CUR.company, role: CUR.role, message: m });
    App.roleChatLoad();
    if (!ROLE_TIMER && DTAB === 1) ROLE_TIMER = setInterval(rolePoll, 1500);
  },
  roleChatStop: async () => {
    if (!CUR) return;
    const d = await api('/api/role-chat/stop', { key: CUR.key });
    toast(d.ok || d.error, !!d.error); App.roleChatLoad();
  },
  roleChatNew: async () => {
    if (!CUR) return;
    if (!confirm('Clear this role\'s chat history?')) return;
    const d = await api('/api/role-chat/new', { key: CUR.key });
    toast(d.ok || d.error, !!d.error); ROLE_DATA = { segments: [], running: false, pending: 0 }; App.roleChatLoad();
  },
  draftAsk: () => {
    if (!CUR) return;
    const act = (CUR.action || '').trim(), notes = (CUR.notes || '').trim().slice(0, 1500);
    const msg = ['Draft a reply for this application and save it as a draft (do NOT send it).',
      `Company: ${CUR.company}`, `Role: ${CUR.role}`,
      act ? `What is needed: ${act}` : '', notes ? `Context: ${notes}` : '',
      'Read the latest relevant email in Gmail for this role (search the sender/subject), write a concise reply in my voice, then save it with:',
      `  python3 tools/draft_email.py --company "${CUR.company}" --role "${CUR.role}" --to "<recipient>" --subject "Re: <subject>" --body-file /tmp/reply.txt`,
      'Then tell me the saved path. I will review and send it from the row drawer.'].filter(Boolean).join('\n');
    setPanel('agent', { open: true });
    $('#chatmsg').value = msg; App.chat();
  },
};
let CF = 'cv.json', CUR = null, CF_SEC = 'accounts', DRAFT = null, AI_MODEL_SEQ = 0;
let ROLE_DATA = { segments: [], running: false, pending: 0 }, ROLE_TIMER = null;

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
let GRID_TIMER = null, LIVE_RUNNING = false, IDLE_TICKS = 0, WAS_BUSY = false, BUSY_NAME = '', DTAB = 0;
let SHOW_DISMISSED = localStorage.getItem('showDismissed') === '1';
let GROUPED = localStorage.getItem('grid.grouped') !== '0';
const shown = (r) => SHOW_DISMISSED || !r.dismissed;
async function loadGrid() {
  const sc = document.querySelector('.scroll'), y = sc ? sc.scrollTop : 0;
  const g = await api('/api/grid');
  if (Array.isArray(g)) GRID = g;          // keep the last good grid through a transient error
  renderBuckets();
  renderRows();
  if (sc) sc.scrollTop = y;
}
function bucketCounts() {
  const c = { needs: 0, prepared: 0, ongoing: 0, pipeline: 0, done: 0 };
  GRID.forEach(r => { if (!shown(r)) return; const k = bucketOf(r); c[k] = (c[k] || 0) + 1; });
  const live = GRID.filter(shown);
  return { ...c, focus: live.filter(r => r.focus || r.focus_unknown).length,
           active: c.needs + c.prepared + c.ongoing + c.pipeline, all: live.length };
}
function renderBuckets() {
  const el = $('#metrics'); if (!el) return;
  const c = bucketCounts();
  el.innerHTML = BUCKETS.map(b =>
    `<button type="button" class="metric bucket ${b.k === BUCKET ? 'on' : ''}${b.k === 'needs' && c.needs ? ' hot' : ''}" data-bucket="${b.k}"${T(b.hint)}><b>${c[b.k] || 0}</b>${esc(b.label)}</button>`
  ).join('');
  el.querySelectorAll('.bucket').forEach(b => b.onclick = () => App.bucket(b.dataset.bucket));
}
async function gridTick() {                 // keep the grid live (faster while a run is active)
  try { await loadGrid(); } catch (e) { console.warn('grid refresh failed', e); }
  setTimeout(gridTick, LIVE_RUNNING ? 3000 : 8000);
}
/* ---------- application state graph ---------- */
const SG_W = 130, SG_H = 62, SG_H2 = 56;
const SG_MAIN = [
  { s: 'QUEUED', x: 20, note: 'queued, not applied' },
  { s: 'DRAFTING', x: 195, note: 'ad saved, docs in progress' },
  { s: 'PREPARED', x: 370, note: 'documents gated' },
  { s: 'SUBMITTED', x: 545, note: 'application sent' },
  { s: 'IN_PROGRESS', x: 720, note: 'employer reviewing' },
  { s: 'INTERVIEW', x: 895, note: 'invited / booked / held' },
  { s: 'OFFER', x: 1070, note: 'offer received' },
];
const SG_SIDE = [
  { s: 'BLOCKED', x: 545, note: 'wall: captcha / login' },
  { s: 'MANUAL', x: 720, note: 'needs you' },
  { s: 'REJECTED', x: 895, note: 'not selected' },
  { s: 'CLOSED', x: 1070, note: 'withdrawn / expired / dup' },
];
const SG_EDGES = [
  [150, 81, 193, 81, 'ad saved'], [325, 81, 368, 81, 'docs gated'],
  [500, 81, 543, 81, 'sent'], [675, 81, 718, 81, 'reply'],
  [850, 81, 893, 81, 'invite'], [1025, 81, 1068, 81, 'offer'],
  [590, 112, 590, 183, 'wall'], [675, 213, 718, 213, 'hand over'],
];
// Rejection can follow any applied state, so it is fed by a bus from
// SUBMITTED, IN_PROGRESS and INTERVIEW rather than a single arrow.
const SG_PATHS = [
  { d: 'M640,112 L640,165 L960,165 L960,183', label: 'not selected', lx: 800, ly: 159, arrow: true },
  { d: 'M785,112 L785,165', lx: 0, ly: 0, arrow: false },
  { d: 'M960,112 L960,165', lx: 0, ly: 0, arrow: false },
];

function renderStateGraph() {
  const box = document.getElementById('sg-body');
  if (!box) return;
  const counts = {};
  GRID.forEach(r => { if (shown(r)) counts[r.status] = (counts[r.status] || 0) + 1; });
  const active = ($('#fstatus') || {}).value || '';
  const arrow = '<defs><marker id="sg-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#4b5563"/></marker></defs>';
  const edge = ([x1, y1, x2, y2, label]) => {
    const midx = (x1 + x2) / 2, midy = (y1 + y2) / 2;
    const horiz = y1 === y2;
    const dashed = !horiz ? ' dashed' : '';
    const labelPos = horiz
      ? `x="${midx}" y="${midy - 5}" text-anchor="middle"`
      : `x="${x1 + 8}" y="${midy + 3}" text-anchor="start"`;
    return `<path class="sg-edge-path${dashed}" d="M${x1},${y1} L${x2},${y2}" marker-end="url(#sg-arrow)"/>` +
      `<text class="sg-edge" ${labelPos}>${esc(label)}</text>`;
  };
  const node = (n, y, h) => {
    const on = active === n.s;
    return `<g class="sg-node sg-${n.s}${on ? ' active' : ''}" data-status="${n.s}" role="button" tabindex="0" aria-label="Filter the grid by ${n.s}">` +
      `<rect class="sg-rect" x="${n.x}" y="${y}" width="${SG_W}" height="${h}" rx="9"/>` +
      `<text class="sg-title" x="${n.x + 12}" y="${y + 23}">${n.s}</text>` +
      `<text class="sg-count" x="${n.x + SG_W - 12}" y="${y + 23}" text-anchor="end">${counts[n.s] || 0}</text>` +
      `<text class="sg-note" x="${n.x + 12}" y="${y + 44}">${esc(n.note)}</text></g>`;
  };
  const paths = SG_PATHS.map(p =>
    `<path class="sg-edge-path dashed" d="${p.d}"${p.arrow ? ' marker-end="url(#sg-arrow)"' : ''}/>` +
    (p.label ? `<text class="sg-edge" x="${p.lx}" y="${p.ly}" text-anchor="middle">${esc(p.label)}</text>` : '')).join('');
  const svg = `<svg viewBox="0 0 1220 272" class="sg-svg" role="img" aria-label="Application states">` +
    arrow + SG_EDGES.map(edge).join('') + paths +
    SG_MAIN.map(n => node(n, 50, SG_H)).join('') +
    SG_SIDE.map(n => node(n, 185, SG_H2)).join('') +
    `<text class="sg-cap" x="20" y="262">Counts exclude dismissed roles · click a state to filter · REJECTED can follow any applied state; CLOSED any state</text></svg>`;
  box.innerHTML = svg;
  // Side states are reached from several places; say so in the caption area.
}
(() => {
  const sg = document.getElementById('sg');
  if (!sg) return;
  try { sg.open = localStorage.getItem('sg.open') === '1'; } catch (e) {}
  sg.addEventListener('toggle', () => {
    try { localStorage.setItem('sg.open', sg.open ? '1' : '0'); } catch (e) {}
    if (sg.open) renderStateGraph();
  });
  const body = document.getElementById('sg-body');
  if (!body) return;
  body.addEventListener('click', (e) => {
    const g = e.target.closest('.sg-node');
    if (!g) return;
    const sel = $('#fstatus');
    if (!sel) return;
    sel.value = g.dataset.status;
    BUCKET = 'all'; BUCKET_BEFORE_SEARCH = null;
    renderBuckets(); renderRows();
  });
  body.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const g = e.target.closest('.sg-node');
    if (!g) return;
    e.preventDefault(); g.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
})();

function renderRows() {
  const q = $('#q').value.toLowerCase(), st = $('#fstatus').value, qq = $('#fqueue').value;
  const ft = $('#ftype') ? $('#ftype').value : '';
  const fa = $('#faction') && $('#faction').checked;
  const mp = parseInt(($('#fpay') || {}).value || '0', 10) || 0;
  const mf = parseInt(($('#ffit') || {}).value || '0', 10) || 0;
  const wm = ($('#fwork') || {}).value || '';
  const cy = String(new Date().getFullYear());
  const shortDate = (d) => { const [y, m, dd] = d.split('-'); return y === cy ? `${m}-${dd}` : `${y.slice(2)}-${m}-${dd}`; };
  const disp = (r) => r.label || r.status;               // INTERVIEW rows show SCHEDULED when an interview is still ahead
  const statusMatch = (r) => !st || (st === 'INTERVIEW' ? ['INTERVIEW', 'SCHEDULED', 'INVITED'].includes(disp(r)) : disp(r) === st);
  const typeMatch = (r) => !ft || (ft === '__none' ? !r.employment : (r.employment || '') === ft);
  const actMatch = (r) => !fa || !!r.action;
  const payMatch = (r) => !mp || (r.salary_eur != null && r.salary_eur >= mp);
  const fitMatch = (r) => !mf || (r.match != null && r.match >= mf);
  const workMatch = (r) => !wm || (r.work_model || 'unknown') === wm;
  const filt = (r) => shown(r) && statusMatch(r) && typeMatch(r) && actMatch(r) && payMatch(r) && fitMatch(r) && workMatch(r) &&
    (!qq || r.queue === qq) &&
    (!q || (r.company + ' ' + r.role + ' ' + (r.ats || '') + ' ' + (r.action || '')).toLowerCase().includes(q));
  let rows = GRID.filter(filt);
  if (BUCKET === 'active') rows = rows.filter(r => bucketOf(r) !== 'done');
  else if (BUCKET === 'focus') rows = rows.filter(r => r.focus || r.focus_unknown);
  else if (BUCKET !== 'all') rows = rows.filter(r => bucketOf(r) === BUCKET);
  VIEW = rows.map(r => r.key);

  const k = SORT.k;
  const rank = (r) => r.running ? 0 : (r.status === 'QUEUED' ? 1 : 2);   // in-flight + queued float to the top
  const needRank = (r) => r.status === 'OFFER' ? 0 : ((r.label || '') === 'INVITED' ? 1 : (r.action ? 2 : 3));
  const sortRows = (arr, group) => arr.slice().sort((a, b) => {
    const pa = a.pinned ? 0 : 1, pb = b.pinned ? 0 : 1;
    if (pa !== pb) return pa - pb;
    if (group === 'focus_pay' && k === 'date') {
      const sa = a.focus_score || 0, sb = b.focus_score || 0;
      if (sa !== sb) return sb - sa;
    }
    if (group === 'focus_unknown' && k === 'date') {
      const ma = a.match || 0, mb = b.match || 0;
      if (ma !== mb) return mb - ma;
    }
    if (group === 'needs' && k === 'date') {
      const na = needRank(a), nb = needRank(b);
      if (na !== nb) return na - nb;
    }
    const ra = rank(a), rb = rank(b);
    if (ra !== rb) return ra - rb;
    const av = a[k] || '', bv = b[k] || '';
    return av < bv ? -SORT.dir : av > bv ? SORT.dir : 0;
  });
  const mbadge = (r) => r.match == null ? '<span class="muted"' + T('No score — this role has no saved job ad (ATS keywords) and/or no CV to compare') + '>—</span>'
    : `<span class="badge ${r.match >= 70 ? 'good' : r.match >= 40 ? 'mid' : 'bad'}"${T("CV-to-job fit: this % of the ad's ATS keywords are covered by the tailored CV")}>${r.match}%</span>`
      + (r.alignment === 'FAIL' ? ' <span class="badge bad"' + T('Pre-submit alignment gate FAILED for this role — open the row to see why') + '>✗</span>' : '');
  const payBadge = (r) => r.salary_eur == null
    ? (r.salary_override && r.salary_raw
        ? `<span class="badge bad"${T('Could not parse the salary override: ' + r.salary_raw + ' — edit it in the row’s Summary')}>?</span>`
        : `<span class="muted"${T('No salary figure in the ad — add one in the row’s Summary, or read the ad')}>—</span>`)
    : `<span class="badge ${r.salary_band === 'good' ? 'good' : r.salary_band === 'mid' ? 'mid' : 'bad'}"${T('Estimated annual pay in EUR' + (r.salary_override ? ' (manual override)' : ' from the ad') + (r.salary_raw ? ': ' + r.salary_raw : ''))}>${esc(r.salary_label || '—')}</span>`;
  const workBadge = (r) => {
    const w = r.work_model || 'unknown';
    if (w === 'unknown')
      return `<span class="muted"${T('Work model not found in the ad — set an override in the row’s Summary')}>—</span>`;
    const cls = w === 'remote' ? 'wm-remote' : w === 'hybrid' ? 'wm-hybrid' : 'wm-onsite';
    return `<span class="badge ${cls}"${T('Work model ' + (r.work_override ? '(manual override)' : 'detected from the ad') + ': ' + (r.work_label || w))}>${esc(r.work_label || w)}</span>`;
  };
  const rowHTML = (r) => {
    const i = GRID.indexOf(r);
    const sel = (CUR && (r.key === CUR.key || (r.company === CUR.company && r.role === CUR.role))
      && PANELS.detail && PANELS.detail.open) ? ' sel' : '';
    return `<tr class="click${sel}" onclick="App.open(${i})" oncontextmenu="return App.rowMenu(event, ${i})">` +
      `<td class="muted"${T(r.date ? 'Register row last updated ' + r.date : 'Not dated yet — queued, not applied')}>${r.date ? esc(shortDate(r.date)) : '—'}</td>` +
      `<td${T(r.company + '  ·  employer / recruiter')}>${r.running ? `<a class="runlink" data-company="${esc(r.company)}" data-role="${esc(r.role)}" onclick="event.stopPropagation();App.showTaskLogFor(this.dataset.company,this.dataset.role)" title="Show the live log"><span class="spin">🥜</span></a> ` : (PENDING.has(r.key) ? '<span class="spin" title="Queued — waiting to start">🥜</span> ' : '')}${r.pinned ? `<span class="pinned"${T('Pinned to the top of its group')}>📌</span> ` : ''}${r.action ? `<span class="actflag"${T(r.action)}>⚑</span> ` : ''}${esc(r.company)}</td>` +
      `<td${T(r.role + (r.employment ? '  ·  ' + r.employment : '') + '  ·  job title')}>${esc(r.role)}${r.employment && r.employment !== 'full-time' ? ` <span class="etag">${esc(r.employment)}</span>` : ''}</td>` +
      `<td class="muted"${T(r.ats ? 'Submitted through ' + r.ats + ' (the employer’s applicant-tracking system)' : 'No ATS recorded')}>${esc(r.ats)}</td>` +
      `<td>${chip(r.label || r.status)}${r.hint ? `<div class="mini muted whycell"${T(r.hint)}>${esc(r.hint.slice(0, 66))}</div>` : ''}</td><td>${mbadge(r)}</td>` +
      `<td>${payBadge(r)}</td><td>${workBadge(r)}</td>` +
      `<td${T(QUEUE_HELP[r.queue] || 'Not in any queue')}>${['pending', 'human', 'retry'].includes(r.queue)
        ? `<span class="badge ${r.queue === 'human' ? 'bad' : r.queue === 'retry' ? 'mid' : 'good'}">${esc(r.queue)}</span>`
        : `<span class="muted">—</span>`}</td>` +
      `<td${T(r.applied ? 'Provenance recorded — exact CV, letter and SHA-256 hashes on file' : 'No submission recorded (not applied, or not reconciled yet)')}>${r.applied ? '✓' : '<span class="muted">—</span>'}</td>` +
      `<td${T(r.spec ? 'A saved job description exists — open the row for the ad, ATS keywords and grounded context' : 'No saved job description')}>${r.spec ? '✓' : '<span class="muted">—</span>'}</td></tr>`;
  };

  const empty = (msg) => `<tr><td colspan="11" class="muted">${msg}
    <button class="small" type="button" onclick="App.clearFilters()">Clear filters</button>
    <button class="small" type="button" onclick="App.bucket('all')">Show all</button></td></tr>`;
  let html = '';
  let rendered = [];
  const advanced = !!(st || qq || ft || fa || mp || mf || wm || q);
  let groups = null;
  if (GROUPED && (BUCKET === 'active' || BUCKET === 'all')) {
    groups = BUCKET_GROUPS.filter(g => BUCKET === 'all' || g.k !== 'done')
      .map(g => ({ ...g, test: r => bucketOf(r) === g.k }));
    if (BUCKET === 'active' && !advanced && !rows.some(r => bucketOf(r) === 'needs'))
      html += '<tr class="grp calm"><td colspan="11">✓ Nothing needs you right now — ongoing applications and the apply queue are below.</td></tr>';
  } else if (BUCKET === 'focus') {
    groups = FOCUS_GROUPS;
  }
  if (groups) {
    for (const g of groups) {
      const gr = sortRows(rows.filter(g.test), g.k);
      if (!gr.length) continue;
      const collapsed = !advanced && !!COLLAPSED[g.k];
      const target = g.k === 'focus_pay' ? "App.focusGroup('pay')" :
        g.k === 'focus_unknown' ? "App.focusGroup('unknown')" : `App.bucket('${g.k}')`;
      html += `<tr class="grp ${g.k}${collapsed ? ' collapsed' : ''}" onclick="window.toggleGroup('${g.k}')">` +
        `<td colspan="11"><span class="grp-caret">${collapsed ? '▸' : '▾'}</span>` +
        `<span class="grp-name" onclick="event.stopPropagation();${target}" title="Filter to this group">${esc(g.title)}</span>` +
        `<span class="grp-desc">${esc(g.desc)}</span>` +
        `<span class="grp-n"><button type="button" class="countlink" onclick="event.stopPropagation();${target}" title="Filter to this group">${gr.length}</button></span></td></tr>`;
      if (!collapsed) { html += gr.map(rowHTML).join(''); rendered.push(...gr); }
    }
    if (!rows.length) html = empty(BUCKET === 'focus' ? 'No active roles match this focus.' : 'No rows in this view.');
  } else {
    const gr = sortRows(rows, BUCKET);
    rendered = gr;
    html = gr.map(rowHTML).join('') || empty('No matching rows in this view.');
  }
  VISIBLE = rendered.map(r => r.key);
  $('#rows').innerHTML = html;
  sortIndicators();
  renderStateGraph();
  if ($('#count')) {
    const c = { needs: 0, prepared: 0, ongoing: 0, pipeline: 0, done: 0 };
    rows.forEach(r => { const b = bucketOf(r); c[b] = (c[b] || 0) + 1; });
    const cl = (n, label, action, hint) =>
      `<button type="button" class="countlink" onclick="${action}" title="${esc(hint || ('Filter to ' + label))}">${n} ${label}</button>`;
    const dot = '<span class="muted"> · </span>';
    if (BUCKET === 'active')
      $('#count').innerHTML = cl(c.needs, 'need you', "App.bucket('needs')", 'Show the roles that need you') + dot +
        cl(c.prepared, 'prepared', "App.bucket('prepared')", 'Show prepared documents ready to review') + dot +
        cl(c.ongoing, 'ongoing', "App.bucket('ongoing')", 'Show ongoing applications') + dot +
        cl(c.pipeline, 'to apply', "App.bucket('pipeline')", 'Show the roles still to apply to');
    else if (BUCKET === 'all')
      $('#count').innerHTML = cl(c.needs, 'need you', "App.bucket('needs')") + dot +
        cl(c.prepared, 'prepared', "App.bucket('prepared')") + dot +
        cl(c.ongoing, 'ongoing', "App.bucket('ongoing')") + dot +
        cl(c.pipeline, 'to apply', "App.bucket('pipeline')") + dot +
        cl(c.done, 'done', "App.bucket('done')", 'Show finished roles');
    else if (BUCKET === 'focus')
      $('#count').innerHTML =
        cl(rows.filter(r => r.focus).length, 'pay well + fit', "App.focusGroup('pay')", 'Show roles with known pay at/above target') + dot +
        cl(rows.filter(r => r.focus_unknown).length, 'high fit, pay not stated', "App.focusGroup('unknown')", 'Show high-fit roles with no salary figure');
    else
      $('#count').textContent = `${rows.length} ${((BUCKETS.find(b => b.k === BUCKET) || {}).label || BUCKET).toLowerCase()}`;
  }
  const dismissedN = GRID.filter(r => r.dismissed).length;
  if (dismissedN && $('#count') && !SHOW_DISMISSED)
    $('#count').innerHTML += ` <button type="button" class="countlink" onclick="App.toggleDismissedView(true)" title="Show the roles you dismissed from the lists">· ${dismissedN} dismissed</button>`;
  if ($('#fact-count')) { const n = GRID.filter(r => r.action && shown(r)).length; $('#fact-count').textContent = n ? `(${n})` : ''; }
  if ($('#fdismissed-count')) { const n = GRID.filter(r => r.dismissed).length; $('#fdismissed-count').textContent = n ? `(${n})` : ''; }
  if ($('#filt-n')) {
    const n = [st, qq, ft, fa ? '1' : '', mp, mf, wm, q].filter(Boolean).length;
    $('#filt-n').textContent = n ? `(${n})` : '';
  }
}
window.toggleGroup = (k) => { COLLAPSED[k] = !COLLAPSED[k]; renderRows(); };

/* ---------- row context menu ---------- */
let CTX = null;

function closeCtx() {
  document.querySelectorAll('.ctxmenu').forEach(el => el.remove());
  CTX = null;
}
document.addEventListener('click', (e) => {
  if (CTX && ![...document.querySelectorAll('.ctxmenu')].some(el => el.contains(e.target))) closeCtx();
});
document.addEventListener('keydown', (e) => {
  if (!CTX) return;
  if (e.key === 'Escape') { closeCtx(); return; }
  const items = [...CTX.querySelectorAll('.ctx-item:not(.disabled)')];
  const at = items.indexOf(document.activeElement);
  if (e.key === 'ArrowDown') { e.preventDefault(); items[(at + 1 + items.length) % items.length]?.focus(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); items[(at - 1 + items.length) % items.length]?.focus(); }
});

function ctxMenuEl(items, head) {
  const el = document.createElement('div');
  el.className = 'ctxmenu';
  el.setAttribute('role', 'menu');
  if (head) {
    const h = document.createElement('div');
    h.className = 'ctx-head';
    h.innerHTML = head;
    el.appendChild(h);
  }
  items.forEach(it => {
    if (it.sep) { const s = document.createElement('div'); s.className = 'ctx-sep'; el.appendChild(s); return; }
    const b = document.createElement('button');
    b.type = 'button'; b.tabIndex = -1;
    b.className = 'ctx-item' + (it.danger ? ' danger' : '') + (it.disabled ? ' disabled' : '') + (it.sub ? ' has-sub' : '');
    b.setAttribute('role', 'menuitem');
    b.innerHTML = `<span class="ctx-ico">${it.icon || ''}</span><span class="ctx-lbl">${esc(it.label)}</span>` +
      (it.hint ? `<span class="ctx-hint">${esc(it.hint)}</span>` : '') +
      (it.sub ? '<span class="ctx-arrow">›</span>' : '');
    b.onmouseenter = () => { if (it.sub) ctxSub(b, it.sub); else ctxSubClose(); };
    b.onclick = (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      if (it.disabled) return;
      if (it.sub) { ctxSub(b, it.sub); return; }
      closeCtx(); it.run();
    };
    el.appendChild(b);
  });
  return el;
}

function ctxSubClose() { document.querySelectorAll('.ctxmenu.ctx-sub').forEach(el => el.remove()); }

function ctxSub(anchor, items) {
  ctxSubClose();
  const el = ctxMenuEl(items);
  el.classList.add('ctx-sub');
  document.body.appendChild(el);
  const r = anchor.getBoundingClientRect();
  let left = r.right + 4;
  if (left + 230 > innerWidth) left = r.left - el.offsetWidth - 4;
  el.style.left = Math.max(6, left) + 'px';
  el.style.top = Math.max(6, Math.min(r.top - 6, innerHeight - el.offsetHeight - 6)) + 'px';
}

function copyText(text) {
  if (!text) return;
  navigator.clipboard?.writeText(text).then(
    () => toast('copied: ' + text),
    () => toast('copy failed', true));
}

App.rowMenu = (ev, i) => {
  ev.preventDefault(); ev.stopPropagation();
  const r = GRID[i];
  if (!r) return;
  closeCtx();
  const tab = (n) => { DTAB = n; App.open(i); };
  const cur = (s) => (r.status || '').toUpperCase() === s;
  const st = (r.status || '').toUpperCase();
  const applied = !!r.applied || ['SUBMITTED', 'IN_PROGRESS', 'INTERVIEW', 'OFFER', 'REJECTED'].includes(st);
  const closed = ['REJECTED', 'CLOSED'].includes(st);
  const blocked = ['BLOCKED', 'MANUAL'].includes(st);
  const queued = ['pending', 'human', 'retry'].includes(r.queue);
  const hasDocs = !!(r.stages && r.stages.documents);
  const prepared = st === 'PREPARED';
  const canWrite = applied && !closed;
  const STATUSES = closed
    ? ['IN_PROGRESS', 'PREPARED', 'SUBMITTED', 'BLOCKED', 'MANUAL']
    : ['PREPARED', 'SUBMITTED', 'IN_PROGRESS', 'INTERVIEW', 'OFFER', 'REJECTED', 'BLOCKED', 'MANUAL', 'CLOSED'];
  const items = [
    { icon: '📄', label: 'Open details', run: () => App.open(i) },
    hasDocs ? { icon: '🗂', label: 'Documents', run: () => tab(6) } : null,
    r.spec ? { icon: '📋', label: 'Job ad & keywords', run: () => tab(3) } : null,
    { icon: '💬', label: 'Discuss this role', run: () => tab(1) },
    r.url ? { icon: '🌐', label: 'Open apply page', run: () => window.open(r.url, '_blank', 'noopener') } : null,
    r.running ? { icon: '🥜', label: 'Show live log', run: () => App.showTaskLogFor(r.company, r.role) } : null,
    { sep: true },
    (!applied || prepared) && !closed && !r.running
      ? { icon: '⚡', label: hasDocs ? 'Re-prepare documents' : 'Prepare documents', hint: 'CV + letter + gates', run: () => App.prepareRoles([r.key]) }
      : null,
    prepared && !r.running
      ? { icon: '🚀', label: 'Submit prepared', hint: 'sends it', danger: true, run: () => App.submitRoles([r.key]) }
      : null,
    (r.spec || hasDocs) ? { icon: '↻', label: 'Recompute match', run: () => App.matchThis(r.key) } : null,
    canWrite ? { icon: '🤖', label: 'Draft a reply with the agent', run: () => { App.open(i); App.draftAsk(); } } : null,
    { sep: true },
    { icon: '🏷', label: closed ? 'Reopen as' : 'Set status', sub: STATUSES.map(x => ({
        label: (cur(x) ? '✓ ' : '') + x,
        run: () => App.setStatus(r, x) })) },
    (!closed && !r.running) ? { icon: '⚑', label: r.action ? 'Update follow-up flag…' : 'Flag follow-up…', run: () => App.flagAction(r) } : null,
    r.action ? { icon: '⚐', label: 'Clear follow-up flag', run: () => App.clearFlag(r) } : null,
    { icon: '📌', label: r.pinned ? 'Unpin' : 'Pin to top', run: () => App.togglePin(r) },
    r.dismissed
      ? { icon: '↩', label: 'Restore to list', run: () => App.toggleDismiss(r) }
      : { icon: '✕', label: 'Dismiss from list', run: () => App.toggleDismiss(r) },
    ((!applied && !queued) || blocked) ? { sep: true } : null,
    (!applied && !prepared && !queued && !closed && !r.running)
      ? { icon: '🔁', label: blocked ? 'Re-queue for another attempt' : 'Queue to apply', run: () => App.queueAct('retry', r.company, r.role) }
      : null,
    blocked ? { icon: '🖐', label: 'Hand to me (autofill & finish)', danger: true, disabled: r.running, run: () => App.queueAct('human', r.company, r.role) } : null,
    queued ? { icon: '🗑', label: 'Remove from queue', danger: true, run: () => App.queueAct('delete', r.company, r.role) } : null,
    { sep: true },
    { icon: '📑', label: 'Copy', sub: [
      { label: 'Company', run: () => copyText(r.company) },
      { label: 'Role', run: () => copyText(r.role) },
      r.url ? { label: 'Apply URL', run: () => copyText(r.url) } : null,
      { label: 'Role key', run: () => copyText(r.key) },
    ].filter(Boolean) },
  ].filter(Boolean);

  // A separator must not lead, trail, or double up once items are filtered out.
  const clean = [];
  for (const it of items) {
    if (it.sep) { if (clean.length && !clean[clean.length - 1].sep) clean.push(it); }
    else clean.push(it);
  }
  while (clean.length && clean[clean.length - 1].sep) clean.pop();

  const head = `<div class="ctx-co">${esc(r.company)}</div>` +
    `<div class="ctx-role">${esc(r.role)}</div>` +
    `<div class="ctx-meta">${chip(r.label || r.status)}` +
      `${r.action ? ' <span class="actflag">⚑</span>' : ''}${r.pinned ? ' <span title="pinned">📌</span>' : ''}` +
      `${r.match != null ? ' · ' + r.match + '% fit' : ''}` +
      `${r.employment ? ' · ' + esc(r.employment) : ''}` +
      `${r.interview_at ? ' · ' + esc(String(r.interview_at).slice(0, 16)) : ''}</div>` +
    (r.action ? `<div class="ctx-note">${esc(r.action)}</div>` : '');

  const el = ctxMenuEl(clean, head);
  el.style.left = '0px'; el.style.top = '0px';
  document.body.appendChild(el);
  const w = el.offsetWidth, h = el.offsetHeight;
  const x = ev.clientX || (ev.target.getBoundingClientRect().right || 40);
  const y = ev.clientY || (ev.target.getBoundingClientRect().top || 40);
  el.style.left = Math.max(6, Math.min(x, innerWidth - w - 8)) + 'px';
  el.style.top = Math.max(6, Math.min(y, innerHeight - h - 8)) + 'px';
  CTX = el;
  el.querySelector('.ctx-item:not(.disabled)')?.focus();
  return false;
};

App.setStatus = async (r, status) => {
  const d = await api('/api/register/row', { company: r.company, role: r.role, status, key: r.key });
  toast(d.ok || d.error, !!d.error);
  if (!d.error) { await loadGrid(); if (CUR) openDetail(CUR); }
};

App.flagAction = async (r) => {
  const text = prompt('What needs doing for this role?', r.action || '');
  if (text === null) return;
  const d = await api('/api/register/row', { company: r.company, role: r.role, action: text.trim(), key: r.key });
  toast(d.ok || d.error, !!d.error);
  if (!d.error) { await loadGrid(); if (CUR) openDetail(CUR); }
};

App.clearFlag = async (r) => {
  const d = await api('/api/register/row', { company: r.company, role: r.role, action: '', key: r.key });
  toast(d.ok || d.error, !!d.error);
  if (!d.error) { await loadGrid(); if (CUR) openDetail(CUR); }
};

App.toggleDismiss = async (r) => {
  const d = await api('/api/roles/flags', { key: r.key, dismissed: !r.dismissed });
  toast(d.error ? d.error : (r.dismissed ? 'restored to the list' : 'dismissed from the list'), !!d.error);
  if (!d.error) { await loadGrid(); if (CUR && CUR.key === r.key && !r.dismissed) setPanel('detail', { open: false }); }
};

App.togglePin = async (r) => {
  const d = await api('/api/roles/flags', { key: r.key, pinned: !r.pinned });
  toast(d.error ? d.error : (r.pinned ? 'unpinned' : 'pinned to the top'), !!d.error);
  if (!d.error) await loadGrid();
};

App.toggleDismissedView = (on) => {
  SHOW_DISMISSED = !!on;
  localStorage.setItem('showDismissed', SHOW_DISMISSED ? '1' : '0');
  renderBuckets(); renderRows();
};
function sortIndicators() {
  document.querySelectorAll('#grid thead th[data-s]').forEach(th => {
    const on = th.dataset.s === SORT.k;
    th.classList.toggle('sorted', on);
    th.dataset.dir = on ? (SORT.dir === 1 ? 'asc' : 'desc') : '';
    th.setAttribute('aria-sort', on ? (SORT.dir === 1 ? 'ascending' : 'descending') : 'none');
  });
}
function syncGroupingButton() {
  const b = $('#grouping');
  if (!b) return;
  b.textContent = GROUPED ? '☰ Grouped' : '▤ Flat';
  b.classList.toggle('on', !GROUPED);
}
document.querySelectorAll('#grid th[data-s]').forEach(th => th.onclick = () => {
  const k = th.dataset.s;
  SORT = { k, dir: SORT.k === k ? -SORT.dir : (k === 'date' ? -1 : 1) };
  // A column sort is a whole-list sort: leave the bucket grouping so the order
  // is not hidden inside collapsed sections.
  GROUPED = false;
  localStorage.setItem('grid.grouped', '0');
  syncGroupingButton();
  renderRows();
});

/* ---------- resizable columns ---------- */
const COL_DEFAULTS = { date: 90, company: 195, role: 320, ats: 110, status: 160,
                       match: 70, salary: 85, work: 95, queue: 90, files: 55, ad: 50 };
function initGridCols() {
  const table = $('#grid'); if (!table) return;
  const ths = [...table.querySelectorAll('thead th')];
  const cols = ths.map((th, i) => th.dataset.col || th.dataset.s || ('c' + i));
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('grid.cols') || '{}') || {}; } catch (e) { saved = {}; }
  const widths = {};
  const cg = document.createElement('colgroup');
  cols.forEach((k) => {
    let w = Number(saved[k]);
    if (!Number.isFinite(w)) w = COL_DEFAULTS[k] || 100;
    widths[k] = Math.max(40, Math.min(800, w));
    const c = document.createElement('col');
    c.dataset.col = k; c.style.width = widths[k] + 'px';
    cg.appendChild(c);
  });
  table.insertBefore(cg, table.querySelector('thead'));
  table.style.tableLayout = 'fixed';
  // Percentage widths: the table always fills the same width as the toolbar and
  // the state graph, and every column scales with the window. The saved pixel
  // widths remain the ratio between columns.
  const applyWidth = () => {
    const total = cols.reduce((n, k) => n + (widths[k] || 100), 0) || 1;
    cols.forEach((k, i) => {
      cg.children[i].style.width = (100 * (widths[k] || 100) / total).toFixed(3) + '%';
    });
    table.style.width = '100%';
    table.style.minWidth = '980px';
  };
  applyWidth();
  const save = () => { try { localStorage.setItem('grid.cols', JSON.stringify(widths)); } catch (e) {} };
  const reset = (k, i) => {
    widths[k] = COL_DEFAULTS[k] || 100;
    applyWidth(); save();
  };
  ths.forEach((th, i) => {
    const k = cols[i];
    const h = document.createElement('span');
    h.className = 'col-resize';
    h.title = 'Drag to resize; double-click to reset';
    h.addEventListener('click', (e) => e.stopPropagation());
    h.addEventListener('dblclick', (e) => { e.preventDefault(); e.stopPropagation(); reset(k, i); });
    h.addEventListener('pointerdown', (e) => {
      e.preventDefault(); e.stopPropagation();
      const startX = e.clientX, startW = th.getBoundingClientRect().width;
      try { h.setPointerCapture(e.pointerId); } catch (err) {}
      table.classList.add('resizing');
      const move = (ev) => {
        const w = Math.max(40, Math.min(800, Math.round(startW + ev.clientX - startX)));
        widths[k] = w; applyWidth();
      };
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', up);
        table.classList.remove('resizing'); save();
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
      window.addEventListener('pointercancel', up);
    });
    th.appendChild(h);
  });
}

/* ---------- detail drawer ---------- */
async function openDetail(r) {
  if (!r) return;
  CUR = r; D = {}; P = {};
  if (ROLE_TIMER) { clearInterval(ROLE_TIMER); ROLE_TIMER = null; }
  ROLE_DATA = { segments: [], running: false, pending: 0 };
  setPanel('detail', { open: true });            // also re-renders the grid, marking this row
  $('#d-title').textContent = `${r.company} — ${r.role}`;
  const tabs = ['Summary', 'Discuss', 'Provenance', 'Job spec', 'ATS', 'Grounding', 'Documents'];
  $('#dtabs').innerHTML = tabs.map((t, i) => `<a class="${i === DTAB ? 'on' : ''}" onclick="dt(${i})">${t}</a>`).join('');
  $('#d-body').innerHTML = '<span class="muted">loading…</span>';
  const jobs = [api(`/api/provenance?company=${encodeURIComponent(r.company)}&role=${encodeURIComponent(r.role)}`)];
  if (r.spec) jobs.push(api('/api/roles/' + encodeURIComponent(r.jd_key || r.key)));
  const [p, d] = await Promise.all(jobs); P = p || {}; D = d || {};
  dt(DTAB);
}
window.dt = (i) => {
  const r = CUR, map = [summary, discuss, prov, spec, ats, grounding, tailored];
  DTAB = i;
  document.querySelectorAll('#dtabs a').forEach((a, n) => a.classList.toggle('on', n === i));
  $('#d-body').innerHTML = map[i](r) || '<span class="muted">—</span>';
  if (i === 0) App.loadDrafts();
  if (i === 1) {
    if (!ROLE_TIMER) ROLE_TIMER = setInterval(rolePoll, 1500);
    App.roleChatLoad();
  } else if (ROLE_TIMER) { clearInterval(ROLE_TIMER); ROLE_TIMER = null; }
};
const sec = (s, raw) => s ? (raw ? `<pre class="doc">${esc(s)}</pre>` : `<div class="doc md">${md(s)}</div>`) : '<span class="muted">(nothing yet)</span>';
const vbtn = (f, t) => f ? ` <button class="mini" onclick='viewDoc(${JSON.stringify(f)},"${t}")'>view</button>` : '';
function summary(r) {
  const m = (D.match) || {};
  const reg = ['QUEUED', 'PREPARED', 'SUBMITTED', 'IN_PROGRESS', 'INTERVIEW', 'OFFER', 'REJECTED', 'BLOCKED', 'MANUAL', 'CLOSED'];
  const known = reg.includes(r.status);
  const wl = (w) => w === 'remote' ? 'Remote' : w === 'hybrid' ? 'Hybrid' : w === 'on-site' ? 'On-site' : 'unknown';
  const notes = (r.notes || '').trim();
  const hist = notes ? notes.split(/\s*\|\s*/).filter(Boolean).map(x => `<li>${md(x)}</li>`).join('') : '';
  const act = (r.action || '').trim();
  return (act ? `<div class="actionbox"><span class="actflag">⚑</span> <b>Action:</b> ${esc(act)}</div>` : '') +
    `<div class="row" style="margin:6px 0 10px"><input id="dt-action" placeholder="needs a reply or follow-up? describe it…" value="${esc(act)}" style="flex:1">
      <button onclick="App.saveAction()">${act ? 'Update flag' : '⚑ Flag action'}</button>
      ${act ? '<button onclick="App.clearAction()">Clear</button>' : ''}</div>` +
    `<div class="drafts"><div class="row"><b>Drafted replies</b><span class="muted mini">review before sending</span><span style="flex:1"></span>
        <button class="small" onclick="App.draftAsk()" title="Ask the agent to read the latest email and save a draft for this role">🤖 Draft with agent</button>
        <button class="small" onclick="App.draftNew()">＋ New</button>
        <button class="small" onclick="App.loadDrafts()" title="Refresh drafts (the agent may have just saved one)">↻</button></div>
      <div id="dt-draft-list" class="muted mini">loading…</div></div>` +
    `<div class="statebox">
      <div class="row">${chip(r.label || r.status)}${r.hint ? `<span class="statehint">${esc(r.hint)}</span>` : ''}</div>
      <div class="stages">${(() => {
        const st = r.stages || {};
        const cell = (k, label) => `<span class="stage ${st[k] ? 'on' : ''}" title="${st[k] ? 'done' : 'not yet'}">${st[k] ? '✓' : '○'} ${label}</span>`;
        return cell('ad', 'Ad saved') + cell('keywords', 'Keywords') + cell('grounding', 'Grounded') + cell('documents', 'Documents') + cell('applied', 'Applied');
      })()}</div>
      <div class="state-meta mini muted">ATS: ${esc(r.ats || '—')}${r.employment ? ' · type: ' + esc(r.employment) : ''} · Pay: ${esc(r.salary_label || '—')}${r.salary_override ? ' (manual)' : ''} · Work: ${esc(wl(r.work_model))}${r.work_override ? ' (manual)' : ''} · Queue: ${esc(r.queue || 'not queued')}${r.date ? ' · updated ' + esc(r.date) : ''}${r.interview_at ? ' · interview ' + esc(r.interview_at) : ''} · <span class="mono">${esc(r.key)}</span></div>
      ${r.running ? `<div class="working"><a class="runlink" data-company="${esc(r.company)}" data-role="${esc(r.role)}" onclick="App.showTaskLogFor(this.dataset.company,this.dataset.role)" title="Show what this run is doing"><span class="spin">🥜</span> being worked on right now — show live log</a></div>` : ''}
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
    `<div class="row" style="margin:0 0 10px">
      <span class="muted">Work</span>
      <select id="dt-work">
        <option value="">auto — ${esc(wl(r.work_detected))}</option>
        ${['remote', 'hybrid', 'on-site'].map(x => `<option value="${x}" ${r.work_override && r.work_model === x ? 'selected' : ''}>${wl(x).toLowerCase()}</option>`).join('')}
      </select>
      <span class="muted">Pay</span>
      <input id="dt-salary" style="flex:1;max-width:380px" value="${esc(r.salary_override ? (r.salary_raw || '') : '')}" placeholder="${esc(r.salary_raw && !r.salary_override ? 'auto: ' + r.salary_raw : 'e.g. EUR 90000/yr')}">
      <span class="muted mini">blank = auto from the ad</span>
    </div>` +
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
function openDraft(d) {
  DRAFT = d && d.path ? d : null;
  $('#draftm-title').textContent = 'Draft reply' + (CUR ? ` — ${CUR.company} · ${CUR.role}` : '');
  $('#dr-to').value = d.to || '';
  $('#dr-cc').value = d.cc || '';
  $('#dr-subject').value = d.subject || '';
  $('#dr-attach').value = (d.attachments || []).join(', ');
  $('#dr-body').value = d.body || '';
  const de = $('#draft-error'); if (de) { de.textContent = ''; de.classList.add('hide'); }
  $('#draftm').classList.remove('hide');
  setTimeout(() => $('#dr-body').focus(), 50);
}
window.draftClose = () => $('#draftm').classList.add('hide');
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

/* Evidence overlay: the generated CV, colour-coded by the evidence behind each line. */
function evKws() {
  return (D.ats || '').split('\n').map(s => s.trim()).filter(s => s && s[0] !== '#');
}
function evMark(text, kws) {
  let out = esc(text);
  [...kws].sort((a, b) => b.length - a.length).forEach(k => {
    const re = new RegExp('(' + k.replace(/[.*+?^${}()|[\]\\-]/g, '\\$&') + ')', 'gi');
    out = out.replace(re, '<mark class="kw">$1</mark>');
  });
  return out;
}
function evRow(text, kws, kbText, sec) {
  const low = String(text || '').toLowerCase();
  const matched = kws.filter(k => low.includes(k.toLowerCase()));
  const grounded = matched.filter(k => kbText.includes(k.toLowerCase()));
  const s = matched.length && grounded.length ? 'good' : matched.length ? 'warn' : 'plain';
  const icon = s === 'good' ? '✓' : s === 'warn' ? '~' : '·';
  const tip = s === 'good' ? 'evidence-backed: names a requirement the knowledge base supports'
    : s === 'warn' ? 'names a requirement the knowledge base does not confirm — see the Grounding tab'
      : 'supporting detail: no job requirement keyword';
  const chips = matched.map(k => `<span class="missk${grounded.includes(k) ? ' evidenced' : ''}">${esc(k)}</span>`).join(' ');
  return `<div class="claim ${s}" data-sec="${esc(sec)}" data-kws="${esc(matched.join(', '))}" title="${esc(tip)}">`
    + `<span class="cl-mark">${icon}</span><span class="cl-text">${evMark(text, kws)}</span>`
    + (chips ? `<div class="cl-kws">${chips}</div>` : '') + '</div>';
}
function evSec(title, inner) { return `<div class="evsec"><div class="evsec-h">${esc(title)}</div>${inner}</div>`; }
function renderEvidence() {
  const view = $('#evview'); if (!view) return;
  if (!D.tailored_cv) { view.innerHTML = '<span class="muted">no content pack for this role yet</span>'; return; }
  let pack; try { pack = JSON.parse(D.tailored_cv); } catch (e) { pack = null; }
  if (!pack || typeof pack !== 'object') { view.innerHTML = '<span class="muted">could not parse the content pack</span>'; return; }
  const kws = evKws(), kbText = (D.kb || '').toLowerCase();
  const whole = JSON.stringify(pack).toLowerCase();
  const covered = kws.filter(k => whole.includes(k.toLowerCase()));
  const pct = kws.length ? Math.round(100 * covered.length / kws.length) : 0;
  const list = (arr, sec) => (arr || []).map((b, i) => evRow(b, kws, kbText, sec + ' #' + (i + 1))).join('');
  const exp = (pack.experience || []).map(e => {
    const hdr = `<div class="evjob">${esc(e.employer || '')}${e.title ? ' — ' + esc(e.title) : ''}<span class="muted">${e.dates ? ' · ' + esc(e.dates) : ''}</span></div>`;
    const bs = list(e.bullets, e.employer || 'role');
    const gs = (e.groups || []).map(g => list(g.bullets, g.label || e.employer || 'role')).join('');
    return hdr + bs + gs;
  }).join('');
  view.innerHTML =
    `<div class="evintro mini muted">Every line of the generated CV, scored against the job's `
    + `<b>${kws.length}</b> ATS requirement(s) and the knowledge base. `
    + `<span style="color:#8ce99a">green</span> = evidence-backed · `
    + `<span style="color:#ffd479">amber</span> = requirement not confirmed by the grounding · grey = supporting detail.</div>`
    + (pack.profile ? evSec('Profile', evRow(pack.profile, kws, kbText, 'profile')) : '')
    + (exp ? evSec('Experience', exp) : '')
    + ((pack.skills || []).length ? evSec('Skills', list(pack.skills, 'skills')) : '')
    + ((pack.selected_work || []).length ? evSec('Selected work', list(pack.selected_work, 'selected work')) : '');
  let g = 0, w = 0, n = 0;
  view.querySelectorAll('.claim').forEach(el => {
    if (el.classList.contains('good')) g++; else if (el.classList.contains('warn')) w++; else n++;
    el.onclick = () => toast((el.dataset.kws ? el.dataset.sec + ' → ' + el.dataset.kws
      : el.dataset.sec + ' → no requirement keyword (supporting detail)'));
  });
  const bar = $('#evbar'), sum = $('#evsum');
  if (bar) bar.style.width = pct + '%';
  if (sum) sum.innerHTML = `<b>${covered.length}/${kws.length}</b> requirements named · `
    + `<span style="color:#8ce99a">${g} backed</span> · <span style="color:#ffd479">${w} unconfirmed</span> · ${n} neutral`;
}
function tailored() {
  const d = D.docs || {};
  if (!d.cv && !d.cv_pdf && !d.letter && !d.letter_pdf) {
    return '<span class="muted">No rendered documents yet — run Prepare (review).</span>';
  }
  const raw = (p) => '/raw?path=' + encodeURIComponent(p);
  setTimeout(async () => {
    renderEvidence();
    const btn = $('#ev-toggle');
    if (btn) btn.onclick = () => {
      const shown = $('#evview').classList.toggle('hide') === false;
      $('#tpre').classList.toggle('hide', shown);
      btn.classList.toggle('on', shown);
    };
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
    `<div class="evhead">
      <button id="ev-toggle" class="small" title="Colour every line of the generated CV by the evidence behind it">◧ Evidence overlay</button>
      <span class="muted mini" id="evsum"></span>
    </div>
    <span class="evbar" title="share of the job's ATS requirements named somewhere in the CV"><i id="evbar"></i></span>
    <div id="evview" class="hide"></div>` +
    `<div class="muted mini" style="margin:10px 0 4px">CV${d.cv_pdf ? ' (PDF)' : ''}</div><div id="tpre">loading…</div>` +
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
  if (d && d.build) {                                  // server restarted or web files changed
    if (BUILD && d.build !== BUILD) { location.reload(); return; }
    BUILD = d.build;
  }
  LIVE_TASKS = d.running_tasks || [];
  const lb = $('#live-log');
  if (lb) {
    lb.classList.toggle('hide', !LIVE_TASKS.length);
    lb.title = LIVE_TASKS.length ? 'Show the live log: ' + LIVE_TASKS[0].label : 'No running task';
  }
  const a = d.action || {};
  const aname = (a.name || '').replace(/^action=/, '').replace(/\s*\(.*\)\s*$/, '');
  const delegated = d.delegated || [];
  let s = a.running ? '● ' + aname + ' …' : (d.active ? '● running' : '○ idle');
  (d.running || []).forEach(r => s += '  ▶ ' + r);
  delegated.forEach(x => s += '  ▶ ' + (x.title || 'subagent'));
  const t = (d.tail || []).slice(-1)[0];
  if (t) s += '   ' + t.t;
  const busy = !!a.running || d.active;
  if (busy) $('#live').innerHTML = NUT + esc(s);
  else $('#live').textContent = s;
  LIVE_RUNNING = busy || LIVE_RUNNING;                 // stay optimistic until confirmed idle
  document.querySelectorAll('#a-prepare,#a-submit,#a-reconcile,#a-prepare-shown,#a-submit-shown,#a-match,#d-body [data-act]')
    .forEach(b => { b.disabled = LIVE_RUNNING; });
  const rc = $('#runctl'); if (rc) { rc.classList.toggle('hide', !LIVE_RUNNING); $('#btn-pause').textContent = d.paused ? '▶ Resume' : '⏸ Pause'; }
  if (LIVE_RUNNING && !busy) $('#live').textContent = '● starting… (the run takes a few minutes — see the monitor)';
  if (busy) {
    IDLE_TICKS = 0; WAS_BUSY = true;
    BUSY_NAME = a.name || (d.active ? 'queue run' : 'run');
  } else if (LIVE_RUNNING && ++IDLE_TICKS >= 3) {
    LIVE_RUNNING = false;
    if (WAS_BUSY) {                                    // something we were watching finished
      WAS_BUSY = false;
      const was = BUSY_NAME; BUSY_NAME = '';
      loadGrid();
      if (CUR && !$('#detail').hidden) openDetail(CUR);
      // Say what actually finished. An update is not a job run, and reporting
      // it as one made the software-update flow look like the pipeline had
      // applied to a role.
      if (/^update\b/i.test(was)) toast('software updated — restart the dashboard to load the new code');
      else toast(was === 'queue run' ? 'run finished — grid refreshed' : 'finished — grid refreshed');
    }
    PENDING.clear(); $('#peras').classList.add('hide'); renderRows();
  }
  if (!$('#peras').classList.contains('hide')) {         // background-run monitor
    const sm = a.summary || {};
    let h = `<div class="act-h">${a.running ? NUT : '✓'} ${esc(aname || 'working…')} <span class="muted">${a.running ? 'running…' : 'finished'}</span></div>`;
    if (sm.headline) h += `<div class="act-sum">${esc(sm.headline)}</div>`;
    if ((sm.notable || []).length) h += '<ul class="act-list">' + sm.notable.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>';
    const ptasks = d.running_tasks || (d.running || []).map(x => ({ label: x, log: '' }));
    h += ptasks.length ? `<div class="act-h" style="margin-top:6px">▶ ${ptasks.map(t => t.log ? `<a class="runlink" data-task="${esc(t.log)}" data-title="${esc(t.label)}">${esc(t.label)}</a>` : esc(t.label)).join(' · ')}</div>` : '';
    (d.tail || []).slice(-6).forEach(x => h += `<div class="mini muted">${esc(x.t)}</div>`);
    $('#peras-body').innerHTML = h;
  }
  const sm = a.summary || {};
  LAST_ACT_NAME = a.name || '';
  const sig = a.name ? [a.name, a.running, (a.log || []).length, (a.overview || []).join('|')].join('|') : '';
  if ((LIVE_RUNNING || ACT) && sig !== ACT_SIG &&
      (!ACT_IGNORE || a.running || a.name !== ACT_IGNORE)) {
    ACT_IGNORE = '';
    ACT_SIG = sig;
    ACT = a.name && (a.running || (a.log || []).length) ? a : null;
    renderChat();
  }
  $('#act-sum').textContent = a.running ? ('● ' + aname)
    : (d.active ? '● runner active'
       : (delegated.length ? `● ${delegated.length} subagent${delegated.length === 1 ? '' : 's'}` : 'idle'));
  if (document.body.dataset.act === 'open') {
    let h = '';
    if (a.name && a.running) {
      h += `<div class="act-h">${NUT} ${esc(aname)} <span class="muted">running…</span></div>`;
      if (sm.headline) h += `<div class="act-sum">${esc(sm.headline)}</div>`;
      if ((sm.notable || []).length) h += '<ul class="act-list">' + sm.notable.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>';
      const total = (a.log || []).length;
      if (total > (sm.notable || []).length) h += `<details class="act-raw"><summary>full output · ${total} lines</summary><pre>${esc((a.log || []).join('\n'))}</pre></details>`;
      h += '<div class="act-sep"></div>';
    } else if (a.name) {
      // Not running: this is history, not current activity.
      h += `<div class="act-h">✓ last action: ${esc(aname)} <span class="muted">finished</span></div>`;
      if (sm.headline) h += `<div class="act-sum">${esc(sm.headline)}</div>`;
      h += '<div class="act-sep"></div>';
    }
    h += d.active ? '● runner active'
      : (delegated.length ? `▶ ${delegated.length} subagent${delegated.length === 1 ? '' : 's'} running`
                          : '○ runner idle');
    const tasks = d.running_tasks || (d.running || []).map(x => ({ label: x, log: '' }));
    tasks.forEach(t => {
      h += t.log
        ? `\n▶ <a class="runlink" data-task="${esc(t.log)}" data-title="${esc(t.label)}" title="Show the live log">${esc(t.label)}</a>`
        : `\n▶ ${esc(t.label)}`;
    });
    (d.tail || []).forEach(x => h += x.k === 'phase' ? `\n[p] ${esc(x.t)}` : `\n    ${esc(x.t)}`);
    $('#liveterm').innerHTML = h;
  }
  setTimeout(liveTick, 2500);
  permTick();
}
/* the embedded agent asks before doing something risky (agent_access.py -> here) */
async function permTick(force = false) {
  const d = await api('/api/agent/pending');
  const q = (d && d.pending) || [];
  if (!q.length) {
    if (CUR_PERM) { CUR_PERM = null; $('#perm').classList.add('hide'); }
    return;
  }
  if (CUR_PERM && !force && q[0].id === CUR_PERM.id) return;
  CUR_PERM = q[0];
  const dm = $('#draftm'); if (dm) dm.classList.add('hide');
  const email = CUR_PERM.email && typeof CUR_PERM.email === 'object' ? CUR_PERM.email : null;
  const always = CUR_PERM.rememberable !== false;
  $('#perm-title').textContent = email ? 'Review email before sending' : 'Agent requests permission';
  $('#perm-sub').textContent = email
    ? 'This is the exact email that will be sent. Edit anything below before approving.'
    : 'The agent wants to do something that needs your approval.';
  $('#perm-text').textContent = `${CUR_PERM.category}: ${CUR_PERM.detail}`;
  $('#perm-text').style.display = email ? 'none' : '';
  $('#perm-email').classList.toggle('hide', !email);
  $('#perm-save').classList.toggle('hide', !email);
  if (email) {
    $('#pe-to').value = email.to || '';
    $('#pe-cc').value = email.cc || '';
    $('#pe-subject').value = email.subject || '';
    $('#pe-body').value = email.body || '';
    const atts = email.attachments || [];
    $('#pe-attach').textContent = atts.length
      ? 'Attachments (edit in the draft): ' + atts.map(a => String(a).split('/').pop()).join(', ')
      : 'No attachments';
  }
  $('#perm-always').textContent = always ? `Always allow ${CUR_PERM.category}` : 'Allow once';
  $('#perm-always').style.display = always ? '' : 'none';
  $('#perm-once').textContent = email ? 'Approve & send' : (always ? 'Allow once' : 'Approve');
  $('#perm').classList.remove('hide');
}
async function permAnswer(decision, remember, save) {
  if (!CUR_PERM || PERM_BUSY) return;
  PERM_BUSY = true;
  const buttons = [...document.querySelectorAll('#perm .row button')];
  buttons.forEach(b => { b.disabled = true; });
  try {
    const shown = CUR_PERM;
    const email = shown.email && typeof shown.email === 'object' ? shown.email : null;
    let edits;
    if (email) {
      const to = $('#pe-to').value.trim();
      const cc = $('#pe-cc').value.trim();
      const subject = $('#pe-subject').value.trim();
      const body = $('#pe-body').value;
      if (decision === 'allow') {
        if (!to) return toast('add a recipient before sending', true);
        if (!subject) return toast('add a subject before sending', true);
        if (!body.trim()) return toast('the email body is empty', true);
      }
      edits = { to: $('#pe-to').value, cc: $('#pe-cc').value, subject: $('#pe-subject').value, body };
    }
    // The tab may have been open across a restart or another send. Never post a
    // stale pending id: fetch the live request and use its id when it is the
    // same request (same category and recipient/subject).
    let id = shown.id;
    const live = await api('/api/agent/pending');
    const q = (live && live.pending) || [];
    if (!q.some(x => x.id === id)) {
      const same = q.find(x => x.category === shown.category &&
        (email
          ? (((x.email || {}).to || '') === (email.to || '') &&
             ((x.email || {}).subject || '') === (email.subject || ''))
          : String(x.detail || '') === String(shown.detail || '')));
      if (same) {
        id = same.id;
      } else {
        toast('this request expired — showing the current one', true);
        CUR_PERM = null; $('#perm').classList.add('hide');
        await permTick(true);
        return;
      }
    }
    CUR_PERM = null; $('#perm').classList.add('hide');
    const r = await api('/api/agent/decide', { id, decision, remember: !!remember, edits, save: !!save });
    if (r && r.error) {
      toast(r.error, true);
      if (/session/i.test(r.error)) { location.reload(); return; }
      await permTick(true);
      return;
    }
    await permTick();
  } finally {
    PERM_BUSY = false;
    buttons.forEach(b => { b.disabled = false; });
  }
}

/* the human review queue for mail that did not confidently match a role */
let REVIEW_ITEMS = [], REVIEW_USE_MODEL = true;
async function loadGmailReview() {
  try {
    const d = await api('/api/gmail/review');
    const items = (d && d.items) || [];
    REVIEW_ITEMS = items;
    const n = (d && d.count) || 0;
    REVIEW_USE_MODEL = !(d && d.use_model === false);
    const c = $('#review-count'); if (c) c.textContent = String(n);
    const b = $('#a-gmail-review'); if (b) b.classList.toggle('hide', !(d && d.enabled));
    const mc = $('#reviewm-count'); if (mc) mc.textContent = n ? `· ${n} item${n === 1 ? '' : 's'}` : '';
  } catch (e) { /* keep the last count */ }
}
function suggText(s) {
  if (!s) return '';
  if (s.raw) return String(s.raw);
  return [
    s.action === true ? 'ACTION needed' : s.action === false ? 'no action' : '',
    s.category ? `category: ${s.category}` : '',
    (s.company || s.role) ? `match: ${s.company || '?'} — ${s.role || '?'}` : '',
    s.reason ? `reason: ${s.reason}` : '',
    s.evidence ? `evidence: "${s.evidence}"` : ''
  ].filter(Boolean).join(' · ');
}
function renderGmailReview() {
  const el = $('#reviewm-list'); if (!el) return;
  const f = ($('#review-filter') && $('#review-filter').value) || '';
  const items = f ? REVIEW_ITEMS.filter(x => String(x.category || '') === f) : REVIEW_ITEMS;
  el.innerHTML = items.length ? items.map(x => {
    const mail = 'https://mail.google.com/mail/u/0/#all/' + encodeURIComponent(x.id || '');
    const links = (x.links || []).slice(0, 2).map(l =>
      `<a href="${esc(l)}" target="_blank" rel="noopener">verification link ↗</a>`).join(' ');
    const codes = (x.codes || []).slice(0, 2).map(c => `<code>${esc(c)}</code>`).join(' ');
    const sg = x.suggestion || null;
    const sgText = sg ? `${x.model || ''}: ${suggText(sg)}` : '';
    return `<div style="padding:10px 0;border-bottom:1px solid rgba(255,255,255,.08)">
      <div><b>${esc(x.category || '?')}</b> <span class="muted mini">${esc((x.date || '').slice(0, 16))}</span>
        ${x.company ? ` · <b>${esc(x.company)}</b>` : ''}${x.role ? ` — ${esc(x.role)}` : ''}</div>
      <div class="muted mini">${esc(x.sender || '')} · ${esc(x.subject || '')}</div>
      <div>${esc(x.reason || '')}</div>
      <div class="row" style="margin-top:6px"><a href="${mail}" target="_blank" rel="noopener">Open email ↗</a> ${links} ${codes}
        <span style="flex:1"></span>
        ${REVIEW_USE_MODEL ? `<button class="small" onclick="reviewAsk('${esc(x.id || '')}', this)">Ask model</button>` : ''}
        <button class="small" onclick="reviewAck('${esc(x.id || '')}')">Done</button></div>
      <div id="sugg-${esc(x.id || '')}" class="muted mini${sg ? '' : ' hide'}" style="margin-top:6px;white-space:pre-wrap">${esc(sgText)}</div>
    </div>`;
  }).join('') : '<span class="muted">Nothing needs review in this category.</span>';
}
window.reviewOpen = async () => {
  await loadGmailReview();
  renderGmailReview();
  $('#reviewm').classList.remove('hide');
};
window.reviewClose = () => $('#reviewm').classList.add('hide');
window.reviewAck = async (id) => {
  const d = await api('/api/gmail/review/ack', { id });
  if (d && d.error) return toast(d.error, true);
  await loadGmailReview();
  renderGmailReview();
};
window.reviewAsk = async (id, btn) => {
  if (btn) { btn.disabled = true; btn.textContent = 'Asking…'; }
  try {
    const d = await api('/api/gmail/review/ask', { id });
    if (d && d.error) return toast(d.error, true);
    const s = (d && d.suggestion) || {};
    const el = document.getElementById('sugg-' + id);
    if (el) { el.textContent = `${d.model || ''}: ${suggText(s)}`; el.classList.remove('hide'); }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Ask model'; }
  }
};

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
  if (key === 'detail' && props.open === false && ROLE_TIMER) { clearInterval(ROLE_TIMER); ROLE_TIMER = null; }
  Object.assign(PANELS[key], props);
  if (key === 'detail') renderRows();             // keep the row highlight in sync with the drawer
  localStorage.setItem(key + '.pos', PANELS[key].pos);
  localStorage.setItem(key + '.open', PANELS[key].open ? '1' : '0');
  layoutPanels();
}
function openDock(v) { setPanel('agent', { open: v }); if (v) api('/api/agent').then(d => $('#agent-name').textContent = d.agent || '?'); }

/* ---------- per-task live log ---------- */
let TASKLOG = { name: '', title: '', timer: null };
function taskLogName(company, role) { return `${company}-${role}`.replace(/[ \/|]/g, '_'); }
async function taskLogPoll() {
  if (!TASKLOG.name) return;
  const d = await api('/api/log?task=' + encodeURIComponent(TASKLOG.name));
  const raw = (d && d.raw) || [];
  const lines = (d && d.curated) || [];
  const age = d && d.age, size = d && d.size;
  let meta = (d && d.error) ? 'log not found'
    : `${size != null ? size : 0} bytes · ${age == null ? 'no output yet' : 'last output ' + age + 's ago'}` +
      (age != null && age > 90 ? ' · quiet for ' + Math.floor(age / 60) + 'm — the model may be stalled (20m timeout)' : '');
  if (!LIVE_TASKS.length) meta += ' · no task running now';
  else if (!LIVE_TASKS.some(t => t.log === TASKLOG.name)) meta += ' · task finished — the runner moved on';
  const mEl = $('#tasklog-meta'); if (mEl) mEl.textContent = meta;
  const txt = raw.length ? raw.join('\n')
    : (lines.map(x => (x.k === 'phase' ? '[phase] ' : '') + (x.t || '')).join('\n')
       || `No log output yet.\n\n${meta}\n\nThe runner will time out after 20 minutes and move on.`);
  const el = $('#tasklog-body');
  const stick = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  el.textContent = txt;
  if (stick) el.scrollTop = el.scrollHeight;
  TASKLOG.timer = setTimeout(taskLogPoll, 1500);
}
function openTaskLog(name, title) {
  if (!name) return;
  clearTimeout(TASKLOG.timer);
  TASKLOG = { name, title: title || name, timer: null };
  $('#tasklog-title').textContent = TASKLOG.title;
  $('#tasklog-body').textContent = 'loading…';
  $('#tasklog').classList.remove('hide');
  document.body.dataset.tasklog = 'open';
  if (document.body.dataset.act !== 'open') {
    document.body.dataset.act = 'open';
    localStorage.setItem('dock.actOpen', '1');
  }
  openDock(true);
  taskLogPoll();
}
function closeTaskLog() {
  clearTimeout(TASKLOG.timer);
  TASKLOG = { name: '', title: '', timer: null };
  document.body.dataset.tasklog = 'closed';
  $('#tasklog').classList.add('hide');
  if (document.body.dataset.act === 'open') liveTick();
}
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
function cmdLine(cmd) {
  let first = String(cmd || '').split('\n')[0].replace(/\s+/g, ' ').trim();
  if (/<<-?\s*['"]?(PY|SH|BASH|EOF)\b/i.test(first)) first = first.split(/<<-?\s*/)[0].trim().replace(/[\s-]+$/, '') + ' (inline script)';
  return first.length > 110 ? first.slice(0, 110) + '…' : first;
}
function toolBlock(s) {
  const tag = (s.tool && s.tool !== 'bash') ? esc(s.tool) + ' · ' : '$ ';
  const full = String(s.cmd || '');
  const multi = full.includes('\n') ? ' <span class="muted mini">+ more</span>' : '';
  return `<details class="c-tool" data-k="t:${esc(full).slice(0, 90)}"><summary title="${esc(full.slice(0, 1200))}"><code>${tag}${esc(cmdLine(full))}</code>${multi}</summary>${s.body ? `<pre>${esc(s.body)}</pre>` : ''}</details>`;
}
function collapseCode(html) {
  return html.replace(/<pre>([\s\S]*?)<\/pre>/g, (m, c) => {
    const n = (c.match(/\n/g) || []).length + 1;
    return `<details class="c-code" data-k="c:${esc(c).slice(0, 80)}"><summary>code <span class="muted mini">· ${n} line${n === 1 ? '' : 's'}</span></summary><pre>${c}</pre></details>`;
  });
}
/* A wall of script/output that slipped through as prose: keep one line, hide the rest. */
function looksLikeDump(s) {
  const t = String(s || ''); if (t.length < 700) return false;
  const lines = t.split('\n').filter(l => l.trim()); if (lines.length < 6) return false;
  const codey = lines.filter(l => /^[\s>{}\[\]()#]|^\s*(def |class |import |from |curl |python|npm |git |SELECT |<\/?[a-z]+)/i.test(l)).length;
  const prose = lines.filter(l => /[.!?]\s*$/.test(l.trim())).length;
  return codey / lines.length > 0.6 && prose < lines.length * 0.2;
}
function setSpin(v) {
  const s = $('#chat-spin'); if (s) s.classList.toggle('hide', !v);   // the single "agent working" indicator
  const b = $('#chat-stop'); if (b) b.classList.toggle('hide', !v);   // Stop is only meaningful mid-turn
}
function openKeys(el) { return new Set([...el.querySelectorAll('details[open]')].map(d => d.getAttribute('data-k')).filter(Boolean)); }
let CHAT_STICK = true;                                        // follow new output only if the reader is at the bottom
function chatAtBottom(el) { return el.scrollHeight - el.scrollTop - el.clientHeight < 60; }
let ACT = null, ACT_SIG = '', ACT_IGNORE = '', LAST_ACT_NAME = '';   // last dashboard action, shown in the chat
function actionCard(a) {
  const sm = a.summary || {}, ov = a.overview || [];
  let h = `<div class="c-user">${a.running ? NUT : ''}${esc(a.name)} <span class="muted">${a.running ? 'running…' : 'done'}</span></div>`;
  if (ov.length) {
    h += '<div class="act-h" style="margin-top:6px">Where we are</div>';
    h += '<ul class="act-list">' + ov.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>';
  } else if (sm.headline) {
    h += `<div class="c-status">${esc(sm.headline)}</div>`;
  }
  const notable = (sm.notable || []).filter(x => x !== sm.headline &&
    !(ov.length && /^==\s*(summary|proposed register changes)/i.test(x)));
  if (notable.length) h += '<ul class="act-list">' + notable.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>';
  const log = a.log || [];
  if (log.length) h += `<details class="act-raw" data-k="a:${esc(a.name)}"><summary>full output · ${log.length} lines</summary><pre>${esc(log.join('\n'))}</pre></details>`;
  return `<div class="c-act">${h}</div>`;
}
function renderChat() {
  const el = $('#chat'), segs = (CHAT && CHAT.segments) || [];
  if (!segs.length && !CHAT.running && !ACT) { el.innerHTML = '<span class="muted">ask the agent anything…</span>'; return; }
  const keys = openKeys(el);                                  // keep expanded steps open across re-renders
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
    else if (looksLikeDump(s.body)) h += `<details class="c-code" data-k="d:${esc(s.body).slice(0, 80)}"><summary>output <span class="muted mini">· ${s.body.split('\n').length} lines</span></summary><pre>${esc(s.body)}</pre></details>`;
    else h += `<div class="md">${collapseCode(md(s.body))}</div>`;
    i++;
  }
  if (ACT) h += actionCard(ACT);
  if (CHAT.running) h += `<div class="working"><span class="muted">▮ working…</span></div>`;
  el.innerHTML = h;
  el.querySelectorAll('details[data-k]').forEach(d => { if (keys.has(d.getAttribute('data-k'))) d.open = true; });
  if (CHAT_STICK) el.scrollTop = el.scrollHeight;             // never yank the reader back down
}

/* ---------- per-role chat (drawer → Discuss) ---------- */
function roleSegsHTML(segs, running) {
  let h = '', i = 0;
  while (i < segs.length) {
    const s = segs[i];
    if (s.t === 'tool') {
      const grp = [];
      while (i < segs.length && segs[i].t === 'tool') { grp.push(segs[i]); i++; }
      h += grp.length === 1 ? toolBlock(grp[0])
        : `<details class="c-tools"><summary>🔧 ${grp.length} steps</summary>${grp.map(toolBlock).join('')}</details>`;
      continue;
    }
    if (s.t === 'user') h += `<div class="c-user"><div class="md">${md(s.body)}</div></div>`;
    else if (s.t === 'status') h += `<div class="c-status">${esc(s.body)}</div>`;
    else if (looksLikeDump(s.body)) h += `<details class="c-code"><summary>output <span class="muted mini">· ${s.body.split('\n').length} lines</span></summary><pre>${esc(s.body)}</pre></details>`;
    else h += `<div class="md">${collapseCode(md(s.body))}</div>`;
    i++;
  }
  if (running) h += `<div class="working"><span class="muted">▮ working…</span></div>`;
  return h;
}
function rolePoll() {
  if (!CUR || DTAB !== 1) { if (ROLE_TIMER) { clearInterval(ROLE_TIMER); ROLE_TIMER = null; } return; }
  App.roleChatLoad();
}
function discuss(r) {
  return `<div class="rolechat">
    <div class="row"><b>Discuss this role with the agent</b><span class="muted mini">it knows this row, its notes, the ad and your documents</span>
      <span style="flex:1"></span>
      <button class="small" id="rc-stop" onclick="App.roleChatStop()">⏹ Stop</button>
      <button class="small" onclick="App.roleChatNew()">🗑 Clear</button></div>
    <div id="rc-log" class="term role-log"><span class="muted">Ask anything about this role — e.g. “what should I say back?”, “what will they probe?”, “draft a follow-up”.</span></div>
    <div class="row chat-in"><input id="rc-in" placeholder="ask about this role…" onkeydown="if(event.key==='Enter')App.roleChatSend()" style="flex:1"><button onclick="App.roleChatSend()">Send</button></div>
  </div>`;
}

/* ---------- settings sections ---------- */
async function setData(b) {
  const d = await api('/api/backup?info=1');
  if (CF_SEC !== 'data') return;
  if (d.error) { b.innerHTML = `<span class="muted">${esc(d.error)}</span>`; return; }
  const p = d.parts || {};
  const docs = (p.documents || {}).bytes || 0;
  const rows = [
    ['config', p.config], ['answers', p.answers], ['state', p.state],
    ['kb/sources', p.sources], ['documents', p.documents],
  ].filter(([, v]) => v && v.files).map(([k, v]) =>
    `<span class="pill">${esc(k)} · ${v.files} file(s) · ${fmtSize(v.bytes)}</span>`).join(' ');
  const total = Object.values(p).reduce((n, v) => n + ((v || {}).bytes || 0), 0);
  const backups = (d.backups || []).length
    ? d.backups.map(x => `<li><span class="mini">${esc(x.at)}</span> <span class="muted mini">${fmtSize(x.bytes)}</span> ${esc(x.name)}</li>`).join('')
    : '<li class="muted mini">none yet</li>';
  b.innerHTML = `
    <p class="muted">A backup is one <code>.zip</code> with everything the pipeline cannot regenerate:
      <code>config/</code> (profile, CV, archetypes, mail and calendar settings), <code>answers/</code>,
      <code>kb/sources/</code>, <code>state/</code> (register, queues, provenance, drafts, saved ads, keyword files,
      grounding and content packs, gate receipts) and, unless you untick it, <code>documents/</code> (rendered CVs,
      letters and the exact files you sent).</p>
    <div class="muted mini">${rows} <span class="pill">total ${fmtSize(total)}</span></div>
    <p class="muted mini" style="margin-top:6px">⚠ A backup contains <b>your personal data</b> — CV, applications, and any Google client
      secret stored in <code>config/google.json</code>. Keep it somewhere private and never commit it. The OAuth token lives outside
      the repo, so it is not in the zip. Agent transcripts (<code>state/logs/</code>), the mail cache and the GraphRAG index are
      deliberately left out.</p>
    ${d.busy ? '<p class="muted mini"><b>A run is in progress</b> — downloading is paused until it finishes.</p>' : ''}

    <h4 style="margin:14px 0 4px">Back up</h4>
    <div class="row" style="margin:7px 0">
      <label class="mini"><input type="checkbox" id="bk-docs" checked> include generated documents (${fmtSize(docs)})</label>
      <button onclick="App.backupDownload()">Download backup (.zip)</button>
    </div>
    <div class="muted mini">Saved copies live in <code>${esc(d.backup_dir)}</code>. Backups taken before a restore or a clear are
      written there too.</div>
    <div class="muted mini" style="margin-top:6px">Last backups: <ul style="margin:4px 0 0 16px;padding:0">${backups}</ul></div>

    <h4 style="margin:16px 0 4px">Restore a backup</h4>
    <p class="muted mini">Replaces <code>config/</code>, <code>state/</code>, <code>documents/</code> and <code>kb/sources/</code> with the
      contents of the zip. A safety backup of the current system is written first, so a wrong choice is recoverable.</p>
    <div class="row" style="margin:7px 0">
      <input type="file" id="bk-file" accept=".zip">
      <input id="bk-confirm" placeholder="type RESTORE" style="max-width:190px">
      <button class="risky" onclick="App.backupRestore()">Restore backup</button>
    </div>

    <h4 style="margin:16px 0 4px;color:#c98">Danger zone</h4>
    <p class="muted mini"><b>Clear</b> deletes the pipeline's data and starts you over with the same identity: the register, queues,
      drafts, saved job ads, keyword files, grounding packs and every generated document. <code>config/</code> and
      <code>kb/sources/</code> are never touched. A safety backup is taken first, but treat this as irreversible.</p>
    <div class="row" style="margin:7px 0">
      <input id="cl-confirm" placeholder="type CLEAR" style="max-width:190px">
      <button class="risky" onclick="App.clearData('data')">Clear pipeline data</button>
      <button class="risky" onclick="App.clearData('full')" title="also deletes the GraphRAG index — a rebuild takes 20–30 min">Full reset (incl. index)</button>
    </div>`;
}
const fmtSize = (n) => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : n > 1024 ? (n / 1024).toFixed(0) + ' KB' : n + ' B';
function secretRowHTML(sec, r) {
  return `<div class="row" data-sec="${sec}" data-name="${esc(r.name)}" data-user="${esc(r.username || '')}" style="margin:3px 0;align-items:center">
    <code style="min-width:210px">${esc(r.name)}</code>
    ${r.username ? `<span class="muted mini" style="max-width:190px;overflow:hidden;text-overflow:ellipsis">${esc(r.username)}</span>` : ''}
    <span class="muted mini" data-mask>${r.set ? esc(r.value) : 'not set'}</span>
    <input type="password" data-new autocomplete="new-password" placeholder="new value" style="flex:1;display:none">
    <button class="small" onclick="App.secretEdit(this)">Replace</button>
    <button class="small" onclick="App.secretDel(this)" title="delete">✕</button>
  </div>`;
}

async function setSecrets(b) {
  const d = await api('/api/secrets');
  if (CF_SEC !== 'secrets') return;
  if (!d || d.error) {
    b.innerHTML = `<p class="bad">${esc((d && d.error) || 'could not read the secrets store')}</p>`;
    return;
  }
  const known = d.known || {}, secs = d.sections || {};
  const rows = (s) => (secs[s] || []).map(r => secretRowHTML(s, r)).join('') ||
    '<span class="muted mini">nothing stored</span>';
  const problem = (d.problems || []).map(x => `<div class="bad mini">${esc(x)}</div>`).join('');
  const needed = ((d.migration || {}).needed || []);
  const opt = (k) => `<option>${esc(k)}</option>`;
  const extra = Object.keys(secs).filter(s => !['agent', 'graphrag', 'google', 'accounts'].includes(s));
  const block = (title, hint, sec, add) => `<div style="margin-top:16px">
      <h4 style="margin:0 0 2px">${title}</h4>
      <div class="muted mini" style="margin-bottom:6px">${hint}</div>
      <div>${rows(sec)}</div>${add}</div>`;
  b.innerHTML = `<p class="muted">Every secret the app uses lives in one encrypted store outside the repo:
      <code>${esc(d.path)}</code> · <b>${esc(d.encryption || 'not created yet')}</b>${d.key_source ? ` · key: ${esc(d.key_source)}` : ''}.
      Only masked forms are returned here - replacing a value writes it straight to the store.
      The key lives in the OS keyring when available, otherwise in a 0600 key file beside the store.
      Files that Google's libraries and GraphRAG read (<code>credentials.json</code>, <code>token.json</code>,
      <code>kb/graphrag/.env</code>) are regenerated from the store at 0600.</p>
    ${d.encryption === 'plaintext' ? `<div class="row" style="margin:6px 0"><span class="bad mini">This store is still plaintext.</span>
      <button onclick="App.secretEncrypt()">Encrypt now</button></div>` : ''}
    ${problem}
    ${needed.length ? `<div class="row" style="margin:6px 0"><span class="muted mini">Found ${needed.length} existing
        secret source(s) outside the store.</span>
      <button onclick="App.secretMigrate()">Import existing secrets</button></div>` : ''}
    ${block('Model &amp; agent keys', 'Used by the dashboard, the queue and every agent run.',
      'agent', `<div class="row" style="margin-top:6px">
        <input id="add-agent-name" list="secret-agent-known" placeholder="KEY name" style="max-width:230px">
        <datalist id="secret-agent-known">${(known.agent || []).map(opt).join('')}</datalist>
        <input id="add-agent-value" type="password" autocomplete="new-password" placeholder="value" style="flex:1">
        <button onclick="App.secretAdd('agent')">＋ Add</button></div>`)}
    ${block('GraphRAG', 'The LLM/embeddings endpoint for the knowledge graph.',
      'graphrag', `<div class="row" style="margin-top:6px">
        <input id="add-graphrag-name" list="secret-graphrag-known" placeholder="KEY name" style="max-width:230px">
        <datalist id="secret-graphrag-known">${(known.graphrag || []).map(opt).join('')}</datalist>
        <input id="add-graphrag-value" type="password" autocomplete="new-password" placeholder="value" style="flex:1">
        <button onclick="App.secretAdd('graphrag')">＋ Add</button></div>`)}
    ${block('Google OAuth', 'The client id/secret and the serialized token. Paste a new client in Accounts; authorise there too.',
      'google', `<div class="muted mini" style="margin-top:4px">credentials: ${d.google && d.google.credentials ? 'in store' : 'not in store'}
        · token: ${d.google && d.google.token ? 'in store' : 'not in store'}
        · token-modify: ${d.google && d.google.token_modify ? 'in store' : 'not in store'}</div>`)}
    ${block('Per-site logins', 'Used when an application form asks you to sign in.',
      'accounts', `<div class="row" style="margin-top:6px">
        <input id="add-accounts-host" placeholder="site host" style="max-width:220px">
        <input id="add-accounts-user" placeholder="username / email" style="max-width:210px">
        <input id="add-accounts-pass" type="password" autocomplete="new-password" placeholder="password" style="flex:1">
        <button onclick="App.secretAdd('accounts')">＋ Add</button></div>`)}
    ${extra.length ? extra.map(s => `<div style="margin-top:16px"><h4 style="margin:0 0 4px">${esc(s)}</h4>${rows(s)}</div>`).join('') : ''}
    <div style="margin-top:16px"><h4 style="margin:0 0 2px">Other secrets</h4>
      <div class="muted mini" style="margin-bottom:6px">Free-form entries for anything else a tool needs.</div>
      <div class="row" style="margin-top:6px">
        <input id="add-custom-section" placeholder="section (custom)" style="max-width:160px">
        <input id="add-custom-name" placeholder="name" style="max-width:200px">
        <input id="add-custom-value" type="password" autocomplete="new-password" placeholder="value" style="flex:1">
        <button onclick="App.secretAdd('custom')">＋ Add</button></div></div>`;
}

async function setAccounts(b) {
  const [d, g] = await Promise.all([api('/api/accounts'), api('/api/google')]);
  if (CF_SEC !== 'accounts') return;
  const sc = g.scopes || [];
  const dot = (ok) => `<span class="pill" style="background:${ok ? '#1f6f43' : '#7a2e2e'}">${ok ? '✓' : '✗'}</span>`;
  const scopeName = (s) => s.split('/').pop();
  b.innerHTML = `<p class="muted">Connect your accounts. Authorisation opens in your browser - finish it there, then re-check.
      Per-site logins: <b>${d.sites}</b> stored.</p>
    <h4 style="margin:10px 0 4px">Google (Gmail + Calendar)</h4>
    <p class="muted mini">Create a <b>Desktop</b> OAuth client in Google Cloud, then paste its client id and secret here; changes save automatically.
      The pipeline writes <code>credentials.json</code> for you (or drop a downloaded one at the path below).
      Gmail can read, send and attach files; Calendar can read and book events. Sending mail and writing to the calendar
      still ask for your approval every time. Timezone and meeting defaults live in <code>config/calendar.json</code>, mail
      signature and attachments in <code>config/email.json</code>.</p>
    <div class="row" style="margin:6px 0"><span class="muted" style="min-width:118px">Client ID</span>
      <input id="g-id" placeholder="${esc(g.client_id || '…apps.googleusercontent.com')}" style="flex:1" onchange="App.googleSave()"></div>
    <div class="row" style="margin:6px 0"><span class="muted" style="min-width:118px">Client secret</span>
      <input id="g-secret" type="password" placeholder="${g.has_client_secret ? '•••• stored — leave blank to keep' : ''}" style="flex:1" onchange="App.googleSave()"></div>
    <div class="row" style="margin:6px 0"><span class="muted" style="min-width:118px">Config dir</span>
      <input id="g-dir" value="${esc(g.config_dir)}" style="flex:1" onchange="App.googleSave()">
      <span class="muted mini">credentials ${dot(g.credentials_exists)} · token ${dot(g.token_exists)}</span></div>
    <div class="row" style="margin:6px 0"><span class="muted" style="min-width:118px">Files</span>
      <input id="g-cred" value="${esc(g.credentials)}" style="flex:1" title="credentials.json path" onchange="App.googleSave()">
      <input id="g-token" value="${esc(g.token)}" style="flex:1" title="token.json path" onchange="App.googleSave()"></div>
    <div class="row" style="margin:8px 0">
      <button onclick="App.auth('gmail')">Authorise Gmail</button>
      <button onclick="App.auth('calendar')">Authorise Calendar</button>
      <button onclick="viewDoc('docs/ACCOUNT-SETUP.md','Account setup guide')">Setup guide</button>
      <button onclick="App.settings('accounts')">Re-check</button></div>
    <div class="muted mini">scopes: ${sc.length ? sc.map(scopeName).map(esc).join(' · ') : 'none yet'}${g.account ? ` · ${esc(g.account)}` : ''}</div>
    <pre class="doc">${esc(d.text || '(no output)')}</pre>`;
}
async function setKB(b) {
  const d = await api('/api/kb');
  if (CF_SEC !== 'kb') return;
  let list = '';
  for (const [g, files] of Object.entries(d.sources || {})) {
    if (!files.length) continue;
    list += `<div class="kb-group"><b>${esc(g)}</b> <span class="muted mini">${files.length} file(s)</span><ul>` +
      files.map(f => {
        const p = `kb/sources/${g === '(root)' ? '' : g + '/'}${f.name}`;
        return `<li><span class="mini">${esc(f.name)}</span> <span class="muted mini">${fmtSize(f.size)}</span>
        <button class="small" title="delete" onclick='App.kbDel(${JSON.stringify(p)})'>✕</button></li>`;
      }).join('') +
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
/* ---------- GraphRAG: a hierarchical, navigable knowledge graph ---------- */
const KGNS = 'http://www.w3.org/2000/svg';
let KG = null;
const KG_COLORS = {
  TECHNOLOGY: '#3b82f6', SKILL: '#22c55e', METRIC: '#f59e0b', PROJECT: '#a855f7',
  PRODUCT: '#06b6d4', ORGANIZATION: '#ef4444', ROLE: '#eab308', PLATFORM: '#8b5cf6',
  CERTIFICATION: '#14b8a6', EDUCATION: '#64748b', PERSON: '#f97316'
};
const KG_LEVEL_COLORS = ['#f59e0b', '#3b82f6', '#22c55e', '#a855f7', '#06b6d4', '#ef4444', '#ec4899', '#14b8a6'];

function kgColor(type) {
  if (KG_COLORS[type]) return KG_COLORS[type];
  let h = 0;
  for (const c of String(type || '?')) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 55% 58%)`;
}
function kgNodeColor(n) {
  if (n.color) return n.color;
  if (n.kind === 'community') return KG_LEVEL_COLORS[(n.level || 0) % KG_LEVEL_COLORS.length];
  return KG_COLORS[n.type] || kgColor(n.type);
}
function kgTrunc(s, n) {
  s = String(s == null ? '' : s);
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}
function kgShort(s, n) {
  const words = String(s == null ? '' : s).split(/\s+/).filter(Boolean);
  let out = '';
  for (const w of words) {
    if ((out + ' ' + w).trim().length > (n || 24)) break;
    out = (out + ' ' + w).trim();
  }
  return out + (out.split(/\s+/).length < words.length ? '…' : '');
}
function kgStop() { if (window.__kg3d) window.__kg3d.pause(); }

function kgCrumbs(crumbs, extra) {
  const el = $('#kg-crumbs'); if (!el) return;
  const typeView = KG && (KG.view === 'types' || KG.view === 'type');
  let h = `<button class="kg-crumb${(!crumbs || !crumbs.length) && !extra ? ' on' : ''}"
    onclick="${typeView ? 'App.graphTypes()' : 'App.graphTop()'}">${typeView ? 'All topics' : 'All communities'}</button>`;
  const all = crumbs || [];
  if (all.length > 4) h += '<span class="kg-sep">›</span><span class="muted mini">…</span>';
  (all.length > 4 ? all.slice(-3) : all).forEach(c => {
    h += `<span class="kg-sep">›</span><button class="kg-crumb" data-id="${c.community}"
      onclick="App.graphCommunity(this.dataset.id)">${esc(kgTrunc(c.title, 38))}</button>`;
  });
  if (extra) h += `<span class="kg-sep">›</span><span class="kg-crumb on">${esc(kgTrunc(extra, 38))}</span>`;
  el.innerHTML = h;
  const back = $('#kg-back');
  if (back) back.style.visibility = (all.length || extra) ? 'visible' : 'hidden';
  kgViewButtons();
}

function kgViewButtons() {
  const v = KG ? KG.view : '';
  const t = $('#kg-tab-types'), c = $('#kg-tab-comm');
  if (t) t.classList.toggle('on', v === 'types' || v === 'type');
  if (c) c.classList.toggle('on', v === 'communities' || v === 'entities' || v === 'ego');
}

function kgDefaultHint() {
  const v = KG ? KG.view : 'types';
  return v === 'types'
    ? 'Click a topic to see its entities. Drag to orbit, scroll to zoom, right-drag (or shift-drag) to pan.'
    : v === 'communities'
      ? 'Click a community for its summary and sources; double-click to drill down. Drag to orbit, scroll to zoom.'
      : 'Click an entity for its description, sources and neighbours. Double-click for its ego network.';
}

async function kgRender(d) {
  const stage = $('#kg-stage');
  const canvas = $('#kg3d');
  if (!stage || !canvas) return;
  let mod;
  try {
    mod = await import('./graph3d.js');
  } catch (e) {
    stage.innerHTML = `<div class="kg3d-fallback">The 3D renderer could not load: ${esc(String(e))}</div>`;
    return;
  }
  window.__kg3d = mod;
  const nodes = (d.nodes || []).map(n => ({ ...n }));
  const links = (d.links || []).map(l => ({ ...l }));
  const isComm = d.mode === 'communities';
  if (isComm) nodes.forEach(n => { n.type = 'LEVEL ' + (n.level || 0); });
  const isType = d.mode === 'types';
  const isSpread = isComm || isType;
  KG = {
    nodes, links, byId: new Map(nodes.map(n => [n.id, n])),
    top: new Set(isSpread ? nodes.map(n => n.id)
      : [...nodes].sort((a, b) => (b.degree || 0) - (a.degree || 0)).slice(0, 14).map(n => n.id)),
    kind: isType ? 'types' : isComm ? 'communities' : 'entities',
    view: isType ? 'types' : isComm ? 'communities' : d.mode === 'ego' ? 'ego' : d.type ? 'type' : 'entities',
    type: d.type || null, selected: null, hidden: new Set(),
    crumbs: d.breadcrumb || [], center: d.center || ''
  };
  if (d.center) KG.top.add(d.center);
  try {
    await mod.show(d, {
      onSelect: (id) => kgSelect(id),
      onOpen: (n) => {
        if (n.kind === 'entity') App.graphEgo(n.title);
        else if (n.kind === 'community') App.graphCommunity(n.community);
        else if (n.kind === 'type') App.graphTypeEntities(n.type);
      },
      onClear: () => kgClear()
    });
  } catch (e) {
    stage.innerHTML = `<div class="kg3d-fallback">WebGL could not start: ${esc(String(e))}</div>`;
    return;
  }
  const legend = $('#kg-legend');
  if (legend) {
    if (isType || isComm) legend.innerHTML = '';
    else {
      const counts = {}, colors = {};
      nodes.forEach(n => {
        const k = n.type || '?';
        counts[k] = (counts[k] || 0) + 1;
        colors[k] = n.color || (n.kind === 'community'
          ? KG_LEVEL_COLORS[(n.level || 0) % KG_LEVEL_COLORS.length]
          : KG_COLORS[n.type] || kgColor(n.type));
      });
      legend.innerHTML = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([t, c]) =>
        `<span class="kg-chip on" data-type="${esc(t)}" onclick="App.graphType(this.dataset.type)"><i style="background:${colors[t]}"></i>${esc(t)} ${c}</span>`).join('');
    }
  }
  const body = $('#kg-side-body');
  if (body) {
    body.className = 'kg-side-body muted mini';
    body.innerHTML = isType
      ? 'Each node is an ontology class; the links aggregate relationships between classes. Click a class to see the individual entities behind it.'
      : isComm
        ? 'Each node is a community in the generated hierarchy. Click one for its summary and sources; double-click to drill into its sub-communities.'
        : 'Each node is an entity from your documents. Click it for its description and source documents; double-click for its ego network.';
  }
  document.querySelectorAll('.kg-side-tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === 'details'));
  kgViewButtons();
}

function kgSelect(id) {
  if (!KG) return;
  const n = KG.byId.get(id);
  if (!n) return;
  KG.selected = id;
  if (window.__kg3d) window.__kg3d.select(id);
  const body = $('#kg-side-body'); if (!body) return;
  document.querySelectorAll('.kg-side-tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === 'details'));
  body.className = 'kg-side-body';
  const sources = n.sources || [];
  const srcHtml = sources.length
    ? `<h4 style="margin:10px 0 2px">Sources (${sources.length})</h4><div class="kg-neigh">` +
      sources.map(s => `<button data-src="${esc(s)}" onclick="App.openSource(this.dataset.src)">📄 ${esc(kgTrunc(s, 52))}</button>`).join('') + '</div>'
    : '';
  if (n.kind === 'community' || n.kind === 'type') {
    const isComm = n.kind === 'community';
    const keys = n.keywords || [];
    body.innerHTML = `<h4>${esc(n.title || n.label)}</h4>
      <div class="muted mini">${isComm ? 'Community' : 'Topic'} · ${n.size} entities${isComm && n.level != null ? ` · level ${n.level}` : ''}</div>
      <p class="kg-desc">${esc(n.description || 'No summary.')}</p>
      ${keys.length ? `<div class="kg-tags">${keys.map(k => `<span class="kg-tag">${esc(k)}</span>`).join('')}</div>` : ''}
      ${srcHtml}
      <div class="row" style="margin-top:10px;flex-wrap:wrap">
        ${isComm
          ? `<button class="small" data-id="${n.community}" onclick="App.graphCommunity(this.dataset.id)">Open community</button>`
          : `<button class="small" data-id="${esc(n.type)}" onclick="App.graphTypeEntities(this.dataset.id)">Open topic</button>`}
      </div>`;
    return;
  }
  const neigh = new Set([id]);
  for (const l of KG.links) {
    if (l.source === id) neigh.add(l.target);
    else if (l.target === id) neigh.add(l.source);
  }
  const neighbours = [...neigh].filter(x => x !== id).map(x => KG.byId.get(x)).filter(Boolean)
    .sort((a, b) => (b.degree || 0) - (a.degree || 0));
  body.innerHTML = `<h4>${esc(n.title)}</h4>
    <div class="muted mini">${esc(n.class_label || n.type)} · degree ${n.degree} · frequency ${n.frequency}</div>
    <p class="kg-desc">${esc(n.description || 'No description.')}</p>
    ${srcHtml}
    <h4 style="margin:10px 0 2px">Neighbours (${neighbours.length})</h4>
    <div class="kg-neigh">${neighbours.length ? neighbours.map(x =>
      `<button data-id="${esc(x.id)}" onclick="App.graphSelect(this.dataset.id)">${esc(kgTrunc(x.title, 42))}
        <span class="muted">${esc(x.class_label || x.type)}</span></button>`).join('') :
      '<span class="muted mini">None visible in this view.</span>'}</div>
    <div class="row" style="margin-top:10px;flex-wrap:wrap">
      <button class="small" data-id="${esc(n.title)}" onclick="App.graphEgo(this.dataset.id)">Focus ego network</button>
      ${n.community != null ? `<button class="small" data-id="${n.community}" onclick="App.graphCommunity(this.dataset.id)">Open community</button>` : ''}
    </div>`;
}

function kgClear() {
  if (!KG) return;
  KG.selected = null;
  if (window.__kg3d) window.__kg3d.clearSelection();
  const body = $('#kg-side-body');
  document.querySelectorAll('.kg-side-tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === 'details'));
  if (body) {
    body.className = 'kg-side-body muted mini';
    body.innerHTML = kgDefaultHint();
  }
}

function kgVisibility() {
  if (!KG) return;
  if (window.__kg3d) window.__kg3d.setHiddenTypes([...KG.hidden]);
  document.querySelectorAll('#kg-legend .kg-chip').forEach(el => {
    el.classList.toggle('on', !KG.hidden.has(el.dataset.type));
  });
}

async function setGraph(b) {
  const d = await api('/api/graph?kind=stats');
  if (CF_SEC !== 'graph') return;
  const built = d && d.entities;
  b.innerHTML = `<p class="muted">The knowledge graph is a full-page workspace, not a settings pane: a hierarchy of
      communities you can drill through to the entities and relationships behind every generated document.</p>
    <div class="muted mini">${built
      ? `<b>${d.entities}</b> entities · <b>${d.relationships}</b> relationships · <b>${d.communities}</b> communities`
      : 'Not built yet.'}</div>
    <div class="row" style="margin-top:10px">
      <button onclick="App.openKnowledge()">Open the knowledge graph</button>
      <button class="small" onclick="App.rebuildKB()" title="Full re-index of the knowledge graph — can take 20–30+ minutes">Rebuild graph</button>
    </div>
    <p class="muted mini" style="margin-top:10px">Search communities and entities, drill from the highest-level community down to
      individual entities, and open any entity's ego network. The graph fills the page and keeps the job grid out of the way.</p>`;
}
async function setPerms(b) {
  const d = await api('/api/permissions');
  if (CF_SEC !== 'perms') return;
  const cats = Object.keys(d.defaults || {});
  const help = { read_repo: 'read files in this repo', read_external: 'read files outside the repo',
    write_repo: 'write files in this repo', write_external: 'write files outside the repo',
    bash: 'run shell commands', web: 'fetch web pages', task: 'launch subagents' };
  b.innerHTML = `<p class="muted">What the embedded agent may do <b>without asking</b>. <b>ask</b> shows you a
      prompt (Allow once / Always allow / Deny) the moment the agent tries it — the agent waits for your answer.</p>
    <table><tbody>${cats.map(c => `<tr><td><code>${esc(c)}</code><div class="muted mini">${esc(help[c] || '')}</div></td>
      <td><select data-cat="${esc(c)}" onchange="App.savePerms()">${['allow', 'ask', 'deny'].map(v =>
        `<option value="${v}" ${(d.policy[c] === v) ? 'selected' : ''}>${v}</option>`).join('')}</select></td></tr>`).join('')}</tbody></table>
    <div class="row" style="margin-top:10px"><span class="muted mini">Changes save immediately. Applies to every agent (opencode, Claude Code, any <code>AGENT=</code>).</span></div>`;
}
async function setAI(b) {
  const [a, g, gr] = await Promise.all([api('/api/agent/config'), api('/api/graphrag/env'), api('/api/gmail/review')]);
  if (CF_SEC !== 'ai') return;
  const detected = (a.detected || []);
  const orKey = (a.env || {}).OPENROUTER_API_KEY || '';
  const knownAgents = [['', 'Auto (OpenCode, else Claude)'], ['opencode', 'OpenCode'],
    ['openrouter', 'OpenRouter'], ['local', 'Local LLM (OpenAI-compatible)'], ['claude', 'Claude Code']];
  const customAgent = a.agent && !knownAgents.some(([v]) => v === a.agent) ? a.agent : '';
  const agentOpts = knownAgents.map(([v, label]) =>
    `<option value="${v}"${a.agent === v ? ' selected' : ''}>${label}</option>`).join('') +
    `<option value="__custom__"${customAgent ? ' selected' : ''}>Custom…</option>`;
  const envRows = (a.env_keys || []).filter(k => !['OPENROUTER_API_KEY', 'LOCAL_LLM_BASE_URL', 'LOCAL_LLM_API_KEY', 'LLAMACPP_BASE_URL'].includes(k)).map(k =>
    `<div class="row" style="margin:3px 0"><code style="min-width:190px">${esc(k)}</code>
      <input data-env="${esc(k)}" placeholder="${esc(a.env[k])} (blank = keep)" style="flex:1" onchange="App.saveAI()">
      <button class="small" onclick="App.aiDel('${esc(k)}')" title="remove">✕</button></div>`).join('');
  const grRows = (g.keys || []).map(k =>
    `<div class="row" style="margin:3px 0"><code style="min-width:190px">${esc(k)}</code>
      <input data-gr="${esc(k)}" placeholder="${esc(g.vars[k])} (blank = keep)" style="flex:1" onchange="App.saveGR()"></div>`).join('');
  b.innerHTML = `<p class="muted">Which LLM/agent runs the pipeline. Changes save automatically. Keys live in the central
      secrets store (<code>${esc(a.secrets_path || '')}</code>, 0600) and are shown masked.</p>
    <div class="row" style="margin:6px 0"><b>Detected:</b>
      ${detected.length ? detected.map(x => `<span class="pill">${esc(x)}</span>`).join(' ')
        : '<span class="muted">none on PATH</span>'}
      <span class="muted">· in use: <b id="ai-inuse">${esc(a.which || '?')}</b></span>
      <span id="ai-msg" class="muted mini"></span></div>
    ${detected.length ? '' : `<div class="muted mini" style="margin-bottom:8px">Install one, then set the command below:
      <code>npm i -g opencode-ai</code> (opencode) or <code>npm i -g @anthropic-ai/claude-code</code> (Claude Code),
      or set a custom command.</div>`}
    <div class="row" style="margin-top:8px"><span class="muted">Agent</span>
      <select id="ai-agent" style="min-width:200px">${agentOpts}</select>
      <input id="ai-agent-custom" value="${esc(customAgent)}" placeholder="custom command" style="flex:1; display:${customAgent ? '' : 'none'}">
      <span class="muted">Model</span>
      <select id="ai-model-sel" style="min-width:220px"></select>
      <input id="ai-model-custom" placeholder="or type a model id" style="flex:1"></div>
    <div class="muted mini">Pick <b>OpenCode</b> or <b>OpenRouter</b> here. The model list comes from the selected provider (OpenCode's list or OpenRouter's catalogue); anything else can be typed.
      Applies to chat, role chats and queue/API runs; <code>MODEL=...</code> overrides for one run.</div>
    <div class="row" style="margin-top:8px"><b>OpenRouter</b>
      <input id="ai-or-key" type="password" autocomplete="new-password" placeholder="${orKey ? esc(orKey) + ' (blank = keep)' : 'sk-or-v1-…'}" style="flex:1" onchange="App.saveAI()">
      <button onclick="App.useOpenRouter()">Use OpenRouter</button>
      <span class="muted mini">OpenRouter serves the model; OpenCode is only the local tool runner. The key is stored with the other env values.</span></div>
    <div class="row" style="margin-top:8px"><b>Local LLM</b>
      <input id="ai-local-url" placeholder="http://127.0.0.1:8080/v1" value="${esc((a.env || {}).LOCAL_LLM_BASE_URL || 'http://127.0.0.1:8080/v1')}" style="flex:1" onchange="App.saveAI()">
      <input id="ai-local-key" type="password" autocomplete="new-password" placeholder="optional API key" style="max-width:180px" onchange="App.saveAI()">
      <button onclick="App.useLocal()">Use local LLM</button>
      <span class="muted mini">Any OpenAI-compatible endpoint; the model list comes from its /v1/models.</span></div>
    <div class="row" style="margin-top:8px"><b>Gmail review</b>
      <label class="mini"><input type="checkbox" id="gmail-review-enabled" onchange="App.saveGmailReview()" ${gr && gr.enabled !== false ? 'checked' : ''}> capture unclassified/ambiguous emails</label>
      <label class="mini"><input type="checkbox" id="gmail-review-model" onchange="App.saveGmailReview()" ${gr && gr.use_model !== false ? 'checked' : ''}> use the selected model for review suggestions</label>
      <label class="mini"><input type="checkbox" id="gmail-review-auto" onchange="App.saveGmailReview()" ${gr && gr.auto_model ? 'checked' : ''}> automatically ask it for new review items</label>
      <span class="muted mini">Changes save immediately. New items only; the existing backlog is never auto-processed. Suggestions use the agent/model above and never change status automatically.</span></div>
    <h4 style="margin:14px 0 4px">API keys / env</h4>
    <div id="ai-env">${envRows || '<span class="muted mini">none set</span>'}</div>
    <div class="row" style="margin-top:6px">
      <input id="ai-env-k" list="ai-known" placeholder="KEY name" style="max-width:220px">
      <datalist id="ai-known">${(a.known_keys || []).map(k => `<option>${esc(k)}</option>`).join('')}</datalist>
      <input id="ai-env-v" placeholder="value" style="flex:1"><button onclick="App.aiAdd()">＋ Add</button></div>
    <div class="row" style="margin-top:10px"><span class="muted mini">Agent/model are saved automatically and read by every runner via tools/agent_run.sh.</span></div>
    <h4 style="margin:18px 0 4px">GraphRAG LLM (stored in Secrets, mirrored to <code>kb/graphrag/.env</code>)</h4>
    <div id="ai-gr">${grRows || '<span class="muted mini">no .env yet</span>'}</div>
    <div class="row" style="margin-top:8px"><span class="muted mini">Changes save immediately. Used by the knowledge graph (same OPENCODE_API_KEY works for both).</span></div>`;
  const initialModel = $('#ai-model-sel');
  if (initialModel) initialModel.innerHTML = modelOptionsHTML(
    a.model ? [{ label: 'current', models: [a.model] }] : [], a.model || '', a.model ? [a.model] : []);
  App.aiFillModels(a);
  const ag = $('#ai-agent'), ci = $('#ai-agent-custom');
  if (ag) ag.onchange = async () => {
    const isCustom = ag.value === '__custom__';
    if (ci) ci.style.display = isCustom ? '' : 'none';
    const who = isCustom ? ((ci && ci.value.trim()) || '') : ag.value;
    if (isCustom && !who) return;
    let model = (a.models || {})[who] || '';
    if (!model && who === 'openrouter') model = 'deepseek/deepseek-v4.1-flash';
    if (!model && who === 'local') {
      try { const mm = await api('/api/agent/models?agent=local'); model = ((mm && mm.models) || [])[0] || ''; } catch (e) {}
    }
    const nextModels = Object.assign({}, a.models || {});
    if (model) nextModels[who] = model;
    App.aiFillModels({ which: who, agent: who, model, models: nextModels });
    const d = await App.saveAI({ agent: who, model });
    if (!d.error) App.aiFillModels({ which: who, agent: who,
      model: (d.config && d.config.model) || model, models: (d.config && d.config.models) || nextModels });
  };
  if (ci) ci.onchange = () => {
    if (ag && ag.value === '__custom__' && ci.value.trim()) App.saveAI({ agent: ci.value.trim() });
  };
  const sel = $('#ai-model-sel');
  if (sel) sel.onchange = () => {
    const custom = $('#ai-model-custom');
    if (custom) custom.value = '';
    App.saveAI();
  };
  const customModel = $('#ai-model-custom');
  if (customModel) customModel.onchange = () => {
    if (customModel.value.trim()) App.saveAI();
  };
}
function setProfile(b) {
  b.innerHTML = `<p class="muted">Your ground-truth CV, role-family templates and rules. Changes save automatically on blur; JSON is validated before saving and a <code>.bak</code> is kept.</p>
    <div class="row"><div class="tabs2" id="cf-tabs" style="margin:0;border:0">
      <a data-t="cv.json" onclick="App.cf('cv.json')">cv.json</a>
      <a data-t="archetypes.json" onclick="App.cf('archetypes.json')">archetypes.json</a>
      <a data-t="profile.md" onclick="App.cf('profile.md')">profile.md</a></div>
      <span style="flex:1"></span>
      <button onclick="App.run('build_archetypes')">Regenerate archetype CVs</button></div>
    <textarea id="cf-text" spellcheck="false" onchange="App.cfSave()"></textarea>
    <div id="cf-msg" class="muted"></div>`;
  App.cf(CF);
}

/* ---------- wiring ---------- */
$('#a-prepare').onclick = () => App.run('prepare');
$('#a-submit').onclick = () => App.run('submit_queue');
$('#a-reconcile').onclick = () => App.run('reconcile');
$('#a-knowledge').onclick = () => App.openKnowledge();
$('#a-config').onclick = () => { $('#cfg').classList.remove('hide'); App.settings(CF_SEC); };
window.cfgClose = () => $('#cfg').classList.add('hide');
window.legendClose = () => $('#legend-modal').classList.add('hide');
$('#legend').onclick = () => {
  $('#legend-views').innerHTML = BUCKETS.map(b => `<dt>${esc(b.label)}</dt><dd>${esc(b.hint)}</dd>`).join('');
  $('#legend-status').innerHTML = Object.entries(STATUS_HELP).map(([k, v]) => `<dt>${chip(k)}</dt><dd>${esc(v)}</dd>`).join('');
  $('#legend-queue').innerHTML = Object.entries(QUEUE_HELP).map(([k, v]) => `<dt><code>${esc(k)}</code></dt><dd>${esc(v)}</dd>`).join('');
  $('#legend-modal').classList.remove('hide');
};
$('#a-drawer').onclick = () => openDock(!PANELS.agent.open);
$('#a-gmail-review').onclick = () => reviewOpen();
if ($('#review-filter')) $('#review-filter').onchange = renderGmailReview;
loadGmailReview();
setInterval(loadGmailReview, 60000);
if ($('#chat-model')) $('#chat-model').onchange = async (e) => {
  const val = e.target.value, who = e.target.dataset.agent || '', cfg = e.target.dataset.configured || '';
  const models = {}; if (who && val) models[who] = val;
  const d = await api('/api/agent/config', { agent: cfg, model: val, models });
  toast(d.error ? d.error : `model: ${val || '(agent default)'} — applies to chat, role chats and queue/API runs`, !!d.error);
  if (d.error) loadChatModel(true);
};
$('#updpill').onclick = () => updateDialog();
$('#btn-stop').onclick = () => App.stop();
window.evidClose = () => $('#evid').classList.add('hide');
$('#evid-save').onclick = () => App.saveEvidence();
$('#peras-stop').onclick = () => App.stop();
$('#btn-pause').onclick = () => App.togglePause($('#btn-pause').textContent.includes('Pause'));
$('#perm-once').onclick = () => permAnswer('allow', false);
$('#perm-always').onclick = () => permAnswer('allow', true);
$('#perm-deny').onclick = () => permAnswer('deny', false);
$('#perm-save').onclick = () => permAnswer('deny', false, true);
setInterval(() => permTick(), 2500);
window.addEventListener('focus', () => permTick(true));
document.addEventListener('visibilitychange', () => { if (!document.hidden) permTick(true); });
$('#act-toggle').onclick = () => {
  const open = document.body.dataset.act !== 'open';
  document.body.dataset.act = open ? 'open' : 'closed';
  localStorage.setItem('dock.actOpen', open ? '1' : '0');
  if (!open) closeTaskLog();
  if (open) liveTick();
};
$('#tasklog-close').onclick = () => closeTaskLog();
$('#live-log').onclick = () => { const t = LIVE_TASKS[0]; if (t) openTaskLog(t.log, t.label); };
$('#peras-body').addEventListener('click', (e) => {
  const a = e.target.closest('.runlink'); if (!a) return;
  e.preventDefault(); window.perasClose(); openTaskLog(a.dataset.task, a.dataset.title);
});
$('#liveterm').addEventListener('click', (e) => {
  const a = e.target.closest('.runlink'); if (!a) return;
  e.preventDefault(); openTaskLog(a.dataset.task, a.dataset.title);
});
$('#chat').addEventListener('scroll', () => {                 // remember whether the reader is following along
  const el = $('#chat'); CHAT_STICK = chatAtBottom(el);
}, { passive: true });
$('#chat-send').onclick = () => App.chat();
$('#chat-stop').onclick = () => App.chatStop();
$('#chat-new').onclick = () => App.newChat();
$('#q').oninput = () => {
  const has = !!($('#q').value || '').trim();
  if (has && BUCKET !== 'all') { BUCKET_BEFORE_SEARCH = BUCKET; BUCKET = 'all'; renderBuckets(); }
  else if (!has && BUCKET_BEFORE_SEARCH) { BUCKET = BUCKET_BEFORE_SEARCH; BUCKET_BEFORE_SEARCH = null; renderBuckets(); }
  renderRows();
};
['#fstatus', '#fqueue', '#ftype', '#faction'].forEach(sel => {
  const el = $(sel); if (!el) return;
  el.onchange = () => { if (BUCKET !== 'focus') BUCKET = 'all'; renderBuckets(); renderRows(); };
});
['#fpay', '#ffit', '#fwork'].forEach(sel => {
  const el = $(sel); if (!el) return;
  el.onchange = () => { renderRows(); };      // quality filters apply within the current bucket
});
$('#fclear').onclick = () => App.clearFilters();
const fd = $('#fdismissed');
if (fd) { fd.checked = SHOW_DISMISSED; fd.onchange = () => App.toggleDismissedView(fd.checked); }
$('#a-prepare-shown').onclick = () => App.prepareShown();
$('#a-submit-shown').onclick = () => App.submitPrepared();
$('#a-match').onclick = () => App.matchShown($('#a-match'));
$('#grouping').onclick = () => {
  GROUPED = !GROUPED;
  localStorage.setItem('grid.grouped', GROUPED ? '1' : '0');
  syncGroupingButton();
  renderRows();
};
$('#export').onclick = () => {
  const cs = ['date', 'company', 'role', 'employment', 'work_model', 'salary_label', 'ats', 'status', 'action', 'match', 'focus', 'queue', 'applied', 'spec', 'key'];
  const body = GRID.map(r => cs.map(c => JSON.stringify(r[c] == null ? '' : r[c])).join(',')).join('\n');
  const url = URL.createObjectURL(new Blob([cs.join(',') + '\n' + body], { type: 'text/csv' }));
  const a = document.createElement('a'); a.href = url; a.download = 'jobsquirrel.csv'; a.click(); URL.revokeObjectURL(url);
};
function modelShort(m) {
  const s = String(m || '');
  return s.includes('/') ? s.split('/').slice(1).join('/') : s;
}
function modelOptionsHTML(groups, cur, flat) {
  const list = flat || (groups || []).reduce((a, g) => a.concat(g.models || []), []);
  let h = '<option value="">agent default</option>';
  if (cur && !list.includes(cur)) h += `<option value="${esc(cur)}" selected>${esc(cur)} (current)</option>`;
  for (const g of groups || []) {
    if (!g.models || !g.models.length) continue;
    h += `<optgroup label="${esc(g.label)}">` + g.models.map(m =>
      `<option value="${esc(m)}"${m === cur ? ' selected' : ''} title="${esc(m)}">${esc(modelShort(m))}</option>`).join('') + '</optgroup>';
  }
  return h;
}
let CHAT_MODEL_LOADING = false, CHAT_MODEL_PENDING = false;
async function loadChatModel(force) {
  const sel = $('#chat-model'); if (!sel) return;
  if (CHAT_MODEL_LOADING) { if (force) CHAT_MODEL_PENDING = true; return; }
  if (!force && document.activeElement === sel) return;
  CHAT_MODEL_LOADING = true;
  try {
    const c = await api('/api/agent/config');
    const who = c.which || c.agent || '';
    const m = await api('/api/agent/models?agent=' + encodeURIComponent(who));
    const cur = c.model || '';
    sel.innerHTML = modelOptionsHTML(m.groups || [], cur, m.models || []);
    sel.dataset.agent = who; sel.dataset.configured = c.agent || '';
    sel.title = 'Model for chat, role chats and queue/API runs' + (m.source ? ` (${m.source})` : '');
  } catch (e) { /* leave the picker empty */ }
  finally {
    CHAT_MODEL_LOADING = false;
    if (CHAT_MODEL_PENDING) { CHAT_MODEL_PENDING = false; loadChatModel(true); }
  }
}
window.addEventListener('focus', () => loadChatModel(true));
setInterval(() => loadChatModel(true), 60000);
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
(() => {
  const cm = document.getElementById('chatmsg');
  const hist = document.getElementById('chat-hist');
  if (cm) {
    cm.addEventListener('keydown', chatKey);
    cm.addEventListener('input', () => { if (HIST.open) histOpen(cm.value); });
    cm.addEventListener('blur', () => setTimeout(histClose, 150));
  }
  if (hist) {
    hist.addEventListener('mousedown', (e) => {
      const it = e.target.closest('.ch-item');
      if (!it) return;
      e.preventDefault();                       // keep the input focused
      const v = HIST.items[+it.dataset.i];
      if (v != null) { cm.value = v; cm.focus(); cm.setSelectionRange(v.length, v.length); }
      histClose();
    });
  }
})();
initPanels(); initGridCols(); syncGroupingButton(); loadGrid(); gridTick(); liveTick(); healthPill(); chatPoll(); updateCheck(); loadChatModel();
if (location.hash === '#knowledge') setTimeout(() => App.openKnowledge(), 400);
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !$('#knowledge').classList.contains('hide')) App.closeKnowledge();
});

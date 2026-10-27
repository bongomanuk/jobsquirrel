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
  googleSave: async () => {
    const d = await api('/api/google', { config_dir: $('#g-dir').value, credentials: $('#g-cred').value,
      token: $('#g-token').value, client_id: $('#g-id').value, client_secret: $('#g-secret').value });
    toast(d.ok || d.error, !!d.error); if (!d.error) App.settings('accounts');
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
      <input data-env="${esc(k)}" value="${esc(v)}" style="flex:1"><button class="small" onclick="this.parentElement.remove()">✕</button>`;
    box.appendChild(row); $('#ai-env-k').value = ''; $('#ai-env-v').value = '';
  },
  aiDel: (k) => { const el = document.querySelector(`#ai-env input[data-env="${k}"]`); if (el) el.closest('.row').remove(); },
  aiFillModels: async (a) => {
    const sel = $('#ai-model-sel'); if (!sel) return;
    const who = (a && (a.which || a.agent)) || '';
    let m = { models: [], source: '' };
    try { m = await api('/api/agent/models?agent=' + encodeURIComponent(who)); } catch (e) { return; }
    const cur = (a && a.model) || '';
    const list = m.models || [];
    sel.innerHTML = modelOptionsHTML(m.groups || [], cur, list);
    const custom = $('#ai-model-custom');
    if (custom) custom.value = (cur && !list.includes(cur)) ? cur : '';
    sel.title = m.source ? `models from ${m.source}` : 'type a model id instead';
  },
  saveAI: async () => {
    const env = {}; document.querySelectorAll('#ai-env input[data-env]').forEach(i => { if (i.value) env[i.dataset.env] = i.value; });
    const orKey = ($('#ai-or-key') && $('#ai-or-key').value || '').trim();
    if (orKey) env.OPENROUTER_API_KEY = orKey;
    const model = (($('#ai-model-custom') && $('#ai-model-custom').value.trim()) || ($('#ai-model-sel') && $('#ai-model-sel').value) || '');
    let agent = $('#ai-agent').value.trim();
    if (agent === '__custom__') agent = ($('#ai-agent-custom') && $('#ai-agent-custom').value.trim()) || '';
    const models = agent && model ? { [agent]: model } : {};
    const d = await api('/api/agent/config', { agent, model, models, env });
    toast(d.ok || d.error, !!d.error);
    if (!d.error) { loadChatModel(); App.settings('ai'); }
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
    ACT = null; ACT_SIG = '';
    CHAT.running = true; CHAT_STICK = true; setSpin(true); renderChat();
    const d = await api('/api/chat', { message: m });
    if (d.error) { toast(d.error, true); CHAT.running = false; setSpin(false); renderChat(); return; }  // keep your text
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
let CF = 'cv.json', CUR = null, CF_SEC = 'accounts', DRAFT = null;
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
let GRID_TIMER = null, LIVE_RUNNING = false, IDLE_TICKS = 0, WAS_BUSY = false, DTAB = 0;
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
  GRID.forEach(r => { const k = bucketOf(r); c[k] = (c[k] || 0) + 1; });
  return { ...c, focus: GRID.filter(r => r.focus || r.focus_unknown).length,
           active: c.needs + c.prepared + c.ongoing + c.pipeline, all: GRID.length };
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
  const filt = (r) => statusMatch(r) && typeMatch(r) && actMatch(r) && payMatch(r) && fitMatch(r) && workMatch(r) &&
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
    return `<tr class="click${sel}" onclick="App.open(${i})">` +
      `<td class="muted"${T(r.date ? 'Register row last updated ' + r.date : 'Not dated yet — queued, not applied')}>${r.date ? esc(shortDate(r.date)) : '—'}</td>` +
      `<td${T(r.company + '  ·  employer / recruiter')}>${r.running ? `<a class="runlink" data-company="${esc(r.company)}" data-role="${esc(r.role)}" onclick="event.stopPropagation();App.showTaskLogFor(this.dataset.company,this.dataset.role)" title="Show the live log"><span class="spin">🥜</span></a> ` : (PENDING.has(r.key) ? '<span class="spin" title="Queued — waiting to start">🥜</span> ' : '')}${r.action ? `<span class="actflag"${T(r.action)}>⚑</span> ` : ''}${esc(r.company)}</td>` +
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
  if (BUCKET === 'active' || BUCKET === 'all') {
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
  if ($('#fact-count')) { const n = GRID.filter(r => r.action).length; $('#fact-count').textContent = n ? `(${n})` : ''; }
  if ($('#filt-n')) {
    const n = [st, qq, ft, fa ? '1' : '', mp, mf, wm, q].filter(Boolean).length;
    $('#filt-n').textContent = n ? `(${n})` : '';
  }
}
window.toggleGroup = (k) => { COLLAPSED[k] = !COLLAPSED[k]; renderRows(); };
document.querySelectorAll('#grid th[data-s]').forEach(th => th.onclick = () => { const k = th.dataset.s; SORT = { k, dir: SORT.k === k ? -SORT.dir : 1 }; renderRows(); });

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
  const applyWidth = () => {
    table.style.width = cols.reduce((n, k) => n + widths[k], 0) + 'px';
  };
  applyWidth();
  const save = () => { try { localStorage.setItem('grid.cols', JSON.stringify(widths)); } catch (e) {} };
  const reset = (k, i) => {
    widths[k] = COL_DEFAULTS[k] || 100;
    cg.children[i].style.width = widths[k] + 'px';
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
        widths[k] = w; cg.children[i].style.width = w + 'px'; applyWidth();
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
  if (r.spec) jobs.push(api('/api/roles/' + encodeURIComponent(r.key)));
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
  let s = a.running ? '● ' + a.name + ' …' : (d.active ? '● running' : '○ idle');
  (d.running || []).forEach(r => s += '  ▶ ' + r);
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
    let h = `<div class="act-h">${a.running ? NUT : '✓'} ${esc(a.name || 'working…')} <span class="muted">${a.running ? 'running…' : 'finished'}</span></div>`;
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
  $('#act-sum').textContent = a.name ? ((a.running ? '● ' : '✓ ') + a.name) : (d.active ? 'runner active' : 'idle');
  if (document.body.dataset.act === 'open') {
    let h = '';
    if (a.name && (a.running || (a.log || []).length)) {
      h += `<div class="act-h">${a.running ? NUT : '✓'} ${esc(a.name)} <span class="muted">${a.running ? 'running…' : 'done'}</span></div>`;
      if (sm.headline) h += `<div class="act-sum">${esc(sm.headline)}</div>`;
      if ((sm.notable || []).length) h += '<ul class="act-list">' + sm.notable.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>';
      const total = (a.log || []).length;
      if (total > (sm.notable || []).length) h += `<details class="act-raw"><summary>full output · ${total} lines</summary><pre>${esc((a.log || []).join('\n'))}</pre></details>`;
      h += '<div class="act-sep"></div>';
    }
    h += d.active ? '● runner active' : '○ runner idle';
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
const fmtSize = (n) => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : n > 1024 ? (n / 1024).toFixed(0) + ' KB' : n + ' B';
async function setAccounts(b) {
  const [d, g] = await Promise.all([api('/api/accounts'), api('/api/google')]);
  const sc = g.scopes || [];
  const dot = (ok) => `<span class="pill" style="background:${ok ? '#1f6f43' : '#7a2e2e'}">${ok ? '✓' : '✗'}</span>`;
  const scopeName = (s) => s.split('/').pop();
  b.innerHTML = `<p class="muted">Connect your accounts. Authorisation opens in your browser - finish it there, then re-check.
      Per-site logins: <b>${d.sites}</b> stored.</p>
    <h4 style="margin:10px 0 4px">Google (Gmail + Calendar)</h4>
    <p class="muted mini">Create a <b>Desktop</b> OAuth client in Google Cloud, then paste its client id and secret here and press
      <b>Save Google settings</b> - the pipeline writes <code>credentials.json</code> for you (or drop a downloaded one at the path below).
      Gmail can read, send and attach files; Calendar can read and book events. Sending mail and writing to the calendar
      still ask for your approval every time. Timezone and meeting defaults live in <code>config/calendar.json</code>, mail
      signature and attachments in <code>config/email.json</code>.</p>
    <div class="row" style="margin:6px 0"><span class="muted" style="min-width:118px">Client ID</span>
      <input id="g-id" placeholder="${esc(g.client_id || '…apps.googleusercontent.com')}" style="flex:1"></div>
    <div class="row" style="margin:6px 0"><span class="muted" style="min-width:118px">Client secret</span>
      <input id="g-secret" type="password" placeholder="${g.has_client_secret ? '•••• stored — leave blank to keep' : ''}" style="flex:1"></div>
    <div class="row" style="margin:6px 0"><span class="muted" style="min-width:118px">Config dir</span>
      <input id="g-dir" value="${esc(g.config_dir)}" style="flex:1">
      <span class="muted mini">credentials ${dot(g.credentials_exists)} · token ${dot(g.token_exists)}</span></div>
    <div class="row" style="margin:6px 0"><span class="muted" style="min-width:118px">Files</span>
      <input id="g-cred" value="${esc(g.credentials)}" style="flex:1" title="credentials.json path">
      <input id="g-token" value="${esc(g.token)}" style="flex:1" title="token.json path"></div>
    <div class="row" style="margin:8px 0"><button onclick="App.googleSave()">Save Google settings</button>
      <button onclick="App.auth('gmail')">Authorise Gmail</button>
      <button onclick="App.auth('calendar')">Authorise Calendar</button>
      <button onclick="viewDoc('docs/ACCOUNT-SETUP.md','Account setup guide')">Setup guide</button>
      <button onclick="App.settings('accounts')">Re-check</button></div>
    <div class="muted mini">scopes: ${sc.length ? sc.map(scopeName).map(esc).join(' · ') : 'none yet'}${g.account ? ` · ${esc(g.account)}` : ''}</div>
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
  const orKey = (a.env || {}).OPENROUTER_API_KEY || '';
  const knownAgents = [['', 'Auto (OpenCode, else Claude)'], ['opencode', 'OpenCode'],
    ['openrouter', 'OpenRouter'], ['claude', 'Claude Code']];
  const customAgent = a.agent && !knownAgents.some(([v]) => v === a.agent) ? a.agent : '';
  const agentOpts = knownAgents.map(([v, label]) =>
    `<option value="${v}"${a.agent === v ? ' selected' : ''}>${label}</option>`).join('') +
    `<option value="__custom__"${customAgent ? ' selected' : ''}>Custom…</option>`;
  const envRows = (a.env_keys || []).filter(k => k !== 'OPENROUTER_API_KEY').map(k =>
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
      <select id="ai-agent" style="min-width:200px">${agentOpts}</select>
      <input id="ai-agent-custom" value="${esc(customAgent)}" placeholder="custom command" style="flex:1; display:${customAgent ? '' : 'none'}">
      <span class="muted">Model</span>
      <select id="ai-model-sel" style="min-width:220px"></select>
      <input id="ai-model-custom" placeholder="or type a model id" style="flex:1"></div>
    <div class="muted mini">Pick <b>OpenCode</b> or <b>OpenRouter</b> here. The model list comes from the selected provider (OpenCode's list or OpenRouter's catalogue); anything else can be typed.
      Applies to chat, role chats and queue/API runs; <code>MODEL=...</code> overrides for one run.</div>
    <div class="row" style="margin-top:8px"><b>OpenRouter</b>
      <input id="ai-or-key" type="password" autocomplete="new-password" placeholder="${orKey ? esc(orKey) + ' (blank = keep)' : 'sk-or-v1-…'}" style="flex:1">
      <button onclick="App.useOpenRouter()">Use OpenRouter</button>
      <span class="muted mini">OpenRouter serves the model; OpenCode is only the local tool runner. The key is stored with the other env values.</span></div>
    <h4 style="margin:14px 0 4px">API keys / env</h4>
    <div id="ai-env">${envRows || '<span class="muted mini">none set</span>'}</div>
    <div class="row" style="margin-top:6px">
      <input id="ai-env-k" list="ai-known" placeholder="KEY name" style="max-width:220px">
      <datalist id="ai-known">${(a.known_keys || []).map(k => `<option>${esc(k)}</option>`).join('')}</datalist>
      <input id="ai-env-v" placeholder="value" style="flex:1"><button onclick="App.aiAdd()">＋ Add</button></div>
    <div class="row" style="margin-top:10px"><button onclick="App.saveAI()">Save agent config</button>
      <span class="muted mini">Agent/model are read by every runner via tools/agent_run.sh.</span></div>
    <h4 style="margin:18px 0 4px">GraphRAG LLM (<code>kb/graphrag/.env</code>)</h4>
    <div id="ai-gr">${grRows || '<span class="muted mini">no .env yet</span>'}</div>
    <div class="row" style="margin-top:8px"><button onclick="App.saveGR()">Save GraphRAG env</button>
      <span class="muted mini">Used by the knowledge graph (same OPENCODE_API_KEY works for both).</span></div>`;
  App.aiFillModels(a);
  const ag = $('#ai-agent');
  if (ag) ag.onchange = () => {
    const isCustom = ag.value === '__custom__';
    const ci = $('#ai-agent-custom');
    if (ci) ci.style.display = isCustom ? '' : 'none';
    const who = isCustom ? ((ci && ci.value.trim()) || '') : ag.value;
    App.aiFillModels({ which: who, model: (a.models || {})[who] || '', models: a.models || {} });
  };
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
  $('#legend-views').innerHTML = BUCKETS.map(b => `<dt>${esc(b.label)}</dt><dd>${esc(b.hint)}</dd>`).join('');
  $('#legend-status').innerHTML = Object.entries(STATUS_HELP).map(([k, v]) => `<dt>${chip(k)}</dt><dd>${esc(v)}</dd>`).join('');
  $('#legend-queue').innerHTML = Object.entries(QUEUE_HELP).map(([k, v]) => `<dt><code>${esc(k)}</code></dt><dd>${esc(v)}</dd>`).join('');
  $('#legend-modal').classList.remove('hide');
};
$('#a-drawer').onclick = () => openDock(!PANELS.agent.open);
if ($('#chat-model')) $('#chat-model').onchange = async (e) => {
  const val = e.target.value, who = e.target.dataset.agent || '', cfg = e.target.dataset.configured || '';
  const models = {}; if (who && val) models[who] = val;
  const d = await api('/api/agent/config', { agent: cfg, model: val, models });
  toast(d.error ? d.error : `model: ${val || '(agent default)'} — applies to chat, role chats and queue/API runs`, !!d.error);
  loadChatModel();
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
$('#a-prepare-shown').onclick = () => App.prepareShown();
$('#a-submit-shown').onclick = () => App.submitPrepared();
$('#a-match').onclick = () => App.matchShown($('#a-match'));
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
async function loadChatModel() {
  const sel = $('#chat-model'); if (!sel) return;
  try {
    const c = await api('/api/agent/config');
    const who = c.which || c.agent || '';
    const m = await api('/api/agent/models?agent=' + encodeURIComponent(who));
    const cur = c.model || '';
    sel.innerHTML = modelOptionsHTML(m.groups || [], cur, m.models || []);
    sel.dataset.agent = who; sel.dataset.configured = c.agent || '';
    sel.title = 'Model for chat, role chats and queue/API runs' + (m.source ? ` (${m.source})` : '');
  } catch (e) { /* leave the picker empty */ }
}
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
initPanels(); initGridCols(); loadGrid(); gridTick(); liveTick(); healthPill(); chatPoll(); updateCheck(); loadChatModel();

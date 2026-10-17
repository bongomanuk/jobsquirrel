/* Jobsquirrel WebUI — zero-build vanilla client */
const TOKEN = document.body.dataset.sessionToken;
const $ = (s) => document.querySelector(s);
const view = $('#view');
let REG = [], ROLES = [];

async function api(path, body) {
  const o = { headers: {} };
  if (body !== undefined) {
    o.method = 'POST';
    o.headers['Content-Type'] = 'application/json';
    o.headers['X-Session'] = TOKEN;
    o.body = JSON.stringify(body);
  }
  try { return await (await fetch(path, o)).json(); }
  catch (e) { return { error: String(e) }; }
}
const esc = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const chip = (s) => `<span class="chip ${esc(s)}">${esc(s || '?')}</span>`;
const kpi = (c, l, n) => `<div class="kpi ${c}"><div class="n">${n}</div><div class="l">${l}</div></div>`;

function toast(msg, bad) {
  const t = document.createElement('div');
  t.textContent = msg;
  t.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:60;background:' + (bad ? '#3a1414' : '#10351f') +
    ';color:#fff;padding:10px 14px;border-radius:10px;border:1px solid #232838;max-width:420px;font-size:13px';
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 6000);
}

/* ---------- approval modal ---------- */
function approve(purpose, token, command) {
  return new Promise(res => {
    $('#ap-text').textContent = purpose;
    $('#ap-cmd').textContent = `POST /api/action/run { "command": "${command}", "approval_token": "${token}" }`;
    $('#ap-check').checked = false; $('#ap-confirm').disabled = true;
    $('#approve').classList.remove('hide');
    $('#ap-confirm').onclick = () => { $('#approve').classList.add('hide'); res(true); };
    $('#ap-cancel').onclick = () => { $('#approve').classList.add('hide'); res(false); };
    $('#ap-check').onchange = () => { $('#ap-confirm').disabled = !$('#ap-check').checked; };
  });
}

const App = {
  async run(command) {
    if (command === 'submit_queue') {
      const ok = await approve('Run the apply queue — this SUBMITS applications on your behalf and is irreversible.',
        'APPROVE_RUN_QUEUE', command);
      if (!ok) return;
    }
    const d = await api('/api/action/run', { command, approval_token: command === 'submit_queue' ? 'APPROVE_RUN_QUEUE' : '' });
    toast(d.ok || d.error || 'done', !!d.error);
    if (!d.error) { drawer(true); }
  },
  registerRow: async (c, r) => {
    const d = await api('/api/register/row', {
      company: c, role: r, status: $('#rd-status').value, notes: $('#rd-notes').value
    });
    toast(d.ok || d.error, !!d.error); route();
  },
  prov: async (c, r) => { const d = await api(`/api/provenance?company=${encodeURIComponent(c)}&role=${encodeURIComponent(r)}`);
    $('#rd-prov').innerHTML = Object.keys(d).length ? provHtml(d) : '<span class="muted">no provenance recorded yet</span>'; },
  pickRole: async (k) => { ROLESEL = k;
    document.querySelectorAll('#roles-list .it').forEach(x => x.classList.toggle('on', x.dataset.k === k));
    const d = await api('/api/roles/' + encodeURIComponent(k));
    const m = d.match || {};
    const badge = m.alignment === 'PASS' ? '<span class="badge good">alignment PASS</span>'
      : m.alignment === 'FAIL' ? '<span class="badge bad">alignment FAIL</span>' : '<span class="badge mid">no CV mapped</span>';
    const cov = m.coverage == null ? '<span class="badge mid">no generated docs</span>'
      : `<span class="badge ${m.coverage >= 70 ? 'good' : m.coverage >= 40 ? 'mid' : 'bad'}">keyword coverage ${m.coverage}%</span>`;
    $('#role-detail').innerHTML =
      `<div class="card"><h2 style="margin-top:0">${esc(k)}</h2><div class="row">${badge}${cov}${m.archetype ? ` <span class="muted">archetype: ${esc(m.archetype)}</span>` : ''}</div>` +
      (m.missing && m.missing.length ? `<div class="muted" style="margin-top:8px">missing: ${m.missing.map(esc).join(', ')}</div>` : '') +
      `<div class="row" style="margin-top:10px"><button onclick="App.run('prepare')">Prepare (review)</button></div></div>` +
      `<div class="tabs2" id="rtabs"><a class="on" onclick="App.rtab(0)">Job description</a><a onclick="App.rtab(1)">ATS keywords</a>` +
      `<a onclick="App.rtab(2)">GraphRAG context</a><a onclick="App.rtab(3)">Tailored output</a></div>` +
      `<pre class="doc" id="rtab">${esc(d.jd || '(no saved ad)')}</pre>`;
    window.__role = d;
  },
  rtab: (i) => {
    const d = window.__role || {};
    const map = [d.jd, d.ats, d.kb, d.tailored_cv || d.letter];
    document.querySelectorAll('#rtabs a').forEach((a, n) => a.classList.toggle('on', n === i));
    $('#rtab').textContent = map[i] || '(nothing yet)';
  },
  cf: async (target) => {
    document.querySelectorAll('#cf-tabs a').forEach(a => a.classList.toggle('on', a.dataset.t === target));
    const d = await api('/api/config?target=' + target);
    CF = target; $('#cf-text').value = d.content || ''; $('#cf-msg').textContent = '';
  },
  cfSave: async () => {
    const d = await api('/api/config', { target: CF, content: $('#cf-text').value });
    $('#cf-msg').textContent = d.ok || d.error; toast(d.ok || d.error, !!d.error);
  },
  qact: async (action, c, r) => {
    const d = await api('/api/queue/action', { action, company: c, role: r });
    toast(d.ok || d.error, !!d.error); route();
  },
  chat: async () => {
    const inp = $('#chatmsg'), m = inp.value.trim(); if (!m) return; inp.value = '';
    $('#chat').textContent += `\n\n> ${m}\n`;
    const d = await api('/api/chat', { message: m });
    if (d.error) { toast(d.error, true); return; }
    chatOffset = 0; clearInterval(CHAT_TIMER); CHAT_TIMER = setInterval(chatPoll, 1200);
  },
};
let CF = 'cv.json', ROLESEL = null, chatOffset = 0, CHAT_TIMER = null, LIVE_TIMER = null;

function provHtml(d) {
  const sha = (s) => s ? `<span class="sha" title="click to copy" onclick="navigator.clipboard.writeText('${esc(s)}')">${esc(s.slice(0, 16))}…</span>` : '—';
  const shots = (d.screenshots || []).map(p => `<div class="mono muted">${esc(p)}</div>`).join('');
  return `<table><tbody>
    <tr><td class="muted">CV</td><td>${esc(d.cv_file || '—')} ${sha(d.cv_sha256)}</td></tr>
    <tr><td class="muted">letter</td><td>${esc(d.letter_file || '—')} ${sha(d.letter_sha256)}</td></tr>
    <tr><td class="muted">confidence</td><td>${chip((d.confidence || '').toUpperCase())}</td></tr>
    <tr><td class="muted">evidence</td><td>${esc(d.evidence || '—')}</td></tr>
    <tr><td class="muted">snapshot</td><td class="mono">${esc(d.snapshot_dir || '—')}</td></tr>${shots}</tbody></table>`;
}

/* ---------- views ---------- */
async function overview() {
  view.innerHTML = '<div class="muted">loading…</div>';
  const s = await api('/api/state');
  view.innerHTML =
    `<div class="kpis">${kpi('hero', 'In process', s.kpis.in_process)}${kpi('', 'Interviews', s.kpis.interviews)}` +
    `${kpi('', 'Blocked / human', s.kpis.blocked + s.kpis.human)}${kpi('', 'Offers', s.kpis.offers)}` +
    `${kpi('', 'Total', s.kpis.total)}${kpi('', 'Submissions', s.kpis.submissions)}</div>` +
    `<div class="funnel">${['PREPARED', 'SUBMITTED', 'INTERVIEW', 'OFFER', 'REJECTED'].map(x => `<span class="step">${x} <b>${s.counts[x] || 0}</b></span>`).join('<span class="muted">→</span>')}</div>` +
    `<div class="cols"><div class="card"><h2 style="margin-top:0">Live runner &amp; tail</h2><div id="ov-live" class="term" style="max-height:34vh">…</div></div>` +
    `<div class="card"><h2 style="margin-top:0">Interviews</h2><div id="ov-int" class="muted">…</div></div></div>` +
    `<h2>Recent runs</h2><table><thead><tr><th>When</th><th>Company</th><th>Role</th><th>Outcome</th><th>Detail</th></tr></thead><tbody id="ov-runs"></tbody></table>`;
  $('#ov-int').innerHTML = (s.interviews || []).map(x => `· ${esc(x.company)} — ${esc(x.role)}`).join('<br>') || '<span class="muted">none yet</span>';
  const runs = await api('/api/runs');
  $('#ov-runs').innerHTML = runs.map(r => `<tr><td class="muted">${esc((r.ts || '').slice(11, 19))}</td><td>${esc(r.company)}</td><td>${esc(r.role)}</td><td>${chip(r.outcome || '?')}</td><td class="muted">${esc(r.reason || '')}</td></tr>`).join('') || '<tr><td colspan=5 class="muted">no runs yet</td></tr>';
  clearInterval(LIVE_TIMER); LIVE_TIMER = setInterval(liveFill, 2500); liveFill();
}
async function liveFill() {
  const d = await api('/api/live'); const el = $('#ov-live'); if (!el) return;
  let h = d.active ? '● runner active' : '○ runner idle';
  (d.running || []).forEach(r => h += `\n▶ ${r}`);
  (d.tail || []).forEach(x => h += x.k === 'phase' ? `\n[p] ${x.t}` : `\n    ${x.t}`);
  el.textContent = h;
}

async function register() {
  view.innerHTML = '<div class="muted">loading…</div>';
  const d = await api('/api/register'); REG = d.rows;
  view.innerHTML =
    `<div class="row" style="margin-bottom:12px"><input id="rg-q" placeholder="search company / role…" style="flex:1;max-width:340px">` +
    `<select id="rg-s"><option value="">all statuses</option>${['SUBMITTED', 'IN_PROGRESS', 'INTERVIEW', 'OFFER', 'REJECTED', 'BLOCKED', 'MANUAL', 'PREPARED', 'CLOSED'].map(x => `<option>${x}</option>`).join('')}</select>` +
    `<span class="muted">${d.total} rows</span></div>` +
    `<div class="grid2"><div class="list" id="rg-list"></div><div id="rg-detail" class="muted">select an application…</div></div>`;
  $('#rg-q').oninput = rgFill; $('#rg-s').onchange = rgFill; rgFill();
}
function rgFill() {
  const q = $('#rg-q').value.toLowerCase(), s = $('#rg-s').value;
  const rows = REG.filter(r => (!q || r.company.toLowerCase().includes(q) || r.role.toLowerCase().includes(q)) && (!s || r.status === s));
  $('#rg-list').innerHTML = rows.map(r => `<div class="it" onclick="App.openRow(this)" data-c="${esc(r.company)}" data-r="${esc(r.role)}">${chip(r.status)} ${esc(r.company)} — ${esc(r.role)}</div>`).join('') || '<div class="it muted">no matches</div>';
}
App.openRow = (el) => {
  document.querySelectorAll('#rg-list .it').forEach(x => x.classList.remove('on')); el.classList.add('on');
  const c = el.dataset.c, r = el.dataset.r, row = REG.find(x => x.company === c && x.role === r) || {};
  $('#rg-detail').innerHTML =
    `<div class="card"><h2 style="margin-top:0">${esc(c)}</h2><div>${esc(r)}</div>` +
    `<div class="row" style="margin:12px 0"><span class="muted">status</span><select id="rd-status">${['SUBMITTED', 'INTERVIEW', 'OFFER', 'REJECTED', 'BLOCKED', 'MANUAL', 'PREPARED', 'IN_PROGRESS', 'CLOSED'].map(x => `<option ${x === row.status ? 'selected' : ''}>${x}</option>`).join('')}</select>` +
    `<span class="muted">ATS</span><b>${esc(row.ats || '—')}</b><span class="muted">date</span><b>${esc(row.date || '—')}</b></div>` +
    `<div class="muted">notes</div><textarea id="rd-notes" style="min-height:14vh">${esc(row.notes || '')}</textarea>` +
    `<div class="row" style="margin-top:10px"><button onclick="App.registerRow('${c.replace(/'/g, "\\'")}','${r.replace(/'/g, "\\'")}')">Save</button></div></div>` +
    `<h2>Provenance</h2><div id="rd-prov" class="muted">loading…</div>`;
  App.prov(c, r);
};

async function queue() {
  view.innerHTML = '<div class="muted">loading…</div>';
  const d = await api('/api/queue');
  const grp = (title, arr, acts) => `<h2>${title} (${arr.length})</h2>` +
    (arr.length ? arr.map(it => `<div class="card"><b>${esc(it.company || it)}</b> — ${esc(it.role || '')}` +
      `<div class="muted">${esc(it.url || '')}</div><div class="row" style="margin-top:8px">` +
      (acts || []).map(a => `<button class="small" onclick="App.qact('${a}',${JSON.stringify(it.company || '')},${JSON.stringify(it.role || '')})">${a}</button>`).join('') +
      `</div></div>`).join('') : '<div class="muted">empty</div>');
  view.innerHTML = `<h2>Human assist / blocked — needs you</h2>` +
    (d.human.length ? d.human.map(it => `<div class="card"><b>${esc(it.company)}</b> — ${esc(it.role)}<div class="muted">${esc(it.url)}</div>` +
      `<div class="row" style="margin-top:8px"><button class="small" onclick="App.run('prepare')">Open assist (visible browser)</button>` +
      `<button class="small" onclick="App.qact('unblock',${JSON.stringify(it.company)},${JSON.stringify(it.role)})">To pending</button>` +
      `<button class="small" onclick="App.qact('delete',${JSON.stringify(it.company)},${JSON.stringify(it.role)})">Delete</button></div></div>`).join('') : '<div class="muted">nothing waiting</div>') +
    grp('Pending queue', d.pending, ['delete']) + grp('Retry queue', d.retry, ['retry', 'delete']) +
    `<h2>Done (${d.done.length})</h2><div class="card mono muted" style="max-height:30vh;overflow:auto">${d.done.slice(-100).map(esc).join('<br>') || '—'}</div>`;
}

async function roles() {
  view.innerHTML = '<div class="muted">loading…</div>';
  const d = await api('/api/roles'); ROLES = d;
  view.innerHTML = `<div class="row" style="margin-bottom:10px"><input id="rq" placeholder="filter roles…" style="flex:1;max-width:340px">` +
    `<input id="rdis" placeholder="add role by URL…" style="flex:1"><button onclick="App.discover()">Add role</button>` +
    `<span class="muted">${d.length} saved</span></div>` +
    `<div class="grid2"><div class="list" id="roles-list"></div><div id="role-detail" class="muted">select a role…</div></div>`;
  const fill = () => { const q = ($('#rq').value || '').toLowerCase();
    $('#roles-list').innerHTML = ROLES.filter(r => !q || r.key.includes(q)).map(r =>
      `<div class="it" data-k="${esc(r.key)}" onclick="App.pickRole(this.dataset.k)">${esc(r.key)}${r.match_pct != null ? ` <span class="muted">${r.match_pct}%</span>` : ''}</div>`).join('') || '<div class="it muted">none</div>'; };
  $('#rq').oninput = fill; fill();
}
App.discover = async () => {
  const url = $('#rdis').value.trim(); if (!url) return;
  toast('fetching…');
  const d = await api('/api/roles/discover', { url });
  toast(d.ok || d.error, !!d.error); if (!d.error) { $('#rdis').value = ''; roles(); }
};

async function config() {
  view.innerHTML =
    `<div class="row"><div class="tabs2" id="cf-tabs" style="margin:0">` +
    `<a data-t="cv.json" onclick="App.cf('cv.json')">cv.json</a><a data-t="archetypes.json" onclick="App.cf('archetypes.json')">archetypes.json</a>` +
    `<a data-t="profile.md" onclick="App.cf('profile.md')">profile.md</a></div>` +
    `<button onclick="App.cfSave()">Save</button>` +
    `<button onclick="App.run('build_archetypes')">Regenerate archetype CVs</button>` +
    `<span id="cf-msg" class="muted"></span></div>` +
    `<textarea id="cf-text" spellcheck="false" style="margin-top:12px"></textarea>` +
    `<div class="muted" style="margin-top:6px">JSON is validated before saving; a <code>.bak</code> copy is kept. After editing, click <b>Regenerate archetype CVs</b>.</div>`;
  App.cf('cv.json');
}

async function outcomes() {
  view.innerHTML = '<div class="muted">loading…</div>';
  const d = await api('/api/outcomes');
  const rows = Object.entries(d.by_ats).sort((a, b) => b[1].total - a[1].total);
  view.innerHTML = `<h2>Conversion by source / ATS <span class="muted" style="text-transform:none">· overall interview rate ${d.interview_rate}%</span></h2>` +
    `<table><thead><tr><th>Source / ATS</th><th>Applications</th><th>Interviews</th><th>Offers</th><th>Interview rate</th></tr></thead><tbody>` +
    rows.map(([a, v]) => `<tr><td>${esc(a)}</td><td>${v.total}</td><td>${v.interview}</td><td>${v.offer}</td><td>${Math.round(100 * v.interview / v.total)}%</td></tr>`).join('') +
    `</tbody></table>`;
}

/* ---------- chat + live drawer ---------- */
function drawer(open) { $('#drawer').classList.toggle('open', open); if (open) { agentName(); liveDrawer(); } }
async function agentName() { const d = await api('/api/agent'); $('#agent-name').textContent = d.agent || '?'; }
async function chatPoll() {
  const d = await api('/api/chat/stream?since=' + chatOffset);
  if (d.chunk) { const el = $('#chat'); el.textContent += d.chunk; el.scrollTop = el.scrollHeight; }
  chatOffset = d.offset; if (d.done) { clearInterval(CHAT_TIMER); CHAT_TIMER = null; }
}
async function liveDrawer() {
  if (!$('#drawer').classList.contains('open')) return;
  const d = await api('/api/live'); const el = $('#liveterm');
  let h = d.active ? '● runner active' : '○ runner idle';
  (d.running || []).forEach(r => h += `\n▶ ${r}`);
  (d.tail || []).forEach(x => h += x.k === 'phase' ? `\n[p] ${x.t}` : `\n    ${x.t}`);
  el.textContent = h;
  setTimeout(liveDrawer, 2500);
}

/* ---------- routing ---------- */
const views = { overview, register, queue, roles, config, outcomes };
function route() {
  if (LIVE_TIMER) { clearInterval(LIVE_TIMER); LIVE_TIMER = null; }
  const t = (location.hash || '#overview').slice(1);
  document.querySelectorAll('#tabs a').forEach(a => a.classList.toggle('on', a.dataset.t === t));
  (views[t] || overview)();
}
window.addEventListener('hashchange', route);
$('#a-prepare').onclick = () => App.run('prepare');
$('#a-submit').onclick = () => App.run('submit_queue');
$('#a-reconcile').onclick = () => App.run('reconcile');
$('#a-drawer').onclick = () => drawer(!$('#drawer').classList.contains('open'));
$('#d-close').onclick = () => drawer(false);
$('#chat-send').onclick = () => App.chat();
$('#abort').onclick = async () => { toast('Abort is advisory: stop the runner with Ctrl-C in its terminal.'); };
window.App = App;
async function healthPill() { const s = await api('/api/state'); const h = $('#health');
  h.textContent = 'health: ' + s.doctor; h.className = 'pill ' + s.doctor; h.title = s.doctor_detail || ''; }
route(); healthPill(); setInterval(healthPill, 30000);

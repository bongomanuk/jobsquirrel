/* Jobsquirrel WebUI — single master data grid + detail drawer (zero-build) */
const TOKEN = document.body.dataset.sessionToken;
const $ = (s) => document.querySelector(s);
const esc = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const chip = (s) => `<span class="chip ${esc(s)}">${esc(s || '')}</span>`;
let GRID = [], SORT = { k: 'date', dir: -1 }, D = {}, P = {}, chatOffset = 0, CHAT_TIMER = null;

async function api(path, body) {
  const o = { headers: {} };
  if (body !== undefined) { o.method = 'POST'; o.headers['Content-Type'] = 'application/json'; o.headers['X-Session'] = TOKEN; o.body = JSON.stringify(body); }
  try { return await (await fetch(path, o)).json(); } catch (e) { return { error: String(e) }; }
}
function toast(msg, bad) {
  const t = document.createElement('div'); t.textContent = msg;
  t.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:60;border-radius:10px;padding:10px 14px;font-size:13px;max-width:440px;color:#fff;background:' + (bad ? '#3a1414' : '#10351f') + ';border:1px solid #232838';
  document.body.appendChild(t); setTimeout(() => t.remove(), 6000);
}

const App = {
  async run(command) {
    if (command === 'submit_queue') {
      const ok = await approve('Run the apply queue — this SUBMITS applications and is irreversible.', 'APPROVE_RUN_QUEUE', command);
      if (!ok) return;
    }
    const d = await api('/api/action/run', { command, approval_token: command === 'submit_queue' ? 'APPROVE_RUN_QUEUE' : '' });
    toast(d.ok || d.error, !!d.error); if (!d.error) { drawer(true); }
  },
  cf: async (target) => {
    document.querySelectorAll('#cf-tabs a').forEach(a => a.classList.toggle('on', a.dataset.t === target));
    const d = await api('/api/config?target=' + target); CF = target; $('#cf-text').value = d.content || ''; $('#cf-msg').textContent = '';
  },
  cfSave: async () => { const d = await api('/api/config', { target: CF, content: $('#cf-text').value }); $('#cf-msg').textContent = d.ok || d.error; toast(d.ok || d.error, !!d.error); },
  chat: async () => {
    const inp = $('#chatmsg'), m = inp.value.trim(); if (!m) return; inp.value = '';
    $('#chat').textContent += `\n\n> ${m}\n`;
    const d = await api('/api/chat', { message: m }); if (d.error) { toast(d.error, true); return; }
    chatOffset = 0; clearInterval(CHAT_TIMER); CHAT_TIMER = setInterval(chatPoll, 1200);
  },
  open: (i) => openDetail(GRID[i]),
  saveRow: async () => {
    const d = await api('/api/register/row', { company: CUR.company, role: CUR.role, status: $('#dt-status').value, notes: $('#dt-notes').value });
    toast(d.ok || d.error, !!d.error); if (!d.error) { loadGrid(); }
  },
};
let CF = 'cv.json', CUR = null;

/* ---------- approval ---------- */
function approve(purpose, token, command) {
  return new Promise(res => {
    $('#ap-text').textContent = purpose;
    $('#ap-cmd').textContent = `POST /api/action/run { "command": "${command}", "approval_token": "${token}" }`;
    $('#ap-check').checked = false; $('#ap-confirm').disabled = true; $('#approve').classList.remove('hide');
    $('#ap-confirm').onclick = () => { $('#approve').classList.add('hide'); res(true); };
    $('#ap-cancel').onclick = () => { $('#approve').classList.add('hide'); res(false); };
    $('#ap-check').onchange = () => { $('#ap-confirm').disabled = !$('#ap-check').checked; };
  });
}

/* ---------- grid ---------- */
async function loadGrid() {
  const [g, s] = await Promise.all([api('/api/grid'), api('/api/state')]);
  GRID = Array.isArray(g) ? g : [];
  $('#metrics').innerHTML =
    `<span class="metric hero"><b>${s.kpis.in_process}</b>in process</span>` +
    `<span class="metric"><b>${s.kpis.interviews}</b>interviews</span>` +
    `<span class="metric"><b>${s.kpis.blocked}</b>blocked</span>` +
    `<span class="metric"><b>${s.kpis.human}</b>human</span>` +
    `<span class="metric"><b>${s.kpis.offers}</b>offers</span>` +
    `<span class="metric"><b>${s.kpis.total}</b>total</span>` +
    `<span class="metric"><b>${s.kpis.submissions}</b>submissions</span>`;
  renderRows();
}
function renderRows() {
  const q = $('#q').value.toLowerCase(), st = $('#fstatus').value, qq = $('#fqueue').value;
  let rows = GRID.filter(r => (!st || r.status === st) && (!qq || r.queue === qq) &&
    (!q || (r.company + ' ' + r.role + ' ' + (r.ats || '')).toLowerCase().includes(q)));
  const k = SORT.k; rows = rows.slice().sort((a, b) => (a[k] || '') < (b[k] || '') ? -SORT.dir : (a[k] || '') > (b[k] || '') ? SORT.dir : 0);
  $('#count').textContent = `${rows.length} / ${GRID.length} rows`;
  const mbadge = (r) => r.match == null ? '<span class="muted">—</span>'
    : `<span class="badge ${r.match >= 70 ? 'good' : r.match >= 40 ? 'mid' : 'bad'}">${r.match}%</span>` + (r.alignment === 'FAIL' ? ' <span class="badge bad">align✗</span>' : '');
  $('#rows').innerHTML = rows.map((r) => {
    const i = GRID.indexOf(r);
    return `<tr class="click" onclick="App.open(${i})">` +
      `<td class="muted">${esc(r.date)}</td><td>${esc(r.company)}</td><td>${esc(r.role)}</td>` +
      `<td class="muted">${esc(r.ats)}</td><td>${chip(r.status)}</td><td>${mbadge(r)}</td>` +
      `<td class="muted">${esc(r.queue)}</td><td>${r.applied ? '✓' : '<span class="muted">—</span>'}</td>` +
      `<td>${r.spec ? '✓' : '<span class="muted">—</span>'}</td></tr>`;
  }).join('') || '<tr><td colspan=9 class="muted">no matching rows</td></tr>';
}
document.querySelectorAll('#grid th[data-s]').forEach(th => th.onclick = () => { const k = th.dataset.s; SORT = { k, dir: SORT.k === k ? -SORT.dir : 1 }; renderRows(); });

/* ---------- detail drawer ---------- */
async function openDetail(r) {
  if (!r) return; CUR = r; D = {}; P = {};
  $('#detail').classList.add('open'); $('#d-title').textContent = `${r.company} — ${r.role}`;
  const tabs = ['Summary', 'Provenance', 'Job spec', 'ATS', 'KB context', 'Tailored'];
  $('#dtabs').innerHTML = tabs.map((t, i) => `<a class="${i === 0 ? 'on' : ''}" onclick="dt(${i})">${t}</a>`).join('');
  $('#d-body').innerHTML = '<span class="muted">loading…</span>';
  const jobs = [api(`/api/provenance?company=${encodeURIComponent(r.company)}&role=${encodeURIComponent(r.role)}`)];
  if (r.spec) jobs.push(api('/api/roles/' + encodeURIComponent(r.key)));
  const [p, d] = await Promise.all(jobs); P = p || {}; D = d || {};
  dt(0);
}
window.dt = (i) => {
  const r = CUR, map = [summary, prov, spec, ats, kb, tailored];
  document.querySelectorAll('#dtabs a').forEach((a, n) => a.classList.toggle('on', n === i));
  $('#d-body').innerHTML = map[i](r) || '<span class="muted">—</span>';
};
const sec = (s) => `<pre class="doc">${s ? esc(s) : '(nothing yet)'}</pre>`;
function summary(r) {
  const m = (D.match) || {};
  return `<div class="row" style="margin-bottom:10px"><span class="muted">status</span><select id="dt-status">` +
    ['SUBMITTED', 'INTERVIEW', 'OFFER', 'REJECTED', 'BLOCKED', 'MANUAL', 'PREPARED', 'IN_PROGRESS', 'CLOSED'].map(x => `<option ${x === r.status ? 'selected' : ''}>${x}</option>`).join('') + '</select>' +
    `<span class="muted">ATS</span><b>${esc(r.ats || '—')}</b><span class="muted">queue</span><b>${esc(r.queue || '—')}</b>` +
    `<span class="muted">key</span><span class="mini mono">${esc(r.key)}</span></div>` +
    `<div class="row">${m.alignment ? `<span class="badge ${m.alignment === 'PASS' ? 'good' : 'bad'}">alignment ${m.alignment}</span>` : ''}` +
    `${m.coverage != null ? `<span class="badge ${m.coverage >= 70 ? 'good' : 'mid'}">coverage ${m.coverage}%</span>` : ''}</div>` +
    (m.missing && m.missing.length ? `<div class="muted mini" style="margin-top:6px">missing: ${m.missing.map(esc).join(', ')}</div>` : '') +
    `<div class="muted" style="margin:12px 0 4px">notes</div><textarea id="dt-notes" style="min-height:16vh">${esc(r.notes || (D.match ? '' : ''))}</textarea>` +
    `<div class="row" style="margin-top:10px"><button onclick="App.saveRow()">Save</button>` +
    `<button onclick="App.run('prepare')">Prepare (review)</button></div>`;
}
function prov() {
  if (!Object.keys(P).length) return '<span class="muted">no provenance recorded yet</span>';
  const sha = (s) => s ? `<span class="sha" title="copy" onclick="navigator.clipboard.writeText('${esc(s)}')">${esc(s.slice(0, 16))}…</span>` : '—';
  return `<table><tbody>` +
    `<tr><td class="muted">CV</td><td>${esc(P.cv_file || '—')} ${sha(P.cv_sha256)}</td></tr>` +
    `<tr><td class="muted">letter</td><td>${esc(P.letter_file || '—')} ${sha(P.letter_sha256)}</td></tr>` +
    `<tr><td class="muted">confidence</td><td>${chip((P.confidence || '').toUpperCase())}</td></tr>` +
    `<tr><td class="muted">evidence</td><td>${esc(P.evidence || '—')}</td></tr>` +
    `<tr><td class="muted">snapshot</td><td class="mini mono">${esc(P.snapshot_dir || '—')}</td></tr>` +
    `<tr><td class="muted">screenshots</td><td class="mini mono">${(P.screenshots || []).map(esc).join('<br>') || '—'}</td></tr></tbody></table>`;
}
const spec = () => sec(D.jd), ats = () => sec(D.ats), kb = () => sec(D.kb), tailored = () => sec(D.tailored_cv || D.letter);

/* ---------- live strip + drawer ---------- */
async function liveTick() {
  const d = await api('/api/live');
  const a = d.action || {};
  let s = a.running ? '● ' + a.name + ' …' : (d.active ? '● running' : '○ idle');
  (d.running || []).forEach(r => s += '  ▶ ' + r);
  const t = (d.tail || []).slice(-1)[0];
  if (t) s += '   ' + t.t;
  $('#live').textContent = s;
  if ($('#drawer').classList.contains('open')) {
    const a = d.action || {};
    let h = '';
    if (a.name && (a.running || (a.log || []).length)) {
      h += (a.running ? '● ' : '✓ ') + a.name + (a.running ? '  (running…)' : '  (finished)') + '\n' +
        (a.log || []).join('\n') + '\n\n';
    }
    h += d.active ? '● runner active' : '○ runner idle';
    (d.running || []).forEach(r => h += `\n▶ ${r}`);
    (d.tail || []).forEach(x => h += x.k === 'phase' ? `\n[p] ${x.t}` : `\n    ${x.t}`);
    $('#liveterm').textContent = h;
  }
  setTimeout(liveTick, 2500);
}
function drawer(open) { $('#drawer').classList.toggle('open', open); if (open) { api('/api/agent').then(d => $('#agent-name').textContent = d.agent || '?'); liveTick(); } }
async function chatPoll() { const d = await api('/api/chat/stream?since=' + chatOffset); if (d.chunk) { const el = $('#chat'); el.textContent += d.chunk; el.scrollTop = el.scrollHeight; } chatOffset = d.offset; if (d.done) { clearInterval(CHAT_TIMER); CHAT_TIMER = null; } }

/* ---------- wiring ---------- */
$('#d-close').onclick = () => $('#detail').classList.remove('open');
$('#a-prepare').onclick = () => App.run('prepare');
$('#a-submit').onclick = () => App.run('submit_queue');
$('#a-reconcile').onclick = () => App.run('reconcile');
$('#a-config').onclick = () => { $('#cfg').classList.remove('hide'); App.cf(CF); };
window.cfgClose = () => $('#cfg').classList.add('hide');
$('#a-drawer').onclick = () => drawer(!$('#drawer').classList.contains('open'));
$('#dr-close').onclick = () => drawer(false);
$('#chat-send').onclick = () => App.chat();
$('#q').oninput = renderRows; $('#fstatus').onchange = renderRows; $('#fqueue').onchange = renderRows;
$('#export').onclick = () => {
  const cs = ['date', 'company', 'role', 'ats', 'status', 'match', 'queue', 'applied', 'spec', 'key'];
  const body = GRID.map(r => cs.map(c => JSON.stringify(r[c] == null ? '' : r[c])).join(',')).join('\n');
  const url = URL.createObjectURL(new Blob([cs.join(',') + '\n' + body], { type: 'text/csv' }));
  const a = document.createElement('a'); a.href = url; a.download = 'jobsquirrel.csv'; a.click(); URL.revokeObjectURL(url);
};
window.App = App;
async function healthPill() { const s = await api('/api/health'); const h = $('#health');
  h.textContent = 'health: ' + (s.v || '?'); h.className = 'pill ' + (s.v || 'unknown'); h.title = s.detail || ''; setTimeout(healthPill, 60000); }
loadGrid(); liveTick(); healthPill();

/* Jobsquirrel WebUI — single master data grid + detail drawer (zero-build) */
const TOKEN = document.body.dataset.sessionToken;
const $ = (s) => document.querySelector(s);
const esc = (s) => (s == null ? '' : String(s)).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const chip = (s) => `<span class="chip ${esc(s)}">${esc(s || '')}</span>`;
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
let GRID = [], SORT = { k: 'date', dir: -1 }, D = {}, P = {}, chatOffset = 0, CHAT_TIMER = null, CHAT = { segments: [] };

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
    CHAT = { segments: [], running: true }; renderChat();
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
const sec = (s, raw) => s ? (raw ? `<pre class="doc">${esc(s)}</pre>` : `<div class="doc md">${md(s)}</div>`) : '<span class="muted">(nothing yet)</span>';
const vbtn = (f, t) => f ? ` <button class="mini" onclick='viewDoc(${JSON.stringify(f)},"${t}")'>view</button>` : '';
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
    `<tr><td class="muted">CV</td><td>${esc(P.cv_file || '—')} ${sha(P.cv_sha256)}${vbtn(P.cv_file, 'CV')}</td></tr>` +
    `<tr><td class="muted">letter</td><td>${esc(P.letter_file || '—')} ${sha(P.letter_sha256)}${vbtn(P.letter_file, 'Cover letter')}</td></tr>` +
    `<tr><td class="muted">confidence</td><td>${chip((P.confidence || '').toUpperCase())}</td></tr>` +
    `<tr><td class="muted">evidence</td><td class="md">${P.evidence ? md(P.evidence) : '—'}</td></tr>` +
    `<tr><td class="muted">snapshot</td><td class="mini mono">${esc(P.snapshot_dir || '—')}</td></tr>` +
    `<tr><td class="muted">screenshots</td><td class="mini mono">${(P.screenshots || []).map(esc).join('<br>') || '—'}</td></tr></tbody></table>`;
}
const spec = () => sec(D.jd), ats = () => sec(D.ats, true), kb = () => sec(D.kb), tailored = () => sec(D.tailored_cv || D.letter);

window.docClose = () => $('#docv').classList.remove('open');
window.viewDoc = async (rel, title) => {
  if (!rel) return;
  $('#docv-title').textContent = title || String(rel).split('/').pop();
  $('#docv-raw').href = '/raw?path=' + encodeURIComponent(rel);
  $('#docv-body').innerHTML = '<span class="muted">loading…</span>';
  $('#docv').classList.add('open');
  const d = await api('/api/file?path=' + encodeURIComponent(rel));
  if (!d || d.error) { $('#docv-body').innerHTML = `<span class="muted">${esc((d && d.error) || 'not found')}</span>`; return; }
  if (d.kind === 'docx') $('#docv-body').innerHTML = `<div class="md">${d.html}</div>`;
  else if (d.kind === 'text') $('#docv-body').innerHTML = `<pre class="doc">${esc(d.text)}</pre>`;
  else if (d.kind === 'pdf') $('#docv-body').innerHTML = `<embed src="${d.url}" type="application/pdf" style="width:100%;height:76vh">`;
  else if (d.kind === 'image') $('#docv-body').innerHTML = `<img src="${d.url}" style="max-width:100%">`;
  else $('#docv-body').innerHTML = `<a href="${d.url}" target="_blank">open ${esc(d.name)}</a>`;
};

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
    let h = '';
    const a = d.action || {};
    if (a.name && (a.running || (a.log || []).length)) {
      const sm = a.summary || {};
      h += `<div class="act-h">${a.running ? '●' : '✓'} ${esc(a.name)} <span class="muted">${a.running ? 'running…' : 'done'}</span></div>`;
      if (sm.headline) h += `<div class="act-sum">${esc(sm.headline)}</div>`;
      if ((sm.notable || []).length) h += '<ul class="act-list">' + sm.notable.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>';
      const shown = (sm.notable || []).length;
      const total = (a.log || []).length;
      if (total > shown) h += `<details class="act-raw"><summary>full output · ${total} lines</summary><pre>${esc((a.log || []).join('\n'))}</pre></details>`;
      h += '<div class="act-sep"></div>';
    }
    h += d.active ? '● runner active' : '○ runner idle';
    (d.running || []).forEach(r => h += `\n▶ ${esc(r)}`);
    (d.tail || []).forEach(x => h += x.k === 'phase' ? `\n[p] ${esc(x.t)}` : `\n    ${esc(x.t)}`);
    $('#liveterm').innerHTML = h;
  }
  setTimeout(liveTick, 2500);
}
function drawer(open) { $('#drawer').classList.toggle('open', open); if (open) { api('/api/agent').then(d => $('#agent-name').textContent = d.agent || '?'); liveTick(); } }
async function chatPoll() { const d = await api('/api/chat/stream?since=' + chatOffset); if (d.segments) { CHAT = d; renderChat(); } chatOffset = d.offset || chatOffset; if (d.done) { clearInterval(CHAT_TIMER); CHAT_TIMER = null; renderChat(); } }
function renderChat() {
  const el = $('#chat'), segs = (CHAT && CHAT.segments) || [];
  if (!segs.length) { el.innerHTML = '<span class="muted">' + (CHAT.running ? '◌ thinking…' : 'ask the agent anything…') + '</span>'; return; }
  let h = '';
  for (const s of segs) {
    if (s.t === 'user') h += `<div class="c-user"><div class="md">${md(s.body)}</div></div>`;
    else if (s.t === 'status') h += `<div class="c-status">${esc(s.body)}</div>`;
    else if (s.t === 'tool') { const tag = (s.tool && s.tool !== 'bash') ? esc(s.tool) + ' · ' : '$ '; h += `<details class="c-tool"><summary><code>${tag}${esc(s.cmd)}</code></summary>${s.body ? `<pre>${esc(s.body)}</pre>` : ''}</details>`; }
    else h += `<div class="md">${md(s.body)}</div>`;
  }
  if (CHAT.running) h += '<span class="muted">▮</span>';
  el.innerHTML = h; el.scrollTop = el.scrollHeight;
}

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

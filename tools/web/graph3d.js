/* Three.js view for the knowledge graph.
 *
 * Loaded on demand from app.js. It owns the WebGL scene, a small 3D force
 * layout, orbit/zoom/pan, raycast selection and the HTML label layer; the
 * dashboard owns the data, breadcrumbs, side panel and search.
 */
import * as THREE from './vendor/three.module.min.js';

const LEVEL_COLORS = ['#f59e0b', '#3b82f6', '#22c55e', '#a855f7', '#06b6d4', '#ef4444', '#ec4899', '#14b8a6'];
const COMM_COLORS = ['#f59e0b', '#3b82f6', '#22c55e', '#a855f7', '#06b6d4', '#ef4444',
  '#ec4899', '#14b8a6', '#eab308', '#8b5cf6', '#f97316', '#84cc16'];
const TYPE_COLORS = {
  TECHNOLOGY: '#3b82f6', SKILL: '#22c55e', METRIC: '#f59e0b', PROJECT: '#a855f7',
  PRODUCT: '#06b6d4', ORGANIZATION: '#ef4444', ROLE: '#eab308', PLATFORM: '#8b5cf6',
  CERTIFICATION: '#14b8a6', EDUCATION: '#64748b', PERSON: '#f97316', CONCEPT: '#94a3b8'
};
const ACCENT = 0xf59e0b;
const DIM = 0x334155;

const S = {
  inited: false, canvas: null, labels: null, tip: null, stage: null,
  renderer: null, scene: null, camera: null, group: null, raycaster: null,
  nodes: [], links: [], byId: new Map(), meshes: [], glows: [], hits: [], lineMesh: null,
  visibleLabels: new Set(), measureCtx: null,
  linePos: null, lineColors: null, labelEls: new Map(), top: new Set(),
  selected: null, hovered: null, hidden: new Set(), opts: {}, paused: true,
  raf: 0, alpha: 1, fitted: false, hitEls: new Map(), lastInteract: Date.now(), W: 1, H: 1, orbit: { theta: 0.72, phi: 1.12, radius: 260, target: new THREE.Vector3() },
  drag: null, lastTap: null, glowTex: null
};

function colorOf(n) {
  if (n.color) return n.color;
  if (n.kind === 'community') {
    return COMM_COLORS[(Number(n.community || 0) + 3) % COMM_COLORS.length];
  }
  return TYPE_COLORS[n.class] || TYPE_COLORS[n.type] || '#94a3b8';
}
function radiusOf(n) {
  if (n.kind === 'community') return 8 + Math.min(18, Math.sqrt(Math.max(1, n.size || 1)) * 0.72);
  if (n.kind === 'type') return 8 + Math.min(14, Math.sqrt(Math.max(1, n.size || 1)) * 0.34);
  return 2.2 + Math.min(5.5, Math.sqrt(Math.max(1, n.degree || 1)) * 0.34);
}
function short(s, n) {
  s = String(s == null ? '' : s);
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

function glowTexture() {
  if (S.glowTex) return S.glowTex;
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(64, 64, 2, 64, 64, 64);
  grad.addColorStop(0, 'rgba(255,255,255,.95)');
  grad.addColorStop(.28, 'rgba(255,255,255,.55)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  S.glowTex = new THREE.CanvasTexture(c);
  return S.glowTex;
}

function init() {
  if (S.inited) return;
  S.canvas = document.getElementById('kg3d');
  S.labels = document.getElementById('kg-labels');
  S.tip = document.getElementById('kg-tip');
  S.stage = document.getElementById('kg-stage') || S.canvas.parentElement;
  if (!S.canvas) throw new Error('no graph canvas');
  S.renderer = new THREE.WebGLRenderer({ canvas: S.canvas, antialias: true, alpha: true });
  S.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  S.renderer.setClearColor(0x07090c, 1);
  S.renderer.toneMapping = THREE.ACESFilmicToneMapping;
  S.renderer.toneMappingExposure = 1.35;
  if ('outputColorSpace' in S.renderer) S.renderer.outputColorSpace = THREE.SRGBColorSpace;
  S.scene = new THREE.Scene();
  S.scene.fog = new THREE.FogExp2(0x07090c, 0.00045);
  S.camera = new THREE.PerspectiveCamera(38, 1, 1, 8000);
  S.group = new THREE.Group();
  S.scene.add(S.group);
  S.raycaster = new THREE.Raycaster();
  const mc = document.createElement('canvas');
  S.measureCtx = mc.getContext('2d');
  S.scene.add(new THREE.AmbientLight(0xffffff, 1.4));
  const key = new THREE.DirectionalLight(0xffffff, 3.2);
  key.position.set(180, 240, 220);
  S.scene.add(key);
  const rim = new THREE.PointLight(0x3b82f6, 1800, 1600);
  rim.position.set(-260, -160, -220);
  S.scene.add(rim);
  const warm = new THREE.PointLight(0xf59e0b, 1400, 1400);
  warm.position.set(260, -120, 160);
  S.scene.add(warm);
  const starGeo = new THREE.BufferGeometry();
  const starPos = new Float32Array(1100 * 3);
  for (let i = 0; i < 1100; i++) {
    const r = 700 + Math.random() * 1400;
    const th = Math.random() * Math.PI * 2;
    const ph = Math.acos(2 * Math.random() - 1);
    starPos[i * 3] = r * Math.sin(ph) * Math.cos(th);
    starPos[i * 3 + 1] = r * Math.cos(ph);
    starPos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
  }
  starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
  S.stars = new THREE.Points(starGeo, new THREE.PointsMaterial({
    color: 0x64748b, size: 2.2, transparent: true, opacity: 0.8, sizeAttenuation: true
  }));
  S.scene.add(S.stars);
  bindControls();
  new ResizeObserver(resize).observe(S.stage);
  resize();
  S.inited = true;
}

function resize() {
  if (!S.renderer || !S.stage) return;
  const r = S.stage.getBoundingClientRect();
  S.W = Math.max(320, r.width);
  S.H = Math.max(260, r.height);
  S.camera.aspect = S.W / S.H;
  S.camera.updateProjectionMatrix();
  S.renderer.setSize(S.W, S.H, false);
}

function clearScene() {
  for (const m of S.meshes) {
    if (m.material) m.material.dispose();
    S.group.remove(m);
  }
  for (const g of S.glows) S.group.remove(g);
  for (const h of S.hits) {
    if (h.material) h.material.dispose();
    S.group.remove(h);
  }
  if (S.lineMesh) {
    S.group.remove(S.lineMesh);
    S.lineMesh.geometry.dispose();
    S.lineMesh.material.dispose();
    S.lineMesh = null;
  }
  S.meshes = [];
  S.glows = [];
  S.hits = [];
  if (S.labels) S.labels.innerHTML = '';
  S.labelEls.clear();
  S.hitEls.clear();
}

function fibonacci(i, n, radius) {
  const y = 1 - (i / Math.max(1, n - 1)) * 2;
  const r = Math.sqrt(Math.max(0, 1 - y * y));
  const phi = i * 2.399963229728653;
  return new THREE.Vector3(Math.cos(phi) * r * radius, y * radius, Math.sin(phi) * r * radius);
}

export async function show(data, opts = {}) {
  init();
  S.opts = opts;
  S.paused = true;
  cancelAnimationFrame(S.raf);
  S.raf = 0;
  S.selected = null;
  S.hovered = null;
  S.hidden = new Set();
  S.visibleLabels = new Set();
  clearScene();
  const raw = data.nodes || [];
  S.nodes = raw.map((n, i) => ({ ...n, color: colorOf(n), r: radiusOf(n), pos: new THREE.Vector3() }));
  S.byId = new Map(S.nodes.map(n => [n.id, n]));
  const links = (data.links || []).map(l => ({ ...l, s: S.byId.get(l.source), t: S.byId.get(l.target) }))
    .filter(l => l.s && l.t);
  S.links = links;
  const isSpread = data.mode === 'types' || data.mode === 'communities';
  if (isSpread) {
    const R = Math.max(210, S.nodes.length * (data.mode === 'communities' ? 20 : 22));
    S.nodes.forEach((n, i) => {
      const a = (i / Math.max(1, S.nodes.length)) * Math.PI * 2;
      n.pos.set(Math.cos(a) * R, Math.sin(i * 1.7) * 38, Math.sin(a) * R);
    });
  } else {
    const spreadRadius = 60 + Math.sqrt(S.nodes.length) * 16;
    S.nodes.forEach((n, i) => n.pos.copy(fibonacci(i, S.nodes.length, spreadRadius)));
  }
  S.top = new Set(isSpread ? S.nodes.map(n => n.id)
    : [...S.nodes].sort((a, b) => (b.degree || 0) - (a.degree || 0)).slice(0, 14).map(n => n.id));
  if (data.center) S.top.add(data.center);

  const sphere = new THREE.SphereGeometry(1, 22, 16);
  const glow = glowTexture();
  const labelFrag = document.createDocumentFragment();
  for (const n of S.nodes) {
    const mat = new THREE.MeshStandardMaterial({
      color: n.color, emissive: n.color, emissiveIntensity: 0.95,
      roughness: 0.26, metalness: 0.28, transparent: true, opacity: 0.98
    });
    const mesh = new THREE.Mesh(sphere, mat);
    mesh.position.copy(n.pos);
    mesh.scale.setScalar(n.r);
    mesh.userData.id = n.id;
    S.group.add(mesh);
    S.meshes.push(mesh);
    const sm = new THREE.SpriteMaterial({
      map: glow, color: n.color, transparent: true, opacity: 0.6,
      blending: THREE.AdditiveBlending, depthWrite: false
    });
    const sprite = new THREE.Sprite(sm);
    sprite.position.copy(n.pos);
    sprite.scale.setScalar(n.r * 4.8);
    S.group.add(sprite);
    S.glows.push(sprite);
    const hit = new THREE.Mesh(sphere, new THREE.MeshBasicMaterial({
      transparent: true, opacity: 0, depthWrite: false
    }));
    hit.position.copy(n.pos);
    hit.scale.setScalar(Math.max(n.r * 1.7, 5.5));
    hit.userData.id = n.id;
    S.group.add(hit);
    S.hits.push(hit);
    if (S.labels) {
      const el = document.createElement('span');
      el.className = 'kg3d-label ' + (n.kind || 'entity');
      el.dataset.id = n.id;
      el.textContent = n.kind === 'entity' ? short(n.title, 28)
        : `${short(n.label || n.title, 24)} · ${n.size || ''}`.trim();
      el.addEventListener('pointerdown', e => e.stopPropagation());
      el.addEventListener('click', e => { e.stopPropagation(); S.opts.onSelect && S.opts.onSelect(n.id); });
      el.addEventListener('dblclick', e => { e.stopPropagation(); S.opts.onOpen && S.opts.onOpen(n); });
      labelFrag.appendChild(el);
      S.labelEls.set(n.id, el);
      const hit = document.createElement('span');
      hit.className = 'kg3d-hit';
      hit.dataset.id = n.id;
      hit.style.width = hit.style.height = (n.kind === 'entity' ? 24 : 38) + 'px';
      hit.addEventListener('pointerdown', e => e.stopPropagation());
      hit.addEventListener('click', e => { e.stopPropagation(); S.opts.onSelect && S.opts.onSelect(n.id); });
      hit.addEventListener('dblclick', e => { e.stopPropagation(); S.opts.onOpen && S.opts.onOpen(n); });
      labelFrag.appendChild(hit);
      S.hitEls.set(n.id, hit);
    }
  }
  if (S.labels) S.labels.appendChild(labelFrag);

  const pos = new Float32Array(links.length * 6);
  const col = new Float32Array(links.length * 6);
  S.linePos = pos;
  S.lineColors = col;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  const lmat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.62 });
  S.lineMesh = new THREE.LineSegments(geo, lmat);
  S.group.add(S.lineMesh);
  paintLines(null, null);
  S.alpha = isSpread ? 0 : 1;
  S.fitted = isSpread;
  fit();
  S.paused = false;
  if (!S.raf) animate();
  return { nodes: S.nodes.length, links: links.length };
}

export function select(id) {
  S.selected = id;
  const n = S.byId.get(id);
  if (!n) return;
  const neigh = new Set([id]);
  for (const l of S.links) {
    if (l.source === id) neigh.add(l.target);
    else if (l.target === id) neigh.add(l.source);
  }
  S.meshes.forEach((m, i) => {
    const nn = S.nodes[i], active = neigh.has(nn.id);
    m.material.opacity = active ? 1 : 0.14;
    m.material.emissiveIntensity = nn.id === id ? 1.1 : active ? 0.5 : 0.08;
    m.scale.setScalar(nn.r * (nn.id === id ? 1.35 : 1));
  });
  S.glows.forEach((g, i) => {
    const nn = S.nodes[i];
    g.material.opacity = neigh.has(nn.id) ? (nn.id === id ? 0.8 : 0.36) : 0.04;
  });
  paintLines(id, neigh);
  updateLabels(neigh);
}

export function clearSelection() {
  S.selected = null;
  S.meshes.forEach((m, i) => {
    m.material.opacity = 0.98;
    m.material.emissiveIntensity = 0.95;
    m.scale.setScalar(S.nodes[i].r);
  });
  S.glows.forEach(g => { g.material.opacity = 0.6; });
  paintLines(null, null);
  updateLabels(null);
}

export function setHiddenTypes(types) {
  S.hidden = new Set(types || []);
  S.meshes.forEach((m, i) => {
    const hidden = S.hidden.has(S.nodes[i].type);
    m.visible = !hidden;
    if (S.glows[i]) S.glows[i].visible = !hidden;
    if (S.hits[i]) S.hits[i].visible = !hidden;
  });
  S.links.forEach((l, i) => { /* line visibility handled by positions below */ });
  updateLabels(S.selected ? new Set([S.selected]) : null);
}

export function fit() {
  if (!S.nodes.length) return;
  const box = new THREE.Box3();
  S.nodes.forEach(n => box.expandByPoint(n.pos));
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3()).length() || 120;
  S.orbit.target.copy(center);
  S.orbit.radius = Math.max(85, size * 0.82);
  S.orbit.theta = 0.72;
  S.orbit.phi = 1.12;
  applyCamera();
}

export function screenOf(id) {
  const n = S.byId.get(id); if (!n) return null;
  const p = n.pos.clone().project(S.camera);
  return { x: (p.x * 0.5 + 0.5) * S.W, y: (-p.y * 0.5 + 0.5) * S.H };
}

export function pause() {
  S.paused = true;
  cancelAnimationFrame(S.raf);
  S.raf = 0;
}

export function resume() {
  if (S.inited && !S.raf) { S.paused = false; animate(); }
}

function applyCamera() {
  const o = S.orbit;
  const sp = Math.sin(o.phi), cp = Math.cos(o.phi);
  S.camera.position.set(
    o.target.x + o.radius * sp * Math.sin(o.theta),
    o.target.y + o.radius * cp,
    o.target.z + o.radius * sp * Math.cos(o.theta)
  );
  S.camera.lookAt(o.target);
}

function pointerNdc(e) {
  const r = S.canvas.getBoundingClientRect();
  return { x: ((e.clientX - r.left) / r.width) * 2 - 1,
           y: -((e.clientY - r.top) / r.height) * 2 + 1 };
}

function pick(e) {
  const p = pointerNdc(e);
  S.raycaster.setFromCamera(p, S.camera);
  const hits = S.raycaster.intersectObjects(S.hits.filter(m => m.visible), false);
  return hits.length ? S.byId.get(hits[0].object.userData.id) : null;
}

function bindControls() {
  const c = S.canvas;
  c.addEventListener('contextmenu', e => e.preventDefault());
  c.addEventListener('pointerdown', e => {
    S.lastInteract = Date.now();
    try { c.setPointerCapture(e.pointerId); } catch (_) {}
    S.drag = { x: e.clientX, y: e.clientY, mode: (e.button === 2 || e.shiftKey) ? 'pan' : 'rotate', moved: false };
  });
  c.addEventListener('pointermove', e => {
    if (!S.drag) {
      const n = pick(e);
      if (n && n.id !== S.hovered) {
        S.hovered = n.id;
        c.style.cursor = 'pointer';
        showTip(n, e);
      } else if (!n && S.hovered) {
        S.hovered = null;
        c.style.cursor = 'grab';
        hideTip();
      }
      return;
    }
    const dx = e.clientX - S.drag.x, dy = e.clientY - S.drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) S.drag.moved = true;
    if (S.drag.mode === 'rotate') {
      S.orbit.theta -= dx * 0.006;
      S.orbit.phi = Math.max(0.12, Math.min(Math.PI - 0.12, S.orbit.phi - dy * 0.006));
    } else {
      const scale = S.orbit.radius * 0.0016;
      const right = new THREE.Vector3().setFromMatrixColumn(S.camera.matrix, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(S.camera.matrix, 1);
      S.orbit.target.addScaledVector(right, -dx * scale).addScaledVector(up, dy * scale);
    }
    S.drag.x = e.clientX; S.drag.y = e.clientY;
    applyCamera();
  });
  const up = e => {
    const d = S.drag;
    S.drag = null;
    if (!d || d.moved) return;
    const n = pick(e);
    if (n) {
      const now = Date.now();
      if (S.lastTap && S.lastTap.id === n.id && now - S.lastTap.t < 360) {
        S.lastTap = null;
        S.opts.onOpen && S.opts.onOpen(n);
      } else {
        S.lastTap = { id: n.id, t: now };
        S.opts.onSelect && S.opts.onSelect(n.id);
      }
    } else {
      S.opts.onClear && S.opts.onClear();
    }
  };
  c.addEventListener('pointerup', up);
  c.addEventListener('pointercancel', () => { S.drag = null; });
  c.addEventListener('wheel', e => {
    e.preventDefault();
    S.lastInteract = Date.now();
    S.orbit.radius = Math.max(30, Math.min(1600, S.orbit.radius * Math.exp(e.deltaY * 0.0012)));
    applyCamera();
  }, { passive: false });
}

function showTip(n, e) {
  if (!S.tip) return;
  S.tip.classList.remove('hide');
  S.tip.innerHTML = `<b>${escapeHtml(n.title || n.label)}</b><span>${escapeHtml(
    n.kind === 'entity' ? `${n.class_label || n.type} · degree ${n.degree}`
      : `${n.kind === 'community' ? 'Community' : 'Topic'} · ${n.size} entities`
  )}</span>`;
  const r = S.stage.getBoundingClientRect();
  S.tip.style.left = (e.clientX - r.left + 14) + 'px';
  S.tip.style.top = (e.clientY - r.top + 14) + 'px';
}
function hideTip() { if (S.tip) S.tip.classList.add('hide'); }
function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function paintLines(selected, neigh) {
  if (!S.lineMesh) return;
  const pos = S.linePos, col = S.lineColors;
  const accent = new THREE.Color(ACCENT), dim = new THREE.Color(DIM), base = new THREE.Color(0x64748b);
  S.links.forEach((l, i) => {
    const hot = selected && (l.source === selected || l.target === selected);
    const active = !selected || (neigh && (neigh.has(l.source) || neigh.has(l.target)));
    const c = hot ? accent : active ? base : dim;
    col[i * 6] = c.r; col[i * 6 + 1] = c.g; col[i * 6 + 2] = c.b;
    col[i * 6 + 3] = c.r; col[i * 6 + 4] = c.g; col[i * 6 + 5] = c.b;
  });
  S.lineMesh.geometry.attributes.color.needsUpdate = true;
}

function labelWidth(text, size) {
  if (!S.measureCtx) return text.length * size * 0.58;
  S.measureCtx.font = `600 ${size}px ui-sans-serif, system-ui, sans-serif`;
  return S.measureCtx.measureText(text).width + 12;
}

function updateLabels(neigh) {
  if (!S.labels) return;
  S.labels.style.display = 'block';
  const W = S.W, H = S.H;
  const fov = THREE.MathUtils.degToRad(S.camera.fov);
  const proj = H / (2 * Math.tan(fov / 2));
  const candidates = [];
  S.nodes.forEach(n => {
    if (S.hidden.has(n.type)) return;
    const el = S.labelEls.get(n.id);
    if (!el) return;
    let score = 50;
    if (n.id === S.selected) score = 0;
    else if (n.id === S.hovered) score = 1;
    else if (neigh && neigh.has(n.id)) score = 3;
    else if (n.kind === 'community' || n.kind === 'type') score = 5;
    else score = 20 + (S.top.has(n.id) ? 0 : 20) - Math.min(15, (n.degree || 0) * 0.15);
    if (S.visibleLabels.has(n.id)) score -= 4;        // hysteresis: keep what was readable
    candidates.push({ n, el, score });
  });
  candidates.sort((a, b) => a.score - b.score);
  const placed = [];
  const visible = new Set();
  const margin = 3;
  for (const { n, el } of candidates) {
    const p = n.pos.clone().project(S.camera);
    if (p.z > 1 || p.z < -1) { el.style.display = 'none'; continue; }
    const cx = (p.x * 0.5 + 0.5) * W;
    const cy = (-p.y * 0.5 + 0.5) * H;
    const dist = Math.max(1, S.camera.position.distanceTo(n.pos));
    const sr = n.r * proj / dist;
    const size = Math.max(9, Math.min(n.kind === 'entity' ? 13 : 16, sr * 0.55 + 7));
    el.style.fontSize = size + 'px';
    const text = el.textContent || '';
    const w = labelWidth(text, size);
    const h = size * 1.35 + 4;
    const spots = [
      { left: cx, top: cy + sr + 7 },                  // below
      { left: cx, top: cy - sr - 7 - h },              // above
      { left: cx + sr + 8 + w / 2, top: cy - h / 2 },  // right
      { left: cx - sr - 8 - w / 2, top: cy - h / 2 }   // left
    ];
    let chosen = null;
    for (const spot of spots) {
      const rect = { x: spot.left - w / 2, y: spot.top, w, h };
      if (rect.x < 2 || rect.y < 2 || rect.x + w > W - 2 || rect.y + h > H - 2) continue;
      const hit = placed.some(r => !(rect.x + w < r.x - margin || rect.x > r.x + r.w + margin ||
        rect.y + h < r.y - margin || rect.y > r.y + r.h + margin));
      if (!hit) { chosen = { spot, rect }; break; }
    }
    if (!chosen) { el.style.display = 'none'; continue; }
    el.style.left = chosen.spot.left + 'px';
    el.style.top = chosen.spot.top + 'px';
    el.style.display = '';
    placed.push(chosen.rect);
    visible.add(n.id);
  }
  S.visibleLabels = visible;
}

function step() {
  if (S.alpha < 0.015) return;
  const isSpread = S.nodes.some(n => n.kind === 'community' || n.kind === 'type');
  const alpha = S.alpha;
  const N = S.nodes;
  const rep = isSpread ? 62000 : 12000;
  for (let i = 0; i < N.length; i++) {
    const a = N[i];
    for (let j = i + 1; j < N.length; j++) {
      const b = N[j];
      let dx = b.pos.x - a.pos.x, dy = b.pos.y - a.pos.y, dz = b.pos.z - a.pos.z;
      let d2 = dx * dx + dy * dy + dz * dz;
      if (d2 < 1) { dx = Math.random() - .5; dy = Math.random() - .5; dz = Math.random() - .5; d2 = 1; }
      const d = Math.sqrt(d2);
      const min = a.r + b.r + (isSpread ? 34 : 12);
      const f = (rep / (d2 + 240) + (d < min ? (min - d) * 2.2 : 0)) * alpha;
      const fx = dx / d * f, fy = dy / d * f, fz = dz / d * f;
      a.pos.x -= fx; a.pos.y -= fy; a.pos.z -= fz;
      b.pos.x += fx; b.pos.y += fy; b.pos.z += fz;
    }
  }
  for (const l of S.links) {
    const a = l.s.pos, b = l.t.pos;
    let dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
    const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
    const target = isSpread ? 160 : 48;
    const f = (d - target) * (isSpread ? 0.010 : 0.016) * alpha;
    const fx = dx / d * f, fy = dy / d * f, fz = dz / d * f;
    a.x += fx; a.y += fy; a.z += fz;
    b.x -= fx; b.y -= fy; b.z -= fz;
  }
  const center = new THREE.Vector3();
  S.nodes.forEach(n => center.add(n.pos));
  center.multiplyScalar(1 / Math.max(1, N.length));
  S.nodes.forEach(n => {
    n.pos.x += (center.x - n.pos.x) * (isSpread ? 0.010 : 0.018);
    n.pos.y += (center.y - n.pos.y) * (isSpread ? 0.010 : 0.018);
    n.pos.z += (center.z - n.pos.z) * (isSpread ? 0.010 : 0.018);
  });
  S.alpha *= 0.985;
}

function updateScene() {
  S.meshes.forEach((m, i) => { m.position.copy(S.nodes[i].pos); });
  S.glows.forEach((g, i) => { g.position.copy(S.nodes[i].pos); });
  S.hits.forEach((h, i) => { h.position.copy(S.nodes[i].pos); });
  if (S.lineMesh) {
    const pos = S.linePos;
    S.links.forEach((l, i) => {
      pos[i * 6] = l.s.pos.x; pos[i * 6 + 1] = l.s.pos.y; pos[i * 6 + 2] = l.s.pos.z;
      pos[i * 6 + 3] = l.t.pos.x; pos[i * 6 + 4] = l.t.pos.y; pos[i * 6 + 5] = l.t.pos.z;
    });
    S.lineMesh.geometry.attributes.position.needsUpdate = true;
  }
  updateLabels(S.selected ? new Set(neighborSet(S.selected)) : null);
}

function neighborSet(id) {
  const out = new Set([id]);
  for (const l of S.links) {
    if (l.source === id) out.add(l.target);
    else if (l.target === id) out.add(l.source);
  }
  return out;
}

function animate() {
  S.raf = requestAnimationFrame(animate);
  if (S.paused || !S.renderer) return;
  if (S.alpha > 0.015) step();
  if (!S.fitted && S.alpha <= 0.05) { S.fitted = true; fit(); }
  updateScene();
  S.renderer.render(S.scene, S.camera);
}

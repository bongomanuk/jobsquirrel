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
  visibleLabels: new Set(), labelAnchors: new Map(), measureCtx: null,
  interacting: false, interactTimer: 0, lastLabelRelayout: 0, labelDirty: true,
  linePos: null, lineColors: null, labelEls: new Map(), top: new Set(),
  selected: null, hovered: null, hidden: new Set(), opts: {}, paused: true,
  raf: 0, alpha: 1, fitted: false, focusDepth: 1, hitEls: new Map(), lastInteract: Date.now(), W: 1, H: 1, orbit: { theta: 0.72, phi: 1.12, radius: 260, target: new THREE.Vector3() },
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
  return 2.2 + Math.min(5.5, Math.sqrt(Math.max(1, n.degree || 1)) * 0.34)
    + (Number(n.importance) || 0) * 7;
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

let SOFT_TEX = null;
function softTexture() {
  if (SOFT_TEX) return SOFT_TEX;
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, 'rgba(255,255,255,.62)');
  grad.addColorStop(.34, 'rgba(255,255,255,.2)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
  SOFT_TEX = new THREE.CanvasTexture(c);
  return SOFT_TEX;
}

function pointMaterial(map, sizeMul, alphaMul) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uMap: { value: map }, uPixel: { value: 900 },
      uSize: { value: sizeMul }, uAlpha: { value: alphaMul },
      uFog: { value: 0.001 }
    },
    vertexShader: `
      attribute float size;
      attribute float alpha;
      attribute vec3 color;
      varying vec3 vColor;
      varying float vAlpha;
      uniform float uPixel;
      uniform float uSize;
      uniform float uFog;
      varying float vFade;
      void main() {
        vColor = color;
        vAlpha = alpha;
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = clamp(size * uSize * uPixel / max(1.0, -mv.z), 1.5, 380.0);
        float d = max(0.0, -mv.z) * uFog;
        vFade = exp(-d * d);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform sampler2D uMap;
      uniform float uAlpha;
      varying vec3 vColor;
      varying float vAlpha;
      varying float vFade;
      void main() {
        vec4 t = texture2D(uMap, gl_PointCoord);
        float a = t.a * vAlpha * uAlpha * vFade;
        if (a < 0.01) discard;
        gl_FragColor = vec4(vColor * t.rgb * vFade, a);
      }`,
    transparent: true, depthWrite: false, depthTest: true,
    blending: THREE.AdditiveBlending
  });
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
  S.renderer.setClearColor(0x05070c, 1);
  S.renderer.toneMapping = THREE.ACESFilmicToneMapping;
  S.renderer.toneMappingExposure = 1.35;
  if ('outputColorSpace' in S.renderer) S.renderer.outputColorSpace = THREE.SRGBColorSpace;
  S.scene = new THREE.Scene();
  S.scene.background = new THREE.Color(0x05070c);
  S.scene.fog = new THREE.FogExp2(0x05070c, 0.0003);
  S.camera = new THREE.PerspectiveCamera(38, 1, 1, 12000);
  S.group = new THREE.Group();
  S.scene.add(S.group);
  S.raycaster = new THREE.Raycaster();
  S.lastUser = 0;
  S.marker = new THREE.Sprite(new THREE.SpriteMaterial({
    map: glowTexture(), color: new THREE.Color('#fbbf24'), transparent: true,
    opacity: 0.85, depthWrite: false, blending: THREE.AdditiveBlending
  }));
  S.marker.visible = false;
  S.scene.add(S.marker);
  const mc = document.createElement('canvas');
  S.measureCtx = mc.getContext('2d');
  const starGeo = new THREE.BufferGeometry();
  const NSTAR = 1900, starPos = new Float32Array(NSTAR * 3), starCol = new Float32Array(NSTAR * 3);
  for (let i = 0; i < NSTAR; i++) {
    const r = 900 + Math.random() * 2400;
    const th = Math.random() * Math.PI * 2;
    const ph = Math.acos(2 * Math.random() - 1);
    starPos[i * 3] = r * Math.sin(ph) * Math.cos(th);
    starPos[i * 3 + 1] = r * Math.cos(ph);
    starPos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
    const c = new THREE.Color().setHSL(0.52 + Math.random() * 0.16, 0.35, 0.6 + Math.random() * 0.3);
    starCol[i * 3] = c.r; starCol[i * 3 + 1] = c.g; starCol[i * 3 + 2] = c.b;
  }
  starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
  starGeo.setAttribute('color', new THREE.BufferAttribute(starCol, 3));
  S.stars = new THREE.Points(starGeo, new THREE.PointsMaterial({
    size: 7, vertexColors: true, map: glowTexture(), transparent: true,
    opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
  }));
  S.scene.add(S.stars);
  // faint deep-space clouds behind the graph
  const bg = new THREE.Group();
  ['#1d4ed8', '#7c3aed', '#0e7490', '#be123c'].forEach((tint, i) => {
    const m = new THREE.SpriteMaterial({
      map: softTexture(), color: new THREE.Color(tint), transparent: true,
      opacity: 0.07, depthWrite: false, blending: THREE.AdditiveBlending
    });
    const sp = new THREE.Sprite(m);
    const a = i * 1.57, r = 1400;
    sp.position.set(Math.cos(a) * r, (i % 2 ? -1 : 1) * 500, Math.sin(a) * r);
    sp.scale.setScalar(1800 + i * 220);
    bg.add(sp);
  });
  S.backdrop = bg;
  S.scene.add(bg);
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
  const px = S.renderer.domElement.height / (2 * Math.tan(THREE.MathUtils.degToRad(S.camera.fov) / 2));
  [S.core, S.halo].forEach(p => { if (p) { p.material.uniforms.uPixel.value = px; } });
  applyCamera();
}

function clearScene() {
  for (const h of S.hits) {
    if (h.geometry) h.geometry.dispose();
    if (h.material) h.material.dispose();
    S.group.remove(h);
  }
  if (S.nebulae) {
    S.nebulae.traverse(o => { if (o.material) o.material.dispose(); });
    S.group.remove(S.nebulae); S.nebulae = null;
  }
  if (S.impact) { S.group.remove(S.impact); S.impact.geometry.dispose(); S.impact.material.dispose(); S.impact = null; }
  if (S.core) { S.group.remove(S.core); S.core = null; }
  if (S.halo) { S.group.remove(S.halo); S.halo = null; }
  if (S.ptGeo) { S.ptGeo.dispose(); S.ptGeo = null; }
  if (S.lineMesh) {
    S.group.remove(S.lineMesh);
    S.lineMesh.geometry.dispose();
    S.lineMesh.material.dispose();
    S.lineMesh = null;
  }
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
  S.selDist = null;
  if (S.marker) S.marker.visible = false;
  if (S.impact) S.impact.visible = true;
  S.hidden = new Set();
  S.visibleLabels = new Set();
  S.labelAnchors = new Map();
  S.interacting = false;
  S.labelDirty = true;
  clearTimeout(S.interactTimer);
  clearScene();
  const raw = data.nodes || [];
  S.nodes = raw.map((n, i) => ({ ...n, color: colorOf(n), r: radiusOf(n), pos: new THREE.Vector3() }));
  S.byId = new Map(S.nodes.map(n => [n.id, n]));
  const links = (data.links || []).map(l => ({ ...l, s: S.byId.get(l.source), t: S.byId.get(l.target) }))
    .filter(l => l.s && l.t);
  S.links = links;
  const isSpread = data.mode === 'types' || data.mode === 'communities';
  if (isSpread) {
    // a shallow 3D shell rather than a flat ring: it reads as a constellation
    const R = Math.max(300, 130 + Math.sqrt(S.nodes.length) * (data.mode === 'communities' ? 58 : 52));
    S.nodes.forEach((n, i) => {
      n.pos.copy(fibonacci(i, S.nodes.length, R));
      n.pos.y *= 0.92;
      const j = 0.82 + ((i * 37) % 29) / 29 * 0.36;   // uneven radii give depth
      n.pos.multiplyScalar(j);
      n.pos.x += ((i * 13) % 9 - 4) * 4;
      n.pos.z += ((i * 17) % 11 - 5) * 4;
    });
  } else {
    const spreadRadius = 60 + Math.sqrt(S.nodes.length) * 16;
    S.nodes.forEach((n, i) => n.pos.copy(fibonacci(i, S.nodes.length, spreadRadius)));
  }
  S.top = new Set(isSpread ? S.nodes.map(n => n.id)
    : [...S.nodes].sort((a, b) => (b.degree || 0) - (a.degree || 0)).slice(0, 14).map(n => n.id));
  if (data.center) S.top.add(data.center);

  // one geometry shared by the core and halo point clouds
  const N = S.nodes.length;
  const gpos = new Float32Array(N * 3), gcol = new Float32Array(N * 3);
  const gsize = new Float32Array(N), galpha = new Float32Array(N);
  S.nodes.forEach((n, i) => {
    gpos[i * 3] = n.pos.x; gpos[i * 3 + 1] = n.pos.y; gpos[i * 3 + 2] = n.pos.z;
    const c = new THREE.Color(n.color);
    gcol[i * 3] = c.r; gcol[i * 3 + 1] = c.g; gcol[i * 3 + 2] = c.b;
    gsize[i] = n.r;
    galpha[i] = 1;
  });
  const pgeo = new THREE.BufferGeometry();
  pgeo.setAttribute('position', new THREE.BufferAttribute(gpos, 3));
  pgeo.setAttribute('color', new THREE.BufferAttribute(gcol, 3));
  pgeo.setAttribute('size', new THREE.BufferAttribute(gsize, 1));
  pgeo.setAttribute('alpha', new THREE.BufferAttribute(galpha, 1));
  S.ptGeo = pgeo;
  S.halo = new THREE.Points(pgeo, pointMaterial(softTexture(), 6.0, 0.4));
  S.halo.frustumCulled = false;
  S.halo.renderOrder = 1;
  S.group.add(S.halo);
  S.core = new THREE.Points(pgeo, pointMaterial(glowTexture(), 1.35, 1.0));
  S.core.frustumCulled = false;
  S.core.renderOrder = 2;
  S.group.add(S.core);

  // high-impact landmarks get a warm beacon so impact is visible, not just inferred
  const landmarks = S.nodes.filter(n => (Number(n.importance) || 0) >= 0.95);
  S.impactNodes = landmarks;
  if (landmarks.length) {
    const ip = new Float32Array(landmarks.length * 3);
    landmarks.forEach((n, i) => { ip[i * 3] = n.pos.x; ip[i * 3 + 1] = n.pos.y; ip[i * 3 + 2] = n.pos.z; });
    const ig = new THREE.BufferGeometry();
    ig.setAttribute('position', new THREE.BufferAttribute(ip, 3));
    S.impact = new THREE.Points(ig, new THREE.PointsMaterial({
      size: 20, color: 0xfbbf24, map: glowTexture(), transparent: true,
      opacity: 0.85, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
    }));
    S.impact.frustumCulled = false;
    S.group.add(S.impact);
  }

  // island nebulae in the spread views (communities/topics)
  if (isSpread) {
    const neb = new THREE.Group();
    for (const n of S.nodes) {
      if (n.kind !== 'community' && n.kind !== 'type') continue;
      const m = new THREE.SpriteMaterial({
        map: softTexture(), color: new THREE.Color(n.color), transparent: true,
        opacity: 0.34, depthWrite: false, blending: THREE.AdditiveBlending
      });
      const sp = new THREE.Sprite(m);
      sp.position.copy(n.pos);
      sp.scale.setScalar(Math.max(210, n.r * 12));
      sp.userData.baseOpacity = 0.34;
      neb.add(sp);
    }
    S.nebulae = neb;
    S.group.add(neb);
  } else {
    const groups = new Map();
    for (const n of S.nodes) {
      const key = n.community != null ? 'c' + n.community : 't' + (n.class || n.type || 'x');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(n);
    }
    const neb = new THREE.Group();
    for (const list of groups.values()) {
      if (list.length < 3) continue;
      const center = new THREE.Vector3();
      list.forEach(n => center.add(n.pos));
      center.multiplyScalar(1 / list.length);
      const m = new THREE.SpriteMaterial({
        map: softTexture(), color: new THREE.Color(list[0].color), transparent: true,
        opacity: 0.13, depthWrite: false, blending: THREE.AdditiveBlending
      });
      const sp = new THREE.Sprite(m);
      sp.position.copy(center);
      sp.scale.setScalar(120 + Math.sqrt(list.length) * 28);
      sp.userData.baseOpacity = 0.13;
      neb.add(sp);
    }
    S.nebulae = neb;
    S.group.add(neb);
  }

  const labelFrag = document.createDocumentFragment();
  const bindLabel = (el, n) => {
    let tap = 0;
    el.addEventListener('pointerdown', e => e.stopPropagation());
    el.addEventListener('click', e => {
      e.stopPropagation();
      clearTimeout(tap);
      tap = setTimeout(() => { S.opts.onSelect && S.opts.onSelect(n.id); }, 240);
    });
    el.addEventListener('dblclick', e => {
      e.stopPropagation();
      clearTimeout(tap);
      S.opts.onOpen && S.opts.onOpen(n);
    });
  };
  for (const n of S.nodes) {
    const hit = new THREE.Mesh(new THREE.SphereGeometry(1, 10, 8),
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
    hit.position.copy(n.pos);
    hit.scale.setScalar(Math.max(n.r * 1.8, 5.5));
    hit.userData.id = n.id;
    S.group.add(hit);
    S.hits.push(hit);
    if (S.labels) {
      const el = document.createElement('span');
      el.className = 'kg3d-label ' + (n.kind || 'entity') + (n.grounded ? ' grounded' : '');
      el.dataset.id = n.id;
      el.textContent = n.kind === 'entity' ? short(n.title, 28)
        : `${short(n.label || n.title, 24)} · ${n.size || ''}`.trim();
      bindLabel(el, n);
      labelFrag.appendChild(el);
      S.labelEls.set(n.id, el);
      const hitEl = document.createElement('span');
      hitEl.className = 'kg3d-hit';
      hitEl.dataset.id = n.id;
      hitEl.style.width = hitEl.style.height = (n.kind === 'entity' ? 24 : 38) + 'px';
      bindLabel(hitEl, n);
      labelFrag.appendChild(hitEl);
      S.hitEls.set(n.id, hitEl);
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
  const lmat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.2, depthWrite: false, blending: THREE.AdditiveBlending });
  S.lineMesh = new THREE.LineSegments(geo, lmat);
  S.group.add(S.lineMesh);
  S.lineMesh.material.opacity = 0.2;
  paintLines(null, null);
  S.alpha = isSpread ? 0 : 1;
  S.fitted = true;
  fit(isSpread ? 1.02 : 1.18);
  S.paused = false;
  if (!S.raf) animate();
  return { nodes: S.nodes.length, links: links.length };
}

function graphDistances(startId) {
  const adj = new Map();
  for (const l of S.links) {
    if (!adj.has(l.source)) adj.set(l.source, []);
    if (!adj.has(l.target)) adj.set(l.target, []);
    adj.get(l.source).push(l.target);
    adj.get(l.target).push(l.source);
  }
  const dist = new Map([[startId, 0]]);
  const q = [startId];
  while (q.length) {
    const x = q.shift();
    const d = dist.get(x);
    for (const y of (adj.get(x) || [])) {
      if (!dist.has(y)) { dist.set(y, d + 1); q.push(y); }
    }
  }
  return dist;
}

function nearSet(dist) {
  if (!dist) return null;
  return new Set([...dist.entries()].filter(([, d]) => d <= (S.focusDepth || 1)).map(([id]) => id));
}

function repaintNodes(id, dist) {
  if (!S.ptGeo) return;
  const alpha = S.ptGeo.attributes.alpha, size = S.ptGeo.attributes.size;
  S.nodes.forEach((n, i) => {
    const d = dist ? dist.get(n.id) : null;
    alpha.array[i] = S.hidden.has(n.type) ? 0
      : (!id ? 1 : (d == null ? 0.006 : d === 0 ? 1 : d <= (S.focusDepth || 1) ? (d === 1 ? 0.65 : Math.max(0.28, 0.50 - (d - 2) * 0.10)) : 0.02));
    size.array[i] = n.r * (n.id === id ? 1.6 : 1);
  });
  alpha.needsUpdate = true;
  size.needsUpdate = true;
}

export function select(id) {
  S.selected = id;
  const n = S.byId.get(id);
  if (!n) return;
  const dist = graphDistances(id);
  S.selDist = dist;
  if (S.impact) S.impact.visible = false;
  repaintNodes(id, dist);
  if (S.marker) {
    S.marker.visible = true;
    S.marker.position.copy(n.pos);
    S.marker.userData.base = Math.max(30, n.r * (n.kind === 'entity' ? 6.5 : 4.4));
    S.marker.scale.setScalar(S.marker.userData.base);
  }
  if (S.lineMesh) S.lineMesh.material.opacity = 0.34;
  paintLines(id, dist);
  S.labelDirty = true;
  updateLabels(nearSet(dist), true);
}

export function setFocusDepth(d) {
  S.focusDepth = Math.max(1, Math.min(3, +d || 1));
  if (S.selected) {
    S.selDist = graphDistances(S.selected);
    repaintNodes(S.selected, S.selDist);
    paintLines(S.selected, S.selDist);
    updateLabels(nearSet(S.selDist), true);
  }
}

export function clearSelection() {
  S.selected = null;
  S.selDist = null;
  if (S.impact) S.impact.visible = true;
  if (S.lineMesh) S.lineMesh.material.opacity = 0.2;
  if (S.marker) S.marker.visible = false;
  repaintNodes(null, null);
  paintLines(null, null);
  S.labelDirty = true;
  updateLabels(null, true);
}

export function setHiddenTypes(types) {
  S.hidden = new Set(types || []);
  S.hits.forEach((h, i) => { h.visible = !S.hidden.has(S.nodes[i].type); });
  repaintNodes(S.selected, S.selected ? (S.selDist || graphDistances(S.selected)) : null);
  S.labelDirty = true;
  updateLabels(S.selected ? new Set([S.selected]) : null, true);
}

export function fit(margin = 1.02) {
  if (!S.nodes.length) return;
  const box = new THREE.Box3();
  S.nodes.forEach(n => box.expandByPoint(n.pos));
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3()).length() || 120;
  S.orbit.target.copy(center);
  S.orbit.radius = Math.max(85, size * margin);
  S.homeRadius = S.orbit.radius;
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
  S.camera.updateMatrixWorld();
  const fog = 0.62 / Math.max(60, o.radius);
  [S.core, S.halo].forEach(p => { if (p) p.material.uniforms.uFog.value = fog; });
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
    S.lastUser = Date.now();
    S.interacting = true;
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
    S.interacting = false;
    // Keep the chosen sides after an orbit/pan: reassigning them here is what
    // made labels visibly jump at the end of a drag.
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
    S.lastUser = Date.now();
    S.interacting = true;
    clearTimeout(S.interactTimer);
    S.interactTimer = setTimeout(() => {
      S.interacting = false;
      S.labelDirty = true;
      updateLabels(S.selected ? nearSet(S.selDist || graphDistances(S.selected)) : null, true);
    }, 140);
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

function paintLines(selected, dist) {
  if (!S.lineMesh) return;
  const col = S.lineColors;
  const accent = new THREE.Color(ACCENT), base = new THREE.Color(0x93a4bd);
  const gold = new THREE.Color(0xfbbf24), dim = new THREE.Color(0x0b1220);
  S.links.forEach((l, i) => {
    const da = dist ? (dist.get(l.source) ?? 99) : 99;
    const db = dist ? (dist.get(l.target) ?? 99) : 99;
    const D = S.focusDepth || 1;
    let c;
    if (selected && (l.source === selected || l.target === selected)) c = accent;
    else if (l.grounded) c = gold.clone().multiplyScalar(dist ? ((da <= D && db <= D) ? 0.20 : 0.015) : 1);
    else if (dist) c = base.clone().multiplyScalar((da <= D && db <= D) ? 0.20 : 0.015);
    else c = base;
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

function labelSize(n, proj) {
  const dist = Math.max(1, S.camera.position.distanceTo(n.pos));
  const sr = n.r * proj / dist;
  const size = Math.max(9, Math.min(n.kind === 'entity' ? 13 : 16, sr * 0.55 + 7));
  return { size, sr, text: (S.labelEls.get(n.id) || {}).textContent || '' };
}

function labelSpot(mode, cx, cy, sr, w, h) {
  if (mode === 'below') return { left: cx, top: cy + sr + 7 };
  if (mode === 'above') return { left: cx, top: cy - sr - 7 - h };
  if (mode === 'right') return { left: cx + sr + 8 + w / 2, top: cy - h / 2 };
  return { left: cx - sr - 8 - w / 2, top: cy - h / 2 };
}

function placeLabel(n, el, mode, cx, cy, sr, size, w, h, W, H) {
  const spot = labelSpot(mode, cx, cy, sr, w, h);
  const rect = { x: spot.left - w / 2, y: spot.top, w, h };
  if (rect.x < 2 || rect.y < 2 || rect.x + w > W - 2 || rect.y + h > H - 2) return null;
  el.style.transform = `translate3d(${spot.left}px,${spot.top}px,0) translate(-50%,0)`;
  return rect;
}

function updateLabels(neigh, relayout = false) {
  if (!S.labels) return;
  S.camera.updateMatrixWorld();
  S.labels.style.display = 'block';
  const W = S.W, H = S.H;
  const fov = THREE.MathUtils.degToRad(S.camera.fov);
  const proj = H / (2 * Math.tan(fov / 2));

  if (!relayout) {
    // While the camera is moving, keep the chosen side and only move with
    // the node. This is what makes labels track instead of swapping sides.
    S.labelAnchors.forEach((a, id) => {
      const n = S.byId.get(id), el = S.labelEls.get(id);
      if (!n || !el) return;
      if (S.hidden.has(n.type) || (S.selDist && ((S.selDist.get(id) ?? 99) > (S.focusDepth || 1)))) { el.style.display = 'none'; return; }
      const p = n.pos.clone().project(S.camera);
      if (p.z > 1 || p.z < -1) { el.style.display = 'none'; return; }
      const cx = (p.x * 0.5 + 0.5) * W;
      const cy = (-p.y * 0.5 + 0.5) * H;
      const { sr } = labelSize(n, proj);
      el.style.fontSize = a.size + 'px';
      if (!placeLabel(n, el, a.mode, cx, cy, sr, a.size, a.w, a.h, W, H)) el.style.display = 'none';
      else el.style.display = '';
    });
    return;
  }

  const candidates = [];
  S.nodes.forEach(n => {
    if (S.hidden.has(n.type)) return;
    if (S.selDist && ((S.selDist.get(n.id) ?? 99) > (S.focusDepth || 1))) {
      const el = S.labelEls.get(n.id); if (el) el.style.display = 'none';
      return;
    }
    const el = S.labelEls.get(n.id);
    if (!el) return;
    let score = 50;
    if (n.id === S.selected) score = 0;
    else if (n.id === S.hovered) score = 1;
    else if (neigh && neigh.has(n.id)) score = 3;
    else if (n.kind === 'community' || n.kind === 'type') score = 5;
    else score = 20 + (S.top.has(n.id) ? 0 : 20) - Math.min(15, (n.degree || 0) * 0.15)
      - (Number(n.importance) || 0) * 12;
    if (S.visibleLabels.has(n.id)) score -= 4;
    candidates.push({ n, el, score });
  });
  candidates.sort((a, b) => a.score - b.score);
  const home = S.homeRadius || S.orbit.radius || 1;
  const k = S.orbit.radius / Math.max(1, home);
  const maxLabels = k > 1.15 ? 8 : k > 0.7 ? 14 : k > 0.4 ? 22 : 36;
  const placed = [];
  const visible = new Set();
  const anchors = new Map();
  const margin = 3;
  let shown = 0;
  for (const { n, el } of candidates) {
    if (shown >= maxLabels) { el.style.display = 'none'; continue; }
    const p = n.pos.clone().project(S.camera);
    if (p.z > 1 || p.z < -1) { el.style.display = 'none'; continue; }
    const cx = (p.x * 0.5 + 0.5) * W;
    const cy = (-p.y * 0.5 + 0.5) * H;
    const { size, sr } = labelSize(n, proj);
    el.style.fontSize = size + 'px';
    const w = labelWidth(el.textContent || '', size);
    const h = size * 1.35 + 4;
    let chosen = null;
    for (const mode of ['below', 'above', 'right', 'left']) {
      const spot = labelSpot(mode, cx, cy, sr, w, h);
      const rect = { x: spot.left - w / 2, y: spot.top, w, h };
      if (rect.x < 2 || rect.y < 2 || rect.x + w > W - 2 || rect.y + h > H - 2) continue;
      const hit = placed.some(r => !(rect.x + w < r.x - margin || rect.x > r.x + r.w + margin ||
        rect.y + h < r.y - margin || rect.y > r.y + r.h + margin));
      if (!hit) { chosen = { mode, rect }; break; }
    }
    if (!chosen) { el.style.display = 'none'; continue; }
    placeLabel(n, el, chosen.mode, cx, cy, sr, size, w, h, W, H);
    el.style.display = '';
    placed.push(chosen.rect);
    visible.add(n.id);
    anchors.set(n.id, { mode: chosen.mode, size, w, h });
    shown++;
  }
  S.visibleLabels = visible;
  S.labelAnchors = anchors;
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
  if (S.ptGeo) {
    const p = S.ptGeo.attributes.position;
    S.nodes.forEach((n, i) => {
      p.array[i * 3] = n.pos.x; p.array[i * 3 + 1] = n.pos.y; p.array[i * 3 + 2] = n.pos.z;
    });
    p.needsUpdate = true;
  }
  S.hits.forEach((h, i) => { h.position.copy(S.nodes[i].pos); });
  if (S.impact && S.impactNodes) {
    const ip = S.impact.geometry.attributes.position;
    S.impactNodes.forEach((n, i) => {
      ip.array[i * 3] = n.pos.x; ip.array[i * 3 + 1] = n.pos.y; ip.array[i * 3 + 2] = n.pos.z;
    });
    ip.needsUpdate = true;
  }
  if (S.lineMesh) {
    const pos = S.linePos;
    S.links.forEach((l, i) => {
      pos[i * 6] = l.s.pos.x; pos[i * 6 + 1] = l.s.pos.y; pos[i * 6 + 2] = l.s.pos.z;
      pos[i * 6 + 3] = l.t.pos.x; pos[i * 6 + 4] = l.t.pos.y; pos[i * 6 + 5] = l.t.pos.z;
    });
    S.lineMesh.geometry.attributes.position.needsUpdate = true;
  }
  const now = Date.now();
  const moving = S.alpha > 0.03;
  const relayout = !S.interacting &&
    (S.labelDirty || (moving && now - S.lastLabelRelayout > 180));
  if (relayout) { S.lastLabelRelayout = now; S.labelDirty = false; }
  updateLabels(S.selected ? nearSet(S.selDist || graphDistances(S.selected)) : null, relayout);
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
  if (!S.drag && !S.interacting && Date.now() - S.lastUser > 2800) {
    S.orbit.theta += 0.0007;
    applyCamera();
    const now0 = Date.now();
    if (now0 - (S.lastAutoLayout || 0) > 6000) { S.lastAutoLayout = now0; S.labelDirty = true; }
  }
  if (S.alpha > 0.015) step();
  if (!S.fitted && S.alpha <= 0.05) { S.fitted = true; fit(); }
  if (S.nebulae) {
    const t = Date.now();
    S.nebulae.children.forEach((sp, i) => {
      sp.material.opacity = (sp.userData.baseOpacity || 0.3) * (0.86 + 0.14 * Math.sin(t * 0.00045 + i * 0.9));
    });
  }
  if (S.stars) S.stars.rotation.y += 0.00002;
  if (S.marker && S.marker.visible) {
    const p = 1 + Math.sin(Date.now() * 0.0038) * 0.12;
    S.marker.scale.setScalar(S.marker.userData.base * p);
    S.marker.material.opacity = 0.55 + Math.sin(Date.now() * 0.0038) * 0.2;
  }
  updateScene();
  S.renderer.render(S.scene, S.camera);
}

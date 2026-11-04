/* Full-graph "space" explorer.
 *
 * A separate view from the drill-down Knowledge graph. It loads every indexed
 * entity and relationship, lays the communities out as glowing islands in a
 * three-dimensional cosmic web, and lets you orbit, pan, zoom and fly through
 * it: drag to orbit, scroll to zoom, right-drag to pan, WASD/QE to fly, click
 * a star to inspect it, click a cluster label to travel there.
 */
import * as THREE from './vendor/three.module.min.js';

const S = {
  inited: false, loading: false, data: null, canvas: null, labels: null, tip: null,
  renderer: null, scene: null, camera: null, raycaster: null, pointer: new THREE.Vector2(-9, -9),
  nodes: [], links: [], byId: new Map(), clusters: [], clusterOf: new Map(),
  core: null, halo: null, lines: null, stars: null, nebula: null, hits: null, marker: null,
  labelPool: [], clusterPool: [], labelAssigned: [], clusterAssigned: [], widths: new Map(),
  labelRange: 2600, lastAssign: 0, measureCtx: null, activeClusters: null, lodKey: '', lastLOD: 0,
  selected: null, hovered: null, highlight: new Set(),
  W: 1, H: 1, orbit: { theta: 0.7, phi: 1.12, radius: 3000, target: new THREE.Vector3() },
  drag: null, lastInteract: 0, auto: true, raf: 0, fly: null, keys: new Set(),
  baseRadius: 3000, maxDist: 0, lastLabel: 0
};

const COLORS = {
  PERSON: '#fb923c', ORGANIZATION: '#f87171', ROLE: '#facc15', SKILL: '#4ade80',
  TECHNOLOGY: '#60a5fa', PROJECT: '#c084fc', PRODUCT: '#22d3ee', METRIC: '#fbbf24',
  CERTIFICATION: '#2dd4bf', EDUCATION: '#94a3b8', PLATFORM: '#a78bfa', CONCEPT: '#94a3b8'
};
const colorOf = n => new THREE.Color(n.color || COLORS[n.class] || COLORS[n.type] || '#94a3b8');

let TEX_GLOW = null, TEX_SOFT = null;

function glowTexture() {
  if (TEX_GLOW) return TEX_GLOW;
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, 'rgba(255,255,255,1)');
  grad.addColorStop(.18, 'rgba(255,255,255,.82)');
  grad.addColorStop(.45, 'rgba(255,255,255,.28)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
  TEX_GLOW = new THREE.CanvasTexture(c);
  return TEX_GLOW;
}

function softTexture() {
  if (TEX_SOFT) return TEX_SOFT;
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, 'rgba(255,255,255,.55)');
  grad.addColorStop(.35, 'rgba(255,255,255,.18)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
  TEX_SOFT = new THREE.CanvasTexture(c);
  return TEX_SOFT;
}

function init() {
  if (S.inited) return;
  S.dom = { page: document.getElementById('kg-universe') };
  S.canvas = document.getElementById('uni3d');
  S.labels = document.getElementById('uni-labels');
  S.tip = document.getElementById('uni-tip');
  if (!S.canvas) throw new Error('no universe canvas');
  S.renderer = new THREE.WebGLRenderer({ canvas: S.canvas, antialias: true, alpha: false });
  S.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  S.renderer.setClearColor(0x020309, 1);
  S.renderer.toneMapping = THREE.ACESFilmicToneMapping;
  S.renderer.toneMappingExposure = 1.35;
  if ('outputColorSpace' in S.renderer) S.renderer.outputColorSpace = THREE.SRGBColorSpace;
  S.scene = new THREE.Scene();
  S.scene.background = new THREE.Color(0x020309);
  S.scene.fog = new THREE.FogExp2(0x020309, 0.00015);
  S.camera = new THREE.PerspectiveCamera(55, 1, 2, 40000);
  S.raycaster = new THREE.Raycaster();
  S.measureCtx = document.createElement('canvas').getContext('2d');
  addStars();
  addBackdrop();
  bind();
  new ResizeObserver(resize).observe(S.dom.page);
  resize();
  S.inited = true;
  S.raf = requestAnimationFrame(loop);
}

function addStars() {
  const geo = new THREE.BufferGeometry();
  const n = 4200, pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const r = 6000 + Math.random() * 16000;
    const th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
    pos[i * 3] = r * Math.sin(ph) * Math.cos(th);
    pos[i * 3 + 1] = r * Math.cos(ph);
    pos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
    const c = new THREE.Color().setHSL(0.52 + Math.random() * 0.18, 0.35, 0.6 + Math.random() * 0.35);
    col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
  }
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  S.stars = new THREE.Points(geo, new THREE.PointsMaterial({
    size: 9, vertexColors: true, map: glowTexture(), transparent: true,
    opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending,
    sizeAttenuation: true, fog: false
  }));
  S.scene.add(S.stars);
}

/** A few enormous, faint nebula clouds far behind everything for depth. */
function addBackdrop() {
  const group = new THREE.Group();
  const tints = ['#1d4ed8', '#7c3aed', '#0e7490', '#be123c', '#4f46e5'];
  tints.forEach((tint, i) => {
    const m = new THREE.SpriteMaterial({
      map: softTexture(), color: new THREE.Color(tint), transparent: true,
      opacity: 0.06, depthWrite: false, blending: THREE.AdditiveBlending, fog: false
    });
    const sp = new THREE.Sprite(m);
    const a = i * 1.2566, r = 15000;
    sp.position.set(Math.cos(a) * r, (i % 2 ? -1 : 1) * 5200, Math.sin(a) * r);
    sp.scale.setScalar(16000 + i * 2200);
    group.add(sp);
  });
  S.scene.add(group);
}

function resize() {
  if (!S.renderer) return;
  const r = S.dom.page.getBoundingClientRect();
  S.W = Math.max(320, r.width); S.H = Math.max(300, r.height);
  S.renderer.setSize(S.W, S.H, false);
  S.camera.aspect = S.W / S.H; S.camera.updateProjectionMatrix();
  updateLabels(true);
}

/* ---------------------------------------------------------------- layout --- */

function layout(nodes) {
  const groups = new Map();
  for (const n of nodes) {
    const k = n.community != null ? 'c' + n.community : 't' + (n.class || n.type || 'x');
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(n);
  }
  // Communities of 5+ get their own island; the long tail is folded into
  // type-coloured "drift" islands so the map stays legible.
  let islands = [...groups.entries()].filter(([, v]) => v.length >= 5)
    .sort((a, b) => b[1].length - a[1].length);
  const rest = [...groups.entries()].filter(([, v]) => v.length < 5).flatMap(([, v]) => v);
  if (rest.length) {
    const buckets = Math.max(6, Math.min(18, Math.round(rest.length / 45)));
    for (let i = 0; i < buckets; i++) islands.push(['m' + i, []]);
    rest.forEach((n, i) => islands[islands.length - buckets + (i % buckets)][1].push(n));
  }

  const G = islands.length;
  const R = 1500 + Math.sqrt(G) * 58;
  S.clusters = [];
  S.clusterOf = new Map();
  const golden = Math.PI * (3 - Math.sqrt(5));

  islands.forEach(([key, list], gi) => {
    // a large prime stride spreads the biggest islands across the sphere
    // instead of stacking them all at one pole
    const slot = (gi * 137) % Math.max(1, G);
    const y = 1 - (slot / Math.max(1, G - 1)) * 2;
    const rad = Math.sqrt(Math.max(0, 1 - y * y));
    const th = slot * golden;
    const jitter = (Math.random() - 0.5) * 260;
    const rr = R + jitter;
    const center = new THREE.Vector3(Math.cos(th) * rad * rr, y * rr * 0.86, Math.sin(th) * rad * rr);
    const spread = Math.min(215, 14 + Math.sqrt(list.length) * 17);
    const dom = list.reduce((a, b) => ((b.degree || 0) > (a.degree || 0) ? b : a), list[0]);
    const cluster = {
      key, center, spread, list, size: list.length, color: colorOf(dom),
      name: dom.title, top: dom
    };
    S.clusters.push(cluster);
    list.forEach(n => S.clusterOf.set(n.id, cluster));

    list.forEach(n => {
      const a = Math.random() * Math.PI * 2;
      const b = Math.acos(2 * Math.random() - 1);
      const r = spread * Math.cbrt(Math.random());
      n.pos = new THREE.Vector3(
        center.x + r * Math.sin(b) * Math.cos(a),
        center.y + r * Math.cos(b) * 0.82,
        center.z + r * Math.sin(b) * Math.sin(a));
      n.radius = 2.6 + Math.min(21, Math.sqrt(Math.max(1, n.degree || 1)) * 0.68);
      n.colorObj = colorOf(n);
      S.maxDist = Math.max(S.maxDist, n.pos.length());
    });
  });

  // A little local repulsion turns each island into a cluster with structure
  // instead of a uniform ball (cheap: only within one island at a time).
  relax(S.clusters);
}

function relax(clusters) {
  const v = new THREE.Vector3();
  for (const c of clusters) {
    const list = c.list;
    if (list.length < 8) continue;
    const step = Math.min(7, Math.max(2, c.spread * 0.05));
    const iters = list.length > 120 ? 4 : 8;
    for (let k = 0; k < iters; k++) {
      for (let i = 0; i < list.length; i++) {
        const a = list[i];
        for (let j = i + 1; j < list.length; j++) {
          const b = list[j];
          v.subVectors(a.pos, b.pos);
          let d = v.length();
          if (d < 0.001) { v.set(Math.random() - .5, Math.random() - .5, Math.random() - .5); d = v.length(); }
          const min = (a.radius + b.radius) * 2.4 + 6;
          if (d < min) {
            v.multiplyScalar(((min - d) / d) * 0.22);
            a.pos.add(v); b.pos.sub(v);
          }
        }
      }
      // keep the island cohesive: pull outliers back toward its centre
      for (const n of list) {
        v.subVectors(n.pos, c.center);
        const d = v.length();
        const max = c.spread * 1.35;
        if (d > max) n.pos.copy(c.center).addScaledVector(v, max / d);
      }
    }
  }
}

/* ---------------------------------------------------------------- scene ---- */

function build(data) {
  clearScene();
  S.data = data;
  S.nodes = data.nodes || [];
  S.links = data.links || [];
  S.byId = new Map(S.nodes.map(n => [n.id, n]));
  S.maxDist = 0;
  layout(S.nodes);
  const n = S.nodes.length;

  // node cores: soft additive stars
  const cg = new THREE.BufferGeometry();
  const cp = new Float32Array(n * 3), cc = new Float32Array(n * 3);
  S.nodes.forEach((node, i) => {
    cp[i * 3] = node.pos.x; cp[i * 3 + 1] = node.pos.y; cp[i * 3 + 2] = node.pos.z;
    cc[i * 3] = node.colorObj.r; cc[i * 3 + 1] = node.colorObj.g; cc[i * 3 + 2] = node.colorObj.b;
  });
  cg.setAttribute('position', new THREE.BufferAttribute(cp, 3));
  cg.setAttribute('color', new THREE.BufferAttribute(cc, 3));
  S.coreColors = cc;
  S.core = new THREE.Points(cg, new THREE.PointsMaterial({
    size: 13, vertexColors: true, map: glowTexture(), transparent: true,
    opacity: 0.96, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
  }));
  S.scene.add(S.core);

  // halos: bigger, dimmer copy makes bright nodes feel lit from within
  const hg = new THREE.BufferGeometry();
  hg.setAttribute('position', new THREE.BufferAttribute(cp.slice(), 3));
  const hc = cc.slice();
  hg.setAttribute('color', new THREE.BufferAttribute(hc, 3));
  S.haloColors = hc;
  S.halo = new THREE.Points(hg, new THREE.PointsMaterial({
    size: 46, vertexColors: true, map: softTexture(), transparent: true,
    opacity: 0.3, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
  }));
  S.scene.add(S.halo);

  // a beacon on every island's key entity, so the labelled star is visible
  const majors = S.clusters.map(c => c.top).filter(Boolean);
  S.majorNodes = majors;
  const mp = new Float32Array(majors.length * 3), mc = new Float32Array(majors.length * 3);
  majors.forEach((n, i) => {
    mp[i * 3] = n.pos.x; mp[i * 3 + 1] = n.pos.y; mp[i * 3 + 2] = n.pos.z;
    mc[i * 3] = n.colorObj.r; mc[i * 3 + 1] = n.colorObj.g; mc[i * 3 + 2] = n.colorObj.b;
  });
  const mg = new THREE.BufferGeometry();
  mg.setAttribute('position', new THREE.BufferAttribute(mp, 3));
  mg.setAttribute('color', new THREE.BufferAttribute(mc, 3));
  S.majorColors = mc;
  S.major = new THREE.Points(mg, new THREE.PointsMaterial({
    size: 30, vertexColors: true, map: glowTexture(), transparent: true,
    opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
  }));
  S.scene.add(S.major);

  // relationships: faint filaments, brighter than the void
  const L = S.links.length;
  const lp = new Float32Array(L * 6), lc = new Float32Array(L * 6);
  S.links.forEach((l, i) => {
    const a = S.byId.get(l.source), b = S.byId.get(l.target);
    if (!a || !b || !a.pos || !b.pos) return;
    lp[i * 6] = a.pos.x; lp[i * 6 + 1] = a.pos.y; lp[i * 6 + 2] = a.pos.z;
    lp[i * 6 + 3] = b.pos.x; lp[i * 6 + 4] = b.pos.y; lp[i * 6 + 5] = b.pos.z;
    const d = a.pos.distanceTo(b.pos);
    const fade = Math.max(0.06, Math.min(1, 1.25 - d / 2400));   // long bridges barely glimmer
    const c = a.colorObj.clone().lerp(b.colorObj, 0.5).multiplyScalar(fade);
    lc[i * 6] = c.r; lc[i * 6 + 1] = c.g; lc[i * 6 + 2] = c.b;
    lc[i * 6 + 3] = c.r; lc[i * 6 + 4] = c.g; lc[i * 6 + 5] = c.b;
  });
  const lg = new THREE.BufferGeometry();
  lg.setAttribute('position', new THREE.BufferAttribute(lp, 3));
  lg.setAttribute('color', new THREE.BufferAttribute(lc, 3));
  S.lines = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({
    vertexColors: true, transparent: true, opacity: 0.085, depthWrite: false,
    blending: THREE.AdditiveBlending
  }));
  S.scene.add(S.lines);

  // island nebulae
  const ng = new THREE.Group();
  for (const c of S.clusters) {
    if (c.size < 8 && Math.random() < 0.45) continue;
    const m = new THREE.SpriteMaterial({
      map: softTexture(), color: c.color, transparent: true,
      opacity: c.size > 40 ? 0.16 : 0.1, depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    const sp = new THREE.Sprite(m);
    sp.position.copy(c.center);
    sp.scale.setScalar(c.spread * (c.size > 40 ? 7.5 : 6));
    ng.add(sp);
  }
  S.nebula = ng;
  S.scene.add(ng);

  S.marker = new THREE.Sprite(new THREE.SpriteMaterial({
    map: glowTexture(), color: new THREE.Color('#fbbf24'), transparent: true,
    opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending
  }));
  S.marker.visible = false;
  S.scene.add(S.marker);

  buildLabelPool();
  S.clustersRanked = [...S.clusters].sort((a, b) => b.size - a.size);
  S.activeClusters = null;
  S.lodKey = '';
  S.baseRadius = Math.max(3000, (S.maxDist || 2000) * 2.16);
  const st = document.getElementById('uni-stats');
  if (st) st.textContent = `${n} entities · ${S.links.length} relationships · ${S.clusters.length} islands`;
  resetView();
  updateLOD(true);
}

function clearScene() {
  [S.core, S.halo, S.major, S.lines, S.nebula, S.marker, S.hits].forEach(x => {
    if (!x) return;
    S.scene.remove(x);
    x.traverse ? x.traverse(o => { o.geometry && o.geometry.dispose(); o.material && o.material.dispose(); })
               : (x.geometry && x.geometry.dispose(), x.material && x.material.dispose());
  });
  S.core = S.halo = S.major = S.lines = S.nebula = S.marker = S.hits = null;
  S.labelAssigned = []; S.clusterAssigned = [];
  S.labelPool.forEach(el => { el._node = null; el.style.display = 'none'; });
  S.clusterPool.forEach(el => { el._cluster = null; el.style.display = 'none'; });
}

/* ----------------------------------------------------------------- labels -- */

/* A fixed pool of DOM chips, reassigned only when the camera settles. Between
 * reassignments every chip follows its node, so labels track instead of jump. */

function buildLabelPool() {
  if (S.labelPool.length) return;
  for (let i = 0; i < 90; i++) {
    const el = document.createElement('div');
    el.className = 'uni-label';
    el.style.display = 'none';
    el.addEventListener('click', () => { if (el._node) select(el._node); });
    S.labels.appendChild(el);
    S.labelPool.push(el);
  }
  for (let i = 0; i < 26; i++) {
    const el = document.createElement('div');
    el.className = 'uni-cluster-label';
    el.style.display = 'none';
    el.addEventListener('click', () => { if (el._cluster) flyToCluster(el._cluster); });
    S.labels.appendChild(el);
    S.clusterPool.push(el);
  }
}

function labelRange() {
  // the slider sets the range at the overview; zooming in tightens it so the
  // label count stays bounded without any extra work
  const k = S.orbit.radius / Math.max(1, S.baseRadius);
  return Math.max(140, Math.min(26000, S.labelRange * Math.max(0.22, k)));
}

function widthOf(text) {
  if (S.widths.has(text)) return S.widths.get(text);
  if (!S.measureCtx) return text.length * 6.1 + 12;
  S.measureCtx.font = '600 10.5px ui-sans-serif, system-ui, sans-serif';
  const w = Math.min(240, S.measureCtx.measureText(text).width + 14);
  S.widths.set(text, w);
  return w;
}

/* Level of detail: at the overview only the biggest islands are lit and
 * labelled; the rest is faint dust. Zooming in (or flying to an island) lights
 * its neighbours too, so the view reveals itself as you travel. */
function labelTier() {
  const k = S.orbit.radius / Math.max(1, S.baseRadius);
  if (k > 0.72) return 'major';     // overview: the key node of every big island + top hubs
  if (k > 0.45) return 'strong';    // mid: well-connected entities
  if (k > 0.22) return 'detail';    // closer: most named entities
  return 'local';                   // inside a cluster: everything nearby
}

function lodPlan() {
  const k = S.orbit.radius / Math.max(1, S.baseRadius);
  const budget = k > 0.72 ? 18 : k > 0.48 ? 36 : k > 0.3 ? 70 : k > 0.16 ? 120 : 9999;
  const ranked = S.clustersRanked || (S.clustersRanked = [...S.clusters].sort((a, b) => b.size - a.size));
  const act = new Set(ranked.slice(0, budget));
  if (k < 0.55) {
    const rng = labelRange() * 1.15;
    for (const c of S.clusters) if (c.center.distanceTo(S.orbit.target) <= rng) act.add(c);
  }
  if (S.selected) { const c = S.clusterOf.get(S.selected.id); if (c) act.add(c); }
  return act;
}

function applyCamera() {
  if (!S.camera) return;
  const o = S.orbit;
  S.camera.position.set(
    o.target.x + o.radius * Math.sin(o.phi) * Math.sin(o.theta),
    o.target.y + o.radius * Math.cos(o.phi),
    o.target.z + o.radius * Math.sin(o.phi) * Math.cos(o.theta));
  S.camera.lookAt(o.target);
  S.camera.updateMatrixWorld();
}

function zoomAnchorAt(cx, cy) {
  if (!S.canvas) return null;
  const r = S.canvas.getBoundingClientRect();
  const ndc = new THREE.Vector2(((cx - r.left) / r.width) * 2 - 1,
                                -((cy - r.top) / r.height) * 2 + 1);
  S.raycaster.setFromCamera(ndc, S.camera);
  const ray = S.raycaster.ray;
  let best = null, bestD = 1e9;
  for (const n of S.nodes) {
    const along = n.pos.clone().sub(S.camera.position).dot(ray.direction);
    if (along <= 0) continue;
    const d = ray.distanceToPoint(n.pos);
    const score = d + along * 0.0015;
    if (score < bestD) { bestD = score; best = n; }
  }
  return best ? best.pos : null;
}

function updateLOD(force) {
  if (!S.clusters.length || !S.core) return;
  applyCamera();
  const plan = lodPlan();
  const key = labelTier() + '|' + [...plan].map(c => c.key).sort().join(',');
  if (!force && key === S.lodKey) return;
  S.lodKey = key;
  S.activeClusters = plan;
  const core = S.coreColors, halo = S.haloColors;
  if (core) {
    S.nodes.forEach((n, i) => {
      const c = S.clusterOf.get(n.id);
      const on = !c || plan.has(c) || n === S.selected || S.highlight.has(n.id);
      const f = on ? 1 : 0.04;
      core[i * 3] = n.colorObj.r * f; core[i * 3 + 1] = n.colorObj.g * f; core[i * 3 + 2] = n.colorObj.b * f;
      if (halo) {
        halo[i * 3] = core[i * 3]; halo[i * 3 + 1] = core[i * 3 + 1]; halo[i * 3 + 2] = core[i * 3 + 2];
      }
    });
    S.core.geometry.attributes.color.needsUpdate = true;
    if (S.halo) S.halo.geometry.attributes.color.needsUpdate = true;
    if (S.majorColors && S.majorNodes) {
      S.majorNodes.forEach((n, i) => {
        const c = S.clusterOf.get(n.id);
        const on = !c || plan.has(c) || n === S.selected || S.highlight.has(n.id);
        const f = on ? 1 : 0.12;
        S.majorColors[i * 3] = n.colorObj.r * f;
        S.majorColors[i * 3 + 1] = n.colorObj.g * f;
        S.majorColors[i * 3 + 2] = n.colorObj.b * f;
      });
      S.major.geometry.attributes.color.needsUpdate = true;
    }
  }
  assignLabels();
  updateLabels(true);
}

function assignLabels() {
  if (!S.labels || !S.nodes.length) return;
  buildLabelPool();
  S.lastAssign = performance.now();
  const W = S.W, H = S.H;
  const range = labelRange();
  const target = S.orbit.target;
  const tier = labelTier();
  const minDeg = tier === 'major' ? 80 : tier === 'strong' ? 25 : tier === 'detail' ? 8 : 0;

  const onScreen = n => {
    const p = n.pos.clone().project(S.camera);
    if (p.z > 1 || p.z < -1) return null;
    const x = (p.x * 0.5 + 0.5) * W, y = (-p.y * 0.5 + 0.5) * H;
    if (x < -150 || x > W + 150 || y < -20 || y > H + 20) return null;
    return { x, y };
  };
  const represented = n => {
    const cl = S.clusterOf.get(n.id);
    return !S.activeClusters || !cl || S.activeClusters.has(cl);
  };
  const eligible = n => {
    if (n === S.selected || n === S.hovered) return true;
    if (!inRange(n) || !represented(n)) return false;
    const cl = S.clusterOf.get(n.id);
    const isTop = cl && cl.top === n;
    return (n.degree || 0) >= minDeg || isTop;
  };
  const inRange = n => n === S.selected || n === S.hovered
    || n.pos.distanceTo(target) <= range;

  const placed = [];

  // ---- node labels first: the important nodes are what you should see first
  const cands = [];
  for (const n of S.nodes) {
    if (!eligible(n)) continue;
    const d = n.pos.distanceTo(target);
    const score = (n === S.selected ? -1e6 : n === S.hovered ? -9e5 : 0)
      + d * 0.6 - Math.min(460, (n.degree || 0) * 1.4);
    cands.push({ n, score });
  }
  cands.sort((a, b) => a.score - b.score);
  const seen = new Set();
  const ordered = [];
  for (const { n } of S.labelAssigned) {
    if (!seen.has(n.id) && eligible(n)) { seen.add(n.id); ordered.push(n); }
  }
  for (const { n } of cands) {
    if (!seen.has(n.id)) { seen.add(n.id); ordered.push(n); }
  }
  const assigned = [];
  const labelled = new Set();
  for (const n of ordered) {
    if (assigned.length >= S.labelPool.length) break;
    const spot = onScreen(n);
    if (!spot) continue;
    const el = S.labelPool[assigned.length];
    el._node = n;
    el.textContent = n.title;
    el.classList.toggle('extra', n === S.selected || n === S.hovered);
    el.classList.toggle('sel', n === S.selected);
    el.style.display = '';
    const w = el.offsetWidth || widthOf(n.title), h = el.offsetHeight || 16;
    let clash = false;
    for (const r of placed) {
      if (!(spot.x + w / 2 < r.x - r.w / 2 || spot.x - w / 2 > r.x + r.w / 2 ||
            spot.y + h / 2 < r.y - r.h / 2 || spot.y - h / 2 > r.y + r.h / 2)) { clash = true; break; }
    }
    if (clash) { el.style.display = 'none'; el._node = null; continue; }
    placed.push({ x: spot.x, y: spot.y, w: w + 10, h: h + 6 });
    assigned.push({ n, el });
    labelled.add(n.id);
  }
  S.labelAssigned = assigned;
  for (let i = assigned.length; i < S.labelPool.length; i++) {
    S.labelPool[i]._node = null; S.labelPool[i].style.display = 'none';
  }

  // ---- island beacons fill the gaps the node labels left
  const prevClusters = S.clusterAssigned.slice();
  S.clusterAssigned = [];
  const cl = [...S.clusters]
    .filter(c => (!S.activeClusters || S.activeClusters.has(c))
      && c.center.distanceTo(target) <= range * 1.2)
    .sort((a, b) => b.size - a.size);
  const prevSet = new Set(prevClusters.map(a => a.c));
  let ci = 0;
  const tryCluster = c => {
    if (c.top && labelled.has(c.top.id)) return false;   // its key node already speaks for it
    if (c.center.distanceTo(target) > range * 1.2) return false;
    const p = c.center.clone().project(S.camera);
    if (p.z > 1 || p.z < -1) return false;
    const x = (p.x * 0.5 + 0.5) * W, y = (-p.y * 0.5 + 0.5) * H;
    if (x < -90 || x > W + 90 || y < -20 || y > H + 20) return false;
    const el = S.clusterPool[ci];
    el._cluster = c;
    el.innerHTML = `<b>${esc(c.name)}</b><span>${c.size} ${c.size === 1 ? 'entity' : 'entities'}</span>`;
    el.style.display = '';
    const w = el.offsetWidth || 130, h = el.offsetHeight || 30;
    if (x + w / 2 < 0 || x - w / 2 > W || y + h / 2 < 0 || y - h / 2 > H) {
      el.style.display = 'none'; el._cluster = null; return false;
    }
    for (const r of placed) {
      if (!(x + w / 2 < r.x - r.w / 2 || x - w / 2 > r.x + r.w / 2 ||
            y + h / 2 < r.y - r.h / 2 || y - h / 2 > r.y + r.h / 2)) {
        el.style.display = 'none'; el._cluster = null; return false;
      }
    }
    placed.push({ x, y, w: w + 8, h: h + 4 });
    el.style.display = '';
    S.clusterAssigned.push({ c, el });
    ci++;
    return true;
  };
  for (const { c } of prevClusters) {
    if (ci >= S.clusterPool.length) break;
    if (!prevSet.has(c)) continue;
    tryCluster(c);
  }
  for (const c of cl) {
    if (ci >= S.clusterPool.length) break;
    if (prevSet.has(c)) continue;
    tryCluster(c);
  }
  for (; ci < S.clusterPool.length; ci++) {
    S.clusterPool[ci]._cluster = null; S.clusterPool[ci].style.display = 'none';
  }
  const cnt = document.getElementById('uni-labelcount');
  if (cnt) cnt.textContent = String(assigned.length + S.clusterAssigned.length);
}

function updateLabels(force = false) {
  if (!S.labels) return;
  const now = performance.now();
  if (!force && now - S.lastLabel < 33) return;
  S.lastLabel = now;
  const W = S.W, H = S.H;
  const place = (n, el) => {
    if (!n || !n.pos) { el.style.display = 'none'; return; }
    const p = n.pos.clone().project(S.camera);
    if (p.z > 1 || p.z < -1) { el.style.display = 'none'; return; }
    const x = (p.x * 0.5 + 0.5) * W, y = (-p.y * 0.5 + 0.5) * H;
    if (x < -150 || x > W + 150 || y < -20 || y > H + 20) { el.style.display = 'none'; return; }
    el.style.display = '';
    el.style.transform = `translate3d(${x}px,${y}px,0) translate(-50%,-50%)`;
  };
  for (const { n, el } of S.labelAssigned) place(n, el);
  for (const { c, el } of S.clusterAssigned) place({ pos: c.center }, el);
}

function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

/* ------------------------------------------------------------------ loop --- */

function loop(now) {
  S.raf = requestAnimationFrame(loop);
  if (!S.renderer || !S.camera) return;
  if (S.fly) {
    const f = S.fly;
    const t = Math.min(1, (now - f.start) / f.dur);
    const e = t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    const a = f.from, b = f.to;
    // curved path keeps the flight feeling like travel, not sliding
    const lift = Math.sin(Math.PI * e) * f.lift;
    S.camera.position.set(
      a.x + (b.x - a.x) * e + lift * f.side.x,
      a.y + (b.y - a.y) * e + lift * f.side.y,
      a.z + (b.z - a.z) * e + lift * f.side.z);
    S.orbit.target.lerpVectors(f.targetFrom, f.targetTo, e);
    S.orbit.radius = f.r0 + (f.r1 - f.r0) * e;
    if (t >= 1) {
      const d = S.camera.position.clone().sub(S.orbit.target);
      S.orbit.radius = Math.max(30, d.length());
      S.orbit.phi = Math.acos(Math.max(-1, Math.min(1, d.y / S.orbit.radius)));
      S.orbit.theta = Math.atan2(d.x, d.z);
      S.fly = null;
      updateLOD(true);
    }
  } else {
    moveKeys();
    if (S.auto && now - S.lastInteract > 2500) S.orbit.theta += 0.00028;
    const o = S.orbit;
    S.camera.position.set(
      o.target.x + o.radius * Math.sin(o.phi) * Math.sin(o.theta),
      o.target.y + o.radius * Math.cos(o.phi),
      o.target.z + o.radius * Math.sin(o.phi) * Math.cos(o.theta));
  }
  S.camera.lookAt(S.orbit.target);
  S.camera.updateMatrixWorld();

  if (!S.fly && now - (S.lastLOD || 0) > 420) { S.lastLOD = now; updateLOD(); }
  if (S.stars) S.stars.rotation.y += 0.00002;

  // scale glows with zoom so near stars stay soft and far ones stay visible
  const dist = S.orbit.radius;
  if (S.core) S.core.material.size = Math.max(6, Math.min(30, dist * 0.006));
  if (S.halo) S.halo.material.size = Math.max(24, Math.min(170, dist * 0.022));
  if (S.major) S.major.material.size = Math.max(22, Math.min(90, dist * 0.012));
  if (S.marker && S.selected) {
    const pulse = 1 + Math.sin(now * 0.004) * 0.16;
    const s = (S.marker.userData.base || 40) * pulse;
    S.marker.scale.setScalar(s);
    S.marker.material.opacity = 0.55 + Math.sin(now * 0.004) * 0.2;
  }

  updateLabels();
  S.renderer.render(S.scene, S.camera);
}

function moveKeys() {
  if (!S.keys.size) return;
  const speed = (S.orbit.radius * 0.005) * (S.keys.has('shift') ? 3 : 1);
  const fwd = new THREE.Vector3().subVectors(S.orbit.target, S.camera.position).normalize();
  const right = new THREE.Vector3().crossVectors(fwd, S.camera.up).normalize();
  const up = new THREE.Vector3(0, 1, 0);
  const d = new THREE.Vector3();
  if (S.keys.has('w')) d.add(fwd); if (S.keys.has('s')) d.sub(fwd);
  if (S.keys.has('d')) d.add(right); if (S.keys.has('a')) d.sub(right);
  if (S.keys.has('e')) d.add(up); if (S.keys.has('q')) d.sub(up);
  if (d.lengthSq()) {
    d.normalize().multiplyScalar(speed);
    S.orbit.target.add(d); S.camera.position.add(d);
    S.lastInteract = performance.now();
  }
}

/* --------------------------------------------------------------- actions --- */

function resetView() {
  S.orbit.theta = 0.7; S.orbit.phi = 1.12; S.orbit.radius = S.baseRadius;
  S.orbit.target.set(0, 0, 0); S.auto = false; S.selected = null; S.hovered = null;
  S.fly = null;
  if (S.marker) S.marker.visible = false;
  if (S.hits) { S.scene.remove(S.hits); S.hits = null; }
  S.highlight.clear();
  setSide(null); if (S.clusters.length) updateLOD(true); else { assignLabels(); updateLabels(true); }
}

function flyTo(target, radius, dur = 1100, lift = null) {
  const from = S.camera.position.clone();
  const targetFrom = S.orbit.target.clone();
  const dir = from.clone().sub(target).normalize();
  if (!isFinite(dir.x) || dir.lengthSq() < 0.001) dir.set(1, 0.5, 1).normalize();
  const to = target.clone().add(dir.multiplyScalar(radius));
  const side = new THREE.Vector3().crossVectors(
    to.clone().sub(from), new THREE.Vector3(0, 1, 0)).normalize().multiplyScalar(0.35);
  S.fly = {
    start: performance.now(), dur, from, to,
    targetFrom, targetTo: target.clone(), r0: S.orbit.radius, r1: radius,
    lift: lift == null ? Math.min(1200, from.distanceTo(to) * 0.22) : lift, side
  };
  S.auto = false;
}

function select(n) {
  S.selected = n; S.auto = false;
  setSide(n);
  const dist = 240 + Math.min(700, (n.degree || 1) * 4.5);
  flyTo(n.pos.clone(), dist, 950);
  if (S.marker) {
    S.marker.visible = true;
    S.marker.position.copy(n.pos);
    S.marker.userData.base = Math.max(34, n.radius * 5.5);
    S.marker.scale.setScalar(S.marker.userData.base);
    S.marker.material.color.copy(n.colorObj).lerp(new THREE.Color('#ffffff'), 0.45);
  }
  updateLOD(true);
}

function flyToCluster(c) {
  const radius = Math.max(420, c.spread * 3.4);
  S.selected = null; S.auto = false;
  flyTo(c.center.clone(), radius, 1200);
  setSideCluster(c);
  updateLOD(true);
}

function setSide(n) {
  const box = document.getElementById('uni-side');
  if (!box) return;
  if (!n) {
    box.innerHTML = `<div class="uni-side-hint">
      <b>The whole knowledge graph.</b><br>
      Drag to orbit · scroll to zoom · right-drag (or shift-drag) to pan.<br>
      <b>W A S D</b> to fly, <b>Q / E</b> down / up, <b>Shift</b> to boost.<br>
      Click a star to inspect it, click an island label to travel there, double-click a star to fly in close.
    </div>`;
    return;
  }
  box.innerHTML = `<div class="uni-kind">${esc(n.class || n.type || 'entity')}</div>
    <h3>${esc(n.title)}</h3>
    <div class="uni-meta">${n.degree || 0} links · ${n.community != null ? 'island ' + n.community : 'no community'}</div>
    <p>${esc(n.description || 'No description in the index.')}</p>
    <div class="uni-actions">
      <button class="small" onclick="window.__uni && window.__uni.focusSelected()">Fly here</button>
      <button class="small" onclick="window.__uni && window.__uni.reset()">Reset view</button>
    </div>`;
}

function setSideCluster(c) {
  const box = document.getElementById('uni-side');
  if (!box) return;
  box.innerHTML = `<div class="uni-kind">island</div>
    <h3>${esc(c.name)}</h3>
    <div class="uni-meta">${c.size} entities · community ${String(c.key).replace(/^c/, '')}</div>
    <p>The island is named after its best-connected entity. Its neighbours orbit it; click any star or use search to jump straight to one.</p>
    <div class="uni-actions"><button class="small" onclick="window.__uni && window.__uni.reset()">Reset view</button></div>`;
}

function hitAt(x, y) {
  const rect = S.canvas.getBoundingClientRect();
  S.pointer.x = ((x - rect.left) / rect.width) * 2 - 1;
  S.pointer.y = -((y - rect.top) / rect.height) * 2 + 1;
  if (!S.core) return null;
  S.raycaster.setFromCamera(S.pointer, S.camera);
  S.raycaster.params.Points = { threshold: Math.max(6, S.orbit.radius * 0.006) };
  const hits = S.raycaster.intersectObject(S.core, false);
  if (!hits.length) return null;
  let node = S.nodes[hits[0].index];
  // a hidden point may sit behind a visible one; prefer the visible hit
  if (!node) return null;
  return node;
}

function bind() {
  const c = S.canvas;
  c.addEventListener('contextmenu', e => e.preventDefault());
  c.addEventListener('pointerdown', e => {
    S.lastInteract = performance.now(); S.auto = false;
    S.drag = { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY,
               pan: e.button === 2 || e.shiftKey, moved: false };
    try { c.setPointerCapture(e.pointerId); } catch (_) {}
  });
  c.addEventListener('pointermove', e => {
    if (S.drag) {
      const dx = e.clientX - S.drag.x, dy = e.clientY - S.drag.y;
      S.drag.x = e.clientX; S.drag.y = e.clientY;
      if (Math.hypot(e.clientX - S.drag.x0, e.clientY - S.drag.y0) > 4) S.drag.moved = true;
      if (S.drag.pan) {
        const right = new THREE.Vector3().setFromMatrixColumn(S.camera.matrix, 0);
        const up = new THREE.Vector3().setFromMatrixColumn(S.camera.matrix, 1);
        const k = S.orbit.radius * 0.0013;
        S.orbit.target.addScaledVector(right, -dx * k);
        S.orbit.target.addScaledVector(up, dy * k);
      } else {
        S.orbit.theta -= dx * 0.005;
        S.orbit.phi = Math.max(0.08, Math.min(Math.PI - 0.08, S.orbit.phi + dy * 0.005));
      }
      return;
    }
    const n = hitAt(e.clientX, e.clientY);
    if (n !== S.hovered) { S.hovered = n; assignLabels(); updateLabels(true); }
    if (S.tip) {
      if (n) {
        S.tip.classList.remove('hide');
        S.tip.innerHTML = `<b>${esc(n.title)}</b><span>${esc(n.class || n.type || '')} · ${n.degree || 0} links</span>`;
        const r = S.dom.page.getBoundingClientRect();
        S.tip.style.left = (e.clientX - r.left + 16) + 'px';
        S.tip.style.top = (e.clientY - r.top + 14) + 'px';
      } else S.tip.classList.add('hide');
    }
  });
  c.addEventListener('pointerleave', () => { if (S.tip) S.tip.classList.add('hide'); });
  c.addEventListener('pointerup', e => {
    if (S.drag && !S.drag.moved) { const n = hitAt(e.clientX, e.clientY); if (n) select(n); }
    else if (S.drag) { clearTimeout(S.assignTimer); S.assignTimer = setTimeout(assignLabels, 240); }
    S.drag = null;
  });
  c.addEventListener('dblclick', e => { const n = hitAt(e.clientX, e.clientY); if (n) select(n); });
  c.addEventListener('wheel', e => {
    e.preventDefault(); S.lastInteract = performance.now(); S.auto = false;
    const k = e.deltaMode === 1 ? 0.05 : 0.0015;
    const before = S.orbit.radius;
    S.orbit.radius = Math.max(35, Math.min(14000, S.orbit.radius * Math.exp(e.deltaY * k)));
    if (S.orbit.radius < before) {
      // zoom toward what is under the cursor, so wheeling in flies into a
      // cluster instead of into the empty middle of the sphere
      const anchor = zoomAnchorAt(e.clientX, e.clientY);
      if (anchor) {
        const f = Math.min(0.6, (1 - S.orbit.radius / before) * 1.5);
        S.orbit.target.lerp(anchor, f);
      }
      applyCamera();
    }
    clearTimeout(S.assignTimer); S.assignTimer = setTimeout(assignLabels, 300);
  }, { passive: false });
  const rng = document.getElementById('uni-range');
  if (rng) {
    S.labelRange = +rng.value || S.labelRange;
    const show = () => { const v = document.getElementById('uni-range-v'); if (v) v.textContent = rng.value; };
    show();
    rng.addEventListener('input', () => {
      S.labelRange = +rng.value || 0;
      show(); assignLabels(); updateLabels(true);
    });
  }
  addEventListener('keydown', e => {
    if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    const k = e.key.toLowerCase();
    if (['w', 'a', 's', 'd', 'q', 'e', 'shift'].includes(k)) { S.keys.add(k); S.auto = false; }
    if (k === 'escape') {
      const back = document.getElementById('kg-mode-map');
      if (back) back.click();
    }
  });
  addEventListener('keyup', e => S.keys.delete(e.key.toLowerCase()));
  addEventListener('blur', () => S.keys.clear());
}

/* ------------------------------------------------------------------ load --- */

async function load() {
  if (S.loading) return;
  S.loading = true;
  const status = document.getElementById('uni-stats');
  if (status) status.textContent = 'charting the universe…';
  try {
    const token = document.body.dataset.sessionToken || '';
    const r = await fetch('/api/graph/universe', { headers: token ? { 'X-Session': token } : {} });
    const d = await r.json();
    if (!d || d.error) throw new Error((d && d.error) || 'no graph data');
    build(d);
  } catch (e) {
    if (status) status.textContent = 'Could not load the graph: ' + String(e);
  } finally { S.loading = false; }
}

export async function open() {
  init();
  S.dom.page.classList.remove('hide');
  resize();
  if (!S.data) await load();
  S.lastInteract = performance.now();
  if (!S.raf) S.raf = requestAnimationFrame(loop);
}

export function close() {
  if (S.raf) cancelAnimationFrame(S.raf), S.raf = 0;
}

export function reset() { if (S.data) resetView(); }

export function focusSelected() {
  if (S.selected) flyTo(S.selected.pos.clone(), 240 + Math.min(700, (S.selected.degree || 1) * 4.5), 800);
}

export function search(q) {
  q = String(q == null ? '' : q).trim().toLowerCase();
  const st = document.getElementById('uni-stats');
  if (!q || !S.nodes.length) {
    if (st && S.nodes.length) st.textContent = `${S.nodes.length} entities · ${S.links.length} relationships · ${S.clusters.length} islands`;
    return 0;
  }
  const hits = S.nodes.filter(n => (n.title + ' ' + (n.description || '')).toLowerCase().includes(q));
  S.highlight = new Set(hits.map(n => n.id));
  if (S.hits) { S.scene.remove(S.hits); S.hits.geometry.dispose(); S.hits.material.dispose(); S.hits = null; }
  if (hits.length) {
    const pos = new Float32Array(hits.length * 3);
    hits.forEach((n, i) => { pos[i * 3] = n.pos.x; pos[i * 3 + 1] = n.pos.y; pos[i * 3 + 2] = n.pos.z; });
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    S.hits = new THREE.Points(g, new THREE.PointsMaterial({
      size: 34, color: new THREE.Color('#fbbf24'), map: glowTexture(), transparent: true,
      opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
    }));
    S.scene.add(S.hits);
    select(hits.slice().sort((a, b) => (b.degree || 0) - (a.degree || 0))[0]);
  }
  if (st) st.textContent = `${hits.length} match${hits.length === 1 ? '' : 'es'} for “${q}” · ${S.nodes.length} entities`;
  return hits.length;
}

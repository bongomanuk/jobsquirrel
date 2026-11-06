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
  labelRange: 3200, lastAssign: 0, measureCtx: null, activeClusters: null, lodKey: '', lastLOD: 0,
  selected: null, hovered: null, highlight: new Set(),
  W: 1, H: 1, orbit: { theta: 0.7, phi: 1.12, radius: 3000, target: new THREE.Vector3() },
  drag: null, lastInteract: 0, auto: true, raf: 0, fly: null, keys: new Set(),
  baseRadius: 3000, maxDist: 0, lastLabel: 0, focusDepth: 2, focusAmount: 0, focusAt: 0, focusHold: 4000, focusFade: 1200
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
  // Entities with no relationships cannot join a theme. Keep them together in
  // one named island instead of letting them drift as stray labels.
  const linked = new Set();
  for (const l of (S.links || [])) { linked.add(l.source); linked.add(l.target); }
  const unlinked = nodes.filter(n => !linked.has(n.id));
  if (unlinked.length) {
    const drop = new Set(unlinked);
    for (const [k, list] of groups) groups.set(k, list.filter(n => !drop.has(n)));
  }

  // Communities of 5+ get their own island; the long tail is folded into
  // type-coloured "drift" islands so the map stays legible.
  let islands = [...groups.entries()].filter(([, v]) => v.length >= 5)
    .sort((a, b) => b[1].length - a[1].length);
  const rest = [...groups.entries()].filter(([, v]) => v.length < 5).flatMap(([, v]) => v);
  if (unlinked.length) islands.push(['unlinked', unlinked]);
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
    const spread = Math.min(240, 16 + Math.sqrt(list.length) * 19);
    const rank = x => (Number(x.importance) || 0) * 100 + Math.min(40, x.degree || 0);
    const dom = list.reduce((a, b) => (rank(b) > rank(a) ? b : a), list[0]);
    const titled = list.find(x => x.community_title);
    const isUnlinked = key === 'unlinked';
    const cluster = {
      key, center, spread, list, size: list.length,
      color: isUnlinked ? new THREE.Color('#94a3b8') : colorOf(dom),
      name: isUnlinked ? 'Unlinked evidence' : dom.title,
      title: isUnlinked ? 'Unlinked evidence' : ((titled && titled.community_title) || dom.title),
      top: dom, unlinked: isUnlinked
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
      n.radius = 2.6 + Math.min(19, Math.sqrt(Math.max(1, n.degree || 1)) * 0.62)
        + (Number(n.importance) || 0) * 16;
      n.colorObj = colorOf(n);
      S.maxDist = Math.max(S.maxDist, n.pos.length());
    });
  });

  // A little local repulsion turns each island into a cluster with structure
  // instead of a uniform ball (cheap: only within one island at a time).
  relax(S.clusters);

  // Put a single dominant person at the centre of the universe: their links
  // become the career spine between the theme islands.
  const people = nodes.filter(n => (n.class || n.type) === 'PERSON');
  if (people.length && S.clusters.length >= 4) {
    const hub = people.reduce((a, b) => ((b.degree || 0) > (a.degree || 0) ? b : a), people[0]);
    if ((hub.degree || 0) >= 6) {
      hub.pos.set(0, 0, 0);
      hub.central = true;
      hub.radius = Math.max(hub.radius || 0, 18);
    }
  }

  // Operator-attached entities (for example a skill linked to a person) are
  // placed beside their strongest neighbour in the same island. Otherwise a
  // newly linked node can still look stranded inside a sparse part of it.
  const placed = new Map(nodes.map(n => [n.id, n]));
  for (const n of nodes) {
    if (!n.attached) continue;
    let best = null, score = -1;
    for (const e of (S.adj.get(n.id) || [])) {
      const m = placed.get(e.id);
      if (!m || S.clusterOf.get(m.id) !== S.clusterOf.get(n.id)) continue;
      const s2 = (Number(m.degree) || 0) + (Number(m.importance) || 0) * 50;
      if (s2 > score) { score = s2; best = m; }
    }
    if (!best) continue;
    const a = Math.random() * Math.PI * 2;
    const b = Math.acos(2 * Math.random() - 1);
    const r = (best.radius + n.radius + 9) * 2.6;
    n.pos.set(best.pos.x + r * Math.sin(b) * Math.cos(a),
              best.pos.y + r * Math.cos(b) * 0.82,
              best.pos.z + r * Math.sin(b) * Math.sin(a));
  }
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
  S.adj = new Map();
  for (const l of S.links) {
    if (!S.adj.has(l.source)) S.adj.set(l.source, []);
    if (!S.adj.has(l.target)) S.adj.set(l.target, []);
    S.adj.get(l.source).push({ id: l.target, weight: l.weight || 1 });
    S.adj.get(l.target).push({ id: l.source, weight: l.weight || 1 });
  }
  S.selDist = null;
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

  // high-impact landmarks: a warm beacon so the weighting is visible at a glance
  const landmarks = S.nodes.filter(n => (Number(n.importance) || 0) >= 0.95);
  S.impactNodes = landmarks;
  if (landmarks.length) {
    const ip = new Float32Array(landmarks.length * 3), ic = new Float32Array(landmarks.length * 3);
    landmarks.forEach((n, i) => {
      ip[i * 3] = n.pos.x; ip[i * 3 + 1] = n.pos.y; ip[i * 3 + 2] = n.pos.z;
      const c = n.colorObj.clone().lerp(new THREE.Color('#ffd166'), 0.65);
      ic[i * 3] = c.r; ic[i * 3 + 1] = c.g; ic[i * 3 + 2] = c.b;
    });
    const ig = new THREE.BufferGeometry();
    ig.setAttribute('position', new THREE.BufferAttribute(ip, 3));
    ig.setAttribute('color', new THREE.BufferAttribute(ic, 3));
    S.impact = new THREE.Points(ig, new THREE.PointsMaterial({
      size: 42, vertexColors: true, map: glowTexture(), transparent: true,
      opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
    }));
    S.scene.add(S.impact);
  }

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
    const c = l.grounded ? new THREE.Color('#fbbf24') : a.colorObj.clone().lerp(b.colorObj, 0.5).multiplyScalar(fade);
    lc[i * 6] = c.r; lc[i * 6 + 1] = c.g; lc[i * 6 + 2] = c.b;
    lc[i * 6 + 3] = c.r; lc[i * 6 + 4] = c.g; lc[i * 6 + 5] = c.b;
  });
  const lg = new THREE.BufferGeometry();
  lg.setAttribute('position', new THREE.BufferAttribute(lp, 3));
  lg.setAttribute('color', new THREE.BufferAttribute(lc, 3));
  S.linkBaseColors = lc.slice();
  S.lines = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({
    vertexColors: true, transparent: true, opacity: 0.11, depthWrite: false,
    blending: THREE.AdditiveBlending
  }));
  S.scene.add(S.lines);

  // island nebulae
  const ng = new THREE.Group();
  for (const c of S.clusters) {
    if (c.size < 8 && Math.random() < 0.45) continue;
    const m = new THREE.SpriteMaterial({
      map: softTexture(), color: c.color, transparent: true,
      opacity: c.size > 40 ? 0.20 : 0.12, depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    const sp = new THREE.Sprite(m);
    sp.userData.baseOpacity = m.opacity;
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
  S.baseRadius = Math.max(2600, (S.maxDist || 2000) * 1.8);
  const st = document.getElementById('uni-stats');
  if (st) st.textContent = `${n} entities · ${S.clusters.length} islands`;
  resetView();
  updateLOD(true);
}

function clearScene() {
  [S.core, S.halo, S.major, S.impact, S.lines, S.nebula, S.marker, S.hits].forEach(x => {
    if (!x) return;
    S.scene.remove(x);
    x.traverse ? x.traverse(o => { o.geometry && o.geometry.dispose(); o.material && o.material.dispose(); })
               : (x.geometry && x.geometry.dispose(), x.material && x.material.dispose());
  });
  S.core = S.halo = S.major = S.impact = S.lines = S.nebula = S.marker = S.hits = null;
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
  const budget = k > 0.72 ? 28 : k > 0.48 ? 50 : k > 0.3 ? 90 : k > 0.16 ? 140 : 9999;
  const ranked = S.clustersRanked || (S.clustersRanked = [...S.clusters].sort((a, b) => b.size - a.size));
  const act = new Set(ranked.slice(0, budget));
  for (const c of S.clusters) if (c.unlinked) act.add(c);
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
    applySelection();
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
  const minDeg = tier === 'major' ? 55 : tier === 'strong' ? 20 : tier === 'detail' ? 8 : 0;
  const placed = [];

  const onScreen = n => {
    const p = n.pos.clone().project(S.camera);
    if (p.z > 1 || p.z < -1) return null;
    const x = (p.x * 0.5 + 0.5) * W, y = (-p.y * 0.5 + 0.5) * H;
    if (x < -150 || x > W + 150 || y < -20 || y > H + 20) return null;
    return { x, y };
  };
  const inRange = n => n === S.selected || n === S.hovered
    || (S.selDist && S.focusAmount > 0.05 && (S.selDist.get(n.id) == null ? 99 : S.selDist.get(n.id)) <= 1)
    || n.pos.distanceTo(target) <= range;
  const represented = n => {
    const cl = S.clusterOf.get(n.id);
    return !S.activeClusters || !cl || S.activeClusters.has(cl);
  };
  const eligible = n => {
    if (n === S.selected || n === S.hovered) return true;
    if (S.selDist && S.focusAmount > 0.05) {
      const d = S.selDist.get(n.id);
      if (d == null || d > 1) return false;
    }
    if (!inRange(n) || !represented(n)) return false;
    const cl = S.clusterOf.get(n.id);
    return (n.degree || 0) >= minDeg || (cl && cl.top === n) || (Number(n.importance) || 0) >= 0.95;
  };

  // ---- islands are assigned first at the overview: the theme names explain
  // the organisation before the individual stars do
  const prevClusters = S.clusterAssigned.slice();
  const prevSet = new Set(prevClusters.map(a => a.c));
  let ci = 0;
  const tryCluster = c => {
    if (S.selDist) return false;
    if (S.activeClusters && !S.activeClusters.has(c)) return false;
    if (c.center.distanceTo(target) > range * 1.2) return false;
    const p = c.center.clone().project(S.camera);
    if (p.z > 1 || p.z < -1) return false;
    const x = (p.x * 0.5 + 0.5) * W, y = (-p.y * 0.5 + 0.5) * H;
    const el = S.clusterPool[ci];
    el._cluster = c;
    el.innerHTML = `<b>${esc(islandTitle(c))}</b><span>${c.size} ${c.size === 1 ? 'entity' : 'entities'}</span>`;
    el.style.display = '';
    const w = el.offsetWidth || 130, h = el.offsetHeight || 30;
    for (const [dx, dy] of [[0, -38], [0, 38], [-90, 0], [90, 0], [0, 0]]) {
      const xx = x + dx, yy = y + dy;
      if (xx + w / 2 < 0 || xx - w / 2 > W || yy + h / 2 < 0 || yy - h / 2 > H) continue;
      let clash = false;
      for (const r of placed) {
        if (!(xx + w / 2 < r.x - r.w / 2 || xx - w / 2 > r.x + r.w / 2 ||
              yy + h / 2 < r.y - r.h / 2 || yy - h / 2 > r.y + r.h / 2)) { clash = true; break; }
      }
      if (clash) continue;
      placed.push({ x: xx, y: yy, w: w + 8, h: h + 4 });
      el.style.display = '';
      S.clusterAssigned.push({ c, el, dx, dy });
      ci++;
      return true;
    }
    el.style.display = 'none'; el._cluster = null;
    return false;
  };
  const doClusters = (max = S.clusterPool.length) => {
    S.clusterAssigned = [];
    ci = 0;
    const cl = [...S.clusters]
      .filter(c => (!S.activeClusters || S.activeClusters.has(c))
        && c.center.distanceTo(target) <= range * 1.2)
      .sort((a, b) => (b.unlinked ? 1 : 0) - (a.unlinked ? 1 : 0) || b.size - a.size);
    for (const { c } of prevClusters) {
      if (ci >= max) break;
      if (!prevSet.has(c)) continue;
      tryCluster(c);
    }
    for (const c of cl) {
      if (ci >= max) break;
      if (prevSet.has(c)) continue;
      tryCluster(c);
    }
    for (; ci < S.clusterPool.length; ci++) {
      S.clusterPool[ci]._cluster = null; S.clusterPool[ci].style.display = 'none';
    }
  };
  if (tier === 'major') doClusters(10);

  // ---- node labels fill the remaining space (or lead at closer zooms)
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
  for (const n of ordered) {
    if (assigned.length >= S.labelPool.length) break;
    const spot = onScreen(n);
    if (!spot) continue;
    const el = S.labelPool[assigned.length];
    el._node = n;
    el.textContent = n.title;
    el.classList.toggle('extra', n === S.selected || n === S.hovered);
    el.classList.toggle('grounded', !!n.grounded);
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
  }
  S.labelAssigned = assigned;
  for (let i = assigned.length; i < S.labelPool.length; i++) {
    S.labelPool[i]._node = null; S.labelPool[i].style.display = 'none';
  }

  if (tier !== 'major') doClusters();
  const cnt = document.getElementById('uni-labelcount');
  if (cnt) cnt.textContent = String(assigned.length + S.clusterAssigned.length);
}

function updateLabels(force = false) {
  if (!S.labels) return;
  const now = performance.now();
  if (!force && now - S.lastLabel < 33) return;
  S.lastLabel = now;
  const W = S.W, H = S.H;
  const place = (n, el, dx = 0, dy = 0) => {
    if (!n || !n.pos) { el.style.display = 'none'; return; }
    const p = n.pos.clone().project(S.camera);
    if (p.z > 1 || p.z < -1) { el.style.display = 'none'; return; }
    const x = (p.x * 0.5 + 0.5) * W + dx, y = (-p.y * 0.5 + 0.5) * H + dy;
    if (x < -150 || x > W + 150 || y < -20 || y > H + 20) { el.style.display = 'none'; return; }
    el.style.display = '';
    el.style.transform = `translate3d(${x}px,${y}px,0) translate(-50%,-50%)`;
  };
  for (const { n, el } of S.labelAssigned) {
    if (S.selDist && S.focusAmount > 0.05 && (S.selDist.get(n.id) == null || S.selDist.get(n.id) > 1)) { el.style.display = 'none'; continue; }
    place(n, el);
  }
  for (const { c, el, dx, dy } of S.clusterAssigned) place({ pos: c.center }, el, dx, dy);
}

function islandTitle(c) {
  let t = String((c && (c.title || c.name)) || '');
  t = t.replace(/\s+Community$/i, '')
       .replace(/^(Peter Liam Hollas|Peter Hollas)\s*(?:[:\-–,]\s*|\band\s+)?/i, '')
       .replace(/,?\s+and\s+/gi, ' & ')
       .replace(/\s+/g, ' ')
       .trim();
  if (t.length > 52) t = t.slice(0, 49).replace(/[\s,;:&-]+\S*$/, '') + '…';
  return t || (c && c.name) || '';
}

function esc(s) { return String(s == null ? '' : s).replace(/[—–]/g, '-').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

/* ------------------------------------------------------------------ loop --- */

function tickFocus(now) {
  if (!S.selDist || S.focusAmount == null) return;
  const age = now - (S.focusAt || now);
  let a = 1;
  if (age > S.focusHold) a = Math.max(0, 1 - (age - S.focusHold) / S.focusFade);
  if (Math.abs(a - S.focusAmount) > 0.01) {
    const was = S.focusAmount;
    S.focusAmount = a;
    applySelection();
    if (a <= 0.01 && was > 0.01) { assignLabels(); updateLabels(true); }
  }
}

function loop(now) {
  S.raf = requestAnimationFrame(loop);
  if (!S.renderer || !S.camera) return;
  tickFocus(now);
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

  // scale glows with zoom so near stars stay soft and far ones stay visible.
  // While a node is focused, grow the points so distant neighbours read as
  // bright lights instead of one-pixel specks.
  const dist = S.orbit.radius;
  const fm = 1 + 1.1 * (S.focusAmount || 0);
  if (S.core) S.core.material.size = Math.max(9, Math.min(32, dist * 0.006)) * fm;
  if (S.halo) S.halo.material.size = Math.max(34, Math.min(180, dist * 0.022)) * fm;
  if (S.major) S.major.material.size = Math.max(22, Math.min(90, dist * 0.012));
  if (S.impact) S.impact.material.size = Math.max(30, Math.min(150, dist * 0.018));
  if (S.marker && S.selected) {
    const pulse = 1 + Math.sin(now * 0.004) * 0.16;
    const s = (S.marker.userData.base || 40) * pulse;
    S.marker.scale.setScalar(s);
    S.marker.material.opacity = 0.38 + Math.sin(now * 0.004) * 0.12;
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
  S.orbit.target.set(0, 0, 0); S.auto = false; S.selected = null; S.hovered = null; S.selDist = null; S.focusAmount = 0;
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

function graphDistances(startId) {
  const dist = new Map([[startId, 0]]);
  const q = [startId];
  while (q.length) {
    const x = q.shift();
    const d = dist.get(x);
    for (const e of (S.adj.get(x) || [])) {
      if (!dist.has(e.id)) { dist.set(e.id, d + 1); q.push(e.id); }
    }
  }
  return dist;
}

function applySelection() {
  if (!S.coreColors) return;
  const sel = S.selDist;
  const core = S.coreColors, halo = S.haloColors;
  const amt0 = sel ? (S.focusAmount == null ? 1 : S.focusAmount) : 0;
  S.nodes.forEach((n, i) => {
    const cl = S.clusterOf.get(n.id);
    let lod = (!S.activeClusters || !cl || S.activeClusters.has(cl)) ? 1 : 0.04;
    let f = 1, glow = 1;
    if (sel && amt0 > 0) {
      const d = sel.get(n.id);
      const D = S.focusDepth || 2;
      let ff = 1, gg = 1;
      if (d == null) { ff = 0.006; gg = 0; }
      else if (d === 0) { ff = 1; gg = 2.0; }
      else if (d === 1) { ff = 1; gg = 1.55; }
      else if (d <= D) { ff = Math.max(0.45, 0.68 - (d - 2) * 0.15); gg = 1.12; }
      else { ff = 0.012; gg = 0; }
      f = 1 - amt0 * (1 - ff);
      glow = 1 + amt0 * (gg - 1);
      // Keep the focused neighbours lit even when their island is outside the
      // current level of detail; otherwise the subgraph stays invisible.
      if (d != null && d <= D) lod = 1;
    }
    const c = n.colorObj;
    let r = c.r * lod * Math.min(1, f), g = c.g * lod * Math.min(1, f), b = c.b * lod * Math.min(1, f);
    if (n === S.selected) {
      r = Math.min(1, r * 0.35 + 0.65);
      g = Math.min(1, g * 0.35 + 0.65);
      b = Math.min(1, b * 0.35 + 0.65);
    }
    core[i * 3] = r; core[i * 3 + 1] = g; core[i * 3 + 2] = b;
    if (halo) {
      halo[i * 3] = Math.min(3, r * glow);
      halo[i * 3 + 1] = Math.min(3, g * glow);
      halo[i * 3 + 2] = Math.min(3, b * glow);
    }
  });
  S.core.geometry.attributes.color.needsUpdate = true;
  if (S.halo) S.halo.geometry.attributes.color.needsUpdate = true;
  if (S.halo) S.halo.material.opacity = 0.3 + amt0 * 0.35;
  if (S.lines) S.lines.material.opacity = 0.085 + amt0 * (0.30 - 0.085);
  if (S.impact) S.impact.material.opacity = 1 - amt0;
  if (S.major) S.major.material.opacity = 1 - amt0;
  if (S.nebula) S.nebula.children.forEach(sp => {
    const base = sp.userData.baseOpacity == null ? 0.12 : sp.userData.baseOpacity;
    sp.material.opacity = base * (1 - 0.7 * amt0);
  });
  if (S.lines && S.linkBaseColors) {
    const attr = S.lines.geometry.attributes.color;
    const base = S.linkBaseColors;
    for (let i = 0; i < S.links.length; i++) {
      const l = S.links[i];
      let f = 1;
      if (sel && amt0 > 0) {
        const a = sel.get(l.source), b = sel.get(l.target);
        const D = S.focusDepth || 2;
        const ff = (a === 0 || b === 0) ? 1
          : (a != null && b != null && a <= D && b <= D) ? 0.28 : 0.01;
        f = 1 - amt0 * (1 - ff);
      }
      for (let k = 0; k < 6; k++) attr.array[i * 6 + k] = base[i * 6 + k] * f;
    }
    attr.needsUpdate = true;
  }
}

function clearFocus() {
  if (!S.selected && !S.selDist && !S.focusAmount) return;
  S.selected = null; S.selDist = null; S.focusAmount = 0;
  if (S.marker) S.marker.visible = false;
  applySelection();
  assignLabels();
  updateLabels(true);
  setSide(null);
  if (S.returnView) {
    flyTo(S.returnView.target, S.returnView.radius, 700);
    S.returnView = null;
  }
}

function focusFrame(n, dist) {
  const pts = [n];
  for (const m of S.nodes) {
    const d = dist.get(m.id);
    if (m !== n && d != null && d <= 1) pts.push(m);
  }
  let spread = 0, nearest = Infinity;
  for (const m of pts) {
    const d = n.pos.distanceTo(m.pos);
    spread = Math.max(spread, d);
    if (m !== n) nearest = Math.min(nearest, d);
  }
  const local = Number.isFinite(nearest) ? nearest * 4.5 + 300 : 500;
  const wide = spread * 2.0 + 260;
  // Attached nodes sit beside their anchor, so frame the anchor rather than a
  // distant second neighbour. Ordinary selections keep the wider framing.
  const radius = n.attached ? Math.min(wide, local) : wide;
  return { center: n.pos.clone(), radius: Math.max(500, Math.min(2600, radius)) };
}

function select(n) {
  if (!S.selected) S.returnView = { target: S.orbit.target.clone(), radius: S.orbit.radius };
  S.selected = n; S.auto = false;
  S.selDist = graphDistances(n.id);
  S.focusAmount = 1;
  S.focusAt = performance.now();
  applySelection();
  setSide(n);
  const frame = focusFrame(n, S.selDist);
  flyTo(frame.center, frame.radius, 950);
  if (S.marker) {
    S.marker.visible = true;
    S.marker.position.copy(n.pos);
    S.marker.userData.base = Math.max(56, n.radius * 6.2);
    S.marker.scale.setScalar(S.marker.userData.base);
    S.marker.material.color.copy(n.colorObj).lerp(new THREE.Color('#ffffff'), 0.62);
  }
  updateLOD(true);
}

function flyToCluster(c) {
  const radius = Math.max(420, c.spread * 3.4);
  S.selected = null; S.selDist = null; S.focusAmount = 0; S.returnView = null; S.auto = false;
  applySelection(); assignLabels(); updateLabels(true);
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
      Click a star to inspect it and light its subgraph, click an island label to travel there, double-click a star to fly in close.
    </div>`;
    return;
  }
  const req = (S.sideReq || 0) + 1;
  S.sideReq = req;
  box.innerHTML = `<div class="muted mini">loading node details…</div>`;
  const token = document.body.dataset.sessionToken || '';
  fetch('/api/graph/node?title=' + encodeURIComponent(n.title), {
    headers: token ? { 'X-Session': token } : {}
  }).then(r => r.json()).then(d => {
    if (req !== S.sideReq) return;
    if (!d || d.error) { box.innerHTML = `<div class="bad">${esc((d && d.error) || 'could not load details')}</div>`; return; }
    renderNodeSide(d);
  }).catch(e => { if (req === S.sideReq) box.innerHTML = `<div class="bad">${esc(String(e))}</div>`; });
}

function renderNodeSide(d) {
  const box = document.getElementById('uni-side');
  if (!box) return;
  const layers = (d.subgraph && d.subgraph.layers || [])
    .map(x => `<span class="kg-tag">${x.distance}: ${x.nodes}</span>`).join(' ');
  const sources = (d.sources || []).map(s => `<div class="uni-src">${esc(s)}</div>`).join('')
    || '<span class="muted mini">No document source recorded.</span>';
  const neigh = (d.neighbours || []).map(n =>
    `<button class="uni-neigh" data-title="${esc(n.title)}" onclick="window.__uni && window.__uni.selectByTitle(this.dataset.title)">
      ${esc(n.title)} <span>${esc(n.type)} · ${n.weight}</span></button>`).join('')
    || '<span class="muted mini">No direct neighbours.</span>';
  const conns = (d.connections || []).slice(0, 8).map(c =>
    `<div class="uni-conn">${esc(c.source)} to ${esc(c.target)} <span>${c.weight}</span></div>`).join('')
    || '<span class="muted mini">No strong local connections.</span>';
  box.innerHTML = `<div class="uni-kind">${esc(d.class_label || d.type || 'entity')} · impact ${Math.round((d.importance || 0) * 100)}%${d.grounded ? ' · grounded' : ''}</div>
    <h3>${esc(d.title)}</h3>
    <div class="uni-meta">${d.degree || 0} links · ${d.frequency || 0} mention${d.frequency === 1 ? '' : 's'} · ${esc(d.community_title || ((d.degree || 0) === 0 ? 'unlinked evidence' : 'no community'))}</div>
    <p>${esc(d.description || 'No description in the index.')}</p>
    ${(d.degree || 0) === 0 ? '<p class="muted mini">No relationship was extracted for this entity, so it sits in the Unlinked evidence island. It stays available to search and role evidence.</p>' : ''}
    ${d.evidence ? `<div class="uni-evidence"><b>Evidence</b>${esc(d.evidence)}</div>` : ''}
    <div class="uni-subgraph"><b>Subgraph</b> ${d.subgraph ? d.subgraph.nodes : 1} nodes · ${d.subgraph ? d.subgraph.links : 0} links · depth ${d.subgraph ? d.subgraph.max_depth : 0}<div>${layers}</div><div class="muted mini" style="margin-top:3px">Highlight shows the selected node and its ${(S.focusDepth || 1) === 1 ? 'direct neighbours' : `nearest ${S.focusDepth} hops`}; the counts cover the whole connected subgraph. The dimming fades after a few seconds; the selected node stays marked.</div></div>
    <h4>Sources</h4>${sources}
    <h4>Neighbours</h4><div class="uni-neigh-list">${neigh}</div>
    <h4>Strongest connections</h4>${conns}
    <div class="uni-actions">
      <button class="small" data-title="${esc(d.title)}" onclick="App.editNode(this.dataset.title)">Edit details</button>
      <button class="small" onclick="window.__uni && window.__uni.focusSelected()">Fly here</button>
      <button class="small" onclick="window.__uni && window.__uni.reset()">Reset view</button>
    </div>`;
}

function setSideCluster(c) {
  const box = document.getElementById('uni-side');
  if (!box) return;
  box.innerHTML = `<div class="uni-kind">island</div>
    <h3>${esc(islandTitle(c))}</h3>
    <div class="uni-meta">${c.size} ${c.unlinked ? 'unlinked entities' : `entities · community ${String(c.key).replace(/^c/, '')}`}</div>
    <p>${c.unlinked
      ? 'These entities appear in the evidence but no relationship was extracted for them, so they cannot be placed in a theme. They stay available to search and role evidence.'
      : 'The island is named after its best-connected entity. Its neighbours orbit it; click any star or use search to jump straight to one.'}</p>
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
  c.addEventListener('mousedown', e => e.preventDefault());
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
    if (S.drag && !S.drag.moved) {
      const n = hitAt(e.clientX, e.clientY);
      if (n) select(n);
      else clearFocus();
    }
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
  const focus = document.getElementById('uni-focus');
  if (focus) {
    S.focusDepth = +focus.value || S.focusDepth;
    const fv = document.getElementById('uni-focus-v');
    if (fv) fv.textContent = S.focusDepth + ' hop' + (S.focusDepth === 1 ? '' : 's');
    focus.addEventListener('input', () => {
      S.focusDepth = Math.max(1, Math.min(3, +focus.value || 1));
      if (fv) fv.textContent = S.focusDepth + ' hop' + (S.focusDepth === 1 ? '' : 's');
      S.focusAmount = S.selDist ? 1 : 0;
      S.focusAt = performance.now();
      applySelection(); assignLabels(); updateLabels(true);
    });
  }
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

export async function reload() {
  if (!S.inited) return;
  S.data = null;
  await load();
}

export function selectByTitle(title) {
  const n = S.nodes.find(x => x.title.toLowerCase() === String(title).toLowerCase());
  if (n) select(n);
}

export function reset() { if (S.data) resetView(); }

export function view(theta, phi, radius) {
  if (!S.data) return;
  if (theta != null) S.orbit.theta = Number(theta);
  if (phi != null) S.orbit.phi = Number(phi);
  if (radius != null) S.orbit.radius = Number(radius);
  S.auto = false; S.fly = null;
  updateLOD(true);
}

export function focusSelected() {
  if (S.selected) flyTo(S.selected.pos.clone(), 240 + Math.min(700, (S.selected.degree || 1) * 4.5), 800);
}

export function search(q) {
  q = String(q == null ? '' : q).trim().toLowerCase();
  const st = document.getElementById('uni-stats');
  if (!q || !S.nodes.length) {
    if (st && S.nodes.length) st.textContent = `${S.nodes.length} entities · ${S.clusters.length} islands`;
    return 0;
  }
  const hits = S.nodes.filter(n => (n.title + ' ' + (n.description || '')).toLowerCase().includes(q));
  const rank = n => {
    const t = (n.title || '').toLowerCase();
    return (t === q ? 100 : t.startsWith(q) ? 70 : t.includes(q) ? 45 : 0)
      + Math.min(30, (n.degree || 0) / 12);
  };
  hits.sort((a, b) => rank(b) - rank(a));
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
    select(hits[0]);
  }
  if (st) st.textContent = `${hits.length} match${hits.length === 1 ? '' : 'es'} for “${q}” · ${S.nodes.length} entities`;
  return hits.length;
}


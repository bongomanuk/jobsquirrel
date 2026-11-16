/* The critters: a properly rigged low-poly squirrel (three.js), plus friends.
 *
 * The squirrel scurries flat on all fours, sits up on its haunches to eat, and
 * has a small set of actions: look at the pointer, hop, wave, groom, stretch,
 * sleep, pull a face, kick acorns. He lives in the logo slot in the top bar and
 * returns there after every adventure. On the right day the gang duels with
 * little swords, pelts each other with nuts, forages in the grove (burying,
 * digging up and nibbling the stash), and when it snows they sledge and throw
 * snowballs.
 *
 * One transparent WebGL canvas spans the bar, so every squirrel and acorn is in
 * one scene. Nothing blocks clicks, the loop stops when nothing is happening,
 * and prefers-reduced-motion wins.
 */
import * as THREE from './vendor/three.module.min.js';

const BAR = 72;                  // canvas height, CSS pixels
const FLOOR = -BAR / 2 + 34;     // feet land inside the 56px bar
const SCALE = 25;                // model units -> pixels
const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)');
let optedOut = false;
try { optedOut = localStorage.getItem('ui.critters') === '0'; } catch (e) {}
if (reduce && reduce.matches) optedOut = true;

const state = {
  renderer: null, scene: null, camera: null, canvas: null,
  critters: [], nuts: [], raf: 0, clock: null, W: 1,
  resident: null, perches: [],
  pointer: { x: 0, y: -999 }, lastPoke: 0,
  snow: null, fx: [], trees: [], grove: null, disco: null, house: null,
};

const MAT = {
  fur: new THREE.MeshStandardMaterial({ color: 0xc98a52, roughness: 0.85 }),
  friend: new THREE.MeshStandardMaterial({ color: 0xa9713f, roughness: 0.9 }),
  furDark: new THREE.MeshStandardMaterial({ color: 0xa4632f, roughness: 0.9 }),
  cream: new THREE.MeshStandardMaterial({ color: 0xf3e6d2, roughness: 0.9 }),
  vest: new THREE.MeshStandardMaterial({ color: 0x6f7d5c, roughness: 0.9 }),
  gold: new THREE.MeshStandardMaterial({ color: 0xe8c98d, roughness: 0.3, metalness: 0.6 }),
  dark: new THREE.MeshStandardMaterial({ color: 0x2b2118, roughness: 0.5 }),
  nut: new THREE.MeshStandardMaterial({ color: 0xc08a4e, roughness: 0.85 }),
  nutCap: new THREE.MeshStandardMaterial({ color: 0x6b4a2a, roughness: 0.9 }),
  beer: new THREE.MeshStandardMaterial({ color: 0xd9a45f, roughness: 0.4 }),
  blade: new THREE.MeshStandardMaterial({ color: 0xf2f6ff, roughness: 0.2, metalness: 0.8, emissive: 0x6f84a8, emissiveIntensity: 0.55 }),
  foam: new THREE.MeshStandardMaterial({ color: 0xf7f0de, roughness: 1 }),
  snow: new THREE.MeshStandardMaterial({ color: 0xf3f8ff, roughness: 0.95 }),
  snowball: new THREE.MeshStandardMaterial({ color: 0xd8e6f7, roughness: 0.9 }),
  leaf: new THREE.MeshStandardMaterial({ color: 0x506b52, roughness: 0.92 }),
  leaf2: new THREE.MeshStandardMaterial({ color: 0x5f7a5b, roughness: 0.92 }),
  leaf3: new THREE.MeshStandardMaterial({ color: 0x46604a, roughness: 0.92 }),
  sled: new THREE.MeshStandardMaterial({ color: 0xb5654a, roughness: 0.75 }),
  wall: new THREE.MeshStandardMaterial({ color: 0x8a6a4a, roughness: 0.9 }),
  roof: new THREE.MeshStandardMaterial({ color: 0x4a3a2e, roughness: 0.95 }),
  stick: new THREE.MeshStandardMaterial({ color: 0x9a6b3f, roughness: 0.9 }),
  tongue: new THREE.MeshStandardMaterial({ color: 0xd97b8a, roughness: 0.7 }),
};

function makeCanvas() {
  if (state.canvas) return state.canvas;
  const c = document.createElement('canvas');
  c.id = 'critter-canvas';
  c.setAttribute('aria-hidden', 'true');
  document.body.appendChild(c);
  const r = new THREE.WebGLRenderer({ canvas: c, alpha: true, antialias: true });
  r.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  r.setClearColor(0x000000, 0);
  r.shadowMap.enabled = true;
  r.shadowMap.type = THREE.PCFSoftShadowMap;
  state.renderer = r;
  state.canvas = c;
  state.scene = new THREE.Scene();
  state.clock = new THREE.Clock();
  state.scene.add(new THREE.AmbientLight(0xffffff, 1.15));
  const key = new THREE.DirectionalLight(0xfff3e2, 1.7);
  key.position.set(-60, 120, 90);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.left = -420; key.shadow.camera.right = 420;
  key.shadow.camera.top = 160; key.shadow.camera.bottom = -120;
  key.shadow.camera.near = 1; key.shadow.camera.far = 800;
  key.shadow.bias = -0.0004;
  state.scene.add(key);
  const rim = new THREE.DirectionalLight(0xbfd4ff, 0.75);
  rim.position.set(2, 1.2, -3);
  state.scene.add(rim);
  resize();
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(4000, 240),
    new THREE.ShadowMaterial({ opacity: 0.22 }));
  ground.rotation.x = -Math.PI / 2;
  ground.position.set(0, FLOOR - 0.5, 0);
  ground.receiveShadow = true;
  state.scene.add(ground);
  state.ground = ground;
  placeGrove();
  window.addEventListener('resize', resize);
  return c;
}

function resize() {
  if (!state.renderer) return;
  const w = Math.max(320, window.innerWidth);
  state.W = w;
  state.renderer.setSize(w, BAR, false);
  state.canvas.style.width = w + 'px';
  state.canvas.style.height = BAR + 'px';
  if (state.ground) { state.ground.position.y = FLOOR - 0.5; }
  if (!state.camera) {
    state.camera = new THREE.OrthographicCamera(-w / 2, w / 2, BAR / 2, -BAR / 2, 0.1, 100);
    state.camera.position.set(0, 0, 20);
  } else {
    state.camera.left = -w / 2; state.camera.right = w / 2;
    state.camera.top = BAR / 2; state.camera.bottom = -BAR / 2;
    state.camera.updateProjectionMatrix();
  }
  if (state.scene) placeGrove();
}

function ball(r, m, x, y, z) {
  const s = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 12), m);
  s.position.set(x, y, z);
  return s;
}
function limb(r, len, m) {
  return new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 4, 8), m);
}

/* A soft round sprite for snow spray, impacts and little sword sparks. */
let TEX_PUFF = null;
function puffTexture() {
  if (TEX_PUFF) return TEX_PUFF;
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, 'rgba(255,255,255,.95)');
  grd.addColorStop(.45, 'rgba(255,255,255,.45)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, 64, 64);
  TEX_PUFF = new THREE.CanvasTexture(c);
  return TEX_PUFF;
}

function addPuff(x, y, opts = {}) {
  if (!state.scene) return;
  const mat = new THREE.SpriteMaterial({
    map: puffTexture(),
    color: opts.color || '#ffffff',
    transparent: true, opacity: opts.opacity || 0.85, depthWrite: false,
  });
  const sp = new THREE.Sprite(mat);
  const size = opts.size || 6;
  sp.position.set(x, y, 0.35);
  sp.scale.setScalar(size);
  state.scene.add(sp);
  state.fx.push({
    sp, born: performance.now(), life: opts.life || 450, base: size,
    vx: opts.vx || 0, vy: opts.vy || 0, grow: opts.grow == null ? 1.1 : opts.grow,
  });
}

/* A squirrel rig. Ground at y = 0, facing +Z.
 * root -> hips (torso, chest, head, tail, front legs) + hind legs on the root,
 * so the haunches stay planted when he sits up. */
export function buildSquirrel(friend = false) {
  const fur = friend ? MAT.friend : MAT.fur;
  const root = new THREE.Group();
  const hips = new THREE.Group();
  hips.position.set(0, 0.34, 0);
  root.add(hips);

  const torso = ball(0.28, fur, 0, 0.04, 0.12);
  torso.scale.set(0.74, 0.66, 1.06);           // rounder and softer
  hips.add(torso);
  const belly = ball(0.22, MAT.cream, 0, -0.06, 0.18);
  belly.scale.set(0.72, 0.62, 0.98);
  hips.add(belly);
  const vest = new THREE.Mesh(
    new THREE.SphereGeometry(0.29, 16, 12, Math.PI * 0.12, Math.PI * 0.76, 1.1, 1.1), MAT.vest);
  vest.scale.set(0.76, 0.68, 1.08);
  vest.position.set(0, 0.04, 0.12);
  hips.add(vest);

  const chest = new THREE.Group();
  chest.position.set(0, 0.08, 0.34);
  hips.add(chest);
  const neck = new THREE.Group();
  neck.position.set(0, 0.14, 0.1);
  chest.add(neck);

  const head = new THREE.Group();
  neck.add(head);
  const skull = ball(0.2, fur, 0, 0, 0);
  skull.scale.set(0.8, 0.72, 0.7);
  head.add(skull);
  const muzzle = ball(0.1, MAT.cream, 0, -0.045, 0.09);
  muzzle.scale.set(0.55, 0.42, 0.6);
  head.add(muzzle);
  for (const s of [-1, 1]) {
    const cheek = ball(0.075, fur, 0.1 * s, -0.04, 0.06);
    cheek.scale.set(0.9, 0.75, 0.75);
    head.add(cheek);
  }
  head.add(ball(0.02, MAT.dark, 0, -0.025, 0.15));
  head.add(ball(0.03, MAT.dark, 0.06, 0.045, 0.12));
  head.add(ball(0.03, MAT.dark, -0.06, 0.045, 0.12));
  for (const s of [-1, 1]) {
    const ear = new THREE.Mesh(new THREE.ConeGeometry(0.052, 0.15, 8), MAT.furDark);
    ear.position.set(0.08 * s, 0.16, -0.02);
    ear.rotation.z = -0.18 * s;
    head.add(ear);
    const tuft = new THREE.Mesh(new THREE.ConeGeometry(0.02, 0.1, 6), MAT.furDark);
    tuft.position.set(0.093 * s, 0.255, -0.03);
    tuft.rotation.z = -0.25 * s;
    head.add(tuft);
    const lens = new THREE.Mesh(new THREE.TorusGeometry(0.07, 0.013, 8, 18), MAT.gold);
    lens.position.set(0.062 * s, 0.035, 0.17);
    head.add(lens);
  }
  const bridge = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.04, 6), MAT.gold);
  bridge.rotation.z = Math.PI / 2;
  bridge.position.set(0, 0.04, 0.175);
  head.add(bridge);
  const tongue = new THREE.Mesh(new THREE.SphereGeometry(0.028, 10, 8), MAT.tongue);
  tongue.position.set(0, -0.09, 0.15);
  tongue.scale.set(1, 0.5, 1);
  tongue.visible = false;
  head.add(tongue);

  // three-segment tail, curling up behind
  const tail1 = new THREE.Group();
  tail1.position.set(0, 0.08, -0.2);
  hips.add(tail1);
  const t1 = ball(0.12, MAT.furDark, 0, 0.1, -0.03);
  t1.scale.set(0.8, 1.5, 0.8);
  tail1.add(t1);
  const tail2 = new THREE.Group();
  tail2.position.set(0, 0.28, 0);
  tail1.add(tail2);
  const t2 = ball(0.15, MAT.furDark, 0, 0.1, 0);
  t2.scale.set(0.8, 1.4, 0.8);
  tail2.add(t2);
  const tail3 = new THREE.Group();
  tail3.position.set(0, 0.28, 0);
  tail2.add(tail3);
  const t3 = ball(0.12, MAT.furDark, 0, 0.08, 0.02);
  t3.scale.set(0.75, 1.3, 0.75);
  tail3.add(t3);

  // front legs: shoulder -> elbow -> paw (children of the hips)
  const front = [];
  for (const s of [-1, 1]) {
    const shoulder = new THREE.Group();
    shoulder.position.set(0.12 * s, 0.0, 0.3);
    hips.add(shoulder);
    const upper = limb(0.05, 0.09, MAT.furDark);
    upper.position.y = -0.06;
    shoulder.add(upper);
    const elbow = new THREE.Group();
    elbow.position.y = -0.13;
    shoulder.add(elbow);
    const fore = limb(0.045, 0.09, MAT.furDark);
    fore.position.y = -0.06;
    elbow.add(fore);
    const paw = ball(0.055, MAT.furDark, 0, -0.13, 0.02);
    paw.scale.set(1, 0.6, 1.3);
    elbow.add(paw);
    front.push({ shoulder, elbow });
  }

  // hind legs: hip -> knee -> long foot, on the root so they stay planted
  const hind = [];
  for (const s of [-1, 1]) {
    const hip = new THREE.Group();
    hip.position.set(0.15 * s, 0.36, -0.1);
    root.add(hip);
    const thigh = limb(0.085, 0.14, MAT.furDark);
    thigh.position.y = -0.1;
    hip.add(thigh);
    const knee = new THREE.Group();
    knee.position.y = -0.2;
    hip.add(knee);
    const shin = limb(0.06, 0.1, MAT.furDark);
    shin.position.y = -0.07;
    knee.add(shin);
    const foot = ball(0.075, MAT.furDark, 0, -0.17, 0.09);
    foot.scale.set(1, 0.45, 2.2);
    knee.add(foot);
    hind.push({ hip, knee });
  }

  const acorn = new THREE.Group();
  acorn.position.set(0, 0.1, 0.28);
  hips.add(acorn);
  const nut = ball(0.05, MAT.nut, 0, 0, 0);
  nut.scale.set(1, 1.25, 1);
  acorn.add(nut);
  const cap = new THREE.Mesh(new THREE.SphereGeometry(0.055, 12, 8, 0, Math.PI * 2, 0, Math.PI / 2), MAT.nutCap);
  cap.position.y = 0.04;
  acorn.add(cap);

  // a nut in the mouth, for carrying one to a cache or nibbling one dug up
  const heldNut = new THREE.Group();
  heldNut.position.set(0, -0.09, 0.17);
  heldNut.visible = false;
  const hnut = ball(0.065, MAT.nut, 0, 0, 0);
  hnut.scale.set(1, 1.25, 1);
  heldNut.add(hnut);
  const hcap = new THREE.Mesh(new THREE.SphereGeometry(0.07, 12, 8, 0, Math.PI * 2, 0, Math.PI / 2), MAT.nutCap);
  hcap.position.y = 0.04;
  heldNut.add(hcap);
  head.add(heldNut);

  const sword = new THREE.Group();
  // a good stout stick, gripped at the right paw and held up for a scrap
  sword.position.set(0.16, 0.1, 0.4);
  sword.rotation.set(1.05, 0, -0.25);
  sword.visible = false;
  chest.add(sword);
  const stick = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.065, 0.85, 6), MAT.stick);
  stick.position.y = 0.425;
  sword.add(stick);
  const twig = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.03, 0.24, 5), MAT.stick);
  twig.position.set(0.04, 0.78, 0);
  twig.rotation.z = 0.7;
  sword.add(twig);
  sword.add(ball(0.045, MAT.stick, 0, 0.06, 0));

  const beer = new THREE.Group();
  beer.position.set(0, -0.16, 0.08);
  beer.visible = false;
  front[0].elbow.add(beer);
  const glass = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.055, 0.13, 10), MAT.beer);
  beer.add(glass);
  const foam = ball(0.062, MAT.foam, 0, 0.075, 0);
  foam.scale.set(1, 0.55, 1);
  beer.add(foam);
  const handle = new THREE.Mesh(new THREE.TorusGeometry(0.045, 0.011, 6, 10, Math.PI * 1.2), MAT.beer);
  handle.position.set(0.065, 0, 0);
  handle.rotation.z = -0.4;
  beer.add(handle);

  // a little wooden sledge, hidden until a snow day
  const sled = new THREE.Group();
  sled.position.set(0, 0.015, 0.06);
  sled.visible = false;
  const board = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.06, 1.08), MAT.sled);
  board.position.y = 0.04;
  sled.add(board);
  for (const s of [-1, 1]) {
    const runner = new THREE.Mesh(new THREE.BoxGeometry(0.045, 0.055, 1.16), MAT.blade);
    runner.position.set(0.2 * s, -0.03, 0.02);
    sled.add(runner);
    const strut = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.07, 0.07), MAT.sled);
    strut.position.set(0.2 * s, 0.01, -0.3);
    sled.add(strut);
  }
  root.add(sled);


  root.traverse(o => { if (o.isMesh) o.castShadow = true; });
  root.scale.setScalar(SCALE);
  return { root, hips, chest, neck, head, tail: [tail1, tail2, tail3],
           front, hind, tongue, beer, sword, acorn, sled, heldNut };
}

function makeNut() {
  const g = new THREE.Group();
  const n = ball(0.1, MAT.nut, 0, 0, 0);
  n.scale.set(1, 1.2, 1);
  g.add(n);
  const cap = new THREE.Mesh(new THREE.SphereGeometry(0.1, 10, 6, 0, Math.PI * 2, 0, Math.PI / 2), MAT.nutCap);
  cap.position.y = 0.05;
  g.add(cap);
  g.scale.setScalar(SCALE);
  return g;
}

function makeSnowball() {
  const g = new THREE.Group();
  const b = ball(0.13, MAT.snowball, 0, 0, 0);
  b.scale.set(1.1, 1, 1.1);
  g.add(b);
  g.scale.setScalar(SCALE);
  return g;
}

function addCritter(opts) {
  const s = buildSquirrel(!!opts.friend);
  s.root.rotation.y = Math.PI / 2;
  s.root.position.set(opts.x, FLOOR, 0);
  state.scene.add(s.root);
  const c = {
    ...s, x: opts.x, y: FLOOR, speed: opts.speed || 0, phase: Math.random() * 6,
    endX: opts.endX || 1e9, holdAt: opts.holdAt || 0, holdUntil: 0, held: false,
    beerOn: false, waveOn: false, waveUntil: 0, faceUntil: 0, groom: false,
    dive: !!opts.dive, nextKick: performance.now() + 700,
    nextAction: performance.now() + 2500, home: opts.x, target: opts.x,
    adventuring: false, look: { x: 0, y: 0 }, pose: '', poseUntil: 0,
    mode: 'travel', meetX: 0, drinkUntil: 0, clinkAt: 0, clink: false, fightUntil: 0, roll: 0, duel: false,
    trickUntil: 0, social: false, tagUntil: 0, visitUntil: 0,
    partner: null, playUntil: 0, nextThrow: 0, sledOn: false, sledSpeed: 0, sprayAt: 0,
    bonkUntil: 0, sparkAt: 0, tree: null, forageX: 0, forageAt: 0, carried: false,
    eatingUntil: 0, foraged: false, throwUntil: 0, danceUntil: 0, buildUntil: 0,
    baby: false, babyUntil: 0, babyTarget: 0, nextBabyTarget: 0,
    fightAt: 0, attackUntil: 0, chipAt: 0,
  };
  state.critters.push(c);
  return c;
}

function removeCritter(c) {
  state.scene.remove(c.root);
  c.root.traverse(o => { if (o.geometry) o.geometry.dispose(); });
  state.critters = state.critters.filter(x => x !== c);
}

function kickNut(from) {
  if (!from) return;
  const nut = makeNut();
  nut.position.set(from.x + 6, FLOOR + 4, 0.2);
  state.scene.add(nut);
  state.nuts.push({
    mesh: nut, x: from.x + 6, y: FLOOR + 4, born: performance.now(),
    vx: 140 + Math.random() * 160, vy: 180 + Math.random() * 170,
    spin: (Math.random() - 0.5) * 14, rot: 0, kind: 'nut', from, hit: false,
  });
}

/* A thrown nut or snowball: solved for a gravity arc that lands on the target,
 * so the two of them can actually pelt each other rather than firing sideways. */
function throwAt(from, to, kind = 'nut') {
  if (!from || !to || from === to) return;
  from.throwUntil = performance.now() + 240;
  const mesh = kind === 'snow' ? makeSnowball() : makeNut();
  const dir = Math.sign(to.x - from.x) || 1;
  const x0 = from.x + dir * 9;
  const y0 = FLOOR + 17;
  const dx = to.x - x0;
  const dy = (FLOOR + 15) - y0;
  const T = 0.3 + Math.abs(dx) / 2600;
  const vx = dx / T;
  const vy = (dy + 0.5 * 900 * T * T) / T;
  mesh.position.set(x0, y0, 0.25);
  state.scene.add(mesh);
  state.nuts.push({
    mesh, x: x0, y: y0, vx, vy, kind, from, born: performance.now(), hit: false,
    spin: (Math.random() - 0.5) * 10, rot: 0,
  });
}

/* ---------- snow ---------- */
function startSnow(ms = 15000) {
  const now = performance.now();
  ensureLoop();
  if (state.snow) { state.snow.until = Math.max(state.snow.until, now + ms); return; }
  const n = 170;
  const span = Math.max(1200, state.W / 2 + 80);
  const pos = new Float32Array(n * 3);
  const vel = [];
  for (let i = 0; i < n; i++) {
    pos[i * 3] = (Math.random() - 0.5) * span;
    pos[i * 3 + 1] = FLOOR + Math.random() * (BAR + 30);
    pos[i * 3 + 2] = -8 + Math.random() * 8;
    vel.push({ fall: 16 + Math.random() * 30, drift: (Math.random() - 0.5) * 14,
               sway: Math.random() * 6.28 });
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const points = new THREE.Points(geo, new THREE.PointsMaterial({
    map: puffTexture(), color: 0x93abc9, size: 3.2, transparent: true,
    opacity: 0.9, depthWrite: false, sizeAttenuation: false,
  }));
  state.scene.add(points);
  // the snow bank that builds up along the bar over the first few seconds
  const bank = new THREE.Group();
  const moundGeo = new THREE.SphereGeometry(1, 10, 6);
  const bankMat = new THREE.MeshBasicMaterial({ color: 0xc7d7ea, transparent: true,
                                                opacity: 0.98, depthWrite: false });
  const bankSpan = Math.max(1200, state.W + 200);
  const count = 22;
  const mounds = [];
  for (let i = 0; i < count; i++) {
    const m = new THREE.Mesh(moundGeo, bankMat);
    m.position.set(-bankSpan / 2 + (i + 0.5) * (bankSpan / count), FLOOR + 1, 0.15);
    m.scale.set((bankSpan / count) * 0.72, 0, 4);
    m.userData.h = 4 + Math.random() * 5;
    bank.add(m);
    mounds.push(m);
  }
  state.scene.add(bank);
  state.snow = { points, geo, vel, bank, mounds, born: now, until: now + ms };
  for (const t of state.trees) for (const c of t.caps) c.visible = true;
  document.body.dataset.snow = '1';
}

function stopSnow() {
  if (!state.snow) return;
  state.scene.remove(state.snow.points);
  state.snow.points.geometry.dispose();
  state.snow.points.material.dispose();
  state.scene.remove(state.snow.bank);
  state.snow.bank.traverse(o => { if (o.isMesh && o.geometry) o.geometry.dispose(); });
  state.snow = null;
  for (const t of state.trees) for (const c of t.caps) c.visible = false;
  delete document.body.dataset.snow;
}

/* ---------- trees and the winter larder ---------- */
function baseNut() {
  const g = new THREE.Group();
  const b = ball(0.12, MAT.nut, 0, 0, 0);
  b.scale.set(1, 1.2, 1);
  g.add(b);
  const cap = new THREE.Mesh(new THREE.SphereGeometry(0.13, 10, 6, 0, Math.PI * 2, 0, Math.PI / 2), MAT.nutCap);
  cap.position.y = 0.05;
  g.add(cap);
  return g;
}

function syncTree(t) {
  if (!t) return;
  t.nuts.forEach((n, i) => { n.visible = i < Math.min(4, t.cache); });
}

const GROVE = [
  { dx: -44, z: -2.4, s: 0.62, kind: 'fir', tone: 2 },
  { dx: -24, z: -1.7, s: 0.8, kind: 'fir', tone: 0 },
  { dx: -2, z: -2.1, s: 0.95, kind: 'round', tone: 0 },
  { dx: 21, z: -1.5, s: 0.72, kind: 'fir', tone: 1 },
  { dx: 41, z: -2.6, s: 0.54, kind: 'fir', tone: 2 },
];

function makeTree(def) {
  const g = new THREE.Group();
  const s = def.s || 1;
  const tone = [MAT.leaf, MAT.leaf2, MAT.leaf3][def.tone % 3] || MAT.leaf;
  const caps = [];
  if (def.kind === 'round') {
    const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.1 * s, 0.16 * s, 1.0 * s, 7), MAT.nutCap);
    trunk.position.y = 0.5 * s;
    g.add(trunk);
    for (const [dx, dy, r] of [[0, 1.18, 0.56], [-0.3, 1.0, 0.4], [0.3, 1.02, 0.42]]) {
      const blob = new THREE.Mesh(new THREE.IcosahedronGeometry(r * s, 0), tone);
      blob.position.set(dx * s, dy * s, 0);
      g.add(blob);
      const cap = new THREE.Mesh(new THREE.IcosahedronGeometry(r * 0.78 * s, 0), MAT.snow);
      cap.position.set(dx * s, (dy + r * 0.55) * s, 0.04);
      cap.visible = false;
      g.add(cap);
      caps.push(cap);
    }
  } else {
    const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.09 * s, 0.14 * s, 0.9 * s, 7), MAT.nutCap);
    trunk.position.y = 0.45 * s;
    g.add(trunk);
    const tiers = [[0.55, 0.8, 0.95], [0.44, 0.7, 1.32], [0.3, 0.55, 1.62]];
    for (const [r, h, y] of tiers) {
      const cone = new THREE.Mesh(new THREE.ConeGeometry(r * s, h * s, 8), tone);
      cone.position.y = y * s;
      g.add(cone);
      const cap = new THREE.Mesh(new THREE.ConeGeometry(r * 0.9 * s, h * 0.28 * s, 8), MAT.snow);
      cap.position.y = (y + h * 0.34) * s;
      cap.visible = false;
      g.add(cap);
      caps.push(cap);
    }
  }
  const nuts = [];
  for (let i = 0; i < 4; i++) {
    const n = baseNut();
    n.position.set((-0.5 + i * 0.34) * s, 0.06, 0.34 + (i % 2) * 0.08);
    n.visible = false;
    g.add(n);
    nuts.push(n);
  }
  g.position.set(def.dx, FLOOR, def.z || -1.6);
  g.scale.setScalar(SCALE * 0.66);
  g.traverse(o => { if (o.isMesh) o.castShadow = true; });
  const tree = { ...def, group: g, caps, nuts, cache: Math.floor(Math.random() * 3), x: def.dx };
  syncTree(tree);
  return tree;
}

function groveX(w) {
  return w < 1000 ? null : Math.round(-w * 0.16);
}

function placeGrove() {
  if (!state.scene) return;
  const x = groveX(state.W);
  if (x == null) { if (state.grove) state.grove.group.visible = false; return; }
  if (!state.grove) {
    const group = new THREE.Group();
    const trees = GROVE.map(d => {
      const t = makeTree(d);
      group.add(t.group);
      return t;
    });
    state.scene.add(group);
    state.grove = { group, trees };
    state.trees = trees;
  }
  state.grove.group.visible = true;
  state.grove.group.position.x = x;
  state.trees.forEach(t => { t.x = x + t.dx; });
  if (state.snow) state.trees.forEach(t => t.caps.forEach(c => { c.visible = true; }));
}

function startForage(c, tree, how = 'auto', side = 0) {
  if (!c || !tree) return;
  const bury = how === 'bury' || (how === 'auto' && Math.random() < 0.5);
  c.mode = 'forage';
  c.tree = tree;
  c.forageX = tree.x + (side || (c.x < tree.x ? -22 : 22));
  c.forageAt = 0;
  c.playUntil = performance.now() + 11000;
  c.carried = bury;
  c.eatingUntil = 0;
  c.foraged = false;
  c.forageAt = 0;
  if (c.heldNut) { c.heldNut.visible = bury; c.heldNut.scale.setScalar(1); }
  c.social = true;
  if (c === state.resident) {
    c.target = c.forageX;
    c.nextAction = performance.now() + 12000;
  }
}

/* ---------- disco, den and babies ---------- */
function groveWorldX() {
  return state.grove ? state.grove.group.position.x : Math.round(-state.W * 0.16);
}

function startDisco(stage) {
  if (state.disco) return;
  const g = new THREE.Group();
  const ball = new THREE.Mesh(new THREE.SphereGeometry(5.5, 16, 12),
    new THREE.MeshStandardMaterial({ color: 0xf2f6ff, metalness: 0.85, roughness: 0.18,
                                     emissive: 0x9fb4ff, emissiveIntensity: 1.1 }));
  ball.position.set(stage, BAR / 2 - 12, 2);
  const glow = new THREE.Sprite(new THREE.SpriteMaterial({
    map: puffTexture(), color: 0xff9ae0, transparent: true, opacity: 0.8,
    depthWrite: false, blending: THREE.AdditiveBlending,
  }));
  glow.scale.setScalar(30);
  glow.position.copy(ball.position);
  const string = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 14, 4), MAT.dark);
  string.position.set(stage, BAR / 2 - 1, 2);
  const light = new THREE.PointLight(0xff6ad5, 10, 300);
  light.position.set(stage, 14, 28);
  g.add(ball, glow, string, light);
  // a full-width wash of colour behind the dancers
  const washes = [];
  for (let i = 0; i < 5; i++) {
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({
      map: puffTexture(), color: 0xff6ad5, transparent: true,
      opacity: 0.14, depthWrite: false,
    }));
    sp.position.set(-state.W / 2 + (i + 0.5) * (state.W / 5), 6, -8);
    sp.scale.set(Math.max(340, state.W / 4.2), 96, 1);
    g.add(sp);
    washes.push(sp);
  }
  const lights = [];
  for (let i = 0; i < 3; i++) {
    const l = new THREE.PointLight(0xff6ad5, 7, 600);
    l.position.set(-state.W / 3 + i * (state.W / 3), 20, 32);
    g.add(l);
    lights.push(l);
  }
  state.scene.add(g);
  state.disco = { g, ball, glow, light, lights, washes, stage,
                  until: performance.now() + 7200, sparkAt: 0 };
}

function stopDisco() {
  if (!state.disco) return;
  state.scene.remove(state.disco.g);
  state.disco.g.traverse(o => { if (o.isMesh) { o.geometry.dispose(); o.material.dispose(); } });
  state.disco = null;
}

function buildHouse(x) {
  if (state.house) return state.house;
  const g = new THREE.Group();
  const wall = new THREE.Mesh(new THREE.BoxGeometry(30, 18, 16), MAT.wall);
  wall.position.y = 9;
  g.add(wall);
  const roof = new THREE.Mesh(new THREE.ConeGeometry(24, 14, 4), MAT.roof);
  roof.position.y = 25;
  roof.rotation.y = Math.PI / 4;
  g.add(roof);
  const door = new THREE.Mesh(new THREE.BoxGeometry(8, 11, 1), MAT.dark);
  door.position.set(0, 5.5, 8.2);
  g.add(door);
  const chimney = new THREE.Mesh(new THREE.BoxGeometry(5, 10, 5), MAT.wall);
  chimney.position.set(9, 27, 0);
  g.add(chimney);
  const cap = new THREE.Mesh(new THREE.ConeGeometry(22, 11, 4), MAT.snow);
  cap.position.y = 27;
  cap.rotation.y = Math.PI / 4;
  cap.visible = false;
  g.add(cap);
  g.position.set(x, FLOOR, -1.2);
  g.scale.set(1, 0.01, 1);
  g.traverse(o => { if (o.isMesh) o.castShadow = true; });
  state.scene.add(g);
  state.house = { g, x, born: performance.now(), cap, puffAt: 0 };
  return state.house;
}

function spawnBaby(x) {
  const c = addCritter({ x, friend: true, speed: 0 });
  c.baby = true;
  c.mode = 'baby';
  c.babyUntil = performance.now() + 15000;
  c.nextBabyTarget = 0;
  c.nextKick = Infinity;
  c.root.scale.setScalar(SCALE * 0.55);
  return c;
}

/* ---------- animation ---------- */
function animate(c, dt) {
  const now = performance.now();
  const p = c.phase;
  const isResident = c === state.resident;
  const walking = isResident ? Math.abs(c.target - c.x) > 1.2 : c.speed > 0 && !c.held;
  const sitting = !walking && (isResident || c.held || c.waveOn || c.groom);
  c.phase += dt * (walking ? 11 + c.speed * 0.02 : 2.4);

  const hipsTilt = sitting ? -0.82 : 0;
  c.hips.rotation.x += (hipsTilt - c.hips.rotation.x) * Math.min(1, dt * 9);
  c.hips.position.y = 0.34 + (walking ? Math.abs(Math.sin(p)) * 0.03 : Math.sin(p) * 0.008);

  if (walking) {
    const s1 = Math.sin(p), s2 = Math.sin(p + Math.PI);
    c.front[0].shoulder.rotation.x = s1 * 0.85;
    c.front[1].shoulder.rotation.x = s2 * 0.85;
    c.front[0].elbow.rotation.x = Math.max(0, -s1) * 0.7;
    c.front[1].elbow.rotation.x = Math.max(0, -s2) * 0.7;
    c.hind[0].hip.rotation.x = s2 * 0.7;
    c.hind[1].hip.rotation.x = s1 * 0.7;
    c.hind[0].knee.rotation.x = 0.5 + Math.max(0, s2) * 0.5;
    c.hind[1].knee.rotation.x = 0.5 + Math.max(0, s1) * 0.5;
    c.tail[0].rotation.x = -0.5 + Math.sin(p) * 0.1;
    c.tail[1].rotation.x = -0.4;
    c.tail[2].rotation.x = -0.25;
    c.head.rotation.x = -0.12;
    c.chest.rotation.x = 0.08;
  } else {
    // sitting up, paws tucked, tail curled
    const breathe = Math.sin(p) * 0.03;
    c.front.forEach(f => {
      f.shoulder.rotation.x = -1.25;
      f.elbow.rotation.x = -1.15;
    });
    c.hind[0].hip.rotation.x = -0.9;
    c.hind[1].hip.rotation.x = -0.9;
    c.hind[0].knee.rotation.x = 1.5;
    c.hind[1].knee.rotation.x = 1.5;
    c.tail[0].rotation.x = -0.15 + breathe;
    c.tail[1].rotation.x = 0.1;
    c.tail[2].rotation.x = 0.18;
    c.head.rotation.x = -0.02;
    c.chest.rotation.x = 0.02;
  }

  // look at the pointer (neck yaw/pitch, clamped)
  const look = c.look || { x: 0, y: 0 };
  const yaw = Math.max(-0.55, Math.min(0.55, look.x));
  const pitch = Math.max(-0.3, Math.min(0.3, look.y));
  c.neck.rotation.y += (yaw - c.neck.rotation.y) * Math.min(1, dt * 6);
  c.neck.rotation.x += (pitch - c.neck.rotation.x) * Math.min(1, dt * 6);

  // actions
  if (c.waveOn) {
    c.front[1].shoulder.rotation.x = -2.3;
    c.front[1].shoulder.rotation.z = 0.4 + Math.sin(p * 3) * 0.45;
    c.neck.rotation.z = 0.12;
  } else {
    c.front[1].shoulder.rotation.z = 0;
    c.neck.rotation.z = 0;
  }
  if (c.groom) {
    c.front[1].shoulder.rotation.x = -2.4 + Math.sin(p * 7) * 0.12;
    c.front[1].elbow.rotation.x = -2.1;
  }
  if (c.poseUntil > now) {
    if (c.pose === 'stretch') {
      c.hips.rotation.x = -0.35;
      c.front.forEach(f => { f.shoulder.rotation.x = -2.4; f.elbow.rotation.x = -0.1; });
      c.neck.rotation.x = -0.25;
    } else if (c.pose === 'sleep') {
      c.hips.rotation.x = -1.15;
      c.neck.rotation.x = 0.55;
      c.neck.rotation.z = 0.25;
      c.tail[0].rotation.x = -0.05;
      c.tail[1].rotation.x = 0.5;
      c.tail[2].rotation.x = 0.7;
    } else if (c.pose === 'kick') {
      c.hind[1].hip.rotation.x = 1.1;
      c.hind[1].knee.rotation.x = 0;
    }
  }
  if (c.faceUntil > now) {
    c.neck.rotation.z = Math.sin(p * 3) * 0.2;
    c.neck.rotation.y = Math.sin(p * 2) * 0.3;
  }
  if (c.tongue) c.tongue.visible = c.faceUntil > now;
  if (c.trickUntil > now) {
    const k = 1 - (c.trickUntil - now) / 700;
    c.root.rotation.z = k * Math.PI * 2;
    c.root.position.y = FLOOR + Math.sin(k * Math.PI) * 26;
    c.root.rotation.y += dt * 10;
  } else if (!c.duel && c.trickUntil) {
    c.trickUntil = 0;
    c.root.rotation.z = 0;
  }
  if (c.duel && c.sword) {
    c.sword.visible = true;
    const dir = c.partner ? (Math.sign(c.partner.x - c.x) || 1) : 1;
    const attacking = c.attackUntil > now;
    const blocking = c.partner && c.partner.attackUntil > now;
    c.front[1].shoulder.rotation.x = attacking ? -2.45 : -2.1;
    c.front[1].elbow.rotation.x = attacking ? -0.7 : -1.15;
    if (attacking) {
      const k = 1 - Math.max(0, c.attackUntil - now) / 320;
      c.sword.rotation.x = 0.35 + k * 1.5;
      c.sword.rotation.z = -0.25 + Math.sin(k * Math.PI) * 0.25;
      c.root.position.x = c.x + dir * 5;
      c.hips.rotation.x = -0.2;
      c.neck.rotation.z = -dir * 0.06;
    } else if (blocking) {
      c.sword.rotation.x = 1.45;
      c.sword.rotation.z = 0.45;
      c.root.position.x = c.x - dir * 2;
      c.hips.rotation.x = -0.08;
    } else {
      c.sword.rotation.x = 1.0 + Math.sin(now / 90) * 0.06;
      c.sword.rotation.z = -0.2;
      c.root.position.x = c.x;
      c.hips.rotation.x = -0.1;
    }
  } else if (c.sword) {
    c.sword.visible = false;
  }
  if (c.mode === 'fight' && c.fightUntil > now) {
    const k = Math.sin(p * 6);
    c.root.rotation.z += c.roll * dt;
    c.root.position.y = FLOOR + Math.abs(k) * 9;
    c.hips.rotation.x = k * 0.25;
    c.neck.rotation.z = -k * 0.3;
    c.front.forEach(f => { f.shoulder.rotation.x = -1.4; f.elbow.rotation.x = -1.5; });
    c.hind.forEach(h => { h.hip.rotation.x = -1.1; h.knee.rotation.x = 1.4; });
  } else if (c.root.rotation.z) {
    c.root.rotation.z *= Math.max(0, 1 - dt * 6);
  }
  if (c.drinkUntil > now) {
    c.front[0].shoulder.rotation.x = -1.9;
    c.front[0].elbow.rotation.x = -0.85;
    if (c.beer) {
      c.beer.visible = true;
      c.beer.rotation.x = -0.85 + Math.sin(p * 2) * 0.12;
      c.beer.rotation.z = c.clink ? 0.35 : 0;
    }
    c.neck.rotation.x = -0.18;
  } else if (c.beer) {
    c.beer.rotation.x = 0;
  }

  if (c.hopUntil > now) {
    const k = 1 - (c.hopUntil - now) / 420;
    c.root.position.y = FLOOR + Math.sin(Math.max(0, Math.min(1, k)) * Math.PI) * 14;
  } else if (isResident) {
    c.root.position.y = FLOOR;
  }
  if (c.sledOn) {
    c.hips.rotation.x = -0.55;
    c.front.forEach(f => { f.shoulder.rotation.x = -1.35; f.elbow.rotation.x = -0.35; });
    c.hind.forEach(h => { h.hip.rotation.x = -0.5; h.knee.rotation.x = 1.1; });
    c.tail[0].rotation.x = -0.8 + Math.sin(p * 2) * 0.08;
    c.tail[1].rotation.x = -0.35;
    c.tail[2].rotation.x = -0.2;
    c.root.rotation.z = Math.sin(p * 1.7) * 0.05;
  }
  if (c.danceUntil > now) {
    const t = now / 1000 + c.phase;
    c.root.position.y = FLOOR + Math.abs(Math.sin(t * 6)) * 6;
    c.hips.rotation.x = -0.25 + Math.sin(t * 8) * 0.12;
    c.front.forEach((f, i) => {
      f.shoulder.rotation.x = -2.4 + Math.sin(t * 8 + i * Math.PI) * 0.35;
      f.elbow.rotation.x = -0.6;
    });
    c.hind[0].hip.rotation.x = -0.8;
    c.hind[1].hip.rotation.x = -0.8;
    c.neck.rotation.z = Math.sin(t * 4) * 0.18;
    c.tail[0].rotation.x = -0.6 + Math.sin(t * 8) * 0.2;
  }
  if (c.buildUntil > now) {
    c.front[1].shoulder.rotation.x = -1.7 + Math.sin(now / 55) * 0.65;
    c.front[1].elbow.rotation.x = -0.45;
    c.neck.rotation.x = -0.05;
  }
  if (c.bonkUntil > now) {
    const k = Math.sin((c.bonkUntil - now) / 55);
    c.neck.rotation.z = k * 0.4;
    c.neck.rotation.x = 0.18;
    c.root.rotation.z = k * 0.14;
  }
  if (c.eatingUntil > now) {
    c.front.forEach(f => { f.shoulder.rotation.x = -2.05; f.elbow.rotation.x = -1.85; });
    c.neck.rotation.x = -0.1 + Math.sin(p * 11) * 0.05;
    c.head.rotation.x = Math.sin(p * 11) * 0.05;
    if (c.heldNut) {
      c.heldNut.visible = true;
      c.heldNut.scale.setScalar(Math.max(0.15, (c.eatingUntil - now) / 2400));
    }
  } else if (c.carried && c.heldNut) {
    c.heldNut.visible = true;
  }
  if (c.throwUntil > now) {
    c.front[1].shoulder.rotation.x = -2.2;
    c.front[1].elbow.rotation.x = -0.35 + Math.sin((c.throwUntil - now) / 38) * 0.2;
    c.neck.rotation.x = -0.05;
  }
  if (c.beer) c.beer.visible = !!c.beerOn;
}

/* ---------- frame loop ---------- */
function updateWeather(now, dt) {
  if (state.snow) {
    const pos = state.snow.geo.attributes.position.array;
    for (let i = 0; i < state.snow.vel.length; i++) {
      const v = state.snow.vel[i];
      pos[i * 3 + 1] -= v.fall * dt;
      pos[i * 3] += Math.sin(now * 0.001 + v.sway) * v.drift * dt;
      if (pos[i * 3 + 1] < FLOOR - 4) {
        pos[i * 3 + 1] = BAR / 2 + 20;
        pos[i * 3] = (Math.random() - 0.5) * Math.max(1200, state.W / 2 + 80);
      }
    }
    state.snow.geo.attributes.position.needsUpdate = true;
    const build = Math.min(1, (now - state.snow.born) / 3200);
    for (const m of state.snow.mounds) m.scale.y = m.userData.h * build;
    if (now > state.snow.until) stopSnow();
  }
  for (const f of [...state.fx]) {
    const age = now - f.born;
    if (age >= f.life) {
      state.scene.remove(f.sp);
      f.sp.material.dispose();
      state.fx = state.fx.filter(x => x !== f);
      continue;
    }
    const k = age / f.life;
    f.sp.position.x += f.vx * dt;
    f.sp.position.y += f.vy * dt;
    f.sp.material.opacity = 0.85 * (1 - k);
    f.sp.scale.setScalar(f.base * (1 + f.grow * k));
  }
  if (state.disco) {
    const d = state.disco;
    d.ball.rotation.y += dt * 4;
    d.light.color.setHSL((now * 0.00035) % 1, 0.75, 0.6);
    d.washes.forEach((sp, i) => {
      sp.material.color.setHSL((now * 0.00028 + i * 0.19) % 1, 0.78, 0.55);
      sp.material.opacity = 0.13 + 0.05 * Math.sin(now * 0.004 + i);
    });
    d.lights.forEach((l, i) => l.color.setHSL((now * 0.00035 + i * 0.31) % 1, 0.8, 0.55));
    if (now > d.sparkAt) {
      d.sparkAt = now + 240;
      addPuff(d.stage + (Math.random() - 0.5) * 34, BAR / 2 - 12 + (Math.random() - 0.5) * 12,
              { color: '#ffd6f2', size: 3, life: 320, vy: 8, grow: 1.6 });
    }
    if (now > d.until) stopDisco();
  }
  if (state.house) {
    const h = state.house;
    const k = Math.min(1, (now - h.born) / 1200);
    h.g.scale.y = Math.max(0.01, k);
    if (k < 1 && now > h.puffAt) {
      h.puffAt = now + 180;
      addPuff(h.x + (Math.random() - 0.5) * 34, FLOOR + 5,
              { color: '#c9b79a', size: 5, life: 500, vy: 22, grow: 2 });
    }
    if (h.cap) h.cap.visible = !!state.snow;
  }
}

function frame() {
  state.raf = 0;
  if (!state.renderer || document.hidden) return;
  const dt = Math.min(0.05, state.clock.getDelta());
  const now = performance.now();
  updateWeather(now, dt);

  const res = state.resident;
  if (res) {
    const dx = state.pointer.x - res.x;
    const dy = state.pointer.y - FLOOR;
    res.look = { x: dx / 260, y: -dy / 300 };
    const overBar = state.pointer.y > FLOOR - 10 && state.pointer.y < FLOOR + 90;
    if (overBar && !res.social && Math.abs(dx) > 46) {
      res.target = Math.max(-state.W / 2 + 70, Math.min(state.W / 2 - 260, state.pointer.x));
      res.speed = 70;
    } else if (!overBar && !res.social && Math.abs(res.x - res.home) > 3 && !res.adventuring) {
      res.target = res.home;
    }
    const near = Math.abs(dx) < 110 && state.pointer.y < FLOOR + 100;
    if (near && now > state.lastPoke + 1500) {
      state.lastPoke = now;
      res.hopUntil = now + 420;
      res.target = res.x + (dx > 0 ? -16 : 16);
    }
    if (now > res.nextAction) {
      res.nextAction = now + 3200 + Math.random() * 5200;
      const r = Math.random();
      if (r < 0.12) res.hopUntil = now + 420;
      else if (r < 0.22) res.faceUntil = now + 1300;
      else if (r < 0.31) { res.groom = true; setTimeout(() => { res.groom = false; }, 700); }
      else if (r < 0.38) kickNut(res);
      else if (r < 0.46) { res.pose = 'sit'; res.poseUntil = now + 2600; }
      else if (r < 0.53) { res.pose = 'sleep'; res.poseUntil = now + 3800; }
      else if (r < 0.60) { res.pose = 'stretch'; res.poseUntil = now + 1400; }
      else if (r < 0.67) { res.pose = 'kick'; res.poseUntil = now + 900; kickNut(res); }
      else if (r < 0.74) { res.waveOn = true; res.waveUntil = now + 1600; }
      else if (r < 0.82) {
        const el = state.perches[Math.floor(Math.random() * state.perches.length)];
        if (el) {
          const r2 = el.getBoundingClientRect();
          res.target = Math.max(-state.W / 2 + 60, Math.min(state.W / 2 - 80,
            r2.left + r2.width / 2 - state.W / 2));
        }
      } else if (r < 0.94 && state.trees.length && (!state.grove || state.grove.group.visible)) {
        const t = state.trees[Math.floor(Math.random() * state.trees.length)];
        startForage(res, t, t.cache > 0 && Math.random() < 0.55 ? 'dig' : 'bury');
      } else {
        res.target = res.home;
      }
    }
    if (res.waveUntil && now > res.waveUntil) { res.waveOn = false; res.waveUntil = 0; }
    const d = res.target - res.x;
    if (Math.abs(d) > 1.2) {
      res.speed = (res.adventuring || res.mode === 'forage' || res.mode === 'nuts' || res.mode === 'snowfight') ? 150 : 55;
      res.x += Math.sign(d) * Math.min(Math.abs(d), res.speed * dt);
    } else if (res.adventuring) {
      res.adventuring = false;
      res.target = res.home;
      res.speed = 55;
    } else {
      res.speed = 0;
      if (Math.abs(res.x - res.home) > 1.2 && now > res.nextAction - 1000) res.target = res.home;
    }
  }

  for (const c of [...state.critters]) {
    if (c.mode === 'meet') {
      const d = c.meetX - c.x;
      if (Math.abs(d) > 1.2) c.x += Math.sign(d) * Math.min(Math.abs(d), 150 * dt);
      else {
        c.mode = 'drink';
        c.drinkUntil = now + 3000;
        c.clinkAt = now + 1300;
        c.beerOn = true;
        const lead = state.resident;
        if (lead) {
          lead.beerOn = true;
          lead.social = true;
          lead.drinkUntil = c.drinkUntil;
          lead.clinkAt = c.clinkAt;
        }
      }
    }
    if (c.mode === 'visit') {
      const d = c.meetX - c.x;
      if (Math.abs(d) > 2) c.x += Math.sign(d) * Math.min(Math.abs(d), 140 * dt);
      else if (!c.visitUntil) {
        c.visitUntil = now + 2600;
        c.hopUntil = now + 420;
      }
      if (c.visitUntil && now > c.visitUntil) { c.mode = 'leave'; c.visitUntil = 0; }
    }
    if (c.mode === 'duel') {
      const d = c.meetX - c.x;
      if (Math.abs(d) > 3) c.x += Math.sign(d) * Math.min(Math.abs(d), 165 * dt);
      else {
        if (!c.fightUntil) {
          c.fightUntil = now + 7200;
          c.duel = true;
          c.fightAt = now + 600;
        }
        if (now > c.fightAt) {
          c.attackUntil = now + 320;
          c.fightAt = now + 680 + Math.random() * 480;
          if (c.partner && Math.random() < 0.32) {
            c.partner.bonkUntil = now + 380;
            c.partner.hopUntil = now + 300;
          }
        }
      }
      if (c.fightUntil && now > c.fightUntil) {
        c.duel = false;
        c.attackUntil = 0;
        c.fightAt = 0;
        if (c === state.resident) { c.mode = 'travel'; c.target = c.home; c.fightUntil = 0; c.social = false; }
        else c.mode = 'leave';
      }
    }
    if (c.mode === 'fight') {
      const d = c.meetX - c.x;
      if (Math.abs(d) > 20) c.x += Math.sign(d) * Math.min(Math.abs(d), 170 * dt);
      else if (!c.fightUntil) {
        c.fightUntil = now + 3200;
        c.roll = (Math.random() < 0.5 ? -1 : 1) * 9;
      }
      if (c.fightUntil && now > c.fightUntil) {
        if (c === state.resident) { c.mode = 'travel'; c.target = c.home; c.fightUntil = 0; c.social = false; }
        else c.mode = 'leave';
      }
    }
    if (c.mode === 'nuts' || c.mode === 'snowfight') {
      if (c !== state.resident) {
        const d = (c.meetX || 0) - c.x;
        c.speed = Math.abs(d) > 44 ? 165 : 0;
        if (Math.abs(d) > 44) c.x += Math.sign(d) * Math.min(Math.abs(d), 165 * dt);
      }
      if (c.partner && now > c.nextThrow && now < (c.playUntil || Infinity) &&
          Math.abs(c.partner.x - c.x) < 260) {
        c.nextThrow = now + 480 + Math.random() * 300;
        throwAt(c, c.partner, c.mode === 'snowfight' ? 'snow' : 'nut');
      }
      if (c.playUntil && now > c.playUntil) {
        c.playUntil = 0;
        c.partner = null;
        if (c === state.resident) { c.mode = 'travel'; c.target = c.home; c.social = false; }
        else c.mode = 'leave';
      }
    }
    if (c.mode === 'sled') {
      c.x += (c.sledSpeed || 250) * dt;
      c.y = FLOOR + 2 + Math.sin(c.x * 0.03) * 1.6;
      if (now > c.sprayAt) {
        c.sprayAt = now + 90;
        addPuff(c.x - 14, FLOOR + 3, { color: '#c9d8ea', size: 5, life: 420,
                                       vx: -40, vy: 26, grow: 2 });
      }
      if (c.x > c.endX) { removeCritter(c); continue; }
    }
    if (c.mode === 'forage') {
      if (c !== state.resident) {
        const d = c.forageX - c.x;
        c.speed = Math.abs(d) > 3 ? 150 : 0;
        if (Math.abs(d) > 3) c.x += Math.sign(d) * Math.min(Math.abs(d), 150 * dt);
      }
      if (!c.foraged && Math.abs(c.forageX - c.x) <= 3 && !c.forageAt && !c.eatingUntil) {
        c.forageAt = now + 650;
      }
      if (c.forageAt && now >= c.forageAt) {
        c.forageAt = 0;
        c.foraged = true;
        const t = c.tree;
        if (c.carried) {
          c.carried = false;
          if (c.heldNut) c.heldNut.visible = false;
          if (t) { t.cache = Math.min(4, t.cache + 1); syncTree(t); }
        } else if (t && t.cache > 0) {
          t.cache -= 1;
          syncTree(t);
          c.eatingUntil = now + 2600;
          if (c.heldNut) { c.heldNut.visible = true; c.heldNut.scale.setScalar(1); }
        }
        addPuff(c.x + 7, FLOOR + 3, { color: state.snow ? '#eaf3ff' : '#8a6a4a',
                                      size: 5, life: 400, vy: 18, grow: 1.8 });
      }
      if (c.eatingUntil && now > c.eatingUntil) {
        c.eatingUntil = 0;
        if (c.heldNut) c.heldNut.visible = false;
      }
      if (c.playUntil && now > c.playUntil) {
        c.playUntil = 0;
        c.tree = null;
        if (c === state.resident) { c.mode = 'travel'; c.target = c.home; c.social = false; }
        else c.mode = 'leave';
      }
    }
    if (c.mode === 'disco') {
      const d = c.meetX - c.x;
      if (Math.abs(d) > 4) { c.x += Math.sign(d) * Math.min(Math.abs(d), 150 * dt); c.speed = 150; }
      else c.speed = 0;
      if (now > c.danceUntil) {
        c.danceUntil = 0;
        if (c === state.resident) { c.mode = 'travel'; c.target = c.home; c.social = false; }
        else c.mode = 'leave';
      }
    }
    if (c.mode === 'build') {
      const d = c.meetX - c.x;
      if (Math.abs(d) > 4) { c.x += Math.sign(d) * Math.min(Math.abs(d), 150 * dt); c.speed = 150; }
      else c.speed = 0;
      if (now > c.buildUntil) { c.buildUntil = 0; c.mode = 'leave'; }
    }
    if (c.mode === 'baby') {
      if (now > c.nextBabyTarget) {
        c.babyTarget = Math.max(-state.W / 2 + 80,
          Math.min(state.W / 2 - 80, c.x + (Math.random() - 0.5) * 340));
        c.nextBabyTarget = now + 600 + Math.random() * 900;
        if (Math.random() < 0.3) c.hopUntil = now + 260;
      }
      const d = c.babyTarget - c.x;
      if (Math.abs(d) > 2) { c.x += Math.sign(d) * Math.min(Math.abs(d), 140 * dt); c.speed = 140; }
      else c.speed = 0;
      if (now > c.babyUntil) { c.mode = 'leave'; c.babyUntil = 0; }
    }
    if (c.mode === 'drink') {
      c.beerOn = now < c.drinkUntil;
      c.clink = now > c.clinkAt && now < c.clinkAt + 400;
      if (now > c.drinkUntil) {
        c.mode = 'leave';
        c.beerOn = false;
        if (state.resident && state.resident.drinkUntil === c.drinkUntil) {
          state.resident.beerOn = false;
          state.resident.drinkUntil = 0;
          state.resident.social = false;
        }
      }
    }
    if (c.mode === 'leave') {
      c.x += 135 * dt;
      if (c.x > state.W / 2 + 90) { removeCritter(c); continue; }
    }
    if (c.holdAt && !c.held && c.x >= c.holdAt) {
      c.held = true;
      c.holdUntil = now + 2000;
      c.beerOn = true;
    }
    if (c.held && now > c.holdUntil) { c.held = false; c.beerOn = false; }
    if (!c.resident && (c.mode === 'travel' || c.mode === 'leave')) {
      if (!c.held) c.x += c.speed * dt;
      if (c.dive && c.x > state.W + 40) c.y -= 220 * dt;
    }
    c.root.position.x = c.x;
    c.root.position.y = Math.max(c.y, FLOOR);
    const moving = c.resident ? Math.abs(c.target - c.x) > 1.2 : !c.held && c.speed > 0;
    let want = Math.PI / 2;
    if (c.mode === 'drink') want = -Math.PI / 2;
    else if (c.partner && (c.mode === 'duel' || c.mode === 'fight' ||
                           c.mode === 'nuts' || c.mode === 'snowfight')) {
      want = c.partner.x < c.x ? -Math.PI / 2 : Math.PI / 2;
    }
    else if (c.mode === 'disco') want = Math.PI / 2 + Math.sin(now / 300 + c.phase) * 0.7;
    else if (c.baby) want = (c.babyTarget - c.x) >= 0 ? Math.PI / 2 : -Math.PI / 2;
    else if (c.waveOn) want = 0;
    else if (moving) want = (c.resident ? Math.sign(c.target - c.x) : 1) > 0 ? Math.PI / 2 : -Math.PI / 2;
    else if (c.resident) {
      const nd = Math.abs(state.pointer.x - c.x);
      want = nd < 160 && state.pointer.y < FLOOR + 120 ? 0 : Math.PI / 2;
    }
    c.root.rotation.y += (want - c.root.rotation.y) * Math.min(1, dt * 9);
    if (!c.resident && !c.held && !c.waveOn && !c.baby && now > c.nextKick &&
        c.x > -state.W / 2 && c.x < state.W / 2) {
      c.nextKick = now + 900 + Math.random() * 1400;
      kickNut(c);
    }
    animate(c, dt);
    if (c.duel && c.partner && c === state.resident && now > (c.chipAt || 0) &&
        (c.attackUntil > now || c.partner.attackUntil > now)) {
      c.chipAt = now + 130;
      const mx = (c.x + c.partner.x) / 2;
      addPuff(mx + (Math.random() - 0.5) * 4, FLOOR + 22 + (Math.random() - 0.5) * 5,
              { color: '#c9a06a', size: 2.6, life: 220, vy: 26, grow: 1.5 });
    }
    if (c.x > c.endX || c.y < -BAR) removeCritter(c);
  }

  for (let i = 0; i < state.critters.length; i++) {
    for (let j = i + 1; j < state.critters.length; j++) {
      const a = state.critters[i], b = state.critters[j];
      if (a.mode !== 'travel' || b.mode !== 'travel') continue;
      if (a === state.resident || b === state.resident) continue;
      const d = b.x - a.x;
      if (Math.abs(d) < 26) {
        const right = d >= 0 ? b : a;
        const push = 26 - Math.abs(d);
        right.x += push * (d >= 0 ? 1 : -1);
        if (Math.random() < 0.03) { a.hopUntil = now + 300; b.hopUntil = now + 300; }
      }
    }
  }

  for (const n of [...state.nuts]) {
    n.vy -= 900 * dt;
    n.x += n.vx * dt;
    n.y += n.vy * dt;
    n.rot += n.spin * dt;
    if (n.kind === 'snow' && now - (n.trailAt || 0) > 90) {
      n.trailAt = now;
      addPuff(n.x, n.y, { color: '#cfe0f4', size: 3.4, life: 240, grow: 1.2 });
    }
    if (!n.hit) {
      for (const c of state.critters) {
        if (c === n.from) continue;
        if (Math.abs(n.x - c.x) < 11 && n.y > FLOOR + 3 && n.y < FLOOR + 32) {
          n.hit = true;
          c.hopUntil = now + 340;
          c.bonkUntil = now + 650;
          if (n.kind === 'snow') {
            addPuff(n.x, n.y, { color: '#ffffff', size: 11, life: 500, vy: 24, grow: 1.8 });
          }
          n.vy = 120;
          n.vx *= -0.35;
          break;
        }
      }
    }
    if (n.y < FLOOR + 3) {
      n.y = FLOOR + 3;
      n.vy = -n.vy * 0.42;
      n.vx *= 0.88;
      if (Math.abs(n.vy) < 40) { n.vy = 0; n.vx *= 0.9; }
      if (n.kind === 'snow' && !n.puffed) {
        n.puffed = true;
        addPuff(n.x, FLOOR + 3, { color: '#ffffff', size: 6, life: 300, vy: 12, grow: 1.5 });
      }
    }
    n.mesh.position.set(n.x, n.y, 0.2);
    n.mesh.rotation.z = n.rot;
    if (n.x > state.W + 60 || n.x < -80 || now - n.born > 6000) {
      state.scene.remove(n.mesh);
      state.nuts = state.nuts.filter(x => x !== n);
    }
  }

  if (state.critters.length || state.nuts.length || state.snow || state.fx.length) {
    state.renderer.render(state.scene, state.camera);
    document.body.dataset.critters = String(state.critters.length);
    state.raf = requestAnimationFrame(frame);
  } else {
    state.canvas.style.display = 'none';
  }
}

function ensureLoop() {
  makeCanvas();
  state.canvas.style.display = 'block';
  if (!state.raf) state.raf = requestAnimationFrame(frame);
}

function stopAll() {
  if (state.raf) cancelAnimationFrame(state.raf);
  state.raf = 0;
  for (const c of [...state.critters]) removeCritter(c);
  for (const n of [...state.nuts]) { state.scene && state.scene.remove(n.mesh); }
  state.nuts = [];
  for (const f of [...state.fx]) { state.scene && state.scene.remove(f.sp); }
  state.fx = [];
  if (state.snow) stopSnow();
  state.resident = null;
  if (state.canvas) state.canvas.style.display = 'none';
}

function startAll() {
  optedOut = false;
  makeResident();
  ensureLoop();
}

window.addEventListener('critters-toggle', (e) => {
  const off = !!(e.detail && e.detail.off);
  if (off) { optedOut = true; stopAll(); }
  else if (optedOut) startAll();
});

// A small hook for the UI (and for checking a scene without waiting for the
// random schedule): nuts | duel | fight | snowfight | sled | snow.
window.addEventListener('critters-play', (e) => {
  if (optedOut || document.hidden) return;
  const kind = (e.detail && e.detail.kind) || 'nuts';
  if (kind === 'snow') { startSnow(16000); return; }
  if (kind === 'stop-snow') { stopSnow(); return; }
  run(kind);
});

function makeResident() {
  ensureLoop();
  const home = 33 - state.W / 2;            // the logo slot, next to the wordmark
  const c = addCritter({ x: home, speed: 0 });
  c.resident = true;
  c.home = home;
  c.target = home;
  c.nextAction = performance.now() + 2200;
  state.resident = c;
  state.perches = [...document.querySelectorAll('header.top button, header.top .pill')];
}

function pointerAt(ev) {
  state.pointer.x = ev.clientX - state.W / 2;
  state.pointer.y = BAR / 2 - ev.clientY;
}

function petCheck(ev) {
  const c = state.resident;
  if (!c) return;
  const wx = ev.clientX - state.W / 2;
  const wy = BAR / 2 - ev.clientY;
  if (Math.abs(wx - c.x) < 26 && wy > FLOOR - 12 && wy < FLOOR + 56) {
    ev.preventDefault();
    ev.stopPropagation();
    c.hopUntil = performance.now() + 700;
    c.trickUntil = performance.now() + 700;
    c.nextAction = performance.now() + 4200;
    kickNut(c);
    setTimeout(() => kickNut(c), 150);
  }
}

/* kinds: through | hold (friends + beer) | chase | wave | dive */
function run(kind) {
  if (optedOut || document.hidden) return;
  ensureLoop();
  const w = state.W;
  const lead = state.resident;
  // the resident stays on the bar: friends do the adventuring
  void lead;
  const base = { endX: w + 90, speed: 115 + Math.random() * 50 };
  if (kind === 'hold') {
    const f = addCritter({ ...base, x: -w / 2 - 60, friend: true, holdAt: 0 });
    f.mode = 'meet';
    f.meetX = (lead ? lead.x : 0) + 58;
  } else if (kind === 'duel') {
    const stage = Math.round(-w * 0.28);
    const f = addCritter({ ...base, x: -w / 2 - 60, friend: true, holdAt: 0 });
    f.mode = 'duel';
    f.meetX = stage + 32;
    if (lead) {
      lead.mode = 'duel';
      lead.meetX = stage - 32;
      lead.target = lead.meetX;
      lead.social = true;
      lead.nextAction = performance.now() + 12000;
      lead.duel = true;
      lead.partner = f;
      f.partner = lead;
    }
  } else if (kind === 'fight') {
    const stage = Math.round(-w * 0.28);
    const f = addCritter({ ...base, x: -w / 2 - 60, friend: true, holdAt: 0 });
    f.mode = 'fight';
    f.meetX = stage + 34;
    if (lead) {
      lead.mode = 'fight';
      lead.meetX = stage - 34;
      lead.target = lead.meetX;
      lead.social = true;
      lead.nextAction = performance.now() + 12000;
      lead.partner = f;
      f.partner = lead;
    }
  } else if (kind === 'nuts' || kind === 'snowfight') {
    if (kind === 'snowfight' && !state.snow) startSnow(16000);
    const f = addCritter({ ...base, x: -w / 2 - 60, friend: true, holdAt: 0 });
    const stage = Math.round(-w * 0.28);
    const until = performance.now() + 11000;
    f.mode = kind;
    f.meetX = stage + 64;
    f.nextThrow = performance.now() + 850;
    f.playUntil = until;
    if (lead) {
      lead.mode = kind;
      lead.meetX = stage - 64;
      lead.target = lead.meetX;
      lead.partner = f;
      f.partner = lead;
      lead.social = true;
      lead.nextAction = performance.now() + 12000;
      lead.nextThrow = performance.now() + 1050;
      lead.playUntil = until;
    }
  } else if (kind === 'sled') {
    startSnow(13000);
    const f = addCritter({ x: -w / 2 - 50, endX: w / 2 + 90, friend: true, speed: 0 });
    f.mode = 'sled';
    f.sledOn = true;
    if (f.sled) f.sled.visible = true;
    f.sledSpeed = 230 + Math.random() * 60;
    f.sprayAt = 0;
  } else if (kind === 'disco') {
    const stage = Math.round(-w * 0.12);
    startDisco(stage);
    const until = performance.now() + 7000;
    const f1 = addCritter({ ...base, x: -w / 2 - 60, friend: true, holdAt: 0 });
    f1.mode = 'disco'; f1.meetX = stage - 46; f1.danceUntil = until;
    const f2 = addCritter({ ...base, x: -w / 2 - 90, friend: true, holdAt: 0 });
    f2.mode = 'disco'; f2.meetX = stage + 46; f2.danceUntil = until;
    if (lead) {
      lead.mode = 'disco';
      lead.meetX = stage;
      lead.target = stage;
      lead.danceUntil = until;
      lead.social = true;
      lead.nextAction = performance.now() + 12000;
    }
  } else if (kind === 'house') {
    const hx = groveWorldX() + 110;
    buildHouse(hx);
    const f = addCritter({ ...base, x: -w / 2 - 60, friend: true, holdAt: 0 });
    f.mode = 'build'; f.meetX = hx + 30; f.buildUntil = performance.now() + 2800;
    if (lead) { lead.target = hx - 70; lead.social = true; lead.nextAction = performance.now() + 12000; }
  } else if (kind === 'family') {
    const hx = state.house ? state.house.x : groveWorldX() + 110;
    if (!state.house) buildHouse(hx);
    spawnBaby(hx - 60);
    spawnBaby(hx + 10);
    spawnBaby(hx + 70);
    if (lead) { lead.target = hx - 110; lead.social = true; lead.nextAction = performance.now() + 12000; }
  } else if (kind === 'forage') {
    if (!state.trees.length || (state.grove && !state.grove.group.visible)) return;
    const withNuts = state.trees.filter(t => t.cache > 0);
    const pool = withNuts.length ? withNuts : state.trees;
    const tree = pool[Math.floor(Math.random() * pool.length)];
    const f = addCritter({ ...base, x: -w / 2 - 60, friend: true, holdAt: 0 });
    startForage(f, tree, tree.cache > 0 ? 'dig' : 'bury', -22);
    if (lead) startForage(lead, tree, tree.cache > 0 ? 'bury' : 'dig', 22);
  } else if (kind === 'chase') {
    const f = addCritter({ ...base, x: -w / 2 - 60, friend: true, holdAt: 0 });
    f.mode = 'visit';
    f.meetX = (lead ? lead.x : 0) + 74;
    if (lead) {
      lead.social = true;
      lead.tagUntil = performance.now() + 5200;
      lead.target = (lead.home || 0) - 90;
      setTimeout(() => { lead.target = (lead.home || 0) + 90; }, 900);
      setTimeout(() => { lead.target = lead.home; lead.social = false; }, 4600);
    }
  } else if (kind === 'wave') {
    if (lead) setTimeout(() => {
      if (!lead) return;
      lead.waveOn = true;
      lead.waveUntil = performance.now() + 2000;
      lead.target = lead.x;
    }, 1200);
  } else {
    const f = addCritter({ ...base, x: -w / 2 - 60, friend: true, holdAt: 0 });
    f.mode = 'visit';
    f.meetX = (lead ? lead.x : 0) + 70;
  }
}

export function callCritters() { run('hold'); }

const ROTATION = ['duel', 'snow', 'house', 'nuts', 'disco', 'family', 'forage', 'snow',
                  'fight', 'disco', 'hold', 'chase', 'wave'];
let rotation = 0;

function snowDay() {
  startSnow(22000);
  setTimeout(() => run('snowfight'), 1200);
  setTimeout(() => run('sled'), 9500);
}

function schedule(delay = 5200) {
  setTimeout(() => {
    const kind = ROTATION[rotation++ % ROTATION.length];
    if (kind === 'snow') snowDay();
    else run(kind);
    schedule(kind === 'snow' ? 22000 : (rotation === 1 ? 9000 : 16000 + Math.random() * 6000));
  }, delay);
}

const hasApp = !!document.querySelector('header.top .brand');
if (!optedOut && hasApp) {
  window.addEventListener('pointermove', pointerAt, { passive: true });
  window.addEventListener('pointerdown', petCheck, true);
  makeResident();
  // A demo hook: ?critters=snow|forage|duel|nuts|sled|fight plays that scene
  // once after the bar has settled (and skips the usual rotation for the visit).
  const scene = new URLSearchParams(location.search).get('critters');
  if (scene) {
    setTimeout(() => {
      if (scene === 'snow') startSnow(22000);
      else run(scene);
    }, 1400);
  } else {
    schedule(5200);
  }
}

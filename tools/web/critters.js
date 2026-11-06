/* The critters: real 3D squirrels (three.js) that now and then run across the
 * top bar. They kick acorns about, friends turn up, someone brings a beer, one
 * waves at you, another dives off the edge.
 *
 * One transparent WebGL canvas spans the bar, so every squirrel and nut lives
 * in one scene. Nothing blocks clicks, the loop stops when the bar is empty,
 * and prefers-reduced-motion wins.
 */
import * as THREE from './vendor/three.module.min.js';

const BAR = 84;                 // canvas height, CSS pixels
const FLOOR = -BAR / 2 + 38;    // feet land inside the 56px bar
const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)');
let optedOut = false;
try { optedOut = localStorage.getItem('ui.critters') === '0'; } catch (e) {}
if (reduce && reduce.matches) optedOut = true;

const state = {
  renderer: null, scene: null, camera: null, canvas: null,
  critters: [], nuts: [], raf: 0, clock: null, W: 1, started: false,
  resident: null, pointer: { x: 0, y: -999 }, lastPoke: 0, lastPet: 0,
};

const MAT = {
  fur: new THREE.MeshStandardMaterial({ color: 0xc98a52, roughness: 0.9, flatShading: true }),
  furDark: new THREE.MeshStandardMaterial({ color: 0xa4632f, roughness: 0.95, flatShading: true }),
  cream: new THREE.MeshStandardMaterial({ color: 0xf3e6d2, roughness: 0.95, flatShading: true }),
  vest: new THREE.MeshStandardMaterial({ color: 0x6f7d5c, roughness: 0.95, flatShading: true }),
  gold: new THREE.MeshStandardMaterial({ color: 0xe8c98d, roughness: 0.3, metalness: 0.6 }),
  dark: new THREE.MeshStandardMaterial({ color: 0x2b2118, roughness: 0.6 }),
  nut: new THREE.MeshStandardMaterial({ color: 0xc08a4e, roughness: 0.9, flatShading: true }),
  nutCap: new THREE.MeshStandardMaterial({ color: 0x6b4a2a, roughness: 0.95, flatShading: true }),
  beer: new THREE.MeshStandardMaterial({ color: 0xd9a45f, roughness: 0.45 }),
  foam: new THREE.MeshStandardMaterial({ color: 0xf7f0de, roughness: 1 }),
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
  state.renderer = r;
  state.canvas = c;
  state.scene = new THREE.Scene();
  state.clock = new THREE.Clock();
  state.scene.add(new THREE.AmbientLight(0xffffff, 1.2));
  const key = new THREE.DirectionalLight(0xfff2dd, 1.6);
  key.position.set(-1, 3, 4);
  state.scene.add(key);
  const rim = new THREE.DirectionalLight(0xbfd4ff, 0.7);
  rim.position.set(2, 1, -3);
  state.scene.add(rim);
  resize();
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
  if (!state.camera) {
    state.camera = new THREE.OrthographicCamera(-w / 2, w / 2, BAR / 2, -BAR / 2, 0.1, 100);
    state.camera.position.set(0, 0, 20);
  } else {
    state.camera.left = -w / 2; state.camera.right = w / 2;
    state.camera.top = BAR / 2; state.camera.bottom = -BAR / 2;
    state.camera.updateProjectionMatrix();
  }
}

function ball(r, m, x, y, z) {
  const s = new THREE.Mesh(new THREE.SphereGeometry(r, 14, 10), m);
  s.position.set(x, y, z);
  return s;
}

/* A squirrel from primitives, feet on y = 0, facing +Z. */
function buildSquirrel() {
  const root = new THREE.Group();
  const body = new THREE.Group();
  root.add(body);

  const torso = ball(0.34, MAT.fur, 0, 0.74, 0);
  torso.scale.set(1, 1.16, 0.92);
  body.add(torso);
  const belly = ball(0.24, MAT.cream, 0, 0.66, 0.16);
  belly.scale.set(0.85, 1.05, 0.55);
  body.add(belly);

  const vest = new THREE.Mesh(
    new THREE.SphereGeometry(0.36, 16, 12, Math.PI * 0.15, Math.PI * 0.7, 0.9, 1.5), MAT.vest);
  vest.scale.set(1, 1.12, 0.95);
  vest.position.set(0, 0.74, 0);
  body.add(vest);

  const head = new THREE.Group();
  head.position.set(0, 1.3, 0.02);
  body.add(head);
  const skull = ball(0.27, MAT.fur, 0, 0, 0);
  skull.scale.set(1, 0.98, 1.02);
  head.add(skull);
  const muzzle = ball(0.13, MAT.cream, 0, -0.05, 0.22);
  muzzle.scale.set(1, 0.85, 0.9);
  head.add(muzzle);
  head.add(ball(0.038, MAT.dark, 0, -0.03, 0.35));
  head.add(ball(0.042, MAT.dark, 0.1, 0.06, 0.235));
  head.add(ball(0.042, MAT.dark, -0.1, 0.06, 0.235));

  for (const s of [-1, 1]) {
    const ear = new THREE.Mesh(new THREE.ConeGeometry(0.085, 0.22, 8), MAT.furDark);
    ear.position.set(0.14 * s, 0.28, -0.02);
    ear.rotation.z = -0.25 * s;
    head.add(ear);
    const tuft = new THREE.Mesh(new THREE.ConeGeometry(0.035, 0.15, 6), MAT.furDark);
    tuft.position.set(0.17 * s, 0.43, -0.03);
    tuft.rotation.z = -0.35 * s;
    head.add(tuft);
    // round glasses, standing proud of the face
    const lens = new THREE.Mesh(new THREE.TorusGeometry(0.105, 0.02, 8, 18), MAT.gold);
    lens.position.set(0.105 * s, 0.06, 0.3);
    head.add(lens);
  }
  const bridge = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.07, 6), MAT.gold);
  bridge.rotation.z = Math.PI / 2;
  bridge.position.set(0, 0.07, 0.31);
  head.add(bridge);

  const tail = new THREE.Group();
  tail.position.set(0, 0.5, -0.28);
  body.add(tail);
  const tailBalls = [[0, 0.05, -0.1, 0.16], [0, 0.3, -0.2, 0.2], [0, 0.6, -0.22, 0.21],
                     [0, 0.9, -0.14, 0.18], [0, 1.12, 0.02, 0.13]];
  for (const [x, y, z, r] of tailBalls) {
    const b = ball(r, MAT.furDark, x, y, z);
    b.scale.set(0.85, 1, 0.85);
    tail.add(b);
  }

  const legs = [];
  for (const [x, z, front] of [[0.16, 0.12, 1], [-0.16, 0.12, 1], [0.17, -0.14, 0], [-0.17, -0.14, 0]]) {
    const hip = new THREE.Group();
    hip.position.set(x, 0.42, z);
    body.add(hip);
    const shin = new THREE.Mesh(new THREE.CapsuleGeometry(0.06, 0.2, 4, 8), MAT.furDark);
    shin.position.set(0, -0.16, front ? 0.02 : 0);
    hip.add(shin);
    const foot = ball(0.09, MAT.furDark, 0, -0.3, 0.04);
    foot.scale.set(1, 0.6, 1.5);
    hip.add(foot);
    legs.push(hip);
  }

  const arms = [];
  for (const s of [-1, 1]) {
    const shoulder = new THREE.Group();
    shoulder.position.set(0.22 * s, 0.9, 0.08);
    shoulder.rotation.x = -0.9;
    shoulder.rotation.z = 0.25 * s;
    body.add(shoulder);
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.045, 0.16, 4, 8), MAT.fur);
    arm.position.y = -0.08;
    shoulder.add(arm);
    const paw = ball(0.06, MAT.furDark, 0, -0.17, 0);
    shoulder.add(paw);
    arms.push(shoulder);
  }

  const acorn = new THREE.Group();
  acorn.position.set(0, 0.78, 0.3);
  body.add(acorn);
  const nut = ball(0.07, MAT.nut, 0, 0, 0);
  nut.scale.set(1, 1.25, 1);
  acorn.add(nut);
  const cap = new THREE.Mesh(new THREE.SphereGeometry(0.075, 12, 8, 0, Math.PI * 2, 0, Math.PI / 2), MAT.nutCap);
  cap.position.y = 0.05;
  acorn.add(cap);

  const beer = new THREE.Group();
  beer.position.set(0.3, 0.95, 0.3);
  beer.visible = false;
  body.add(beer);
  const glass = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.07, 0.17, 10), MAT.beer);
  beer.add(glass);
  const foam = ball(0.078, MAT.foam, 0, 0.095, 0);
  foam.scale.set(1, 0.55, 1);
  beer.add(foam);
  const handle = new THREE.Mesh(new THREE.TorusGeometry(0.055, 0.014, 6, 10, Math.PI * 1.2), MAT.beer);
  handle.position.set(0.08, 0, 0);
  handle.rotation.z = -0.4;
  beer.add(handle);

  const shadow = new THREE.Mesh(new THREE.CircleGeometry(0.3, 16),
    new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.15 }));
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = 0.01;
  shadow.scale.set(1, 0.7, 1);
  root.add(shadow);

  return { root, body, head, tail, legs, arms, beerGroup: beer };
}

function makeNut() {
  const g = new THREE.Group();
  const n = ball(0.1, MAT.nut, 0, 0, 0);
  n.scale.set(1, 1.2, 1);
  g.add(n);
  const cap = new THREE.Mesh(new THREE.SphereGeometry(0.11, 10, 6, 0, Math.PI * 2, 0, Math.PI / 2), MAT.nutCap);
  cap.position.y = 0.055;
  g.add(cap);
  return g;
}

function addCritter(opts) {
  const s = buildSquirrel();
  const scale = 27 + Math.random() * 5;
  s.root.scale.setScalar(scale);
  s.root.rotation.y = Math.PI / 2;
  s.root.position.set(opts.x, FLOOR, 0);
  state.scene.add(s.root);
  const c = {
    ...s, x: opts.x, y: FLOOR, speed: opts.speed, phase: Math.random() * 6,
    endX: opts.endX, holdAt: opts.holdAt || 0, holdUntil: 0, held: false,
    beerOn: false, waveOn: false, waveUntil: 0, dive: !!opts.dive,
    nextKick: performance.now() + 500 + Math.random() * 900,
  };
  state.critters.push(c);
  return c;
}

function removeCritter(c) {
  state.scene.remove(c.root);
  state.critters = state.critters.filter((x) => x !== c);
}

function kickNut(c) {
  const nut = makeNut();
  nut.position.set(c.x + 8, FLOOR + 6, 0.25);
  nut.scale.setScalar(34);
  nut.position.z = 0.25;
  state.scene.add(nut);
  state.nuts.push({
    mesh: nut, x: c.x + 8, y: FLOOR + 6,
    vx: 150 + Math.random() * 170, vy: 200 + Math.random() * 180,
    spin: (Math.random() - 0.5) * 12, rot: 0,
  });
}

function pose(c, dt) {
  const idle = c.resident && Math.abs(c.x - c.target) < 1.5 && !c.held;
  c.phase += dt * (idle ? 2.2 : 10 + c.speed * 0.03);
  const p = c.phase;
  const held = c.held ? 0.2 : 1;
  const step = idle ? 0 : 1;
  c.legs[0].rotation.x = Math.sin(p) * 0.95 * held * step;
  c.legs[1].rotation.x = Math.sin(p + Math.PI) * 0.95 * held * step;
  c.legs[2].rotation.x = Math.sin(p + Math.PI) * 0.85 * held * step;
  c.legs[3].rotation.x = Math.sin(p) * 0.85 * held * step;
  c.body.position.y = idle ? Math.sin(p) * 0.012 : Math.abs(Math.sin(p)) * 0.035;
  c.body.rotation.x = 0.12;
  c.head.rotation.z = Math.sin(p) * 0.05;
  c.tail.rotation.x = -0.15 + Math.sin(p * 0.5) * 0.12;
  c.tail.rotation.z = Math.sin(p * 0.5 + 1) * 0.18;
  if (c.look) {
    c.head.rotation.y = Math.max(-0.6, Math.min(0.6, c.look.x)) * (idle ? 1 : 0.35);
    c.head.rotation.x = Math.max(-0.25, Math.min(0.25, c.look.y)) * (idle ? 1 : 0.35);
  }
  if (c.hopUntil && performance.now() < c.hopUntil) {
    const k = 1 - (c.hopUntil - performance.now()) / 420;
    c.root.position.y = FLOOR + Math.sin(Math.max(0, Math.min(1, k)) * Math.PI) * 16;
  } else if (c.resident) {
    c.root.position.y = FLOOR;
  }
  if (c.groom) {
    c.arms[0].rotation.x = -2.4 + Math.sin(p * 6) * 0.2;
    c.arms[0].rotation.z = -0.6;
  }
  if (c.arms && c.arms[0]) {
    if (c.waveOn) {
      c.arms[0].rotation.z = 0.25 + Math.sin(p * 2.2) * 0.55;
      c.arms[0].rotation.x = -2.1;
    } else {
      c.arms[0].rotation.z = -0.25;
      c.arms[0].rotation.x = -0.9;
    }
  }
  if (c.beerGroup) c.beerGroup.visible = !!c.beerOn;
}

function frame() {
  state.raf = 0;
  if (!state.renderer || document.hidden) return;
  const dt = Math.min(0.05, state.clock.getDelta());
  const now = performance.now();

  const res = state.resident;
  if (res) {
    const dx = state.pointer.x - res.x;
    const dy = state.pointer.y - FLOOR;
    res.look = { x: dx / 260, y: -dy / 260 };
    const near = Math.abs(dx) < 120 && state.pointer.y < FLOOR + 90;
    if (near && now > state.lastPoke + 1600) {
      state.lastPoke = now;
      res.hopUntil = now + 420;
      res.target = res.x + (dx > 0 ? -18 : 18);
    }
    if (now > res.nextAction) {
      res.nextAction = now + 3500 + Math.random() * 6000;
      const r = Math.random();
      if (r < 0.34) {
        const lim = Math.max(120, state.W / 2 - 220);
        res.target = Math.max(-lim, Math.min(lim, res.x + (Math.random() - 0.5) * 260));
      } else if (r < 0.52) {
        res.hopUntil = now + 420;
      } else if (r < 0.64) {
        res.groom = true;
        setTimeout(() => { res.groom = false; }, 700);
      } else if (r < 0.78) {
        kickNut({ x: res.x, y: FLOOR });
      }
    }
    const d = res.target - res.x;
    if (Math.abs(d) > 1.5) {
      res.x += Math.sign(d) * Math.min(Math.abs(d), 62 * dt);
      res.speed = 62;
    } else {
      res.speed = 0;
    }
  }

  for (const c of [...state.critters]) {
    if (c.holdAt && !c.held && c.x >= c.holdAt) {
      c.held = true;
      c.holdUntil = now + 2000;
      c.beerOn = true;
    }
    if (c.held && now > c.holdUntil) { c.held = false; c.beerOn = false; }
    if (c.waveUntil && now > c.waveUntil) { c.waveUntil = 0; c.waveOn = false; }

    if (!c.resident && !c.held) c.x += c.speed * dt;
    if (c.dive && c.x > state.W + 40) c.y -= 240 * dt;
    c.root.position.x = c.x;
    c.root.position.y = c.y;
    c.root.rotation.y = c.waveOn ? 0 : Math.PI / 2;
    if (!c.resident && !c.held && !c.waveOn && now > c.nextKick && c.x > -state.W / 2 && c.x < state.W / 2) {
      c.nextKick = now + 900 + Math.random() * 1500;
      kickNut(c);
    }
    pose(c, dt);
    if (c.x > c.endX || c.y < -BAR) removeCritter(c);
  }

  for (const n of [...state.nuts]) {
    n.vy -= 900 * dt;
    n.x += n.vx * dt;
    n.y += n.vy * dt;
    n.rot += n.spin * dt;
    if (n.y < FLOOR + 3) {
      n.y = FLOOR + 3;
      n.vy = -n.vy * 0.42;
      n.vx *= 0.88;
      if (Math.abs(n.vy) < 40) { n.vy = 0; n.vx *= 0.9; }
    }
    n.mesh.position.set(n.x, n.y, 0.2);
    n.mesh.rotation.z = n.rot;
    if (n.x > state.W + 60 || n.x < -80) {
      state.scene.remove(n.mesh);
      state.nuts = state.nuts.filter((x) => x !== n);
    }
  }

  if (state.resident && !state.critters.includes(state.resident)) state.critters.unshift(state.resident);
  if (state.critters.length || state.nuts.length) {
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

/* kinds: through | hold (two friends + beer) | chase | wave | dive */
function run(kind) {
  if (optedOut || document.hidden) return;
  ensureLoop();
  const w = state.W;
  const base = { endX: w + 90, speed: 115 + Math.random() * 55 };
  if (kind === 'hold') {
    addCritter({ ...base, x: -60, holdAt: w * 0.55 });
    addCritter({ ...base, x: -130, speed: base.speed + 25, holdAt: 0 });
  } else if (kind === 'chase') {
    addCritter({ ...base, x: -60 });
    addCritter({ ...base, x: -150, speed: base.speed + 55 });
  } else if (kind === 'wave') {
    const c = addCritter({ ...base, x: -60 });
    setTimeout(() => {
      if (!c || c.x > w) return;
      c.held = true;
      c.holdUntil = performance.now() + 2200;
      c.waveOn = true;
      c.waveUntil = performance.now() + 2200;
    }, 1600);
  } else if (kind === 'dive') {
    addCritter({ ...base, x: -60, dive: true });
  } else {
    addCritter({ ...base, x: -60 });
  }
}

function schedule() {
  const delay = 48000 + Math.random() * 72000;
  setTimeout(() => {
    const r = Math.random();
    run(r < 0.12 ? 'dive' : r < 0.24 ? 'wave' : r < 0.44 ? 'chase' : r < 0.66 ? 'hold' : 'through');
    schedule();
  }, delay);
}

export function callCritters() { run('hold'); }

function makeResident() {
  ensureLoop();
  const x = Math.max(-state.W / 2 + 100, Math.min(-60, state.W / 2 - 260));
  const c = addCritter({ x, speed: 0, endX: 1e9 });
  c.resident = true;
  c.target = x;
  c.nextAction = performance.now() + 2500;
  state.resident = c;
  if (!state.critters.includes(c)) state.critters.push(c);
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
  if (Math.abs(wx - c.x) < 30 && wy > FLOOR - 14 && wy < FLOOR + 62) {
    c.hopUntil = performance.now() + 420;
    c.nextAction = performance.now() + 4000;
    kickNut({ x: c.x, y: FLOOR });
    setTimeout(() => kickNut({ x: c.x, y: FLOOR }), 140);
    state.lastPet = performance.now();
  }
}

if (!optedOut) {
  window.addEventListener('pointermove', pointerAt, { passive: true });
  window.addEventListener('pointerdown', petCheck, true);
  makeResident();
  setTimeout(() => {
    if (!document.hidden) run('chase');
    schedule();
  }, 8000);
  const logo = document.querySelector('svg.mascot');
  if (logo) {
    const call = (e) => { e.preventDefault(); e.stopPropagation(); callCritters(); };
    logo.addEventListener('click', call);
    logo.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') call(e); });
  }
}

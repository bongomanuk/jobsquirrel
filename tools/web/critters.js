/* The critters: a properly rigged low-poly squirrel (three.js), plus friends.
 *
 * The squirrel scurries flat on all fours, sits up on its haunches to eat, and
 * has a small set of actions: look at the pointer, hop, wave, groom, stretch,
 * sleep, pull a face, kick acorns. He lives in the logo slot in the top bar and
 * returns there after every adventure.
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
  foam: new THREE.MeshStandardMaterial({ color: 0xf7f0de, roughness: 1 }),
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
  state.renderer = r;
  state.canvas = c;
  state.scene = new THREE.Scene();
  state.clock = new THREE.Clock();
  state.scene.add(new THREE.AmbientLight(0xffffff, 1.15));
  const key = new THREE.DirectionalLight(0xfff3e2, 1.7);
  key.position.set(-1.2, 3, 3.5);
  state.scene.add(key);
  const rim = new THREE.DirectionalLight(0xbfd4ff, 0.75);
  rim.position.set(2, 1.2, -3);
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
  const s = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 12), m);
  s.position.set(x, y, z);
  return s;
}
function limb(r, len, m) {
  return new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 4, 8), m);
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
  torso.scale.set(0.62, 0.55, 1.1);            // ~0.35 wide, 0.31 tall, 0.62 long
  hips.add(torso);
  const belly = ball(0.22, MAT.cream, 0, -0.06, 0.18);
  belly.scale.set(0.62, 0.5, 0.95);
  hips.add(belly);
  const vest = new THREE.Mesh(
    new THREE.SphereGeometry(0.29, 16, 12, Math.PI * 0.12, Math.PI * 0.76, 1.1, 1.1), MAT.vest);
  vest.scale.set(0.64, 0.56, 1.12);
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
  skull.scale.set(0.7, 0.62, 0.62);
  head.add(skull);
  const muzzle = ball(0.1, MAT.cream, 0, -0.045, 0.09);
  muzzle.scale.set(0.55, 0.42, 0.6);
  head.add(muzzle);
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
    const upper = limb(0.038, 0.1, MAT.furDark);
    upper.position.y = -0.06;
    shoulder.add(upper);
    const elbow = new THREE.Group();
    elbow.position.y = -0.13;
    shoulder.add(elbow);
    const fore = limb(0.034, 0.1, MAT.furDark);
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
    const thigh = limb(0.07, 0.16, MAT.furDark);
    thigh.position.y = -0.1;
    hip.add(thigh);
    const knee = new THREE.Group();
    knee.position.y = -0.2;
    hip.add(knee);
    const shin = limb(0.05, 0.12, MAT.furDark);
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

  const shadow = new THREE.Mesh(new THREE.CircleGeometry(0.3, 18),
    new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.16 }));
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = 0.01;
  shadow.scale.set(1.15, 0.7, 1);
  root.add(shadow);

  root.scale.setScalar(SCALE);
  return { root, hips, chest, neck, head, tail: [tail1, tail2, tail3],
           front, hind, tongue, beer, acorn };
}

function makeNut() {
  const g = new THREE.Group();
  const n = ball(0.09, MAT.nut, 0, 0, 0);
  n.scale.set(1, 1.2, 1);
  g.add(n);
  const cap = new THREE.Mesh(new THREE.SphereGeometry(0.1, 10, 6, 0, Math.PI * 2, 0, Math.PI / 2), MAT.nutCap);
  cap.position.y = 0.05;
  g.add(cap);
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
    spin: (Math.random() - 0.5) * 14, rot: 0,
  });
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

  if (c.hopUntil > now) {
    const k = 1 - (c.hopUntil - now) / 420;
    c.root.position.y = FLOOR + Math.sin(Math.max(0, Math.min(1, k)) * Math.PI) * 14;
  } else if (isResident) {
    c.root.position.y = FLOOR;
  }
  if (c.beer) c.beer.visible = !!c.beerOn;
}

/* ---------- frame loop ---------- */
function frame() {
  state.raf = 0;
  if (!state.renderer || document.hidden) return;
  const dt = Math.min(0.05, state.clock.getDelta());
  const now = performance.now();

  const res = state.resident;
  if (res) {
    const dx = state.pointer.x - res.x;
    const dy = state.pointer.y - FLOOR;
    res.look = { x: dx / 260, y: -dy / 300 };
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
      else if (r < 0.86) {
        const el = state.perches[Math.floor(Math.random() * state.perches.length)];
        if (el) {
          const r2 = el.getBoundingClientRect();
          res.target = Math.max(-state.W / 2 + 60, Math.min(state.W / 2 - 80,
            r2.left + r2.width / 2 - state.W / 2));
        }
      } else {
        res.target = res.home;
      }
    }
    if (res.waveUntil && now > res.waveUntil) { res.waveOn = false; res.waveUntil = 0; }
    const d = res.target - res.x;
    if (Math.abs(d) > 1.2) {
      res.speed = res.adventuring ? 150 : 55;
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
    if (c.holdAt && !c.held && c.x >= c.holdAt) {
      c.held = true;
      c.holdUntil = now + 2000;
      c.beerOn = true;
    }
    if (c.held && now > c.holdUntil) { c.held = false; c.beerOn = false; }
    if (!c.resident) {
      if (!c.held) c.x += c.speed * dt;
      if (c.dive && c.x > state.W + 40) c.y -= 220 * dt;
    }
    c.root.position.x = c.x;
    c.root.position.y = Math.max(c.y, FLOOR);
    const moving = c.resident ? Math.abs(c.target - c.x) > 1.2 : !c.held && c.speed > 0;
    let want = Math.PI / 2;
    if (c.waveOn) want = 0;
    else if (moving) want = (c.resident ? Math.sign(c.target - c.x) : 1) > 0 ? Math.PI / 2 : -Math.PI / 2;
    else if (c.resident) {
      const nd = Math.abs(state.pointer.x - c.x);
      want = nd < 160 && state.pointer.y < FLOOR + 120 ? 0 : Math.PI / 2;
    }
    c.root.rotation.y += (want - c.root.rotation.y) * Math.min(1, dt * 9);
    if (!c.resident && !c.held && !c.waveOn && now > c.nextKick &&
        c.x > -state.W / 2 && c.x < state.W / 2) {
      c.nextKick = now + 900 + Math.random() * 1400;
      kickNut(c);
    }
    animate(c, dt);
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
    if (n.x > state.W + 60 || n.x < -80 || now - n.born > 6000) {
      state.scene.remove(n.mesh);
      state.nuts = state.nuts.filter(x => x !== n);
    }
  }

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

function makeResident() {
  ensureLoop();
  const home = 33 - state.W / 2;            // the logo slot, next to the wordmark
  const c = addCritter({ x: home, speed: 0 });
  c.resident = true;
  c.home = home;
  c.target = home;
  c.nextAction = performance.now() + 2200;
  state.resident = c;
  state.perches = [...document.querySelectorAll('header.top button, header.top .pill, header.top h1')];
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
    c.hopUntil = performance.now() + 420;
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
  if (lead) {
    lead.adventuring = true;
    lead.target = kind === 'dive' ? w / 2 - 40 : w / 2 - 170;
  }
  const base = { endX: w + 90, speed: 115 + Math.random() * 50 };
  if (kind === 'hold') {
    addCritter({ ...base, x: -w / 2 - 60, friend: true, holdAt: 0 });
    addCritter({ ...base, x: -w / 2 - 150, friend: true, speed: base.speed + 25 });
  } else if (kind === 'chase') {
    addCritter({ ...base, x: -w / 2 - 60, friend: true, speed: base.speed + 20 });
  } else if (kind === 'wave') {
    if (lead) setTimeout(() => {
      if (!lead) return;
      lead.waveOn = true;
      lead.waveUntil = performance.now() + 2000;
      lead.target = lead.x;
    }, 1200);
  } else if (kind === 'dive') {
    addCritter({ ...base, x: -w / 2 - 60, friend: true, dive: true });
  }
}

export function callCritters() { run('hold'); }

function schedule() {
  const delay = 46000 + Math.random() * 70000;
  setTimeout(() => {
    const r = Math.random();
    run(r < 0.12 ? 'dive' : r < 0.24 ? 'wave' : r < 0.44 ? 'chase' : r < 0.66 ? 'hold' : 'through');
    schedule();
  }, delay);
}

const hasApp = !!document.querySelector('header.top .brand');
if (!optedOut && hasApp) {
  window.addEventListener('pointermove', pointerAt, { passive: true });
  window.addEventListener('pointerdown', petCheck, true);
  makeResident();
  setTimeout(() => {
    if (!document.hidden) run('chase');
    schedule();
  }, 8000);
}

/*
 * Ambient homepage background — a physically-grounded orbital that wraps.
 *
 * Function: a linear combination of real spherical harmonics,
 *   f(θ,φ) = Σ c_lm · Y_lm(θ,φ),
 * i.e. a general angular wavefunction (a superposition of angular-momentum
 * eigenstates / a hybrid orbital). Its sign is shown as colour — cyan for one
 * phase, magenta for the other, dark at the nodes.
 *
 * Geometry: a Fibonacci lattice, so points are EQUAL-AREA on the unit sphere
 * (θ = polar, φ = azimuth — a Bloch sphere of pure states, radius 1). The flat
 * "landscape" is the same field as a height map; the transition wraps it
 * directly onto the sphere (no cylinder stage), the relief flattening away as
 * the states settle onto the sphere. Auto-plays, no interaction.
 */
import * as THREE from 'three';

// --- real spherical harmonics via associated Legendre polynomials ---
function plgndr(l, m, x) {
  let pmm = 1;
  if (m > 0) {
    const somx2 = Math.sqrt(Math.max(0, (1 - x) * (1 + x)));
    let fact = 1;
    for (let i = 1; i <= m; i++) {
      pmm *= -fact * somx2;
      fact += 2;
    }
  }
  if (l === m) return pmm;
  let pmmp1 = x * (2 * m + 1) * pmm;
  if (l === m + 1) return pmmp1;
  let pll = 0;
  for (let ll = m + 2; ll <= l; ll++) {
    pll = ((2 * ll - 1) * x * pmmp1 - (ll + m - 1) * pmm) / (ll - m);
    pmm = pmmp1;
    pmmp1 = pll;
  }
  return pll;
}
function realY(l, m, ct, phi) {
  const am = Math.abs(m);
  const p = plgndr(l, am, ct);
  if (m === 0) return p;
  return m > 0 ? p * Math.cos(am * phi) : p * Math.sin(am * phi);
}

// the superposition: a handful of harmonics of different l and m
const TERMS = [
  { l: 1, m: 0, c: 0.5 },
  { l: 2, m: 2, c: 0.85 },
  { l: 3, m: 1, c: 0.7 },
  { l: 4, m: -3, c: 0.55 },
];

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

const NEG = [0.13, 0.83, 0.93];
const POS = [0.91, 0.47, 0.98];
const MID = [0.035, 0.045, 0.09];
function orbitalColor(fn) {
  const k = Math.pow(Math.min(1, Math.abs(fn)), 0.42);
  const end = fn < 0 ? NEG : POS;
  return [MID[0] + (end[0] - MID[0]) * k, MID[1] + (end[1] - MID[1]) * k, MID[2] + (end[2] - MID[2]) * k];
}

const smooth = (x) => {
  x = Math.min(1, Math.max(0, x));
  return x * x * x * (x * (x * 6 - 15) + 10);
};

export function initHomeBackground(canvas) {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const renderer = new THREE.WebGLRenderer({
    canvas,
    alpha: true,
    antialias: true,
    powerPreference: 'low-power',
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 50);
  function placeCamera() {
    const a = camera.aspect || 1;
    const back = a < 1 ? 1.5 : 1;
    camera.position.set(0, 2.4 * back, 4.3 * back); // elevated 3/4 view → clear perspective
    camera.lookAt(0, 0, 0);
    // right-shift only in the desktop two-column layout; centred on mobile
    scene.position.x = window.innerWidth >= 768 ? 1.35 : 0;
  }

  const N = 3600;
  const RS = 1.45;
  const FSCALE = 0.82; // flat map horizontal (φ)
  const DSCALE = 2.7; // flat map depth (θ)
  const RELIEF = 0.85; // flat terrain height, flattens on wrap
  const BULGE = 0.35; // outward puff mid-transition (organic inflate)
  const TILT = -0.8; // tilt the flat landscape toward the camera
  const cT = Math.cos(TILT);
  const sT = Math.sin(TILT);

  const flat = new Float32Array(N * 3);
  const sph = new Float32Array(N * 3);
  const col = new Float32Array(N * 3);

  const ct = new Float32Array(N);
  const ph = new Float32Array(N);
  const stt = new Float32Array(N);
  const thn = new Float32Array(N);

  // pass 1: geometry + per-term normalisation (harmonics differ wildly in scale)
  const termMax = TERMS.map(() => 1e-9);
  for (let i = 0; i < N; i++) {
    const y = 1 - (2 * (i + 0.5)) / N; // cosθ
    const theta = Math.acos(Math.max(-1, Math.min(1, y)));
    const phi = (i * GOLDEN_ANGLE) % (2 * Math.PI);
    ct[i] = y; ph[i] = phi; stt[i] = Math.sin(theta); thn[i] = theta / Math.PI;
    for (let k = 0; k < TERMS.length; k++) {
      const v = Math.abs(realY(TERMS[k].l, TERMS[k].m, y, phi));
      if (v > termMax[k]) termMax[k] = v;
    }
  }
  // pass 2: the superposition, then overall normalisation
  let fmax = 1e-9;
  const fval = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    let s = 0;
    for (let k = 0; k < TERMS.length; k++) {
      s += (TERMS[k].c * realY(TERMS[k].l, TERMS[k].m, ct[i], ph[i])) / termMax[k];
    }
    fval[i] = s;
    if (Math.abs(s) > fmax) fmax = Math.abs(s);
  }
  // pass 3: colours + flat/sphere positions
  for (let i = 0; i < N; i++) {
    const fn = fval[i] / fmax;
    const [r, g, b] = orbitalColor(fn);
    col[i * 3] = r; col[i * 3 + 1] = g; col[i * 3 + 2] = b;

    const a = ph[i] - Math.PI;
    const ca = Math.cos(a), sa = Math.sin(a);
    // flat: a landscape (φ→X, height, θ→depth), tilted toward the camera
    const fy = fn * RELIEF;
    const fz = (thn[i] - 0.5) * DSCALE;
    flat[i * 3] = a * FSCALE;
    flat[i * 3 + 1] = fy * cT - fz * sT;
    flat[i * 3 + 2] = fy * sT + fz * cT;
    // sphere: true unit sphere, polar axis Z
    sph[i * 3] = RS * stt[i] * ca;
    sph[i * 3 + 1] = RS * stt[i] * sa;
    sph[i * 3 + 2] = RS * ct[i];
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(flat), 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  const surface = new THREE.Points(
    geo,
    new THREE.PointsMaterial({
      size: 0.032,
      sizeAttenuation: true, // points shrink with distance → perspective depth
      vertexColors: true,
      transparent: true,
      opacity: 0.72,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }),
  );
  scene.add(surface);
  const pos = geo.attributes.position.array;

  // direct wrap: flat landscape → sphere (no cylinder), with an organic bulge
  function layout(w) {
    const t = smooth(w);
    const bulge = Math.sin(Math.PI * t) * (BULGE / RS);
    for (let i = 0; i < N; i++) {
      const j = i * 3;
      const sx = sph[j], sy = sph[j + 1], sz = sph[j + 2];
      pos[j] = flat[j] + (sx - flat[j]) * t + sx * bulge;
      pos[j + 1] = flat[j + 1] + (sy - flat[j + 1]) * t + sy * bulge;
      pos[j + 2] = flat[j + 2] + (sz - flat[j + 2]) * t + sz * bulge;
    }
    geo.attributes.position.needsUpdate = true;
  }

  function resize() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    if (
      canvas.width !== Math.floor(w * renderer.getPixelRatio()) ||
      canvas.height !== Math.floor(h * renderer.getPixelRatio())
    ) {
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      placeCamera();
    }
  }

  if (reduced) {
    resize();
    placeCamera();
    layout(1);
    surface.rotation.y = 0.5;
    renderer.render(scene, camera);
    return;
  }

  const clock = new THREE.Clock();
  const PERIOD = 24;
  const SPIN = 0.3;
  let last = 0;
  let spin = 0;
  let raf = 0;

  function frame() {
    resize();
    const t = clock.getElapsedTime();
    const dt = Math.min(t - last, 0.05);
    last = t;
    // eased loop that dwells longer on the flat landscape and the sphere
    const raw = 0.5 - 0.5 * Math.cos((2 * Math.PI * t) / PERIOD);
    const s = smooth(raw);
    // always turning, faster once it is the sphere
    spin += dt * SPIN * (0.3 + 0.7 * s);
    surface.rotation.y = spin;
    layout(raw);
    renderer.render(scene, camera);
    raf = requestAnimationFrame(frame);
  }

  const io = new IntersectionObserver(([entry]) => {
    if (entry.isIntersecting) {
      last = 0;
      clock.start();
      frame();
    } else {
      cancelAnimationFrame(raf);
    }
  });
  io.observe(canvas);
}

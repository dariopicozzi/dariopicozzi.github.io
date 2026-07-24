/*
 * Ambient homepage background — a physically-grounded orbital that wraps.
 *
 * Function: a linear combination of real spherical harmonics,
 *   f(θ,φ) = Σ c_lm · Y_lm(θ,φ),
 * i.e. a general angular wavefunction (a superposition of angular-momentum
 * eigenstates / a hybrid orbital). Its sign is shown as colour — cyan for one
 * phase, magenta for the other, dark at the nodes.
 *
 * Geometry: a Fibonacci lattice, so points are EQUAL-AREA on the unit sphere.
 * The flat "landscape" is the same field as a height map; the transition wraps
 * it directly onto the sphere, the relief flattening away as the states settle.
 *
 * Drawn with the 2D canvas: it needs no GPU and no WebGL, so it renders on every
 * browser, and its circles are analytically antialiased. Additive blending is
 * 'lighter'; because addition commutes, no depth sorting is needed.
 */

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

const TERMS = [
  { l: 1, m: 0, c: 0.5 },
  { l: 2, m: 2, c: 0.85 },
  { l: 3, m: 1, c: 0.7 },
  { l: 4, m: -3, c: 0.55 },
];

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

const NEG = [33, 212, 237];
const POS = [232, 120, 250];
const MID = [9, 11, 23];
function orbitalColor(fn) {
  const k = Math.pow(Math.min(1, Math.abs(fn)), 0.42);
  const end = fn < 0 ? NEG : POS;
  return (
    'rgb(' +
    Math.round(MID[0] + (end[0] - MID[0]) * k) + ',' +
    Math.round(MID[1] + (end[1] - MID[1]) * k) + ',' +
    Math.round(MID[2] + (end[2] - MID[2]) * k) + ')'
  );
}

const smooth = (x) => {
  x = Math.min(1, Math.max(0, x));
  return x * x * x * (x * (x * 6 - 15) + 10);
};

// Returns whether the figure is running, so the page can drop the canvas and
// reveal the text on its own if it is not.
export function initHomeBackground(canvas) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return false;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const N = 3600;
  const RS = 1.45;
  const FSCALE = 0.82; // flat map horizontal (φ)
  const DSCALE = 2.7; // flat map depth (θ)
  const RELIEF = 0.85; // flat terrain height, flattens on wrap
  const BULGE = 0.35; // outward puff mid-transition
  const TILT = -0.8; // tilt the flat landscape toward the camera
  const cT = Math.cos(TILT);
  const sT = Math.sin(TILT);
  const FOV = 42;
  // world-space dot diameter. 0.0123 reproduces the old sprite exactly; a disc
  // covers pi/4 of the square it replaces, so widen by 1/sqrt(pi/4) to keep the
  // same total light.
  const SIZE = 0.0139;

  const flat = new Float32Array(N * 3);
  const sph = new Float32Array(N * 3);
  const col = new Array(N);
  const ct = new Float32Array(N);
  const ph = new Float32Array(N);
  const stt = new Float32Array(N);
  const thn = new Float32Array(N);

  // Evaluate each harmonic once and keep it: the normalisation needs a second
  // pass, and re-evaluating the Legendre polynomials there would double the
  // startup cost for nothing.
  const K = TERMS.length;
  const yv = new Float32Array(N * K);
  const termMax = TERMS.map(() => 1e-9);
  for (let i = 0; i < N; i++) {
    const y = 1 - (2 * (i + 0.5)) / N; // cosθ
    const theta = Math.acos(Math.max(-1, Math.min(1, y)));
    const phi = (i * GOLDEN_ANGLE) % (2 * Math.PI);
    ct[i] = y; ph[i] = phi; stt[i] = Math.sin(theta); thn[i] = theta / Math.PI;
    for (let k = 0; k < K; k++) {
      const v = realY(TERMS[k].l, TERMS[k].m, y, phi);
      yv[i * K + k] = v;
      const av = Math.abs(v);
      if (av > termMax[k]) termMax[k] = av;
    }
  }
  let fmax = 1e-9;
  const fval = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    let s = 0;
    for (let k = 0; k < K; k++) s += (TERMS[k].c * yv[i * K + k]) / termMax[k];
    fval[i] = s;
    if (Math.abs(s) > fmax) fmax = Math.abs(s);
  }
  for (let i = 0; i < N; i++) {
    const fn = fval[i] / fmax;
    col[i] = orbitalColor(fn);
    const a = ph[i] - Math.PI;
    const fy = fn * RELIEF;
    const fz = (thn[i] - 0.5) * DSCALE;
    flat[i * 3] = a * FSCALE;
    flat[i * 3 + 1] = fy * cT - fz * sT;
    flat[i * 3 + 2] = fy * sT + fz * cT;
    sph[i * 3] = RS * stt[i] * Math.cos(a);
    sph[i * 3 + 1] = RS * stt[i] * Math.sin(a);
    sph[i * 3 + 2] = RS * ct[i];
  }

  // How many points we actually draw. On a slow device we raise this rather
  // than dropping resolution: cost is linear in the number of points and almost
  // independent of pixel count, and a golden-angle lattice sampled every k-th
  // point is still an equal-area lattice, just a sparser one.
  let stride = 1;

  // scratch buffer for the current morphed positions
  const pos = new Float32Array(N * 3);
  function layout(w) {
    const t = smooth(w);
    const bulge = Math.sin(Math.PI * t) * (BULGE / RS);
    for (let i = 0; i < N; i += stride) {
      const j = i * 3;
      const sx = sph[j], sy = sph[j + 1], sz = sph[j + 2];
      pos[j] = flat[j] + (sx - flat[j]) * t + sx * bulge;
      pos[j + 1] = flat[j + 1] + (sy - flat[j + 1]) * t + sy * bulge;
      pos[j + 2] = flat[j + 2] + (sz - flat[j + 2]) * t + sz * bulge;
    }
  }

  // camera: elevated 3/4 view, looking at the origin. Because it sits in the
  // YZ plane the basis is simple: x stays x, and y/z rotate by the elevation.
  let W = 0, H = 0, dpr = 1, camY = 0, camZ = 0, ny = 0, nz = 0, shiftX = 0, halfTan = 0;
  function resize() {
    const cw = canvas.clientWidth;
    const chh = canvas.clientHeight;
    if (!cw || !chh) return false;
    dpr = Math.min(window.devicePixelRatio || 1, 3);
    const w = Math.floor(cw * dpr);
    const h = Math.floor(chh * dpr);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    W = w; H = h;
    const aspect = W / H;
    const back = aspect < 1 ? 1.5 : 1;
    camY = 2.4 * back;
    camZ = 4.3 * back;
    const len = Math.hypot(camY, camZ);
    ny = camY / len; nz = camZ / len; // camera z-axis (points from origin to camera)
    shiftX = window.innerWidth >= 768 ? 1.35 : 0;
    halfTan = Math.tan((FOV * Math.PI) / 360);
    return true;
  }

  function draw(spin) {
    const cs = Math.cos(spin), sn = Math.sin(spin);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = 0.72;
    const fy = H / (2 * halfTan); // focal length in device px
    for (let i = 0; i < N; i += stride) {
      const j = i * 3;
      // spin about Y, then the scene offset
      const x = pos[j] * cs + pos[j + 2] * sn + shiftX;
      const yw = pos[j + 1];
      const z = -pos[j] * sn + pos[j + 2] * cs;
      // into camera space
      const vy = yw - camY;
      const vz = z - camZ;
      const zc = vy * ny + vz * nz;
      if (zc >= -0.05) continue; // behind or too close to the camera
      const yc = vy * nz - vz * ny;
      const inv = -1 / zc;
      const sx = W / 2 + x * fy * inv;
      const sy = H / 2 - yc * fy * inv;
      const r = SIZE * 0.5 * fy * inv; // perspective size attenuation
      if (r < 0.05 || sx < -8 || sy < -8 || sx > W + 8 || sy > H + 8) continue;
      ctx.fillStyle = col[i];
      ctx.beginPath();
      ctx.arc(sx, sy, r, 0, 6.283185307179586);
      ctx.fill();
    }
  }

  if (reduced) {
    if (resize()) { layout(1); draw(0.5); }
    return true;
  }

  const PERIOD = 24;
  const SPIN = 0.3;
  const BUDGET = 6; // ms of drawing per frame before we thin the lattice
  const MAX_STRIDE = 4;
  let spin = 0;
  let last = 0;
  let raf = 0;
  let t0 = 0;
  let cost = 0;

  function frame(now) {
    if (!t0) t0 = now;
    const t = (now - t0) / 1000;
    const dt = Math.min(t - last, 0.05);
    last = t;
    if (resize()) {
      const raw = 0.5 - 0.5 * Math.cos((2 * Math.PI * t) / PERIOD);
      const s = smooth(raw);
      spin += dt * SPIN * (0.3 + 0.7 * s);
      const t1 = performance.now();
      layout(raw);
      draw(spin);
      // Watch what the frame actually cost and thin the lattice if this device
      // cannot keep up — an old CPU, a busy tab, thermal throttling. Smoothed,
      // so one slow frame does not trigger it.
      cost = cost ? cost * 0.9 + (performance.now() - t1) * 0.1 : performance.now() - t1;
      if (cost > BUDGET && stride < MAX_STRIDE) {
        stride++;
        cost = 0;
      }
    }
    raf = requestAnimationFrame(frame);
  }

  const io = new IntersectionObserver(([entry]) => {
    if (entry.isIntersecting) {
      t0 = 0; last = 0;
      raf = requestAnimationFrame(frame);
    } else {
      cancelAnimationFrame(raf);
    }
  });
  io.observe(canvas);
  return true;
}

/*
 * The hydrogen molecule on one qubit.
 *
 * Bravyi–Kitaev 2-qubit H₂ Hamiltonian at R = 0.75 Å (STO-3G),
 * coefficients from O'Malley et al., Phys. Rev. X 6, 031007 (2016):
 *   H = g0·I + g1·Z0 + g2·Z1 + g3·Z0Z1 + g4·Y0Y1 + g5·X0X1
 * Restricted to the single-excitation sector {|01⟩, |10⟩} this becomes a
 * one-qubit Hamiltonian  H_eff = c0·I + c1·Z + c2·X, so with the state
 * |ψ(θ,φ)⟩ = cos(θ/2)|0⟩ + e^{iφ} sin(θ/2)|1⟩ the energy is exactly
 *   E(θ,φ) = c0 + c1·cosθ + c2·sinθ·cosφ.
 * Including nuclear repulsion (0.7137 Ha at 0.75 Å) the minimum recovers
 * the full-CI ground-state energy of H₂/STO-3G, ≈ −1.137 Ha.
 */

const g = { g0: -0.4804, g1: 0.3435, g2: -0.4347, g3: 0.5716, g4: 0.091, g5: 0.091 };
const E_NUC = 0.7137;

const Haa = g.g0 - g.g1 + g.g2 - g.g3; // ⟨01|H|01⟩
const Hbb = g.g0 + g.g1 - g.g2 - g.g3; // ⟨10|H|10⟩
const Hab = g.g4 + g.g5; // ⟨01|H|10⟩

export const c0 = (Haa + Hbb) / 2 + E_NUC;
export const c1 = (Haa - Hbb) / 2;
export const c2 = Hab;

export const E_MIN = c0 - Math.hypot(c1, c2); // exact ground energy ≈ −1.1373 Ha
export const E_MAX = c0 + Math.hypot(c1, c2);

export function energy(theta, phi) {
  return c0 + c1 * Math.cos(theta) + c2 * Math.sin(theta) * Math.cos(phi);
}

export function grad(theta, phi) {
  return {
    dT: -c1 * Math.sin(theta) + c2 * Math.cos(theta) * Math.cos(phi),
    dP: -c2 * Math.sin(theta) * Math.sin(phi),
  };
}

/* The exact minimum of E(θ,φ) (for drawing the target marker). */
export function minimum() {
  // stationary point: tanθ = c2·cosφ / c1 with cosφ = ±1; pick the lower.
  let best = { theta: 0, phi: 0, E: Infinity };
  for (const phi of [0, Math.PI]) {
    for (let k = 0; k < 2; k++) {
      const theta = Math.atan2(c2 * Math.cos(phi), c1) + k * Math.PI;
      const t = ((theta % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
      if (t <= Math.PI) {
        const E = energy(t, phi);
        if (E < best.E) best = { theta: t, phi, E };
      }
    }
  }
  return best;
}

/*
 * Descend from (θ0, φ0) with plain gradient descent on the chart
 * coordinates, or with natural gradient descent using the Fubini–Study
 * metric  g = ¼·diag(1, sin²θ)  (i.e. the update is g⁻¹·∇E).
 */
export function descend(theta0, phi0, { natural = false, lr = 0.01, steps = 2600 } = {}) {
  const path = [];
  let th = theta0;
  let ph = phi0;
  for (let i = 0; i < steps; i++) {
    if (i % 4 === 0) path.push({ theta: th, phi: ph, E: energy(th, ph) });
    const { dT, dP } = grad(th, ph);
    if (natural) {
      const s2 = Math.max(Math.sin(th) ** 2, 1e-6);
      th -= lr * 4 * dT;
      ph -= (lr * 4 * dP) / s2;
    } else {
      th -= lr * dT;
      ph -= lr * dP;
    }
    th = Math.min(Math.PI - 1e-4, Math.max(1e-4, th));
  }
  path.push({ theta: th, phi: ph, E: energy(th, ph) });
  return path;
}

/* Map a (θ, φ, E) triple to 3D: w = 0 flat chart, w = 1 Bloch sphere.
   On the chart, energy points up (terrain-style): x = φ, z = θ, y = E. */
export function chartToWorld(theta, phi, E, w, { W = 2.2, H = 1.35, R = 1.75, relief = 1.7 } = {}) {
  const eN = (E - E_MIN) / (E_MAX - E_MIN); // 0..1
  // θ runs horizontally (the dominant energy direction), φ in depth
  const fx = (theta / Math.PI - 0.5) * 2 * W;
  const fy = (eN - 0.5) * relief;
  const fz = ((phi / Math.PI) - 1) * H;
  // sphere: radius gently modulated by energy so the landscape stays visible
  const r = R * (1 + 0.13 * (eN - 0.5));
  const sx = r * Math.sin(theta) * Math.cos(phi);
  const sy = r * Math.cos(theta);
  const sz = r * Math.sin(theta) * Math.sin(phi);
  return [fx + (sx - fx) * w, fy + (sy - fy) * w, fz + (sz - fz) * w, eN];
}

/* Energy colormap: cyan (low) → indigo (mid) → magenta (high). */
export function energyColor(eN) {
  const stops = [
    [0.13, 0.83, 0.93], // #22d3ee
    [0.42, 0.45, 0.93], // #6b73ee
    [0.91, 0.47, 0.98], // #e879f9
  ];
  const t = Math.min(1, Math.max(0, eN)) * 2;
  const i = t < 1 ? 0 : 1;
  const f = t - i;
  return [
    stops[i][0] + (stops[i + 1][0] - stops[i][0]) * f,
    stops[i][1] + (stops[i + 1][1] - stops[i][1]) * f,
    stops[i][2] + (stops[i + 1][2] - stops[i][2]) * f,
  ];
}

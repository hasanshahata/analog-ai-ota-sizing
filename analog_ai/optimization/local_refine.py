"""Neural warm-start local refinement (review Phase C).

The global-DE fallback restarts evolution over the whole design domain
(~1,700 oracle calls). Most surrogate misses are near-misses: the right
first move is a *bounded local* search around the best neural candidate,
expanding the trust region only if it fails, and calling global DE only as
the last resort.

Local objective: minimize the TOTAL positive normalized residual (smooth -
every violated constraint pulls), tie-broken by the maximum violation, then
power. A max-only objective plateaus whenever a step does not reduce the
single worst constraint, which empirically stalls Powell after ~46 evals;
with the total-first objective, bounded Nelder-Mead repairs probe near-misses
in ~127 evals. The hard verifier - never this scalar - decides success: a
stage "passes" only when a fresh full-request verification returns
verdict=True.
"""

from __future__ import annotations

import time

import numpy as np
from scipy.optimize import minimize

from .. import config
from ..evaluation.constraints import evaluate_constraints
from .de_baseline import make_objective  # noqa: F401  (re-exported below)


def make_local_objective(ota, specs, cl):
    """Feasibility-first scalar over physical design vectors: total
    violation first (smooth), max violation as tie-breaker, then power."""
    def objective(x):
        try:
            perf = ota.evaluate(x, CL=cl)
        except Exception:
            return 1e3  # invalid designs are maximally bad, finite
        constraints, _ = evaluate_constraints(perf, specs)
        pos = [max(0.0, c.residual) for c in constraints]
        max_v = max(pos) if pos else 0.0
        tot_v = sum(pos)
        return tot_v + 1e-3 * max_v + 1e-6 * (perf["Power"]
                                              / config.OBS_POWER_NORM)
    return objective


def local_refine(ota, specs, candidates, trust_fracs=(0.02, 0.05, 0.10),
                 n_heads: int = 2, maxfev: int = 600,
                 verifier=None) -> dict:
    """Bounded local search around ranked candidate designs.

    candidates: physical design vectors, best-first (e.g. model heads ranked
    by worst violation). For each of the first `n_heads` candidates, the
    trust-region ladder widens around it; the first hard-verified pass ends
    the search. Returns a dict with status, provenance of the winning stage,
    oracle-call count and runtime; `unresolved` carries the best design and
    violation seen.
    """
    # Mode-aware bounds (Phase F3): finite objects optimize the
    # seven-parameter contract, ideal objects the five-parameter one.
    bounds = config.design_bounds(getattr(ota, "tail_device", "ideal"))
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    cl = float(specs.get("CL_pF", 1.0)) * 1e-12
    objective = make_local_objective(ota, specs, cl)

    t0 = time.time()
    n_evals = 0
    best_fail = {"worst_violation": np.inf, "design": None}
    stages = []
    for h, x0 in enumerate(list(candidates)[:n_heads]):
        x0 = np.clip(np.asarray(x0, dtype=float), lo, hi)
        u0 = (x0 - lo) / (hi - lo)
        for t in trust_fracs:
            u_lo = np.maximum(u0 - t, 0.0)
            u_hi = np.minimum(u0 + t, 1.0)
            bounds = list(zip(lo + u_lo * (hi - lo), lo + u_hi * (hi - lo)))
            res = minimize(objective, x0, method="Nelder-Mead",
                           bounds=bounds,
                           options={"maxfev": maxfev,
                                    "xatol": 1e-6, "fatol": 1e-8})
            n_evals += int(getattr(res, "nfev", 0))
            stages.append({"head": h, "trust_frac": t,
                           "n_evals": int(res.nfev),
                           "objective": float(res.fun)})
            row = verifier(ota, res.x, specs) if verifier else None
            viol = (row["worst_violation"] if row is not None
                    else float(res.fun))
            if row is not None and row["verdict"]:
                return {"status": "local_refinement_verified",
                        "design": [float(v) for v in res.x],
                        "head": h, "trust_frac": t, "n_evals": n_evals,
                        "runtime_s": round(time.time() - t0, 1),
                        "stages": stages, "row": row}
            if viol < best_fail["worst_violation"]:
                best_fail = {"worst_violation": viol,
                             "design": [float(v) for v in res.x]}
    return {"status": "unresolved", "design": best_fail["design"],
            "head": None, "trust_frac": None, "n_evals": n_evals,
            "runtime_s": round(time.time() - t0, 1), "stages": stages,
            "worst_violation": best_fail["worst_violation"]}

"""Space-filling design sampling and request derivation (Phase 3).

The correction plan's fix for goal-insensitive models: requests shown to a
learner must come from *verified* designs, so the feasible label is true by
construction. This module samples the 5-parameter design domain (Sobol) and
derives request vectors from evaluated designs:

- feasible:          achieved metrics relaxed by a small random margin — the
                     source design strictly satisfies the request;
- near_boundary:     margins in [0, 0.02) — the request sits at the edge of
                     what the source design achieves;
- beyond_sample_envelope: one dimension pushed beyond the best value observed
                     in the whole dataset at that CL. This is a dataset-
                     relative extreme, NOT proof that no design exists
                     elsewhere in the continuous space; optimizer-failed
                     requests carry the separate `unresolved_by_optimizer`
                     label (see `build.certify_request`).
"""

from __future__ import annotations

import numpy as np

from .. import config

# Load capacitances the sweep evaluates (pF). Spans the OBS normalization and
# the five regression cases (1-5 pF) plus a light-load point.
CL_GRID_PF = (0.2, 1.0, 5.0)

# Request-derivation margins (fraction of the achieved value).
FEASIBLE_MARGIN = (0.02, 0.15)
NEAR_BOUNDARY_MARGIN = (0.0, 0.02)

# Derived-infeasible extremes, relative to the dataset statistics at the same
# CL (see `derive_requests`).
INFEASIBLE_GAIN_ADD_DB = (3.0, 10.0)     # above max observed gain
INFEASIBLE_GBW_FACTOR = (1.3, 2.0)       # above max observed GBW
INFEASIBLE_POWER_FACTOR = (0.3, 0.7)     # below min observed power


def sobol_designs(n: int, seed: int) -> np.ndarray:
    """First `n` Sobol points over DESIGN_BOUNDS, in physical units.

    The full sequence is deterministic in (n, seed); generation is cheap, so
    resumable callers may re-derive row `i` at any time.
    """
    from scipy.stats import qmc

    sampler = qmc.Sobol(d=len(config.DESIGN_PARAM_NAMES), scramble=True, seed=seed)
    lows = np.array([b[0] for b in config.DESIGN_BOUNDS])
    highs = np.array([b[1] for b in config.DESIGN_BOUNDS])
    return lows + sampler.random(n) * (highs - lows)


def _specs(gain, gbw, power, cl_pf) -> dict:
    return {"Gain_min": float(gain), "GBW_min": float(gbw),
            "Power_max": float(power), "CL_pF": float(cl_pf)}


def derive_requests(metrics: dict, cl_pf: float, dataset_stats: dict,
                    rng: np.random.Generator) -> tuple[dict, dict, dict]:
    """(feasible, near_boundary, infeasible_derived) specs for one design.

    `dataset_stats[cl_pf]` must provide max_gain / max_gbw / min_power
    observed at that load (see `build.dataset_stats`); the infeasible variant
    pushes one dimension beyond those observed extremes.
    """
    gain = float(metrics["DC_Gain_dB"])
    gbw = float(metrics["GBW"])
    power = float(metrics["Power"])

    def _relaxed(margin):
        m_g = rng.uniform(*margin)
        m_p = rng.uniform(*margin)
        return _specs(gain * (1.0 - m_g), gbw * (1.0 - m_g),
                      power * (1.0 + m_p), cl_pf)

    feasible = _relaxed(FEASIBLE_MARGIN)
    near_boundary = _relaxed(NEAR_BOUNDARY_MARGIN)

    stats = dataset_stats[cl_pf]
    kind = int(rng.integers(3))
    if kind == 0:    # unrealizable gain
        base = max(gain, stats["max_gain"])
        infeasible = _specs(base + rng.uniform(*INFEASIBLE_GAIN_ADD_DB),
                            gbw * (1.0 - 0.05), power * (1.0 + 0.05), cl_pf)
    elif kind == 1:  # unrealizable GBW
        base = max(gbw, stats["max_gbw"])
        infeasible = _specs(gain * (1.0 - 0.05),
                            base * rng.uniform(*INFEASIBLE_GBW_FACTOR),
                            power * (1.0 + 0.05), cl_pf)
    else:            # unrealizable power
        base = min(power, stats["min_power"])
        infeasible = _specs(gain * (1.0 - 0.05), gbw * (1.0 - 0.05),
                            base * rng.uniform(*INFEASIBLE_POWER_FACTOR), cl_pf)
    infeasible["infeasible_dim"] = ("Gain_min", "GBW_min", "Power_max")[kind]
    return feasible, near_boundary, infeasible

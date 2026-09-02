"""Leakage-safe split assignment (Phase 3, plan item 5).

Splitting rows at random leaks near-duplicates; splitting by target region
alone still leaks *identical designs*: one Sobol design sources a feasible,
a near-boundary, and a beyond-envelope request, and region-based assignment
can send them to different splits — so a model would see the exact target
design during training and again at test time under a slightly different
request (measured: 4,436 shared design IDs between the pilot train and test
splits). The unit of assignment is therefore the **design group**: every
request row referencing the same `design_row_id` inherits that design's
single split. Groups are stratified by coarse target region so all splits
keep balanced coverage of the target space.
"""

from __future__ import annotations

import numpy as np

# Fixed normalization ranges (Gain dB; GBW Hz log; CL pF log; Power W log).
GAIN_RANGE = (0.0, 80.0)
GBW_LOG_RANGE = (6.0, 10.0)        # 1 MHz .. 10 GHz
CL_LOG_RANGE = (np.log10(0.05), np.log10(20.0))
POWER_LOG_RANGE = (-6.0, -2.3)     # 1 uW .. ~5 mW

N_BINS = 10            # fine regions (polish stratification)
N_BINS_COARSE = 2      # coarse strata (split balancing)

SPLIT_PROPORTIONS = (("train", 0.70), ("val", 0.10), ("test", 0.20))


def _frac(v: float, lo: float, hi: float) -> float:
    return min(max((v - lo) / (hi - lo), 0.0), 0.999_999)


def region_key(gain: float, gbw: float, cl_pf: float, power: float) -> tuple:
    dims = (
        _frac(gain, *GAIN_RANGE),
        _frac(np.log10(max(gbw, 1e-12)), *GBW_LOG_RANGE),
        _frac(np.log10(max(cl_pf, 1e-6)), *CL_LOG_RANGE),
        _frac(np.log10(max(power, 1e-12)), *POWER_LOG_RANGE),
    )
    return tuple(int(d * N_BINS) for d in dims)


def coarse_region(gain: float, gbw: float, cl_pf: float, power: float) -> tuple:
    dims = (
        _frac(gain, *GAIN_RANGE),
        _frac(np.log10(max(gbw, 1e-12)), *GBW_LOG_RANGE),
        _frac(np.log10(max(cl_pf, 1e-6)), *CL_LOG_RANGE),
        _frac(np.log10(max(power, 1e-12)), *POWER_LOG_RANGE),
    )
    return tuple(int(d * N_BINS_COARSE) for d in dims)


def region_key_of_row(row: dict) -> tuple:
    return region_key(row["req_Gain_min"], row["req_GBW_min"],
                      row["req_CL_pF"], row["req_Power_max"])


def _coarse_of_group(rows: list[dict]) -> tuple:
    """Coarse region of a design group, represented by its feasible request
    (falls back to the first row for designs with only negative requests)."""
    rep = next((r for r in rows if r["label"] == "feasible"), rows[0])
    return coarse_region(rep["req_Gain_min"], rep["req_GBW_min"],
                         rep["req_CL_pF"], rep["req_Power_max"])


def assign_splits_by_design(request_rows: list[dict], seed: int) -> dict:
    """Set `split` on every request row, by design group; return the map.

    Returns {design_row_id: split}. Deterministic in (rows, seed): groups
    are visited in sorted order within each sorted stratum.
    """
    groups: dict[str, list[dict]] = {}
    for r in request_rows:
        groups.setdefault(r["design_row_id"], []).append(r)

    strata: dict[tuple, list[str]] = {}
    for design_id, rows in groups.items():
        strata.setdefault(_coarse_of_group(rows), []).append(design_id)

    rng = np.random.default_rng([seed, 77])
    n_tr = 0.70
    n_va = 0.10
    mapping: dict[str, str] = {}
    for stratum in sorted(strata):
        ids = sorted(strata[stratum])
        rng.shuffle(ids)
        n = len(ids)
        cut_tr = round(n_tr * n)
        cut_va = cut_tr + round(n_va * n)
        for i, design_id in enumerate(ids):
            mapping[design_id] = ("train" if i < cut_tr
                                  else "val" if i < cut_va else "test")
    for r in request_rows:
        r["split"] = mapping[r["design_row_id"]]
    return mapping


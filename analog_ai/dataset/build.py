"""Row construction for the feasibility-labeled dataset (Phase 3).

Two tables of flat scalar dicts (Parquet schema in `io.py`):

- **designs** — one row per (design vector, CL) evaluation: the 5 parameters,
  achieved metrics, structural residuals (PM / saturation / widths / L
  domain), validity and verdict. Produced by `evaluate_design_row`, which
  wraps the canonical `evaluation.evaluator.evaluate_design` (invalid designs
  become rows, never exceptions).

- **requests** — one row per (request vector, design) pair: the request, all
  residuals under the full spec via the canonical hard verifier, the label
  (`feasible` | `near_boundary` | `infeasible_derived` |
  `infeasible_optimizer`), the split, and DE provenance where applicable.

The verifier is never re-implemented here: request residuals come from
`evaluation.constraints.evaluate_constraints` applied to a perf view
reconstructed from the stored design row, which matches a fresh evaluation
because the proxy is deterministic.
"""

from __future__ import annotations

import numpy as np

from ..evaluation.constraints import evaluate_constraints
from ..evaluation.evaluator import evaluate_design
from ..optimization import optimize_specs

METRIC_COLS = ("DC_Gain_dB", "GBW", "PM", "Power", "SR", "Swing",
               "ICMR_min", "min_sat_margin", "Area")
SPEC_RESIDUALS = ("r_Gain_min", "r_GBW_min", "r_Power_max")
STRUCTURAL_RESIDUALS = ("r_PM_min", "r_Sat_margin_min", "r_W_nmos_max",
                        "r_W_pmos_max", "r_L_domain")
RESIDUAL_COLS = SPEC_RESIDUALS + STRUCTURAL_RESIDUALS

# Label schema v2: negative labels describe the *evidence*, not a claim of
# true infeasibility (only a simulator or exhaustive proof could).
LABELS = ("feasible", "near_boundary", "beyond_sample_envelope",
          "unresolved_by_optimizer", "polish_failed")


# ------------------------------------------------------------ designs ----
def evaluate_design_row(ota, x, cl_pf: float, source: str, row_id: str,
                        op_point: str, build_id: str) -> dict:
    """Evaluate one (design, CL) pair into a flat design row. Never raises
    for invalid DESIGNS; unsupported MODES raise explicitly (Phase F3
    compatibility): the five-parameter dataset path cannot truncate finite
    designs or route them through the historical ideal record."""
    if len(x) != 5:
        raise ValueError(
            "the ideal-tail dataset path serializes exactly five design "
            f"parameters, got {len(x)}; finite designs belong to the finite "
            "schema (Phase F) and are not dataset-compatible until Phase H")
    if (getattr(ota, "tail_device", "ideal") == "finite"
            and getattr(ota, "op_point", "imposed") == "solved"):
        raise ValueError(
            "the ideal-tail dataset path cannot evaluate finite+solved "
            "objects; use the finite record schema directly (datasets are "
            "regenerated only in Phase H)")
    rec = evaluate_design(ota, x, {"CL_pF": float(cl_pf)})
    row = {
        "row_id": row_id, "source": source, "cl_pf": float(cl_pf),
        **{name: float(v) for name, v in
           zip(("L1", "gmid1", "L3", "gmid3", "Itail"), x)},
        **{k: None for k in METRIC_COLS},
        "W1": None, "W3": None,
        **{k: None for k in RESIDUAL_COLS},
        "verdict": False, "valid": False,
        "invalid_reason": None, "warnings": "",
        "op_point": op_point, "build_id": build_id,
    }
    if rec["metrics"] is None:
        row["invalid_reason"] = str(rec.get("invalid_reason", "unknown"))
        return row
    row.update(valid=True, verdict=bool(rec["verdict"]))
    row.update({k: float(rec["metrics"][k]) for k in METRIC_COLS})
    dev = rec["devices"]
    row["W1"] = float(dev["M1"]["W"])
    row["W3"] = float(dev["M3"]["W"])
    for c in rec["constraints"]:
        row[f"r_{c['name']}"] = float(c["residual"])
    row["warnings"] = "; ".join(rec["warnings"])
    return row


def dataset_stats(design_rows: list[dict]) -> dict:
    """Per-CL observed extremes used by `sampling.derive_requests`."""
    stats: dict[float, dict] = {}
    for r in design_rows:
        if not r["valid"] or r["GBW"] != r["GBW"]:  # invalid or NaN GBW
            continue
        s = stats.setdefault(r["cl_pf"], {"max_gain": -np.inf,
                                          "max_gbw": -np.inf,
                                          "min_power": np.inf})
        s["max_gain"] = max(s["max_gain"], r["DC_Gain_dB"])
        s["max_gbw"] = max(s["max_gbw"], r["GBW"])
        s["min_power"] = min(s["min_power"], r["Power"])
    return stats


# ------------------------------------------------------------ requests ----
def _perf_view(drow: dict) -> dict:
    """Rebuild the perf subset the verifier reads from a stored design row."""
    return {
        "DC_Gain_dB": drow["DC_Gain_dB"], "GBW": drow["GBW"], "PM": drow["PM"],
        "Power": drow["Power"], "SR": drow["SR"], "Swing": drow["Swing"],
        "ICMR_min": drow["ICMR_min"],
        "min_sat_margin": drow["min_sat_margin"],
        "devices": {
            "M1": {"W": drow["W1"], "L": drow["L1"]},
            "M2": {"W": drow["W1"], "L": drow["L1"]},
            "M3": {"W": drow["W3"], "L": drow["L3"]},
            "M4": {"W": drow["W3"], "L": drow["L3"]},
        },
    }


def request_row(drow: dict, specs: dict, label: str, row_id: str,
                source: str, op_point: str, build_id: str,
                de_stats: dict | None = None) -> dict:
    """Attach a request to a design row and verify it with the hard verifier."""
    assert label in LABELS, label
    row = {
        "row_id": row_id, "design_row_id": drow["row_id"],
        "source": source, "label": label,
        "req_Gain_min": float(specs["Gain_min"]),
        "req_GBW_min": float(specs["GBW_min"]),
        "req_CL_pF": float(specs["CL_pF"]),
        "req_Power_max": float(specs["Power_max"]),
        "infeasible_dim": specs.get("infeasible_dim"),
        **{k: None for k in RESIDUAL_COLS},
        "worst_violation": None, "verdict": False,
        "split": None,
        "de_objective": None, "de_n_evals": None, "de_runtime_s": None,
        "cl_pf": float(drow["cl_pf"]),
        "op_point": op_point, "build_id": build_id,
    }
    if de_stats:
        row.update({f"de_{k}": de_stats[k] for k in
                    ("objective", "n_evals", "runtime_s")})
    if not drow["valid"]:
        # Best-effort design of a failed certification: nothing to verify.
        row["worst_violation"] = float("inf")
        return row
    constraints, verdict = evaluate_constraints(_perf_view(drow), specs)
    worst = 0.0
    for c in constraints:
        row[f"r_{c.name}"] = float(c.residual)
        worst = max(worst, max(0.0, float(c.residual)))
    row["worst_violation"] = worst
    row["verdict"] = bool(verdict)
    return row


# ----------------------------------------------- DE polish / certify ------
_DESIGN_NAMES = ("L1", "gmid1", "L3", "gmid3", "Itail")


def _design_vector(record: dict) -> list[float]:
    d = record["design"]
    return [float(d[n]) for n in _DESIGN_NAMES]


def polish_request(ota, specs: dict, seed: int, maxiter: int, popsize: int,
                   design_row_id: str, request_row_id: str,
                   op_point: str, build_id: str):
    """Run DE on a derived-feasible request; return (design_row, request_row).

    Gives the one-to-many mapping a second, optimized design per request.
    """
    rec = optimize_specs(ota, specs, seed=seed, maxiter=maxiter,
                         popsize=popsize, n_starts=1)
    cl_pf = float(specs["CL_pF"])
    drow = evaluate_design_row(ota, _design_vector(rec), cl_pf, "de_polish",
                               design_row_id, op_point, build_id)
    rrow = request_row(drow, specs, "feasible", request_row_id, "de_polish",
                       op_point, build_id, de_stats=rec["baseline"])
    # Label from the REQUEST verdict (was the design's structural verdict:
    # a structurally-valid design can still miss the spec).
    rrow["label"] = "feasible" if rrow["verdict"] else "polish_failed"
    return drow, rrow


def certify_request(ota, specs: dict, seed: int, maxiter: int, popsize: int,
                    design_row_id: str, request_row_id: str,
                    op_point: str, build_id: str):
    """Attempt a TARGET_RANGES-sampled request with DE.

    Pass -> `feasible` (source `de_certify`); failure ->
    `unresolved_by_optimizer` (best-effort design kept, DE stats recorded).
    A failed DE run is evidence of difficulty, not proof of infeasibility.
    """
    rec = optimize_specs(ota, specs, seed=seed, maxiter=maxiter,
                         popsize=popsize, n_starts=1)
    cl_pf = float(specs.get("CL_pF", 1.0))
    drow = evaluate_design_row(ota, _design_vector(rec), cl_pf, "de_certify",
                               design_row_id, op_point, build_id)
    rrow = request_row(drow, specs, "feasible", request_row_id, "de_certify",
                       op_point, build_id, de_stats=rec["baseline"])
    rrow["label"] = "feasible" if rrow["verdict"] else "unresolved_by_optimizer"
    return drow, rrow

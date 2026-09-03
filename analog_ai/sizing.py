"""Deployment-facing, hard-verified sizing for the ideal-tail 5T OTA."""

from __future__ import annotations

from .correlation.calibration import (GBW_GUARD_BAND, guarded_specs,
                                      policy_record)
from .evaluation.constraints import evaluate_constraints
from .surrogate.evaluate import eval_request_staged

SPEC_KEYS = ("Gain_min", "GBW_min", "CL_pF", "Power_max")
DESIGN_NAMES = ("L1", "gmid1", "L3", "gmid3", "Itail")


def _constraints(perf: dict, specs: dict) -> tuple[list[dict], bool]:
    checks, verdict = evaluate_constraints(perf, specs)
    return [c.as_dict() for c in checks], bool(verdict)


def size_ideal_tail_ota(ota, model, user_specs: dict, feat_lo, feat_hi,
                        device: str = "cpu",
                        guard_band: float = GBW_GUARD_BAND,
                        global_fallback: bool = True,
                        global_maxiter: int = 20,
                        seed: int = 0) -> dict:
    """Size one nominal-TT ideal-tail OTA with a protected GBW contract.

    The external request is immutable. Proposal, local refinement, and global
    fallback all optimize the stronger internal request. Both verdicts and
    the calibration provenance are returned explicitly.
    """
    missing = [name for name in SPEC_KEYS if name not in user_specs]
    if missing:
        raise ValueError("user specification is missing: " + ", ".join(missing))
    user = {name: float(user_specs[name]) for name in SPEC_KEYS}
    internal = guarded_specs(user, guard_band)
    pipeline = eval_request_staged(
        ota, model, internal, feat_lo, feat_hi, device=device, local=True,
        global_fallback=global_fallback, global_maxiter=global_maxiter,
        seed=seed)
    record = {
        "topology": "5t_ota_ideal_tail",
        "corner": "tt_lib",
        "user_specs": user,
        "internal_specs": internal,
        "calibration": policy_record(guard_band),
        "status": pipeline["status"],
        "n_oracle_evals": pipeline["n_oracle_evals"],
        "pipeline": pipeline,
        "design_variables": None,
        "physical_design": None,
        "lut_metrics": None,
        "user_constraints": [],
        "internal_constraints": [],
        "user_verdict": False,
        "internal_verdict": False,
    }
    if pipeline["status"] == "unresolved":
        return record

    x = [float(v) for v in pipeline["design"]]
    perf = ota.evaluate(x, CL=user["CL_pF"] * 1e-12)
    user_checks, user_pass = _constraints(perf, user)
    internal_checks, internal_pass = _constraints(perf, internal)
    if not internal_pass:
        raise RuntimeError("staged pipeline returned a design that fails its internal contract")
    dev = perf["devices"]
    record.update({
        "design_variables": dict(zip(DESIGN_NAMES, x)),
        "physical_design": {
            "L1": float(dev["M1"]["L"]), "W1": float(dev["M1"]["W"]),
            "L3": float(dev["M3"]["L"]), "W3": float(dev["M3"]["W"]),
            "Itail": x[4],
        },
        "lut_metrics": {name: float(perf[name]) for name in
                        ("DC_Gain_dB", "GBW", "PM", "Power", "Vout",
                         "Vtail", "Vmirror")},
        "user_constraints": user_checks,
        "internal_constraints": internal_checks,
        "user_verdict": user_pass,
        "internal_verdict": internal_pass,
    })
    return record

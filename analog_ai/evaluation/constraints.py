"""Hard-constraint verifier.

The training cost (V10 smooth relative-squared, in the RL environment) is a
*shaping* signal. This module is different: it is the acceptance contract.
A design passes only if every required residual is <= 0 — a weighted scalar
sum can never authorize a pass.

Residual convention: residual <= 0 means satisfied.
    min-type:  residual = (limit - achieved) / scale   (achieved must be >= limit)
    max-type:  residual = (achieved - limit) / scale   (achieved must be <= limit)
Scales follow docs/DESIGN_CONTRACT.md so residuals are comparable across specs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import config


@dataclass
class ConstraintResult:
    name: str
    kind: str                 # "min" | "max" | "domain"
    limit: float
    achieved: float
    residual: float
    scale: float
    passed: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind, "limit": self.limit,
            "achieved": self.achieved, "residual": self.residual,
            "scale": self.scale, "passed": self.passed, "detail": self.detail,
        }


def _min_constraint(name, achieved, limit, scale) -> ConstraintResult:
    if achieved != achieved:  # NaN (e.g. GBW when no crossing was found)
        return ConstraintResult(name, "min", limit, achieved, float("inf"), scale,
                                False, "metric not available")
    residual = (limit - achieved) / scale
    return ConstraintResult(name, "min", limit, achieved, residual, scale,
                            residual <= 0.0)


def _max_constraint(name, achieved, limit, scale) -> ConstraintResult:
    if achieved != achieved:
        return ConstraintResult(name, "max", limit, achieved, float("inf"), scale,
                                False, "metric not available")
    residual = (achieved - limit) / scale
    return ConstraintResult(name, "max", limit, achieved, residual, scale,
                            residual <= 0.0)


def evaluate_constraints(perf: dict, specs: dict,
                         limits: dict | None = None) -> tuple[list[ConstraintResult], bool]:
    """Return (per-constraint results, overall verdict).

    specs keys (all optional, only those present are enforced):
        Gain_min [dB], GBW_min [Hz], Power_max [W], CL_pF [pF],
        PM_min [deg] (default config.PM_MIN_DEFAULT),
        Sat_margin_min [V] (default config.SAT_MARGIN_MIN_DEFAULT),
        SR_min [V/s], Swing_min [V], ICMR_max [V]

    `limits` may override config defaults (W_NMOS_MAX, ...) for experiments;
    production use should keep the defaults.
    """
    limits = {**{
        "PM_min": config.PM_MIN_DEFAULT,
        "Sat_margin_min": config.SAT_MARGIN_MIN_DEFAULT,
        "W_nmos_max": config.W_NMOS_MAX,
        "W_pmos_max": config.W_PMOS_MAX,
    }, **(limits or {})}

    results: list[ConstraintResult] = []

    if perf is None:
        return results, False

    if "Gain_min" in specs:
        results.append(_min_constraint("Gain_min", perf["DC_Gain_dB"],
                                       specs["Gain_min"], scale=10.0))  # dB
    if "GBW_min" in specs:
        results.append(_min_constraint("GBW_min", perf["GBW"],
                                       specs["GBW_min"], scale=specs["GBW_min"]))
    if "Power_max" in specs:
        results.append(_max_constraint("Power_max", perf["Power"],
                                       specs["Power_max"], scale=specs["Power_max"]))
    if "PM_min" in limits:
        results.append(_min_constraint("PM_min", perf["PM"],
                                       limits["PM_min"], scale=45.0))
    if "Sat_margin_min" in limits:
        results.append(_min_constraint("Sat_margin_min", perf["min_sat_margin"],
                                       limits["Sat_margin_min"],
                                       scale=limits["Sat_margin_min"]))
    if "SR_min" in specs:
        results.append(_min_constraint("SR_min", perf["SR"],
                                       specs["SR_min"], scale=specs["SR_min"]))
    if "Swing_min" in specs:
        results.append(_min_constraint("Swing_min", perf["Swing"],
                                       specs["Swing_min"], scale=0.3))
    if "ICMR_max" in specs:
        results.append(_max_constraint("ICMR_max", perf["ICMR_min"],
                                       specs["ICMR_max"], scale=0.3))

    # Geometry / domain limits (always enforced).
    devices = perf.get("devices", {})
    w_nmos = max((devices[d]["W"] for d in ("M1", "M2", "M5") if d in devices),
                 default=0.0)
    w_pmos = max((devices[d]["W"] for d in ("M3", "M4") if d in devices),
                 default=0.0)
    results.append(_max_constraint("W_nmos_max", w_nmos, limits["W_nmos_max"],
                                   scale=limits["W_nmos_max"]))
    results.append(_max_constraint("W_pmos_max", w_pmos, limits["W_pmos_max"],
                                   scale=limits["W_pmos_max"]))
    lengths = [devices[d]["L"] for d in devices if devices[d].get("L")]
    if lengths:
        l_ok = all(60e-9 <= l <= 1.5e-6 for l in lengths)
        results.append(ConstraintResult(
            "L_domain", "domain", (60e-9, 1.5e-6), tuple(lengths),
            0.0 if l_ok else 1.0, 1.0, l_ok))

    verdict = all(r.passed for r in results)
    return results, verdict

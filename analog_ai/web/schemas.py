"""Web/API contract for the ideal-tail sizing service (Phase W0, frozen).

The browser can only talk to the guarded deployment API through the models
here.  Frozen rules enforced by this module:

- UI units: GBW in MHz, power in uW; canonical SI units: GBW in Hz, power
  in W (gain in dB and CL in pF pass through unchanged);
- values outside TARGET_RANGES are rejected, never silently clipped;
- non-finite numbers are rejected;
- only ``user_verdict == True`` plus a non-null physical design may be
  reported as ``status == "success"`` - an unresolved request carries no
  geometry of any kind;
- every response carries the scope warning.
"""

from __future__ import annotations

import math
from typing import Literal, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, \
    field_validator

from .. import config

# ---- UI-unit bounds, derived from the canonical training-domain ranges ----
_GAIN_LO, _GAIN_HI = config.TARGET_RANGES["Gain_min"]            # dB
_CL_LO, _CL_HI = config.TARGET_RANGES["CL_pF"]                   # pF
_GBW_MHZ_LO = config.TARGET_RANGES["GBW_min"][0] / 1e6           # MHz
_GBW_MHZ_HI = config.TARGET_RANGES["GBW_min"][1] / 1e6
_POWER_UW_LO = config.TARGET_RANGES["Power_max"][0] * 1e6        # uW
_POWER_UW_HI = config.TARGET_RANGES["Power_max"][1] * 1e6

STATUS_SUCCESS = "success"
STATUS_UNRESOLVED = "unresolved"
STATUS_ERROR = "error"

SCOPE_WARNING = (
    "Nominal LUT-based sizing candidate only (ideal tail current source, "
    "TSMC 65 nm tt_lib corner, VDD = 1.2 V, Vincm = 0.6 V). Not post-layout "
    "or PVT signoff. Cadence remains the final authority."
)
EXPLANATION_UNRESOLVED = (
    "The guarded pipeline found no design that passes its hard-constraint "
    "verification within the declared search budget. This is evidence of "
    "optimizer difficulty, NOT proof that a physical design does not exist."
)
GUIDANCE_UNRESOLVED = (
    "Relax one or more specifications (lower GBW/gain, allow more power, or "
    "reduce the load), or run a larger offline search budget."
)


# ---------------------------------------------------------------- request --
class SizeRequest(BaseModel):
    """The four supported user inputs, in UI units.

    Unknown or misspelled fields are rejected (the black-box contract is
    exactly these four inputs).
    """

    model_config = ConfigDict(extra="forbid")

    Gain_min_dB: float = Field(
        ..., ge=_GAIN_LO, le=_GAIN_HI, allow_inf_nan=False,
        description="Minimum DC gain [dB]")
    GBW_min_MHz: float = Field(
        ..., ge=_GBW_MHZ_LO, le=_GBW_MHZ_HI, allow_inf_nan=False,
        description="Minimum unity-gain bandwidth [MHz]")
    CL_pF: float = Field(
        ..., ge=_CL_LO, le=_CL_HI, allow_inf_nan=False,
        description="Load capacitance [pF]")
    Power_max_uW: float = Field(
        ..., ge=_POWER_UW_LO, le=_POWER_UW_HI, allow_inf_nan=False,
        description="Maximum power [uW]")

    @field_validator("*", mode="before")
    @classmethod
    def _reject_bools(cls, v):
        # bool is an int subclass; accept() would smuggle True in as 1.0
        if isinstance(v, bool):
            raise ValueError("boolean is not a valid numeric specification")
        return v

    def to_canonical(self) -> dict:
        """UI units -> canonical black-box request (SI, per DESIGN_CONTRACT)."""
        return {
            "Gain_min": float(self.Gain_min_dB),
            "GBW_min": float(self.GBW_min_MHz) * 1e6,
            "CL_pF": float(self.CL_pF),
            "Power_max": float(self.Power_max_uW) * 1e-6,
        }


# --------------------------------------------------------------- response --
class ConstraintOut(BaseModel):
    name: str
    kind: str
    limit: float
    achieved: Optional[float]
    residual: Optional[float]
    scale: float
    passed: bool
    detail: str = ""
    margin: Optional[float] = None   # signed headroom, natural units


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    state: Literal["loading", "ready", "failed"]
    detail: Optional[str] = None
    policy_version: Optional[str] = None
    scope: Optional[str] = None


def json_safe(obj):
    """Recursively convert to JSON-safe primitives (NaN/inf -> null)."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, (int,)) or isinstance(obj, (float, np.integer,
                                                   np.floating)):
        try:
            f = float(obj)
        except (TypeError, ValueError):
            return str(obj)
        return obj if math.isfinite(f) else None
    if hasattr(obj, "item"):          # numpy scalars
        return json_safe(obj.item())
    return str(obj)


def _constraint_out(c: dict) -> dict:
    # scalar min/max constraints get a signed headroom margin; domain
    # constraints (tuple limit/achieved, e.g. L_domain) carry margin=None
    lim, ach = c.get("limit"), c.get("achieved")
    margin = None
    if (isinstance(lim, (int, float)) and isinstance(ach, (int, float))
            and not isinstance(lim, bool) and not isinstance(ach, bool)):
        raw = (ach - lim) if c.get("kind") == "min" else (lim - ach)
        margin = float(raw) if math.isfinite(raw) else None
    out = json_safe(c)
    out["margin"] = margin
    return out


def _presentation(record: dict) -> dict:
    pd = record.get("physical_design") or {}
    lm = record.get("lut_metrics") or {}

    def r(v, nd):
        return None if v is None else round(float(v), nd)

    return {
        "m1_m2": {"w_um": r(pd.get("W1") * 1e6, 3) if pd.get("W1") else None,
                  "l_um": r(pd.get("L1") * 1e6, 3) if pd.get("L1") else None},
        "m3_m4": {"w_um": r(pd.get("W3") * 1e6, 3) if pd.get("W3") else None,
                  "l_um": r(pd.get("L3") * 1e6, 3) if pd.get("L3") else None},
        "itail_uA": r(pd.get("Itail") * 1e6, 3) if pd.get("Itail") else None,
        "metrics": {
            "gain_dB": r(lm.get("DC_Gain_dB"), 2),
            "gbw_MHz": r(lm.get("GBW") / 1e6, 3) if lm.get("GBW") else None,
            "pm_deg": r(lm.get("PM"), 2),
            "power_uW": r(lm.get("Power") * 1e6, 3) if lm.get("Power")
            else None,
            "vout_V": r(lm.get("Vout"), 4),
            "vtail_V": r(lm.get("Vtail"), 4),
            "vmirror_V": r(lm.get("Vmirror"), 4),
        },
    }


def derive_status(record: dict) -> str:
    """Frozen display rule: geometry is only ever shown after BOTH the
    pipeline produced a design AND the user contract verdict is True."""
    has_design = record.get("design_variables") is not None \
        and record.get("physical_design") is not None
    if record.get("status") == "unresolved" or not has_design:
        return STATUS_UNRESOLVED
    if not record.get("user_verdict"):
        return STATUS_UNRESOLVED
    return STATUS_SUCCESS


def build_success_response(record: dict, request_id: str) -> dict:
    """JSON response for a hard-verified sizing (full-precision SI plus a
    presentation layer). Refuses to fabricate a success."""
    if derive_status(record) != STATUS_SUCCESS:
        raise ValueError(
            "refusing to build a success response from a non-verified record")
    return {
        "request_id": request_id,
        "status": STATUS_SUCCESS,
        "scope_warning": SCOPE_WARNING,
        "topology": record.get("topology"),
        "corner": record.get("corner"),
        "user_specs": json_safe(record["user_specs"]),
        "internal_specs": json_safe(record["internal_specs"]),
        "calibration": json_safe(record.get("calibration")),
        "verdict": {
            "user_verdict": bool(record["user_verdict"]),
            "internal_verdict": bool(record["internal_verdict"]),
        },
        "design": {
            "m1_m2": {"w_m": float(record["physical_design"]["W1"]),
                      "l_m": float(record["physical_design"]["L1"])},
            "m3_m4": {"w_m": float(record["physical_design"]["W3"]),
                      "l_m": float(record["physical_design"]["L3"])},
            "itail_a": float(record["physical_design"]["Itail"]),
        },
        "design_variables": json_safe(record["design_variables"]),
        "lut_metrics": json_safe(record.get("lut_metrics")),
        "constraints": [_constraint_out(c)
                        for c in record.get("user_constraints", [])],
        "sizing_path": {
            "pipeline_status": record.get("status"),
            "n_oracle_evals": int(record.get("n_oracle_evals", 0)),
            "stages": json_safe(record.get("pipeline", {}).get("stages", [])),
        },
        "presentation": _presentation(record),
    }


def build_unresolved_response(record: dict, request_id: str) -> dict:
    """JSON response with no geometry of any kind."""
    return {
        "request_id": request_id,
        "status": STATUS_UNRESOLVED,
        "scope_warning": SCOPE_WARNING,
        "user_specs": json_safe(record.get("user_specs")),
        "internal_specs": json_safe(record.get("internal_specs")),
        "calibration": json_safe(record.get("calibration")),
        "pipeline_status": record.get("status"),
        "n_oracle_evals": int(record.get("n_oracle_evals", 0)),
        "explanation": EXPLANATION_UNRESOLVED,
        "guidance": GUIDANCE_UNRESOLVED,
        "design": None,
        "design_variables": None,
        "lut_metrics": None,
        "constraints": None,
    }


def build_error_response(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def validation_error_response(exc: ValidationError) -> dict:
    """One compact line per rejected field; never echoes server internals."""
    parts = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e.get("loc", []))
        parts.append(f"{loc}: {e.get('msg')}")
    return build_error_response("validation_error", "; ".join(parts))

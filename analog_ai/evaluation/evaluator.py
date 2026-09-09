"""Complete, machine-readable evaluation records.

Replaces the Markdown-only partial tables: every evaluation records the
request, the full design, every metric, every constraint residual, the
verdict, and provenance (oracle version + timestamp).
"""

from __future__ import annotations

import datetime
import json
import math

from .. import ORACLE_VERSION, config
from ..circuit.dc_solver import validate_finite_design
from ..circuit.ota5t import InvalidDesignError, OTA5T
from ..devices.device_model import DeviceModel
from ..devices.lut import DomainError
from .constraints import evaluate_constraints


def evaluate_design(ota: OTA5T, design, specs: dict) -> dict:
    """Evaluate one design against one request and return a full record.

    Mode-aware routing (Phase F3): finite+solved objects route to the
    finite schema (:func:`evaluate_design_finite` - seven mode-aware
    parameter names, distinct development oracle identity); every other
    combination keeps the historical five-parameter record under the
    frozen ideal oracle identity. Design vectors whose length does not
    match the routed mode raise explicitly - never truncate or pad.

    Invalid DESIGNS never raise: they produce `verdict=False` with an
    `invalid_reason`, so batch evaluation cannot crash on a single bad
    design.
    """
    tail = getattr(ota, "tail_device", "ideal")
    op = getattr(ota, "op_point", "imposed")
    if tail == "finite" and op == "solved":
        return evaluate_design_finite(ota, design, specs)
    if len(design) != 5:
        raise ValueError(
            "the historical record path serializes exactly five ideal-tail "
            f"parameters, got {len(design)}; finite designs require "
            "tail_device='finite' with op_point='solved' (finite schema)")
    record = {
        "request": dict(specs),
        "design": {name: float(v) for name, v in zip(
            ("L1", "gmid1", "L3", "gmid3", "Itail"), design)},
        "provenance": {
            "oracle_version": ORACLE_VERSION,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        },
    }
    try:
        cl = float(specs.get("CL_pF", 1.0)) * 1e-12
        perf = ota.evaluate(design, CL=cl)
        constraints, verdict = evaluate_constraints(perf, specs)
        record.update(
            metrics={k: _num(perf[k]) for k in (
                "DC_Gain_dB", "GBW", "PM", "Power", "SR", "Swing",
                "ICMR_min", "min_sat_margin", "Area")},
            devices={n: _device_summary(d) for n, d in perf["devices"].items()},
            constraints=[c.as_dict() for c in constraints],
            verdict=bool(verdict),
            warnings=list(perf.get("warnings", [])),
            dc_diagnostics={
                "Vtail": _num(perf["Vtail"]),
                "Vmirror": _num(perf["Vmirror"]),
                "pair_current_mismatch": _num(perf["pair_current_mismatch"]),
                "mirror_current_mismatch": _num(perf["mirror_current_mismatch"]),
            },
        )
    except (InvalidDesignError, DomainError, ValueError, FloatingPointError) as exc:
        record.update(
            metrics=None, devices=None, constraints=[], verdict=False,
            warnings=[], invalid_reason=str(exc),
        )
    return record


def evaluate_invalid(specs: dict, reason: str) -> dict:
    return {
        "request": dict(specs), "design": None, "metrics": None,
        "devices": None, "constraints": [], "verdict": False,
        "warnings": [], "invalid_reason": reason, "provenance": {},
    }


def record_to_markdown_row(name: str, r: dict) -> str:
    """One table row with explicit verdicts for every enforced constraint."""
    req = r["request"]
    if r["metrics"] is None:
        return (f"| {name} | {req.get('Gain_min', '')} | {req.get('GBW_min', '')} | "
                f"{req.get('CL_pF', '')} | {req.get('Power_max', '')} | - | - | - | - | "
                f"FAIL | invalid: {r.get('invalid_reason', '?')[:40]} |")

    m = r["metrics"]
    cons = {c["name"]: c for c in r["constraints"]}

    def mark(cname):
        c = cons.get(cname)
        if c is None:
            return "n/a"
        return "PASS" if c["passed"] else f"FAIL ({c['residual']:+.2f})"

    d = r["devices"]
    m1, m3 = d.get("M1", {}), d.get("M3", {})
    row = (
        f"| {name} "
        f"| {req.get('Gain_min', ''):g}/{m['DC_Gain_dB']:.1f} {mark('Gain_min')} "
        f"| {req.get('GBW_min', 0)/1e6:g}M/{_fmt_gbw(m['GBW'])} {mark('GBW_min')} "
        f"| {req.get('CL_pF', ''):g}p "
        f"| {req.get('Power_max', 0)*1e6:g}/{m['Power']*1e6:.0f} {mark('Power_max')} "
        f"| {m['PM']:.1f} {mark('PM_min')} "
        f"| {m['min_sat_margin']*1e3:.0f}mV {mark('Sat_margin_min')} "
        f"| {_fmt_w(m1.get('W'))}/{m1.get('L', 0)*1e9:.0f}n "
        f"| {_fmt_w(m3.get('W'))}/{m3.get('L', 0)*1e9:.0f}n "
        f"| {'PASS' if r['verdict'] else 'FAIL'} |"
    )
    if r["warnings"]:
        row += " " + "; ".join(r["warnings"][:2])
    return row


RESULTS_TABLE_HEADER = (
    "| Test | Gain tgt/ach (dB) | GBW tgt/ach (MHz) | CL (pF) | Power tgt/max (uW) "
    "| PM (deg) | Sat margin | M1 W/L | M3 W/L | Verdict |\n"
    "|---|---|---|---|---|---|---|---|---|---|"
)


def record_to_json(r: dict) -> str:
    return json.dumps(r, indent=2, default=str)


# -------------------------------------------------------------- helpers ---
def _num(v):
    return float(v) if v is not None else None


def _device_summary(d: dict) -> dict:
    return {
        "W": _num(d.get("W")), "L": _num(d.get("L")),
        "VGS": _num(d.get("VGS")), "VDS": _num(d.get("VDS")),
        "VDSAT": _num(d.get("VDSAT")), "ID": _num(d.get("ID")),
        "gm": _num(d.get("gm")), "gds": _num(d.get("gds")),
    }


def _fmt_gbw(g):
    return "n/a" if g != g else f"{g/1e6:.0f}M"


def _fmt_w(w):
    return "-" if w is None else f"{w*1e6:.1f}u"


# ------------------------------------------------------------ finite (F2) ---
# Distinct development schema/oracle identity for finite-M5 records. This is
# NOT the canonical ideal oracle identity and carries no canonical weight
# until the F2 integration gate (and later F3 versioning) is accepted.
FINITE_SCHEMA_VERSION = "analog_ai-0.2.0-finite-solved-dev"


def _finite_num(v):
    """Strict-JSON-safe metric: nonfinite or unconvertible -> explicit
    null (the unavailability is carried by constraint rows and warnings).
    The conversion guard keeps failure serialization from re-raising on
    oversized integers (Astra F2-R2 boundary)."""
    try:
        v = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def effective_constraint_limits(specs: dict) -> tuple[dict, list[str]]:
    """Effective hard floors for a finite evaluation (Astra R1/A3): a
    request may TIGHTEN the frozen defaults, never relax them; attempted
    relaxations are clamped up to the frozen default and recorded. Raises
    ValueError for nonfinite/negative requested minima. Every residual
    scale stays positive: thresholds that may legitimately be zero
    (Sat_margin_min) are clamped to at least the frozen default, which the
    constraint module uses as its normalization scale."""
    notes: list[str] = []
    limits = {
        "PM_min": config.PM_MIN_DEFAULT,
        "Sat_margin_min": config.SAT_MARGIN_MIN_DEFAULT,
        "W_nmos_max": config.W_NMOS_MAX,
        "W_pmos_max": config.W_PMOS_MAX,
    }
    for key, default in (("PM_min", config.PM_MIN_DEFAULT),
                         ("Sat_margin_min", config.SAT_MARGIN_MIN_DEFAULT)):
        if key in specs:
            req = float(specs[key])
            if not math.isfinite(req):
                raise ValueError(
                    f"requested {key} must be finite, got {specs[key]!r}")
            if req > default:
                limits[key] = req
            elif req < default:
                notes.append(
                    f"requested {key}={req:.4g} below the frozen default "
                    f"{default:.4g}; frozen default enforced (no relaxation)")
    return limits, notes


# Supported finite request fields: True = strictly positive (zero would
# make the constraint's normalization scale zero); False = zero allowed
# (the constraint module applies fixed positive scales for those).
_FINITE_SPEC_RULES = {
    "Gain_min": False,        # dB, >= 0
    "GBW_min": True,          # Hz, > 0
    "CL_pF": True,            # pF, > 0
    "Power_max": True,        # W, > 0 (a nonpositive power limit is
                              # nonphysical and would invert its residual)
    "PM_min": False,          # deg, (0, 180]
    "Sat_margin_min": False,  # V, >= 0
    "SR_min": True,           # V/s, > 0
    "Swing_min": False,       # V, >= 0
    "ICMR_max": False,        # V, >= 0
}


def validate_finite_specs(specs: dict) -> dict:
    """Validate/normalize every supported finite request field BEFORE any
    device work (Astra F2-R2). Returns a float-normalized copy; raises
    ValueError for booleans, non-numeric values, non-finite values,
    out-of-range values, and unsupported fields - deterministic messages,
    fail-closed, finite-scoped (the ideal path is untouched)."""
    out: dict = {}
    for key, value in dict(specs).items():
        if key not in _FINITE_SPEC_RULES:
            raise ValueError(
                f"unsupported request field {key!r} for finite evaluation")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f"request field {key} must be a real number, got {value!r}")
        try:
            v = float(value)
        except OverflowError:
            raise ValueError(
                f"request field {key}={value!r} is out of representable "
                "numeric range") from None
        if not math.isfinite(v):
            raise ValueError(
                f"request field {key} must be finite, got {value!r}")
        if _FINITE_SPEC_RULES[key] and not v > 0.0:
            raise ValueError(
                f"request field {key} must be positive, got {value!r}")
        if key == "Gain_min" and v < 0.0:
            raise ValueError("request field Gain_min must be >= 0 dB")
        if key == "PM_min" and not 0.0 < v <= 180.0:
            raise ValueError("request field PM_min must lie in (0, 180] deg")
        if key in ("Sat_margin_min", "Swing_min", "ICMR_max") and v < 0.0:
            raise ValueError(f"request field {key} must be >= 0")
        out[key] = v
    return out


def _json_safe_scalar(v):
    """JSON-safe request echo: nonfinite floats become null; arbitrary-
    precision integers pass through (valid JSON); strings and booleans are
    preserved (they are valid JSON and carry the reason)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, str):
        return v
    return None


def _finite_num_or_list(v):
    """Numeric scalar or tuple of numerics -> JSON-safe (nulls for
    nonfinite values, list for tuples)."""
    if isinstance(v, (list, tuple)):
        return [_finite_num(x) for x in v]
    return _finite_num(v)


def _finite_constraint_row(c) -> dict:
    """JSON-safe constraint row: nonfinite achieved/residual serialize as
    explicit nulls (L_domain's tuple limit/achieved become lists); the
    pass/fail verdict, name, and reason text are preserved verbatim
    (failures are never turned into passes)."""
    row = c.as_dict()
    row["limit"] = _finite_num_or_list(row["limit"])
    row["achieved"] = _finite_num_or_list(row["achieved"])
    row["residual"] = _finite_num(row["residual"])
    row["scale"] = _finite_num(row["scale"])
    return row


def _finite_device_summary(d: dict) -> dict:
    summary = _device_summary(d)
    summary["VSB"] = _num(d.get("VSB"))
    summary["type"] = d.get("type")
    if d.get("gmid_forward") is not None:
        summary["gmid_forward"] = _num(d.get("gmid_forward"))
        summary["gmid_table"] = _num(d.get("gmid_table"))
        summary["gmid_target"] = _num(d.get("gmid_target"))
    return summary


def _effective_supply(ota) -> tuple:
    """Effective supply/common mode, validated at the finite record
    boundary BEFORE device work (Astra F2-R3 boundary). Returns
    (vdd, vicm, reason): reason is None for a usable context, otherwise a
    deterministic message naming the offending setting. Conversion
    failures occur inside this protected helper, never in the caller."""
    try:
        vdd = float(ota.VDD)
    except (TypeError, ValueError, OverflowError):
        return float("nan"), float("nan"), (
            f"supply VDD={ota.VDD!r} is not a real number")
    try:
        vicm = float(ota.Vicm)
    except (TypeError, ValueError, OverflowError):
        return vdd, float("nan"), (
            f"common mode VICM={ota.Vicm!r} is not a real number")
    if not math.isfinite(vdd) or vdd <= 0.0:
        return vdd, vicm, f"supply VDD={vdd!r} must be finite and positive"
    if not math.isfinite(vicm) or not 0.0 < vicm < vdd:
        return vdd, vicm, (
            f"common mode VICM={vicm!r} must be finite and lie in (0, VDD)")
    return vdd, vicm, None


def evaluate_design_finite(ota: OTA5T, design, specs: dict) -> dict:
    """Complete finite-M5 evaluation record (Phase F2 - development,
    non-canonical).

    Distinct schema/oracle identity from the ideal oracle; serializes all
    SEVEN design parameters under mode-aware names, the solved tail bias,
    full M1-M5 operating-point and saturation evidence, KCL/current/ratio
    errors, convergence and clipping diagnostics, effective constraint
    limits, and the external-bias-generator exclusion. Public finite
    evaluation is still closed (OTA5T.evaluate rejects finite+solved); this
    record path is exercised by the focused suite and later packages.

    Invalid designs or specs produce fail-closed records: null metrics and
    devices, an explicit invalid_reason, and no five-parameter truncation.
    Unavailable optional metrics serialize as strict-JSON nulls.
    """
    record = {
        "schema_version": FINITE_SCHEMA_VERSION,
        "oracle_identity": {
            "schema": FINITE_SCHEMA_VERSION,
            "distinct_from_ideal_oracle": ORACLE_VERSION,
        },
        "topology": "5t_ota",
        "tail_device": "finite",
        "op_point_mode": "solved",
        # Effective supply/common mode of the evaluated object (F2-R4),
        # validated and JSON-safe at the record boundary (F2-R3 boundary):
        # nonfinite or malformed settings serialize as null with the
        # offending value named in invalid_reason.
        "vdd": None,
        "vicm": None,
        "supply_context_canonical": None,
        "request": None,
        "external_bias_generator": (
            "gate-bias generator excluded from power/area/noise/mismatch"),
        "capacitance_assumption": (
            "cdd treated as the complete drain self-capacitance for "
            "grounded gate/source/body; real-pickle convention unverified "
            "(F5 device-level experiment pending)"),
    }
    try:
        vdd_e, vicm_e, supply_reason = _effective_supply(ota)
        record["vdd"] = _finite_num(vdd_e)
        record["vicm"] = _finite_num(vicm_e)
        record["supply_context_canonical"] = (
            supply_reason is None and vdd_e == config.VDD
            and vicm_e == config.VICM)
        if supply_reason is not None:
            raise ValueError(supply_reason)   # fail-closed, before device work
        specs_n = validate_finite_specs(specs)
        record["request"] = specs_n
        values = validate_finite_design(design)
        record["design"] = {name: float(v)
                            for name, v in zip(config.DESIGN_PARAM_NAMES_7,
                                               values)}
        cl = specs_n.get("CL_pF", 1.0) * 1e-12
        limits, notes = effective_constraint_limits(specs_n)
        record["effective_constraints"] = {"limits": limits, "notes": notes}

        perf = ota._evaluate_solved_finite(list(values), cl, None)
        constraints, verdict = evaluate_constraints(perf, specs_n,
                                                    limits=limits)
        record.update(
            metrics={
                "DC_Gain_dB": _finite_num(perf["DC_Gain_dB"]),
                "GBW": _finite_num(perf["GBW"]),
                "gbw_valid": bool(perf["gbw_valid"]),
                "PM": _finite_num(perf["PM"]),
                "Power_core": _finite_num(perf["Power"]),
                "power_requested_vdd_times_itail": _finite_num(
                    perf["power_requested_vdd_times_itail"]),
                "power_kcl_error": _finite_num(perf["power_kcl_error"]),
                "SR_proxy": _finite_num(perf["SR"]),
                "min_sat_margin": _finite_num(perf["min_sat_margin"]),
                "Area": _finite_num(perf["Area"]),
                # Acceptance keys for optional range requests: null (fail
                # closed); only labeled nominal estimates are reported.
                "Swing": None,
                "Swing_est": _finite_num(perf["Swing_est"]),
                "Vout_low_est": _finite_num(perf["Vout_low_est"]),
                "Vout_high_est": _finite_num(perf["Vout_high_est"]),
                "Vout_in_estimated_range": bool(
                    perf["Vout_in_estimated_range"]),
                "ICMR_min": None,
                "ICMR_low_est": _finite_num(perf["ICMR_low_est"]),
                "ICMR_upper": None,
                "sat_m1": _finite_num(perf["sat_m1"]),
                "sat_m2": _finite_num(perf["sat_m2"]),
                "sat_m3": _finite_num(perf["sat_m3"]),
                "sat_m4": _finite_num(perf["sat_m4"]),
                "sat_m5": _finite_num(perf["sat_m5"]),
            },
            devices={name: _finite_device_summary(d)
                     for name, d in perf["devices"].items()},
            dc_diagnostics={
                "Vtail": _finite_num(perf["Vtail"]),
                "Vmirror": _finite_num(perf["Vmirror"]),
                "Vout": _finite_num(perf["Vout"]),
                "Vbias_tail": _finite_num(perf["Vbias_tail"]),
                "ID5": _finite_num(perf["ID5"]),
                "kcl_residuals": {k: _finite_num(v) for k, v
                                  in perf["kcl_residuals"].items()},
                "m5_current_error_rel": _finite_num(
                    perf["m5_current_error_rel"]),
                "m5_gmid_forward_error": _finite_num(
                    perf["m5_gmid_forward_error"]),
                "m5_gmid_forward": _finite_num(perf["m5_gmid_forward"]),
                "m5_gmid_table": _finite_num(perf["m5_gmid_table"]),
                "pair_current_mismatch": _finite_num(
                    perf["pair_current_mismatch"]),
                "mirror_current_mismatch": _finite_num(
                    perf["mirror_current_mismatch"]),
                "convergence": perf["convergence"],
                "clip_diagnostics": perf["clip_diagnostics"],
            },
            constraints=[_finite_constraint_row(c) for c in constraints],
            verdict=bool(verdict),
            warnings=list(perf.get("warnings", [])) + notes,
            ac_model=perf["ac_model"],
        )
    except (InvalidDesignError, DomainError, ValueError,
            FloatingPointError) as exc:
        raw_design = None
        try:
            raw = [_finite_num(v) for v in design]
            if len(raw) == 7:
                raw_design = raw
        except (TypeError, ValueError):
            raw_design = None
        if record["request"] is None:
            record["request"] = {k: _json_safe_scalar(v)
                                 for k, v in dict(specs).items()}
        record.update(
            design=raw_design, metrics=None, devices=None, constraints=[],
            dc_diagnostics=None, effective_constraints=None,
            verdict=False, warnings=[], invalid_reason=str(exc))
    return record

"""Complete, machine-readable evaluation records.

Replaces the Markdown-only partial tables: every evaluation records the
request, the full design, every metric, every constraint residual, the
verdict, and provenance (oracle version + timestamp).
"""

from __future__ import annotations

import datetime
import json

from .. import ORACLE_VERSION
from ..circuit.ota5t import InvalidDesignError, OTA5T
from ..devices.device_model import DeviceModel
from ..devices.lut import DomainError
from .constraints import evaluate_constraints


def evaluate_design(ota: OTA5T, design, specs: dict) -> dict:
    """Evaluate one design against one request and return a full record.

    Never raises for invalid designs: they produce `verdict=False` with an
    `invalid_reason`, so batch evaluation cannot crash on a single bad design.
    """
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

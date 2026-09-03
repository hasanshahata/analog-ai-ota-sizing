"""Stratified campaign selection and Spectre/LUT result comparison."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .. import config

CATEGORIES = ("low_power", "high_gain", "high_gbw", "heavy_load",
              "boundary")
METRIC_RULES = {
    "dc_gain_dB": ("absolute", 1.0, "dB"),
    "gbw_Hz": ("relative", 0.10, "%"),
    "phase_margin_deg": ("absolute", 5.0, "deg"),
    "power_W": ("relative", 0.05, "%"),
    "vout_dc_V": ("absolute", 0.030, "V"),
    "vtail_dc_V": ("absolute", 0.030, "V"),
    "vmirror_dc_V": ("absolute", 0.030, "V"),
}


def _spread_pick(rows: list[dict], score, n: int,
                 used: set[str]) -> list[dict]:
    available = [r for r in rows if r["row_id"] not in used]
    available.sort(key=lambda r: (score(r), r["row_id"]))
    if len(available) < n:
        raise ValueError(f"need {n} unused rows, found {len(available)}")
    # Select across the category tail instead of taking adjacent near-duplicates.
    pool = available[-max(n * 20, n):]
    indices = np.linspace(0, len(pool) - 1, n, dtype=int)
    picked = [pool[int(i)] for i in indices]
    used.update(r["row_id"] for r in picked)
    return picked


def select_campaign_requests(requests: list[dict], n_each: int = 5,
                             excluded_ids: set[str] | None = None) -> list[dict]:
    """Deterministically select disjoint held-out requests in five regimes."""
    excluded_ids = set(excluded_ids or ())
    positives = [r for r in requests if r.get("split") == "test"
                 and r.get("label") in ("feasible", "near_boundary")
                 and bool(r.get("verdict"))
                 and r["row_id"] not in excluded_ids]
    boundary = [r for r in positives if r["label"] == "near_boundary"]
    used: set[str] = set(excluded_ids)
    specs = (
        ("low_power", positives, lambda r: -float(r["req_Power_max"])),
        ("high_gain", positives, lambda r: float(r["req_Gain_min"])),
        ("high_gbw", positives, lambda r: float(r["req_GBW_min"])),
        ("heavy_load", positives,
         lambda r: (float(r["req_CL_pF"]), float(r["req_GBW_min"]))),
        ("boundary", boundary,
         lambda r: max(float(r.get(k) if r.get(k) is not None else -math.inf)
                       for k in ("r_Gain_min", "r_GBW_min", "r_Power_max"))),
    )
    selected = []
    for category, rows, score in specs:
        for rank, row in enumerate(_spread_pick(rows, score, n_each, used), 1):
            selected.append({"category": category, "rank": rank, "row": row})
    return selected


def canonical_specs(row: dict) -> dict:
    return {
        "Gain_min": float(row["req_Gain_min"]),
        "GBW_min": float(row["req_GBW_min"]),
        "CL_pF": float(row["req_CL_pF"]),
        "Power_max": float(row["req_Power_max"]),
    }


def expected_from_perf(perf: dict) -> dict:
    return {
        "dc_gain_dB": float(perf["DC_Gain_dB"]),
        "gbw_Hz": float(perf["GBW"]),
        "phase_margin_deg": float(perf["PM"]),
        "power_W": float(perf["Power"]),
        "vout_dc_V": float(perf["Vout"]),
        "vtail_dc_V": float(perf["Vtail"]),
        "vmirror_dc_V": float(perf["Vmirror"]),
    }


def expected_from_sizing(record: dict) -> dict:
    """Convert a guarded sizing record into the private correlation schema."""
    perf = record["lut_metrics"]
    if perf is None:
        raise ValueError("sizing record has no LUT metrics")
    return {
        "dc_gain_dB": float(perf["DC_Gain_dB"]),
        "gbw_Hz": float(perf["GBW"]),
        "phase_margin_deg": float(perf["PM"]),
        "power_W": float(perf["Power"]),
        "vout_dc_V": float(perf["Vout"]),
        "vtail_dc_V": float(perf["Vtail"]),
        "vmirror_dc_V": float(perf["Vmirror"]),
    }


def compare_measurements(expected: dict, measured: dict) -> dict:
    metrics, all_ok = {}, True
    for name, (kind, tolerance, unit) in METRIC_RULES.items():
        if name not in expected or name not in measured:
            metrics[name] = {"available": False, "passed": False}
            all_ok = False
            continue
        exp, got = float(expected[name]), float(measured[name])
        if not np.isfinite([exp, got]).all():
            metrics[name] = {"available": True, "expected": exp,
                             "measured": got, "passed": False}
            all_ok = False
            continue
        signed = got - exp
        error = abs(signed) if kind == "absolute" else abs(signed) / max(abs(exp), 1e-30)
        passed = bool(error <= tolerance)
        metrics[name] = {
            "available": True, "expected": exp, "measured": got,
            "signed_difference": signed,
            "error": error, "error_kind": kind,
            "tolerance": tolerance, "unit": unit, "passed": passed,
        }
        all_ok &= passed
    return {"metrics": metrics, "correlation_passed": bool(all_ok)}


def measured_constraint_verdict(request: dict, measured: dict) -> dict:
    checks = {
        "Gain_min": measured["dc_gain_dB"] >= request["Gain_min"],
        "GBW_min": measured["gbw_Hz"] >= request["GBW_min"],
        "Power_max": measured["power_W"] <= request["Power_max"],
        "PM_min": measured["phase_margin_deg"] >= config.PM_MIN_DEFAULT,
    }
    return {"checks": {k: bool(v) for k, v in checks.items()},
            "verdict": bool(all(checks.values()))}


def collect_campaign(local_root: str | Path, results_root: str | Path) -> dict:
    """Join completed Spectre JSON with private expected/request evidence."""
    local_root, results_root = Path(local_root), Path(results_root)
    records = []
    jobs_dir = local_root / "jobs"
    for case_dir in sorted(p for p in jobs_dir.iterdir() if p.is_dir()):
        result_path = results_root / f"{case_dir.name}.json"
        if not result_path.exists():
            records.append({"case_id": case_dir.name, "status": "pending"})
            continue
        measured = json.loads(result_path.read_text())
        expected = json.loads((case_dir / "expected_private.json").read_text())
        request = json.loads((case_dir / "request_private.json").read_text())
        job = json.loads((case_dir / "job.json").read_text())
        if measured.get("case_id") != case_dir.name:
            raise ValueError(f"result case mismatch for {case_dir.name}")
        comparison = compare_measurements(expected, measured)
        constraint = measured_constraint_verdict(request, measured)
        records.append({
            "case_id": case_dir.name, "status": "completed",
            "category": job.get("category"), "source_row_id": job.get("source_row_id"),
            "pipeline_status": job.get("pipeline_status"),
            "request": request, "expected": expected, "spectre": measured,
            **comparison, "spectre_constraints": constraint,
            "false_proxy_pass": not constraint["verdict"],
        })
    completed = [r for r in records if r["status"] == "completed"]
    return {
        "schema_version": 1,
        "counts": {
            "total": len(records), "completed": len(completed),
            "pending": len(records) - len(completed),
            "correlation_passed": sum(r["correlation_passed"] for r in completed),
            "false_proxy_passes": sum(r["false_proxy_pass"] for r in completed),
        },
        "records": records,
    }


def write_summary(report: dict, path: str | Path) -> None:
    c = report["counts"]
    lines = ["# Cadence correlation campaign", "",
             f"Completed {c['completed']}/{c['total']}; pending {c['pending']}.",
             f"Correlation passes: {c['correlation_passed']}; "
             f"false proxy passes: {c['false_proxy_passes']}.", "",
             "| Case | Category | Gain err (dB) | GBW err (%) | PM err (deg) | Power err (%) | Correlation | Spectre constraints |",
             "|---|---|---:|---:|---:|---:|---|---|"]
    for r in report["records"]:
        if r["status"] != "completed":
            lines.append(f"| {r['case_id']} | — | — | — | — | — | PENDING | — |")
            continue
        m = r["metrics"]
        lines.append(
            f"| {r['case_id']} | {r.get('category')} | "
            f"{m['dc_gain_dB']['signed_difference']:.3f} | "
            f"{100*m['gbw_Hz']['signed_difference']/m['gbw_Hz']['expected']:.2f} | "
            f"{m['phase_margin_deg']['signed_difference']:.2f} | "
            f"{100*m['power_W']['signed_difference']/m['power_W']['expected']:.2f} | "
            f"{'PASS' if r['correlation_passed'] else 'FAIL'} | "
            f"{'PASS' if r['spectre_constraints']['verdict'] else 'FAIL'} |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

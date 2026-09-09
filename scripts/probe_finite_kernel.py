"""Phase F1 development probe: finite-tail kernel on the real TSMC LUTs.

NOT a canonical evaluation - public finite evaluation is still closed (the
F2 gate). Records measured kernel behavior on real device data for Astra's
F1 review with self-verified LUT hashes, source identity, effective budget
arguments, full kernel OP records, and per-iteration traces for successful
AND failed runs (Astra F1-R5). Strict JSON (no NaN/Infinity). Evidence
lands under ``evaluation_results/finite_m5/f1_probe_<timestamp>/``.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analog_ai import ORACLE_VERSION
from analog_ai.circuit.dc_solver import (FINITE_TOLERANCES,
                                         DCConvergenceError,
                                         solve_operating_point,
                                         solve_operating_point_finite)
from analog_ai.devices.lut import DomainError
from analog_ai.loader import load_engine

PROBE_DESIGNS = [
    {"name": "nominal_50uA",
     "x7": [0.5e-6, 15.0, 0.6e-6, 12.0, 0.5e-6, 10.0, 50e-6]},
    {"name": "wide_100uA",
     "x7": [0.6e-6, 12.0, 0.75e-6, 10.0, 0.6e-6, 12.0, 100e-6]},
    {"name": "boundary_10uA",
     "x7": [0.5e-6, 15.0, 0.6e-6, 12.0, 0.5e-6, 10.0, 10e-6]},
]
WIDE_NAME = "wide_100uA"
COMPARISON_BUDGET = 20   # the pre-corrective default that failed on wide


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_luts(lut_dir: Path) -> dict:
    """Hash the LUT files the probe is about to load and compare against
    the checked-in manifest; abort on any mismatch."""
    manifest_path = Path("configs/lut_manifest.json")
    manifest = (json.loads(manifest_path.read_text())
                if manifest_path.exists() else {})
    out = {"manifest_found": bool(manifest), "files": {}}
    for key in ("nch", "pch"):
        entry = manifest.get(key, {})
        path = lut_dir / entry.get("file", f"TSMC_fast_65nm_{key}.pkl")
        t0 = time.time()
        digest = sha256_of(path)
        verified = digest == entry.get("sha256")
        out["files"][key] = {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": digest,
            "expected_sha256": entry.get("sha256"),
            "verified": verified,
            "hash_seconds": round(time.time() - t0, 1),
        }
        if not verified:
            raise SystemExit(f"LUT hash mismatch for {path}: aborting probe")
    return out


F1_SOURCE_MODULES = [
    "analog_ai", "analog_ai.config", "analog_ai.devices.lut",
    "analog_ai.devices.device_model", "analog_ai.circuit.dc_solver",
    "analog_ai.circuit.mna", "analog_ai.circuit.ota5t",
    "analog_ai.loader",
]


def source_fingerprint(modules=None, extra_scripts=()) -> dict:
    """Content hashes of executed sources, tying evidence to exact source
    contents regardless of Git state (Astra R5b). The DEFAULT set is the
    accepted F1 contract (kernel, device/LUT implementation, configuration,
    loader, this script). F2 callers must pass the explicit extension -
    evaluator + constraints modules and the actual F2 entry point - see
    :func:`source_fingerprint_f2` (Astra F2-R5). Untracked review/output
    files are not code identity and are deliberately excluded."""
    import importlib

    names = F1_SOURCE_MODULES if modules is None else list(modules)
    out = {}
    for name in names:
        path = Path(importlib.import_module(name).__file__).resolve()
        out[name] = {"file": path.name, "sha256": sha256_of(path)}
    probe_path = Path(__file__).resolve()
    out["scripts.probe_finite_kernel"] = {
        "file": probe_path.name, "sha256": sha256_of(probe_path)}
    for extra in extra_scripts:
        p = Path(extra).resolve()
        out[f"scripts/{p.name}"] = {"file": p.name, "sha256": sha256_of(p)}
    return out


def source_fingerprint_f2() -> dict:
    """F2 fingerprint set: the F1 sources plus the evaluator and constraints
    modules and the actual F2 probe entry point (Astra F2-R5)."""
    return source_fingerprint(
        modules=F1_SOURCE_MODULES + ["analog_ai.evaluation.evaluator",
                                     "analog_ai.evaluation.constraints"],
        extra_scripts=[Path(__file__).resolve().parent
                       / "probe_finite_evaluator.py"])


def source_identity() -> dict:
    """Git revision plus TRACKED-change state; untracked review/output
    files do not taint code identity. With tracked changes present, the
    diff hash pins the exact working-tree code that generated the run
    (Astra R5b)."""
    def git(*args: str) -> str | None:
        try:
            return subprocess.run(["git", *args], capture_output=True,
                                  text=True, check=True).stdout.strip()
        except Exception:
            return None

    commit = git("rev-parse", "HEAD")
    tracked_changes = bool(git("status", "--porcelain",
                               "--untracked-files=no"))
    identity = {
        "git_commit": commit,
        "git_tracked_changes": tracked_changes,
        "python": sys.version.split()[0],
        "source_fingerprint": source_fingerprint(),
    }
    if tracked_changes:
        diff = git("diff", "HEAD")
        identity["git_diff_sha256"] = (
            hashlib.sha256(diff.encode("utf-8")).hexdigest()
            if diff is not None else None)
    return identity


def comparison_budgets(budgets: dict,
                       budget: int = COMPARISON_BUDGET) -> dict:
    """Effective budgets for the before/after comparison run: preserve every
    supplied control and override ONLY max_outer (Astra R5b follow-up)."""
    return {**budgets, "max_outer": budget}


def run_design(dm, name: str, x7: list, budgets: dict, out_list: list) -> dict:
    entry = {"name": name, "x7": x7, "budgets": budgets or "kernel defaults"}
    trace: list = []
    t0 = time.time()
    try:
        op = solve_operating_point_finite(dm, *x7, vdd=1.2, vicm=0.6,
                                          trace=trace, **budgets)
        entry.update({
            "status": "converged",
            "runtime_s": round(time.time() - t0, 2),
            "kernel_record": op,
            "trace": trace,
        })
        print(f"[{name}] converged in {entry['runtime_s']} s "
              f"(outer={op['convergence']['outer_iterations']}, "
              f"KCL={op['kcl_max_abs']:.2e} A, "
              f"sat_m5={op['sat_m5'] * 1e3:.1f} mV, "
              f"snaps={len(op['clip_diagnostics']['coordinate_snaps'])})",
              flush=True)
    except (DCConvergenceError, DomainError, ValueError) as exc:
        entry.update({
            "status": type(exc).__name__,
            "message": str(exc),
            "runtime_s": round(time.time() - t0, 2),
            "trace": trace,
        })
        print(f"[{name}] {type(exc).__name__} after {entry['runtime_s']} s "
              f"({len(trace)} traced outer iterations): {exc}", flush=True)
    out_list.append(entry)
    return entry


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-root", default="evaluation_results/finite_m5")
    ap.add_argument("--max-outer", type=int, default=None,
                    help="explicit outer budget (default: kernel default)")
    ap.add_argument("--max-newton", type=int, default=None)
    ap.add_argument("--tol", type=float, default=None)
    ap.add_argument("--skip-comparison", action="store_true",
                    help="skip the wide-design low-budget comparison run")
    args = ap.parse_args()

    budgets = {k: v for k, v in (("max_outer", args.max_outer),
                                 ("max_newton", args.max_newton),
                                 ("tol", args.tol)) if v is not None}

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_root) / f"f1_probe_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "probe": "phase_f1_finite_kernel_real_lut_corrective",
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "oracle_version_of_runtime": ORACLE_VERSION,
        "source_identity": source_identity(),
        "note": ("development probe only; finite records carry no canonical "
                 "identity until the F2/F3 schema gate (Astra A3)"),
        "declared_tolerances": FINITE_TOLERANCES,
        "effective_budgets": budgets or "kernel defaults",
        "designs": [],
    }

    print("Verifying LUT hashes (streaming sha256)...", flush=True)
    record["lut_verification"] = verify_luts(Path("tech_luts"))

    print("Loading real TSMC LUTs (~5.5 GB)...", flush=True)
    t0 = time.time()
    _, ota = load_engine(tail_device="ideal", op_point="imposed")
    dm = ota.dm
    print(f"LUTs loaded in {time.time() - t0:.1f} s", flush=True)

    for design in PROBE_DESIGNS:
        run_design(dm, design["name"], design["x7"], budgets,
                   record["designs"])
        if design["name"] == "nominal_50uA":
            try:
                ideal = solve_operating_point(dm, design["x7"][0],
                                              design["x7"][1],
                                              design["x7"][2],
                                              design["x7"][3],
                                              design["x7"][6],
                                              vdd=1.2, vicm=0.6)
                record["designs"][-1]["ideal_reference_voltages"] = {
                    "Vtail": ideal["Vtail"], "Vmirror": ideal["Vmirror"],
                    "Vout": ideal["Vout"]}
            except (DCConvergenceError, DomainError, ValueError) as exc:
                record["designs"][-1]["ideal_reference_voltages"] = {
                    "status": type(exc).__name__, "message": str(exc)}

    if not args.skip_comparison:
        wide = next(d for d in PROBE_DESIGNS if d["name"] == WIDE_NAME)
        low = comparison_budgets(budgets)
        print(f"[comparison] re-running {WIDE_NAME} at "
              f"max_outer={low['max_outer']} (preserving supplied tol/"
              f"max_newton; no source edits)...", flush=True)
        run_design(dm, f"{WIDE_NAME}_max_outer_{low['max_outer']}",
                   wide["x7"], low, record["designs"])

    out_file = out_dir / "f1_real_lut_probe.json"
    out_file.write_text(
        json.dumps(record, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    print(f"Evidence written to {out_file}", flush=True)


if __name__ == "__main__":
    main()

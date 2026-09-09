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


def source_identity() -> dict:
    def git(*args: str) -> str | None:
        try:
            return subprocess.run(["git", *args], capture_output=True,
                                  text=True, check=True).stdout.strip()
        except Exception:
            return None

    return {
        "git_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain")),
        "python": sys.version.split()[0],
    }


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
        print(f"[comparison] re-running {WIDE_NAME} at "
              f"max_outer={COMPARISON_BUDGET} (no source edits)...",
              flush=True)
        run_design(dm, f"{WIDE_NAME}_max_outer_{COMPARISON_BUDGET}",
                   wide["x7"], {"max_outer": COMPARISON_BUDGET},
                   record["designs"])

    out_file = out_dir / "f1_real_lut_probe.json"
    out_file.write_text(
        json.dumps(record, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    print(f"Evidence written to {out_file}", flush=True)


if __name__ == "__main__":
    main()

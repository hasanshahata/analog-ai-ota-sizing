"""Phase F1 development probe: finite-tail kernel on the real TSMC LUTs.

NOT a canonical evaluation - public finite evaluation is still closed (the
F2 gate). This probe records measured kernel behavior on real device data
for the Astra F1 review. Evidence lands under
``evaluation_results/finite_m5/f1_probe_<timestamp>/``.
"""

from __future__ import annotations

import argparse
import datetime
import json
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


def _lut_manifest() -> dict:
    path = Path("configs/lut_manifest.json")
    if path.exists():
        return json.loads(path.read_text())
    return {"note": "configs/lut_manifest.json not found"}


def _record_error(exc: Exception) -> dict:
    return {"status": type(exc).__name__, "message": str(exc)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-root", default="evaluation_results/finite_m5")
    args = ap.parse_args()

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_root) / f"f1_probe_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading real TSMC LUTs (~5.5 GB)...", flush=True)
    t0 = time.time()
    _, ota = load_engine(tail_device="ideal", op_point="imposed")
    dm = ota.dm
    print(f"LUTs loaded in {time.time() - t0:.1f} s", flush=True)

    record = {
        "probe": "phase_f1_finite_kernel_real_lut",
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "oracle_version_of_runtime": ORACLE_VERSION,
        "note": ("development probe only; finite records carry no canonical "
                 "identity until the F2/F3 schema gate (Astra A3)"),
        "tolerances": FINITE_TOLERANCES,
        "lut_manifest": _lut_manifest(),
        "designs": [],
    }

    for design in PROBE_DESIGNS:
        name, x7 = design["name"], design["x7"]
        entry = {"name": name, "x7": x7}
        print(f"[{name}] solving...", flush=True)
        t0 = time.time()
        try:
            op = solve_operating_point_finite(dm, *x7, vdd=1.2, vicm=0.6)
            entry.update({
                "status": "converged",
                "runtime_s": round(time.time() - t0, 2),
                "Vtail": op["Vtail"], "Vmirror": op["Vmirror"],
                "Vout": op["Vout"],
                "W1": op["W1"], "W3": op["W3"], "W5": op["W5"],
                "Vbias_tail": op["Vbias_tail"],
                "kcl_max_abs": op["kcl_max_abs"],
                "kcl_max_over_itail": op["kcl_max_over_itail"],
                "m5_current_error_rel": op["m5_current_error_rel"],
                "m5_gmid_forward_error": op["m5_gmid_forward_error"],
                "m5_gmid_table": op["M5"]["gmid_table"],
                "m5_gmid_forward": op["M5"]["gmid_forward"],
                "sat_m5": op["sat_m5"],
                "convergence": op["convergence"],
                "clip_diagnostics": op["clip_diagnostics"],
            })
            print(f"[{name}] converged in {entry['runtime_s']} s: "
                  f"Vtail={op['Vtail'] * 1e3:.1f} mV W5={op['W5'] * 1e6:.1f} um "
                  f"Vbias_tail={op['Vbias_tail']:.4f} V "
                  f"KCL={op['kcl_max_abs']:.2e} A "
                  f"table-vs-forward gmid5: {op['M5']['gmid_table']:.4f} vs "
                  f"{op['M5']['gmid_forward']:.4f}", flush=True)
        except (DCConvergenceError, DomainError, ValueError) as exc:
            entry.update({"runtime_s": round(time.time() - t0, 2),
                          **_record_error(exc)})
            print(f"[{name}] {type(exc).__name__}: {exc}", flush=True)

        if name == "nominal_50uA":
            try:
                ideal = solve_operating_point(dm, x7[0], x7[1], x7[2],
                                              x7[3], x7[6], vdd=1.2, vicm=0.6)
                entry["ideal_reference_voltages"] = {
                    "Vtail": ideal["Vtail"], "Vmirror": ideal["Vmirror"],
                    "Vout": ideal["Vout"]}
            except (DCConvergenceError, DomainError, ValueError) as exc:
                entry["ideal_reference_voltages"] = _record_error(exc)

        record["designs"].append(entry)

    out_file = out_dir / "f1_real_lut_probe.json"
    out_file.write_text(json.dumps(record, indent=2) + "\n")
    print(f"Evidence written to {out_file}", flush=True)


if __name__ == "__main__":
    main()

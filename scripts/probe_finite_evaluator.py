"""Phase F2 development probe: integrated finite evaluator on real LUTs.

NOT a canonical evaluation and NOT public finite exposure: this records
measured F2-level evidence (integrated metrics, hard constraints, finite
records) on real TSMC device data for Astra's F2 review, plus a
data-level capacitance-magnitude observation for the A4 convention
question. Magnitudes constrain but cannot settle the capacitance
DEFINITION; that requires the characterization deck or a device-level
Spectre experiment (F5). Strict JSON; evidence under
``evaluation_results/finite_m5/f2_integration_<timestamp>/``.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from analog_ai.circuit.ota5t import OTA5T
from analog_ai.evaluation.evaluator import evaluate_design_finite
from analog_ai.loader import load_engine

PROBE_DESIGNS = [
    {"name": "nominal_50uA",
     "x7": [0.5e-6, 15.0, 0.6e-6, 12.0, 0.5e-6, 10.0, 50e-6]},
    {"name": "boundary_10uA",
     "x7": [0.5e-6, 15.0, 0.6e-6, 12.0, 0.5e-6, 10.0, 10e-6]},
]
LOOSE_SPECS = {"Gain_min": 20.0, "GBW_min": 1e6, "CL_pF": 1.0,
               "Power_max": 400e-6}

_PROBE_PATH = Path(__file__).resolve().parents[1] / "scripts" / \
    "probe_finite_kernel.py"


def _probe_helpers():
    """Reuse the F1 probe's verified helpers (hashing, fingerprints)."""
    spec = importlib.util.spec_from_file_location("probe_finite_kernel",
                                                  _PROBE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def capacitance_magnitude_probe(dm, lut_side, lengths, vgs_values,
                                vds_values) -> dict:
    """Data-level observation of cdd vs cgd magnitudes at legal grid
    points. This constrains - but cannot establish - the capacitance
    convention (A4): a deck/save-expression check or a device-level
    Spectre experiment is still required for the DEFINITION."""
    lut = dm.nch if lut_side == "nch" else dm.pch
    rows = []
    for L in lengths:
        for vgs in vgs_values:
            for vds in vds_values:
                if not bool(lut.in_domain(L, vgs, vds, 0.0).all()):
                    continue
                cgd = float(abs(lut.lookup("cgd", [L], [vgs], [vds], [0.0])[0]))
                cdd = float(abs(lut.lookup("cdd", [L], [vgs], [vds], [0.0])[0]))
                gm = float(abs(lut.lookup("gm", [L], [vgs], [vds], [0.0])[0]))
                rows.append({
                    "L": L, "VGS": vgs, "VDS": vds,
                    "cgd_F_per_refW": cgd,
                    "cdd_F_per_refW": cdd,
                    "cdd_over_cgd": (cdd / cgd) if cgd > 0 else None,
                    "gm_over_2pi_cdd_Hz": (gm / (2 * np.pi * cdd))
                    if cdd > 0 else None,
                })
    ratios = [r["cdd_over_cgd"] for r in rows if r["cdd_over_cgd"]]
    summary = {}
    if ratios:
        arr = np.asarray(ratios)
        summary = {"n": int(arr.size), "cdd_over_cgd_min": float(arr.min()),
                   "cdd_over_cgd_median": float(np.median(arr)),
                   "cdd_over_cgd_max": float(arr.max())}
    return {"side": lut_side, "summary": summary, "samples": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-root", default="evaluation_results/finite_m5")
    args = ap.parse_args()

    helpers = _probe_helpers()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_root) / f"f2_integration_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "probe": "phase_f2_integrated_finite_evaluator_real_lut",
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_identity": helpers.source_identity(),
        "note": ("development probe only; public finite evaluation stays "
                 "closed; finite records carry the dev schema identity"),
        "designs": [],
    }

    print("Verifying LUT hashes (streaming sha256)...", flush=True)
    record["lut_verification"] = helpers.verify_luts(Path("tech_luts"))

    print("Loading real TSMC LUTs (~5.5 GB)...", flush=True)
    t0 = time.time()
    _, ota_imposed = load_engine(tail_device="ideal", op_point="imposed")
    dm = ota_imposed.dm
    ota_finite = OTA5T(dm, vdd=1.2, tail_device="finite",
                       op_point="imposed")
    print(f"LUTs loaded in {time.time() - t0:.1f} s", flush=True)

    print("Capacitance magnitude observation (nch, VSB=0)...", flush=True)
    record["capacitance_magnitude_observation"] = capacitance_magnitude_probe(
        dm, "nch",
        lengths=[0.5e-6, 1.0e-6],
        vgs_values=[0.7, 0.9, 1.1],
        vds_values=[0.2, 0.6])

    for design in PROBE_DESIGNS:
        name = design["name"]
        t0 = time.time()
        rec = evaluate_design_finite(ota_finite, design["x7"],
                                     dict(LOOSE_SPECS))
        rec["runtime_s"] = round(time.time() - t0, 2)
        record["designs"].append(rec)
        verdict = rec["verdict"]
        m = rec.get("metrics") or {}
        print(f"[{name}] verdict={verdict} in {rec['runtime_s']} s "
              f"(gain={m.get('DC_Gain_dB'):.1f} dB, "
              f"GBW={m.get('GBW') / 1e6:.1f} MHz, "
              f"PM={m.get('PM'):.1f} deg, sat_m5={m.get('sat_m5') * 1e3:.1f} mV, "
              f"rows_failed={sum(1 for c in rec['constraints'] if not c['passed'])})",
              flush=True)

    out_file = out_dir / "f2_integration_probe.json"
    out_file.write_text(
        json.dumps(record, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    print(f"Evidence written to {out_file}", flush=True)


if __name__ == "__main__":
    main()

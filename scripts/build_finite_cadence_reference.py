"""Build the local Phase F5 finite-M5 manual reference; never stages it."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analog_ai.correlation.finite_spectre_job import build_finite_manual_reference


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path,
                        default=ROOT / "cadence_templates/5T_OTA_finite_m5_tt.scs")
    parser.add_argument("--tolerances", type=Path,
                        default=ROOT / "configs/finite_m5_cadence_tolerances_v1.json")
    parser.add_argument("--source", type=Path, default=ROOT /
                        "evaluation_results/finite_m5/f4_baseline_20260909_170218/f4_baseline.json")
    parser.add_argument("--source-case", default="test5_balanced")
    parser.add_argument("--case-id", default="finite_manual_reference_001")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "correlation_jobs/finite_m5_manual")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--lut-dir", type=Path, default=ROOT / "tech_luts",
                        help="verified real LUT directory used for one-point OP enrichment")
    args = parser.parse_args()
    import json
    campaign = json.loads(args.source.read_text())
    case = next((item for item in campaign["cases"]
                 if item["name"] == args.source_case), None)
    if case is None:
        parser.error(f"source case not found: {args.source_case}")
    record = case["finite_record"]
    design = [record["design"][name] for name in
              ("L1", "gmid1", "L3", "gmid3", "L5", "gmid5", "Itail")]
    print("Loading verified real LUTs for one-point OP enrichment...", flush=True)
    from analog_ai.loader import load_engine
    _, ota = load_engine(str(args.lut_dir), tail_device="finite", op_point="solved")
    perf = ota.evaluate(design, record["request"]["CL_pF"] * 1e-12)
    enriched = perf["devices"]
    for name in ("M1", "M2", "M3", "M4", "M5"):
        archived = record["devices"][name]
        for field in ("W", "L", "ID", "gm", "gds", "VDSAT", "VDS"):
            if not math.isclose(float(enriched[name][field]),
                                float(archived[field]),
                                rel_tol=1e-9, abs_tol=1e-15):
                raise RuntimeError(f"one-point enrichment mismatch: {name}.{field}")
    case_dir = build_finite_manual_reference(
        args.template, args.tolerances, args.source, args.out,
        case_name=args.source_case, case_id=args.case_id,
        overwrite=args.overwrite, enriched_devices=enriched)
    print(case_dir)


if __name__ == "__main__":
    main()

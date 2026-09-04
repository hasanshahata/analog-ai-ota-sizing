"""Generate the private host-side 25-case Cadence correlation campaign."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analog_ai.correlation.calibration import GBW_GUARD_BAND
from analog_ai.correlation.campaign import (canonical_specs,
                                             expected_from_sizing,
                                             select_campaign_requests)
from analog_ai.correlation.spectre_job import build_job
from analog_ai.sizing import size_ideal_tail_ota
from analog_ai.surrogate import data as sdata
from analog_ai.surrogate.train import load_checkpoint


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="data/pilot")
    ap.add_argument("--ckpt-dir", default="models/surrogate/poc")
    ap.add_argument("--template", default="5T_OTA_netlist_cadence.txt")
    ap.add_argument("--out", default="correlation_jobs/campaign_25")
    ap.add_argument("--n-each", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20260903)
    ap.add_argument("--global-maxiter", type=int, default=20)
    ap.add_argument("--gbw-guard-band", type=float, default=GBW_GUARD_BAND,
                    help="internal fractional GBW margin (default: 0.25)")
    ap.add_argument("--exclude-manifest", action="append", default=[],
                    help="campaign manifest whose source rows must be excluded")
    ap.add_argument("--case-prefix", default="corr",
                    help="case ID prefix (letters, digits, _ or -)")
    ap.add_argument("--campaign-name", default="ideal_tail_tt_25")
    ap.add_argument("--candidate-multiplier", type=int, default=4,
                    help="preselect this many candidates per required job")
    ap.add_argument("--max-request-gbw-mhz", type=float, default=None,
                    help="skip candidates whose request GBW exceeds this "
                         "(e.g. 300 restricts the campaign to the app domain)")
    args = ap.parse_args()

    requests, _ = sdata.load_dataset(args.data)
    excluded_ids = set()
    excluded_campaigns = []
    for manifest_path in args.exclude_manifest:
        previous = json.loads(Path(manifest_path).read_text())
        ids = {case["source_row_id"] for case in previous["cases"]}
        excluded_ids.update(ids)
        excluded_campaigns.append({"manifest": manifest_path,
                                   "source_row_count": len(ids)})
    if args.candidate_multiplier < 1:
        ap.error("--candidate-multiplier must be >= 1")
    if args.max_request_gbw_mhz is not None:
        cap_hz = args.max_request_gbw_mhz * 1e6
        before = len(requests)
        requests = [r for r in requests
                    if float(r["req_GBW_min"]) <= cap_hz]
        print(f"domain cap {args.max_request_gbw_mhz:.0f} MHz: candidate "
              f"rows {before} -> {len(requests)}", flush=True)
    selected = select_campaign_requests(
        requests, args.n_each * args.candidate_multiplier, excluded_ids)
    champion_file = Path(args.ckpt_dir) / "champion.json"
    champion_name = Path(json.loads(champion_file.read_text())["champion"]).name
    ck = load_checkpoint(str(Path(args.ckpt_dir) / champion_name))
    lo = np.asarray(ck["meta"]["feat_lo"])
    hi = np.asarray(ck["meta"]["feat_hi"])

    print("Loading typical-corner LUTs (~5.5 GB)...", flush=True)
    from analog_ai.loader import load_engine
    _, ota = load_engine(op_point="solved")

    out_root = Path(args.out)
    manifest = {
        "schema_version": 1, "campaign": args.campaign_name,
        "selection": {"categories": 5, "n_each": args.n_each,
                      "source_split": "test", "seed": args.seed,
                      "candidate_multiplier": args.candidate_multiplier,
                      "excluded_source_rows": len(excluded_ids),
                      "excluded_campaigns": excluded_campaigns},
        "champion": champion_name, "template": str(Path(args.template)),
        "gbw_guard_band": args.gbw_guard_band,
        "cases": [], "attempts": [],
    }
    out_root.mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / "campaign_manifest.json"
    accepted_by_category = {name: 0 for name in
                            ("low_power", "high_gain", "high_gbw",
                             "heavy_load", "boundary")}
    for attempt_i, item in enumerate(selected, 1):
        row, category = item["row"], item["category"]
        if accepted_by_category[category] >= args.n_each:
            continue
        specs = canonical_specs(row)
        if (args.max_request_gbw_mhz is not None
                and specs["GBW_min"] > args.max_request_gbw_mhz * 1e6):
            manifest["attempts"].append({
                "attempt": attempt_i, "category": category,
                "source_row_id": row["row_id"], "accepted": False,
                "skipped": (f"request GBW {specs['GBW_min'] / 1e6:.0f} MHz "
                            "above the app-domain cap")})
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                                     encoding="utf-8")
            print(f"[attempt {attempt_i:03d}] {row['row_id']} {category}: "
                  "skipped (request above domain cap)", flush=True)
            continue
        result = size_ideal_tail_ota(
            ota, ck["proposal"], specs, lo, hi,
            guard_band=args.gbw_guard_band, global_fallback=True,
            global_maxiter=args.global_maxiter, seed=args.seed + attempt_i)
        attempt = {"attempt": attempt_i, "category": category,
                   "source_row_id": row["row_id"],
                   "pipeline_status": result["status"],
                   "pipeline_oracle_evals": result["n_oracle_evals"]}
        if result["status"] == "unresolved":
            manifest["attempts"].append({**attempt, "accepted": False})
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                                     encoding="utf-8")
            print(f"[attempt {attempt_i:03d}] {row['row_id']} {category}: "
                  "unresolved - retained as rejection evidence", flush=True)
            continue
        accepted_i = len(manifest["cases"]) + 1
        accepted_by_category[category] += 1
        geometry = result["physical_design"]
        case_id = f"{args.case_prefix}_{accepted_i:03d}_{category}"
        metadata = {"category": category,
                    "category_rank": accepted_by_category[category],
                    "source_row_id": row["row_id"],
                    "pipeline_status": result["status"],
                    "pipeline_oracle_evals": result["n_oracle_evals"],
                    "calibration_policy": result["calibration"]["version"],
                    "gbw_guard_band": result["calibration"]["gbw_guard_band"]}
        build_job(args.template, out_root, case_id, geometry,
                  specs["CL_pF"] * 1e-12, request=specs,
                  expected=expected_from_sizing(result), metadata=metadata)
        manifest["cases"].append({
            "case_id": case_id, **metadata,
            "user_specs": result["user_specs"],
            "internal_specs": result["internal_specs"],
            "user_verdict": result["user_verdict"],
            "internal_verdict": result["internal_verdict"]})
        manifest["attempts"].append({**attempt, "accepted": True,
                                     "case_id": case_id})
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                                 encoding="utf-8")
        print(f"[{accepted_i:02d}/{5 * args.n_each}] {case_id}: "
              f"{result['status']}", flush=True)

    missing = {name: args.n_each - count for name, count in
               accepted_by_category.items() if count < args.n_each}
    if missing:
        raise RuntimeError(f"candidate pool exhausted; missing jobs: {missing}")
    print(f"Campaign written to {out_root}", flush=True)


if __name__ == "__main__":
    main()

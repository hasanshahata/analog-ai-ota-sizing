"""Generate the private host-side 25-case Cadence correlation campaign."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analog_ai.correlation.campaign import (canonical_specs,
                                             expected_from_perf,
                                             select_campaign_requests)
from analog_ai.correlation.spectre_job import build_job
from analog_ai.surrogate import data as sdata
from analog_ai.surrogate.evaluate import eval_request_staged
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
    args = ap.parse_args()

    requests, _ = sdata.load_dataset(args.data)
    selected = select_campaign_requests(requests, args.n_each)
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
        "schema_version": 1, "campaign": "ideal_tail_tt_25",
        "selection": {"categories": 5, "n_each": args.n_each,
                      "source_split": "test", "seed": args.seed},
        "champion": champion_name, "template": str(Path(args.template)),
        "cases": [],
    }
    for i, item in enumerate(selected, 1):
        row, category = item["row"], item["category"]
        specs = canonical_specs(row)
        result = eval_request_staged(
            ota, ck["proposal"], specs, lo, hi, local=True,
            global_fallback=True, global_maxiter=args.global_maxiter,
            seed=args.seed + i)
        if result["status"] == "unresolved":
            raise RuntimeError(f"pipeline could not size selected row {row['row_id']}")
        design = result["design"]
        perf = ota.evaluate(design, CL=specs["CL_pF"] * 1e-12)
        devices = perf["devices"]
        geometry = {
            "L1": float(devices["M1"]["L"]),
            "W1": float(devices["M1"]["W"]),
            "L3": float(devices["M3"]["L"]),
            "W3": float(devices["M3"]["W"]),
            "Itail": float(design[4]),
        }
        case_id = f"corr_{i:03d}_{category}"
        metadata = {"category": category, "category_rank": item["rank"],
                    "source_row_id": row["row_id"],
                    "pipeline_status": result["status"],
                    "pipeline_oracle_evals": result["n_oracle_evals"]}
        build_job(args.template, out_root, case_id, geometry,
                  specs["CL_pF"] * 1e-12, request=specs,
                  expected=expected_from_perf(perf), metadata=metadata)
        manifest["cases"].append({"case_id": case_id, **metadata})
        print(f"[{i:02d}/{len(selected)}] {case_id}: {result['status']}", flush=True)

    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "campaign_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Campaign written to {out_root}", flush=True)


if __name__ == "__main__":
    main()

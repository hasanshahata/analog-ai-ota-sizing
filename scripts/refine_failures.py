"""Phase C: benchmark warm-start local refinement on surrogate failures.

Reads a surrogate evaluation record file, takes every unresolved request,
runs the staged ladder (local trust-region refinement around the best heads,
then global DE only if needed), and writes a NEW record file (the original
PoC records are never modified) plus a summary with the review's required
accounting:

  python scripts/refine_failures.py \
      --records evaluation_results/canonical/surrogate_poc_records.json \
      --limit 40          # stratified subset first; omit for all failures
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analog_ai.surrogate import data as sdata
from analog_ai.surrogate.evaluate import eval_request_staged
from analog_ai.surrogate.train import load_checkpoint


def _stratified_subset(failures, limit, seed=0):
    if limit is None or limit >= len(failures):
        return failures
    rng = np.random.default_rng([seed, 31])
    # stratify by request GBW/CL bins so the subset spans the failure space
    def bucket(r):
        return (int(np.log10(max(r["request"]["GBW_min"], 1e6) / 1e7)),
                int(r["request"]["CL_pF"] >= 2.0))
    buckets = {}
    for f in failures:
        buckets.setdefault(bucket(f), []).append(f)
    for k in buckets:
        rng.shuffle(buckets[k])
    out, gi = [], 0
    keys = sorted(buckets)
    while len(out) < limit and any(buckets[k] for k in keys):
        k = keys[gi % len(keys)]
        if buckets[k]:
            out.append(buckets[k].pop())
        gi += 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--records",
                    default="evaluation_results/canonical/"
                            "surrogate_poc_records.json")
    ap.add_argument("--ckpt-dir", default=os.path.join("models", "surrogate",
                                                       "poc"))
    ap.add_argument("--data", default=os.path.join("data", "pilot"))
    ap.add_argument("--out", default="evaluation_results/canonical/"
                                     "surrogate_poc_refined_records.json")
    ap.add_argument("--limit", type=int, default=None,
                    help="stratified subset size (default: all failures)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--global-maxiter", type=int, default=20)
    args = ap.parse_args()

    with open(args.records) as f:
        records = json.load(f)
    with open(os.path.join(args.ckpt_dir, "champion.json")) as f:
        champion = json.load(f)["champion"]
    ck = load_checkpoint(os.path.join(args.ckpt_dir,
                                      os.path.basename(champion)))
    lo = np.array(ck["meta"]["feat_lo"])
    hi = np.array(ck["meta"]["feat_hi"])
    model = ck["proposal"]
    requests, _ = sdata.load_dataset(args.data)
    req_by_id = {r["row_id"]: r for r in requests}

    unresolved = [{"row_id": k, "request": v["request"]}
                  for k, v in records.items()
                  if not k.startswith(("_", "de_", "case_"))
                  and v["status"] == "unresolved"]
    subset = _stratified_subset(unresolved, args.limit, args.seed)
    print(f"[refine] {len(subset)}/{len(unresolved)} unresolved requests "
          f"(champion {os.path.basename(champion)})", flush=True)

    done = {}
    if os.path.exists(args.out):
        with open(args.out) as f:
            done = json.load(f)

    t0 = time.time()
    n_new = 0
    for i, f in enumerate(subset):
        if f["row_id"] in done:
            continue
        out = eval_request_staged(
            None if False else _ota_holder[0] if False else None, model,
            f["request"], lo, hi,
            global_maxiter=args.global_maxiter, seed=args.seed) \
            if False else None
        # (kept simple below - engine passed explicitly)
        break
    # real loop (engine load happens here so --help stays fast)
    from analog_ai.loader import load_engine
    print("Loading LUTs (~5.5 GB)...", flush=True)
    _, ota = load_engine(op_point="solved")
    for i, f in enumerate(subset):
        if f["row_id"] in done:
            continue
        out = eval_request_staged(ota, model, f["request"], lo, hi,
                                  global_maxiter=args.global_maxiter,
                                  seed=args.seed)
        out["source_record_status"] = "unresolved"
        done[f["row_id"]] = out
        n_new += 1
        with open(args.out, "w") as fh:
            json.dump(done, fh, indent=2, default=str)
        stages = {s["stage"]: s for s in out["stages"]}
        how = out["status"]
        cost = out["n_oracle_evals"]
        print(f"  [{i + 1}/{len(subset)}] {f['row_id']}: {how} "
              f"({cost} evals, "
              f"local={'local_refinement' in stages} "
              f"global={'global_fallback' in stages})", flush=True)

    # ---- summary ----
    stats = {
        "n_attempted": len(done),
        "recovery_local": sum(1 for v in done.values()
                              if v["status"] == "local_refinement_verified"),
        "recovery_global": sum(1 for v in done.values()
                               if v["status"] == "global_fallback_verified"),
        "still_unresolved": sum(1 for v in done.values()
                                if v["status"] == "unresolved"),
        "median_evals": float(np.median([v["n_oracle_evals"]
                                         for v in done.values()])),
        "p95_evals": float(np.percentile([v["n_oracle_evals"]
                                          for v in done.values()], 95)),
        "median_runtime_s": float(np.median([v["stages"][-1]["runtime_s"]
                                             if v["stages"] else 0
                                             for v in done.values()])),
        "needed_global": sum(1 for v in done.values()
                             if any(s["stage"] == "global_fallback"
                                    for s in v["stages"])),
    }
    with open(args.out, "w") as fh:
        json.dump(done, fh, indent=2, default=str)
    print("\n=== refinement summary ===")
    for k, v in stats.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()

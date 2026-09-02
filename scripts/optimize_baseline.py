"""Non-learning correctness baseline (correction plan Phase 4).

CLI around `analog_ai.optimization.de_baseline` (the canonical multi-start
constrained-DE implementation, shared with the Phase 3 dataset builder).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analog_ai.loader import load_engine
from analog_ai.optimization import optimize_specs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tests-dir", default=os.path.join("configs", "test_cases"))
    ap.add_argument("--out-dir", default=os.path.join("evaluation_results", "canonical"))
    ap.add_argument("--tag", default=None)
    ap.add_argument("--op-point", choices=["imposed", "solved"], default="solved")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tests", default="all",
                    help="comma-separated test names (e.g. test1_low_power) or 'all'")
    ap.add_argument("--maxiter", type=int, default=60)
    ap.add_argument("--popsize", type=int, default=20)
    ap.add_argument("--n-starts", type=int, default=2)
    args = ap.parse_args()
    if args.tag is None:
        args.tag = f"baseline_de_{args.op_point}"

    print("Loading LUTs (~5.5 GB)...", flush=True)
    _, ota = load_engine(op_point=args.op_point)

    os.makedirs(args.out_dir, exist_ok=True)
    records_path = os.path.join(args.out_dir, f"{args.tag}_records.json")
    # Resumable: keep results from previous runs of the same tag.
    records = {}
    if os.path.exists(records_path):
        with open(records_path) as f:
            records = json.load(f)

    test_files = sorted(f for f in os.listdir(args.tests_dir) if f.endswith(".json"))
    if args.tests != "all":
        wanted = {t.strip() for t in args.tests.split(",")}
        test_files = [f for f in test_files if f.replace(".json", "") in wanted]

    all_ok = True
    for tf in test_files:
        with open(os.path.join(args.tests_dir, tf)) as f:
            specs = json.load(f)
        name = tf.replace(".json", "")
        if name in records and "baseline" in records[name]:
            print(f"[{name}] already done (verdict="
                  f"{'PASS' if records[name]['verdict'] else 'FAIL'}) - skipping",
                  flush=True)
            all_ok &= records[name]["verdict"]
            continue
        print(f"[{name}] optimizing...", flush=True)
        rec = optimize_specs(ota, specs, seed=args.seed, maxiter=args.maxiter,
                             popsize=args.popsize, n_starts=args.n_starts)
        records[name] = rec
        all_ok &= rec["verdict"]
        b = rec["baseline"]
        print(f"  verdict={'PASS' if rec['verdict'] else 'FAIL'} "
              f"objective={b['objective']:.4f} evals={b['n_evals']} "
              f"time={b['runtime_s']}s", flush=True)
        # Incremental write: an interruption never loses completed tests.
        with open(records_path, "w") as f:
            json.dump(records, f, indent=2, default=str)

    md = [f"# Constrained-optimization baseline ({args.tag})\n",
          "Multi-start differential evolution on the canonical proxy,",
          "accepted only through the hard-constraint verifier.\n",
          "| Test | Verdict | Objective | Evals | Time (s) |",
          "|---|---|---|---|---|"]
    for name in sorted(records):
        rec, b = records[name], records[name]["baseline"]
        md.append(f"| {name} | {'PASS' if rec['verdict'] else 'FAIL'} "
                  f"| {b['objective']:.4f} | {b['n_evals']} | {b['runtime_s']} |")
    out_md = os.path.join(args.out_dir, f"{args.tag}_summary.md")
    with open(out_md, "w") as f:
        f.write("\n".join(md) + "\n")
    print(f"\nWrote {out_md} and {records_path}")
    print(f"Overall: {'ALL PASS' if all_ok else 'at least one FAIL'}")


if __name__ == "__main__":
    main()

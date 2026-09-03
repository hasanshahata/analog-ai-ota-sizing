"""Phase B: failure taxonomy for unresolved surrogate requests.

Re-proposes the champion's heads for every unresolved request in a
surrogate evaluation record file, verifies each under the full request,
and writes a machine-readable taxonomy plus a Markdown summary.

  python scripts/analyze_failures.py --records \
      evaluation_results/canonical/surrogate_poc_records.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analog_ai.surrogate import analysis
from analog_ai.surrogate import data as sdata


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--records",
                    default="evaluation_results/canonical/"
                            "surrogate_poc_records.json")
    ap.add_argument("--ckpt-dir", default=os.path.join("models", "surrogate",
                                                       "poc"))
    ap.add_argument("--data", default=os.path.join("data", "pilot"))
    ap.add_argument("--out-dir", default="evaluation_results/canonical")
    args = ap.parse_args()

    with open(args.records) as f:
        records = json.load(f)
    with open(os.path.join(args.ckpt_dir, "champion.json")) as f:
        champion = json.load(f)["champion"]
    ckpt_path = os.path.join(args.ckpt_dir, os.path.basename(champion))
    requests, designs = sdata.load_dataset(args.data)

    print("Loading LUTs (~5.5 GB)...", flush=True)
    from analog_ai.loader import load_engine
    _, ota = load_engine(op_point="solved")

    failures = analysis.analyze_unresolved(ota, ckpt_path, records,
                                           requests, designs)
    tables = analysis.group_tables(failures)
    os.makedirs(args.out_dir, exist_ok=True)
    out_json = os.path.join(args.out_dir, "surrogate_failure_report.json")
    out_md = os.path.join(args.out_dir, "surrogate_failure_report.md")
    analysis.write_report(failures, tables, out_json, out_md)
    print(f"\n{tables['dominant_constraint']}")
    print(f"wrote {out_json} and {out_md}")


if __name__ == "__main__":
    main()

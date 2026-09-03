"""Collect Cadence results and compare them with private LUT predictions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analog_ai.correlation.campaign import collect_campaign, write_summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", default="correlation_jobs/campaign_25")
    ap.add_argument("--results", default=r"E:\Cadence_AI_Share\results")
    ap.add_argument("--out", default="evaluation_results/cadence_correlation/campaign_25")
    args = ap.parse_args()
    report = collect_campaign(args.campaign, args.results)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "campaign_records.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_summary(report, out / "campaign_summary.md")
    c = report["counts"]
    print(f"Collected {c['completed']}/{c['total']} results; "
          f"correlation passes={c['correlation_passed']}; "
          f"false proxy passes={c['false_proxy_passes']}")


if __name__ == "__main__":
    main()

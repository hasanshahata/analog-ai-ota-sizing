"""Derive and record the v1 GBW guard band from the 25-case campaign."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analog_ai.correlation.calibration import analyze_gbw_calibration


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--records", default="evaluation_results/"
                    "cadence_correlation/campaign_25/campaign_records.json")
    ap.add_argument("--out", default="evaluation_results/"
                    "cadence_correlation/campaign_25/gbw_calibration_v1.json")
    args = ap.parse_args()
    records = json.loads(Path(args.records).read_text())["records"]
    analysis = analyze_gbw_calibration(records)
    Path(args.out).write_text(json.dumps(analysis, indent=2) + "\n",
                              encoding="utf-8")
    ratio = analysis["spectre_over_lut_ratio"]
    uplift = analysis["required_lut_uplift"]
    policy = analysis["frozen_policy"]
    print(f"Analyzed {analysis['n']} completed cases")
    print(f"Spectre/LUT GBW ratio: mean={ratio['mean']:.4f}, "
          f"minimum={ratio['minimum']:.4f}")
    print(f"Maximum observed required uplift: "
          f"{100*uplift['maximum_observed']:.2f}%")
    print(f"Frozen {policy['version']}: "
          f"{100*policy['gbw_guard_band']:.0f}% GBW guard band")


if __name__ == "__main__":
    main()

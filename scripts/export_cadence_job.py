"""Export one ideal-tail Cadence/Spectre correlation job.

This Step-2 utility does not load the LUTs.  It accepts a JSON file containing
evaluated physical geometry and creates a runnable job from the immutable
Cadence-exported template.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analog_ai.correlation import build_job


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--template", default="5T_OTA_netlist_cadence.txt")
    ap.add_argument("--design", required=True,
                    help="JSON with SI-valued L1,W1,L3,W3,Itail")
    ap.add_argument("--case-id", required=True)
    ap.add_argument("--out", default=os.path.join("correlation_jobs"))
    ap.add_argument("--cl", required=True, type=float,
                    help="load capacitance in farads")
    ap.add_argument("--vdd", type=float, default=1.2)
    ap.add_argument("--vicm", type=float, default=0.6)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    with open(args.design) as f:
        payload = json.load(f)
    design = payload.get("geometry", payload)
    case_dir = build_job(
        args.template, args.out, args.case_id, design, args.cl,
        vdd=args.vdd, vicm=args.vicm, overwrite=args.overwrite)
    print(case_dir)


if __name__ == "__main__":
    main()

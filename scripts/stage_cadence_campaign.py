"""Stage only blind/public campaign files into the VMware shared folder."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

PUBLIC_FILES = ("input.scs", "measure.ocn", "design.json", "job.json")


def stage(source: Path, destination: Path) -> int:
    count = 0
    for case in sorted((source / "jobs").iterdir()):
        if not case.is_dir():
            continue
        target = destination / "jobs" / case.name
        target.mkdir(parents=True, exist_ok=True)
        for name in PUBLIC_FILES:
            shutil.copy2(case / name, target / name)
        count += 1
    return count


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default="correlation_jobs/campaign_25")
    ap.add_argument("--destination", default=r"E:\Cadence_AI_Share")
    args = ap.parse_args()
    count = stage(Path(args.source), Path(args.destination))
    print(f"Staged {count} blind jobs to {args.destination}")


if __name__ == "__main__":
    main()

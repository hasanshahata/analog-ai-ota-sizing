"""Stage an F5 finite manual reference and its dedicated worker."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

PUBLIC_JOB_FILES = ("input.scs", "measure.ocn", "capacitance_probe.scs",
                    "measure_caps.ocn", "tolerances.json", "design.json",
                    "job.json")
RUNNER_FILES = ("run_finite_jobs.sh", "write_finite_result.py")


def stage_finite(source: Path, destination: Path, runner_source: Path) -> int:
    jobs = sorted(path for path in (source / "jobs").iterdir() if path.is_dir())
    for case in jobs:
        target = destination / "jobs" / case.name
        target.mkdir(parents=True, exist_ok=True)
        for name in PUBLIC_JOB_FILES:
            shutil.copy2(case / name, target / name)
    runner_target = destination / "runner"
    runner_target.mkdir(parents=True, exist_ok=True)
    for name in RUNNER_FILES:
        shutil.copy2(runner_source / name, runner_target / name)
    return len(jobs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=Path("correlation_jobs/finite_m5_manual"))
    parser.add_argument("--destination", type=Path,
                        default=Path(r"E:\Cadence_AI_Share\finite_m5"))
    parser.add_argument("--runner-source", type=Path,
                        default=Path("scripts/cadence_guest"))
    args = parser.parse_args()
    count = stage_finite(args.source, args.destination, args.runner_source)
    print(f"Staged {count} finite manual-reference jobs to {args.destination}")


if __name__ == "__main__":
    main()

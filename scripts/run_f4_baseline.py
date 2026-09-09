"""Phase F4 real-LUT finite-tail feasibility baseline.

Runs the five frozen regression requests through global differential
evolution and the accepted finite evaluator.  Evidence is non-canonical,
strict JSON, resumable, and source-bound.  This script does not perform any
Cadence/F5 work.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from scipy import __version__ as scipy_version
from scipy.optimize import differential_evolution

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analog_ai import config
from analog_ai.circuit.ota5t import OTA5T
from analog_ai.evaluation.evaluator import (effective_constraint_limits,
                                             evaluate_design_finite,
                                             validate_finite_specs)
from analog_ai.loader import load_engine
from analog_ai.optimization.de_baseline import make_objective

SOURCE_PATHS = (
    "analog_ai/config.py", "analog_ai/loader.py",
    "analog_ai/devices/lut.py", "analog_ai/devices/device_model.py",
    "analog_ai/circuit/dc_solver.py", "analog_ai/circuit/mna.py",
    "analog_ai/circuit/ota5t.py", "analog_ai/evaluation/constraints.py",
    "analog_ai/evaluation/evaluator.py",
    "analog_ai/optimization/de_baseline.py", "scripts/run_f4_baseline.py",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_luts(lut_dir: Path) -> dict:
    manifest = json.loads((ROOT / "configs/lut_manifest.json").read_text())
    result = {}
    for side, expected in manifest.items():
        path = lut_dir / expected["file"]
        actual = {"file": path.name, "bytes": path.stat().st_size,
                  "sha256": _sha(path)}
        if actual["bytes"] != expected["bytes"] or actual["sha256"] != expected["sha256"]:
            raise RuntimeError(f"{side} LUT does not match configs/lut_manifest.json")
        result[side] = {**actual, "verified": True}
    return result


class CountingOTA:
    """Transparent counter around OTA evaluation for auditable categories."""

    def __init__(self, ota):
        self._ota = ota
        self.calls = 0
        self.successes = 0
        self.invalid = Counter()

    def __getattr__(self, name):
        return getattr(self._ota, name)

    def evaluate(self, *args, **kwargs):
        self.calls += 1
        try:
            value = self._ota.evaluate(*args, **kwargs)
        except Exception as exc:
            self.invalid[type(exc).__name__] += 1
            raise
        self.successes += 1
        return value


def _initial_population(rng, population: int, ideal_design: dict | None):
    bounds = np.asarray(config.DESIGN_BOUNDS_7, dtype=float)
    lo, hi = bounds[:, 0], bounds[:, 1]
    init = rng.uniform(lo, hi, size=(max(population, 5), 7))
    if ideal_design:
        base = np.asarray([ideal_design[n] for n in config.DESIGN_PARAM_NAMES],
                          dtype=float)
        # The ideal witness seeds only L1/gmid1/L3/gmid3/Itail.  L5/gmid5
        # still span their full frozen bounds; no request or bound is tuned.
        variants = ((0.18e-6, 25.0), (0.6e-6, 25.0),
                    (1.2e-6, 25.0), (0.6e-6, 20.0))
        for row, (l5, gmid5) in zip(init, variants):
            row[:] = (base[0], base[1], base[2], base[3], l5, gmid5,
                      base[4])
    return init


def _run_case(ota, name, specs, ideal_design, seeds, maxiter, population):
    specs = validate_finite_specs(specs)
    effective, notes = effective_constraint_limits(specs)
    cl = specs.get("CL_pF", 1.0) * 1e-12
    seed_runs = []
    best = None
    started = time.time()
    aggregate = Counter()
    optimizer_evals = 0
    for seed in seeds:
        counted = CountingOTA(ota)
        objective = make_objective(counted, specs, cl)
        init = _initial_population(np.random.default_rng(seed), population,
                                   ideal_design)
        t0 = time.time()
        result = differential_evolution(
            objective, config.DESIGN_BOUNDS_7, seed=seed, init=init,
            maxiter=maxiter, mutation=(0.5, 1.0), recombination=0.7,
            tol=1e-6, polish=True, workers=1, updating="immediate")
        runtime = time.time() - t0
        optimizer_evals += int(result.nfev)
        aggregate.update(counted.invalid)
        run = {
            "seed": seed, "objective": float(result.fun),
            "optimizer_evaluations": int(result.nfev),
            "counted_calls": counted.calls,
            "successful_calls": counted.successes,
            "invalid_categories": dict(sorted(counted.invalid.items())),
            "runtime_s": round(runtime, 3),
            "best_design": [float(v) for v in result.x],
            "optimizer_success": bool(result.success),
            "optimizer_message": str(result.message),
        }
        seed_runs.append(run)
        if best is None or result.fun < best.fun:
            best = result
    assert best is not None
    record = evaluate_design_finite(ota, best.x, specs)
    failed = [row for row in record.get("constraints", [])
              if not row["passed"]]
    if record["verdict"]:
        status = "verified_feasible"
    elif record.get("invalid_reason"):
        status = "numerical_or_contract_rejection"
    else:
        status = "unresolved_within_declared_budget"
    return {
        "name": name, "status": status,
        "request_source": f"configs/test_cases/{name}.json",
        "request": specs, "effective_constraints": effective,
        "effective_constraint_notes": notes,
        "search": {
            "method": "scipy.differential_evolution",
            "bounds": [list(b) for b in config.DESIGN_BOUNDS_7],
            "parameter_names": list(config.DESIGN_PARAM_NAMES_7),
            "seeds": list(seeds), "maxiter_per_seed": maxiter,
            "population_per_seed": population, "polish": True,
            "optimizer_evaluations": optimizer_evals,
            "final_verification_evaluations": 1,
            "full_oracle_call_count": optimizer_evals + 1,
            "invalid_categories": dict(sorted(aggregate.items())),
            "seed_runs": seed_runs,
            "runtime_s": round(time.time() - started, 3),
        },
        "best_objective": float(best.fun),
        "failed_constraints": failed,
        "finite_record": record,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--lut-dir", default=ROOT / "tech_luts", type=Path)
    # Frozen before the campaign: a four-point real-LUT timing probe measured
    # 0.760 s total (about 0.19 s/evaluation).  One seed, 42 population
    # members, and 12 generations bounds the five-case campaign while still
    # exercising the full seven-dimensional global domain.
    parser.add_argument("--maxiter", type=int, default=12)
    parser.add_argument("--population", type=int, default=42)
    parser.add_argument("--seeds", default="0")
    parser.add_argument("--tests", default="all")
    args = parser.parse_args()
    if args.maxiter < 0 or args.population < 5:
        raise ValueError("maxiter must be >= 0 and population must be >= 5")
    seeds = tuple(int(value) for value in args.seeds.split(","))
    if not seeds:
        raise ValueError("at least one seed is required")
    args.out_dir.mkdir(parents=True, exist_ok=False)

    tests = sorted((ROOT / "configs/test_cases").glob("*.json"))
    if args.tests != "all":
        wanted = set(args.tests.split(","))
        tests = [path for path in tests if path.stem in wanted]
    ideal_path = ROOT / "evaluation_results/canonical/baseline_de_solved_records.json"
    ideal = json.loads(ideal_path.read_text()) if ideal_path.exists() else {}
    campaign = {
        "schema": "analog_ai-phase-f4-finite-baseline-v1",
        "noncanonical": True,
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "python": platform.python_version(), "numpy": np.__version__,
        "scipy": scipy_version,
        "frozen_saturation_floor_V": config.SAT_MARGIN_MIN_DEFAULT,
        "bounds_version": "DESIGN_BOUNDS_7@source_fingerprint",
        "source_fingerprint": {name: _sha(ROOT / name) for name in SOURCE_PATHS},
        "request_fingerprint": {path.name: _sha(path) for path in tests},
        "ideal_seed_evidence": {
            "path": str(ideal_path.relative_to(ROOT)), "sha256": _sha(ideal_path)
            if ideal_path.exists() else None,
            "purpose": "initialization only; finite hard verifier decides",
        },
        "lut_verification": verify_luts(args.lut_dir),
        "declared_budget": {"seeds": list(seeds), "maxiter_per_seed": args.maxiter,
                            "population_per_seed": args.population,
                            "polish": True},
        "cases": [],
    }
    manifest = args.out_dir / "f4_baseline.json"
    manifest.write_text(json.dumps(campaign, indent=2, allow_nan=False) + "\n")
    print("Loading verified real LUTs...", flush=True)
    dm, _ = load_engine(str(args.lut_dir), tail_device="finite", op_point="solved")
    ota = OTA5T(dm, vdd=config.VDD, tail_device="finite", op_point="solved")
    for path in tests:
        specs = json.loads(path.read_text())
        ideal_design = (ideal.get(path.stem) or {}).get("design")
        print(f"[{path.stem}] global search", flush=True)
        result = _run_case(ota, path.stem, specs, ideal_design, seeds,
                           args.maxiter, args.population)
        campaign["cases"].append(result)
        manifest.write_text(json.dumps(campaign, indent=2, allow_nan=False) + "\n")
        print(f"  {result['status']}: objective={result['best_objective']:.6g}, "
              f"calls={result['search']['full_oracle_call_count']}, "
              f"time={result['search']['runtime_s']:.1f}s", flush=True)
    campaign["summary"] = {
        "verified_feasible": sum(c["status"] == "verified_feasible"
                                 for c in campaign["cases"]),
        "total": len(campaign["cases"]),
        "all_verified": all(c["status"] == "verified_feasible"
                            for c in campaign["cases"]),
    }
    manifest.write_text(json.dumps(campaign, indent=2, allow_nan=False) + "\n")
    print(f"Evidence: {manifest}", flush=True)


if __name__ == "__main__":
    main()

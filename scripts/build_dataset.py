"""Phase 3 dataset builder: feasibility-labeled OTA design data.

Stages (each resumable via `state.json` + append-only Parquet shards, so an
interrupted run loses nothing — re-run the same command):

  sobol     Sobol sample of the design domain, evaluated at each CL of the
            grid (solved op point) -> design rows
  derive    derive feasible / near-boundary / infeasible requests from every
            structurally-passing design row (verifier-checked, no engine)
  polish    multi-start DE on a stratified selection of the feasible requests
            (one-to-many coverage; reuses the canonical Phase 4 baseline)
  certify   DE attempts on TARGET_RANGES-sampled requests; failures are
            labeled `unresolved_by_optimizer` (evidence, not proof)
  finalize  by-design-group splits, consolidated parquet files, manifest

Example (pilot):
  python scripts/build_dataset.py --stage all --n-sobol 10000 --n-polish 8 \
      --n-certify 4 --seed 0 --out-dir data/pilot
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analog_ai import config
from analog_ai.dataset import build, io, sampling, splits

DESIGN_CHUNK = 200        # designs per design-shard flush
REQUEST_CHUNK = 500       # request rows per request-shard flush


# --------------------------------------------------------------- state ----
def _state_path(out_dir):
    return os.path.join(out_dir, "state.json")


def load_state(out_dir, seed):
    if os.path.exists(_state_path(out_dir)):
        with open(_state_path(out_dir)) as f:
            return json.load(f)
    return {
        "build_id": f"ds_s{seed}_"
                    f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "design_next": 0, "request_next": 0,
        "sobol_done": 0, "derive_done": 0,
        "polish_done": 0, "certify_done": 0,
    }


def save_state(out_dir, state):
    with open(_state_path(out_dir), "w") as f:
        json.dump(state, f, indent=2)


def _specs_of_request_row(r):
    return {"Gain_min": r["req_Gain_min"], "GBW_min": r["req_GBW_min"],
            "CL_pF": r["req_CL_pF"], "Power_max": r["req_Power_max"]}


# --------------------------------------------------------------- stages ----
def stage_sobol(ota, args, state):
    X = sampling.sobol_designs(args.n_sobol, args.seed)
    chunk = []
    t0, i0 = time.time(), state["sobol_done"]
    for i in range(state["sobol_done"], args.n_sobol):
        for cl_pf in sampling.CL_GRID_PF:
            chunk.append(build.evaluate_design_row(
                ota, X[i], cl_pf, "sobol",
                f"d{state['design_next']:08d}", args.op_point,
                state["build_id"]))
            state["design_next"] += 1
        state["sobol_done"] = i + 1
        if len(chunk) >= DESIGN_CHUNK:
            io.append_rows(args.out_dir, "design", chunk)
            chunk = []
            save_state(args.out_dir, state)
        if (i + 1) % 25 == 0 or i + 1 == args.n_sobol:
            rate = (i + 1 - i0) / max(time.time() - t0, 1e-9)
            eta = (args.n_sobol - i - 1) / max(rate, 1e-9) / 60
            print(f"  [sobol] {i + 1}/{args.n_sobol} designs "
                  f"({rate:.1f} eval/s, ETA {eta:.0f} min)", flush=True)
    if chunk:
        io.append_rows(args.out_dir, "design", chunk)
    save_state(args.out_dir, state)


def stage_derive(args, state):
    design_rows = [r for r in io.rows_of(args.out_dir, "design")
                   if r["source"] == "sobol"]
    design_rows.sort(key=lambda r: r["row_id"])
    stats = build.dataset_stats(design_rows)
    chunk, flushed = [], 0
    n_valid = 0
    # row_id order is stable, so the state counter aligns across resumes
    for r in design_rows[state["derive_done"]:]:
        i = int(r["row_id"][1:])
        state["derive_done"] += 1
        if not r["valid"] or r["GBW"] != r["GBW"] or r["cl_pf"] not in stats:
            continue
        if not r["verdict"]:
            # DC-solvable but structurally failing (PM / saturation / width):
            # no relaxed request can make such a design pass, so it must not
            # source a "feasible" label. Kept as design-space coverage only.
            continue
        n_valid += 1
        rng = np.random.default_rng([args.seed, 1, i])
        feasible, near_b, infeasible = sampling.derive_requests(
            r, r["cl_pf"], stats, rng)
        for specs, label in ((feasible, "feasible"),
                             (near_b, "near_boundary"),
                             (infeasible, "beyond_sample_envelope")):
            chunk.append(build.request_row(
                r, specs, label, f"r{state['request_next']:08d}",
                "sobol", args.op_point, state["build_id"]))
            state["request_next"] += 1
        if len(chunk) >= REQUEST_CHUNK:
            io.append_rows(args.out_dir, "request", chunk)
            flushed += len(chunk)
            chunk = []
            save_state(args.out_dir, state)
    if chunk:
        io.append_rows(args.out_dir, "request", chunk)
        flushed += len(chunk)
    save_state(args.out_dir, state)
    print(f"  [derive] {n_valid} valid designs -> {flushed} request rows",
          flush=True)


def _stratified_pick(request_rows, n, seed):
    """One request per target-space region, round-robin, then repeat."""
    groups: dict[tuple, list] = {}
    for r in request_rows:
        groups.setdefault(splits.region_key_of_row(r), []).append(r)
    rng = np.random.default_rng([seed, 3])
    keys = sorted(groups)
    for k in keys:
        rng.shuffle(groups[k])
    picked, gi = [], 0
    while len(picked) < n and any(groups[k] for k in keys):
        k = keys[gi % len(keys)]
        if groups[k]:
            picked.append(groups[k].pop())
        gi += 1
    return picked


def stage_polish(ota, args, state):
    feasible = [r for r in io.rows_of(args.out_dir, "request")
                if r["source"] == "sobol" and r["label"] == "feasible"]
    picked = _stratified_pick(feasible, args.n_polish, args.seed)
    for j, req in enumerate(picked[state["polish_done"]:], start=state["polish_done"]):
        print(f"  [polish] {j + 1}/{len(picked)}: "
              f"Gain>={req['req_Gain_min']:.1f}dB "
              f"GBW>={req['req_GBW_min']/1e6:.1f}MHz "
              f"CL={req['req_CL_pF']:.2f}pF "
              f"P<={req['req_Power_max']*1e6:.0f}uW ...", flush=True)
        drow, rrow = build.polish_request(
            ota, _specs_of_request_row(req), seed=args.seed + 1000 + j,
            maxiter=args.maxiter, popsize=args.popsize,
            design_row_id=f"d{state['design_next']:08d}",
            request_row_id=f"r{state['request_next']:08d}",
            op_point=args.op_point, build_id=state["build_id"])
        state["design_next"] += 1
        state["request_next"] += 1
        state["polish_done"] = j + 1
        io.append_rows(args.out_dir, "design", [drow])
        io.append_rows(args.out_dir, "request", [rrow])
        save_state(args.out_dir, state)
        print(f"    -> {rrow['label']} (obj={rrow['de_objective']:.2e}, "
              f"{rrow['de_runtime_s']:.0f}s)", flush=True)


def stage_certify(ota, args, state):
    for j in range(state["certify_done"], args.n_certify):
        rng = np.random.default_rng([args.seed, 4, j])
        g_lo, g_hi = config.TARGET_RANGES["Gain_min"]
        p_lo, p_hi = config.TARGET_RANGES["Power_max"]
        specs = {
            "Gain_min": float(rng.uniform(g_lo, g_hi)),
            "GBW_min": float(10 ** rng.uniform(
                np.log10(config.TARGET_RANGES["GBW_min"][0]),
                np.log10(config.TARGET_RANGES["GBW_min"][1]))),
            "CL_pF": float(rng.uniform(*config.TARGET_RANGES["CL_pF"])),
            "Power_max": float(10 ** rng.uniform(np.log10(p_lo),
                                                 np.log10(p_hi))),
        }
        print(f"  [certify] {j + 1}/{args.n_certify}: "
              f"Gain>={specs['Gain_min']:.1f}dB "
              f"GBW>={specs['GBW_min']/1e6:.1f}MHz "
              f"CL={specs['CL_pF']:.2f}pF "
              f"P<={specs['Power_max']*1e6:.0f}uW ...", flush=True)
        drow, rrow = build.certify_request(
            ota, specs, seed=args.seed + 2000 + j,
            maxiter=args.cert_maxiter, popsize=15,
            design_row_id=f"d{state['design_next']:08d}",
            request_row_id=f"r{state['request_next']:08d}",
            op_point=args.op_point, build_id=state["build_id"])
        state["design_next"] += 1
        state["request_next"] += 1
        state["certify_done"] = j + 1
        io.append_rows(args.out_dir, "design", [drow])
        io.append_rows(args.out_dir, "request", [rrow])
        save_state(args.out_dir, state)
        print(f"    -> {rrow['label']} (worst_violation="
              f"{rrow['worst_violation']:.2f})", flush=True)


def _lut_hashes(lut_dir: str) -> dict:
    """SHA-256 of both LUTs, cached in configs/lut_manifest.json."""
    from analog_ai.loader import DEFAULT_LUT_DIR, NCH_FILENAME, PCH_FILENAME
    cache_path = os.path.join("configs", "lut_manifest.json")
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            cache = json.load(f)
    out = {}
    for key, fname in (("nch", NCH_FILENAME), ("pch", PCH_FILENAME)):
        p = os.path.join(lut_dir or DEFAULT_LUT_DIR, fname)
        if not os.path.exists(p):
            continue
        size = os.path.getsize(p)
        if cache.get(key, {}).get("sha256") and cache[key].get("bytes") == size:
            out[key] = cache[key]["sha256"]
            continue
        h = __import__("hashlib").sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        out[key] = h.hexdigest()
        cache[key] = {"file": fname, "bytes": size, "sha256": out[key]}
    os.makedirs("configs", exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)
    return out


def stage_finalize(args, state):
    request_rows = io.rows_of(args.out_dir, "request")
    split_map = splits.assign_splits_by_design(request_rows, args.seed)
    manifest = io.finalize(
        args.out_dir, seed=args.seed,
        config_summary={
            "n_sobol": args.n_sobol, "n_polish": args.n_polish,
            "n_certify": args.n_certify, "cl_grid_pf": sampling.CL_GRID_PF,
            "op_point": args.op_point, "maxiter": args.maxiter,
            "popsize": args.popsize, "cert_maxiter": args.cert_maxiter,
            "build_id": state["build_id"],
        },
        request_rows=request_rows, split_map=split_map,
        lut_hashes=_lut_hashes(args.lut_dir))
    c = manifest["counts"]
    print("\n=== dataset summary ===")
    print(f"design rows : {c['design_rows']} "
          f"({c['by_source_design']})")
    print(f"request rows: {c['request_rows']}")
    print(f"by label    : {c['by_label']}")
    print(f"by split    : {c['by_split']}")
    print(f"wrote {args.out_dir}/{{designs,requests}}.parquet + manifest.json")


# ----------------------------------------------------------------- main ----
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", default="all",
                    choices=["sobol", "derive", "polish", "certify",
                             "finalize", "all"])
    ap.add_argument("--out-dir", default=os.path.join("data", "pilot"))
    ap.add_argument("--lut-dir", default=None,
                    help="LUT directory for SHA-256 manifest (default: tech_luts)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--op-point", choices=["imposed", "solved"],
                    default="solved")
    ap.add_argument("--n-sobol", type=int, default=10000)
    ap.add_argument("--n-polish", type=int, default=8)
    ap.add_argument("--n-certify", type=int, default=4)
    ap.add_argument("--maxiter", type=int, default=30,
                    help="DE iterations for polish runs")
    ap.add_argument("--popsize", type=int, default=20)
    ap.add_argument("--cert-maxiter", type=int, default=20,
                    help="DE iterations for certification runs")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    state = load_state(args.out_dir, args.seed)

    order = ["sobol", "derive", "polish", "certify", "finalize"]
    stages = order if args.stage == "all" else [args.stage]
    needs_engine = any(s in stages for s in ("sobol", "polish", "certify"))
    ota = None
    if needs_engine:
        print("Loading LUTs (~5.5 GB)...", flush=True)
        from analog_ai.loader import load_engine
        _, ota = load_engine(op_point=args.op_point)

    for s in stages:
        print(f"[{s}] stage", flush=True)
        if s == "sobol":
            stage_sobol(ota, args, state)
        elif s == "derive":
            stage_derive(args, state)
        elif s == "polish":
            stage_polish(ota, args, state)
        elif s == "certify":
            stage_certify(ota, args, state)
        elif s == "finalize":
            stage_finalize(args, state)


if __name__ == "__main__":
    main()

"""Canonical evaluation of the five regression cases with FULL verdicts.

Replaces the archived `Test_Scripts/test_vN_model.py`: one evaluator, every
constraint reported (gain, GBW, power, PM, saturation, widths), programmatic
verdict, JSON records, and provenance.

Sources:
  --source constant   always outputs the median of the design bounds (the
                      "does the policy do anything at all?" baseline)
  --source optimizer  multi-start differential evolution + verification
  --source model      an SB3 PPO model zip (requires stable-baselines3)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analog_ai import config
from analog_ai.evaluation.evaluator import (RESULTS_TABLE_HEADER,
                                            evaluate_design,
                                            record_to_markdown_row)
from analog_ai.loader import load_engine


def run_constant(ota, specs):
    mid = np.array([np.mean(b) for b in config.DESIGN_BOUNDS])
    return evaluate_design(ota, mid, specs)


def run_optimizer(ota, specs, seed):
    from analog_ai.optimization import optimize_specs
    return optimize_specs(ota, specs, seed=seed, n_starts=1, maxiter=40, popsize=15)


def run_model(ota, model_path, specs):
    from stable_baselines3 import PPO  # deferred: heavy import

    from analog_ai.envs.sizing_env import OTA5tSizingEnv
    env = OTA5tSizingEnv(ota, max_steps=200)
    model = PPO.load(model_path)
    specs_env = dict(specs)
    specs_env["CL_pF"] = float(specs.get("CL_pF", 1.0))
    env.target_specs = specs_env
    env.current_step = 0
    env.state = env._sample_design()
    env.current_cost, perf = env._evaluate_state(env.state)
    obs = env._normalize_state(perf)
    for _ in range(200):
        action, _ = model.predict(obs, deterministic=True)
        obs, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
    return evaluate_design(ota, env.state, specs)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["constant", "optimizer", "model"],
                    default="constant")
    ap.add_argument("--op-point", choices=["imposed", "solved"], default="solved",
                    help="solved = KCL-solved bias from LUT curves (canonical); "
                         "imposed = legacy V9-V12-comparable semantics")
    ap.add_argument("--model", default=os.path.join("models",
                                                    "universal_ppo_agent_65nm_v12.zip"))
    ap.add_argument("--tests-dir", default=os.path.join("configs", "test_cases"))
    ap.add_argument("--out-dir", default=os.path.join("evaluation_results", "canonical"))
    ap.add_argument("--tag", default=None)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    tag = args.tag or f"{args.source}_{args.op_point}"

    print("Loading LUTs (~5.5 GB)...", flush=True)
    _, ota = load_engine(op_point=args.op_point)

    os.makedirs(args.out_dir, exist_ok=True)
    test_files = sorted(f for f in os.listdir(args.tests_dir) if f.endswith(".json"))
    records, rows = {}, []
    for tf in test_files:
        with open(os.path.join(args.tests_dir, tf)) as f:
            specs = json.load(f)
        name = tf.replace(".json", "")
        print(f"[{name}] source={tag}...", flush=True)
        if args.source == "constant":
            rec = run_constant(ota, specs)
        elif args.source == "optimizer":
            rec = run_optimizer(ota, specs, args.seed)
        else:
            rec = run_model(ota, args.model, specs)
        records[name] = rec
        rows.append(record_to_markdown_row(name, rec))
        print(f"  verdict={'PASS' if rec['verdict'] else 'FAIL'}", flush=True)

    md = [f"# Regression evaluation — source: {tag}\n", RESULTS_TABLE_HEADER, *rows, ""]
    out_md = os.path.join(args.out_dir, f"{tag}_results.md")
    with open(out_md, "w") as f:
        f.write("\n".join(md))
    out_json = os.path.join(args.out_dir, f"{tag}_records.json")
    with open(out_json, "w") as f:
        json.dump(records, f, indent=2, default=str)
    n_pass = sum(r["verdict"] for r in records.values())
    print(f"\n{n_pass}/{len(records)} PASS — wrote {out_md} and {out_json}")


if __name__ == "__main__":
    main()

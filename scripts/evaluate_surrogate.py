"""Phase 5 PoC evaluation: verified pass rates vs baselines on held-out data.

Stages (each resumable via incremental records):
  select   pick the champion seed by LUT-verified pass rate on a fixed
           validation subsample (loss never selects anything)
  test     held-out positive requests: model (raw + best-of-K),
           nearest-neighbor, constant median, oracle regret, worst
           violation, DE comparison on a subsample, DE fallback on
           failures, risk-head rejection metrics on held-out negatives,
           goal-sensitivity sweeps, and the five regression cases

Example:
  python scripts/evaluate_surrogate.py --stage all --n-eval 1500
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analog_ai.surrogate import data as sdata
from analog_ai.surrogate import evaluate as seval
from analog_ai.surrogate.train import load_checkpoint

DESIGN_NAMES = ("L1", "gmid1", "L3", "gmid3", "Itail")


def _specs_of(row):
    return {"Gain_min": row["req_Gain_min"], "GBW_min": row["req_GBW_min"],
            "CL_pF": row["req_CL_pF"], "Power_max": row["req_Power_max"]}


def _records_path(args):
    return os.path.join(args.out, f"{args.tag}_records.json")


def _load_records(args):
    p = _records_path(args)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def _save_records(args, records):
    with open(_records_path(args), "w") as f:
        json.dump(records, f, indent=2, default=str)


def stage_select(ota, args):
    ckpts = [os.path.join(args.ckpt_dir, f"seed{s}.pt")
             for s in args.select_seeds.split(",")]
    ckpts = [p for p in ckpts if os.path.exists(p)]
    requests, designs = sdata.load_dataset(args.data)
    print(f"[select] {len(ckpts)} checkpoints x {args.n_val} val requests",
          flush=True)
    sel = seval.select_champion(ota, ckpts, requests, designs,
                                n_val=args.n_val, seed=args.seed)
    with open(os.path.join(args.ckpt_dir, "champion.json"), "w") as f:
        json.dump(sel, f, indent=2)
    for p, r in sel["results"].items():
        print(f"  {os.path.basename(p)}: verified pass {r['pass_rate']:.3f} "
              f"(n={r['n']})", flush=True)
    print(f"champion: {sel['champion']}", flush=True)


def stage_test(ota, args):
    records = _load_records(args)
    requests, designs = sdata.load_dataset(args.data)
    champion_path = os.path.join(args.ckpt_dir, "champion.json")
    with open(champion_path) as f:
        champion = json.load(f)["champion"]
    ck = load_checkpoint(os.path.join(args.ckpt_dir,
                                      os.path.basename(champion)))
    meta = ck["meta"]
    lo, hi = np.array(meta["feat_lo"]), np.array(meta["feat_hi"])
    model = ck["proposal"]

    train_rows = [r for r in requests if r["split"] == "train"]
    test_pos = [r for r in requests if r["split"] == "test"
                and r["label"] in sdata.POSITIVE_LABELS]
    test_neg = [r for r in requests if r["split"] == "test"
                and r["label"] not in sdata.POSITIVE_LABELS
                and sdata.risk_label(r) is not None]

    # leakage guard: held-out design IDs must not appear in train
    tr_ids = {r["design_row_id"] for r in train_rows}
    te_ids = {r["design_row_id"] for r in test_pos}
    overlap = tr_ids & te_ids
    assert not overlap, f"split leakage: {len(overlap)} shared designs"

    rng = np.random.default_rng([args.seed, 21])
    pick = rng.choice(len(test_pos), size=min(args.n_eval, len(test_pos)),
                      replace=False)
    subset = [test_pos[i] for i in pick]
    print(f"[test] champion={os.path.basename(champion)}, "
          f"{len(subset)} held-out requests, {len(test_neg)} negatives",
          flush=True)

    const_row = None
    n_new, t0 = 0, time.time()
    for i, r in enumerate(subset):
        if r["row_id"] in records:
            continue
        specs = _specs_of(r)
        out = seval.eval_request(ota, model, specs, lo, hi)
        nn_row, nn_dist = seval.nn_lookup(specs, train_rows, lo, hi)
        if nn_row is not None:
            nn_design = designs[nn_row["design_row_id"]]
            nn_verify = seval._verify(ota,
                                      [nn_design[t] for t in DESIGN_NAMES],
                                      specs)
            nn_status = "verified" if nn_verify["verdict"] else "unresolved"
            nn_viol = nn_verify["worst_violation"]
        else:
            nn_status, nn_viol = "no_pool", None
        if const_row is None:
            const_row = seval._verify(ota, seval.constant_design(), specs)
        src = designs.get(r["design_row_id"], {})
        regret = (None if not src
                  else {"power": out["design_row"]["Power"]
                       - src["Power"],
                       "area": out["design_row"]["Area"]
                       - src["Area"]})
        records[r["row_id"]] = {
            "request": specs, "label": r["label"], "split": r["split"],
            "status": out["status"], "head": out["head"],
            "heads_pass": out["heads_pass"],
            "worst_violation": out["worst_violation"],
            "design": out["design"],
            "nn_status": nn_status, "nn_distance": nn_dist,
            "nn_violation": nn_viol,
            "constant_verdict": bool(const_row["verdict"]),
            "regret": regret, "n_oracle_evals": out["n_oracle_evals"],
        }
        n_new += 1
        if n_new % 25 == 0:
            _save_records(args, records)
            rate = n_new / (time.time() - t0)
            print(f"  {i + 1}/{len(subset)} ({rate:.1f} req/s)", flush=True)
    _save_records(args, records)

    # ---- risk head on held-out requests (no oracle cost) ----
    neg_x = [r for r in test_neg]
    pos_x = [r for r in test_pos if r["row_id"] in records]
    x_all = sdata.normalize(sdata.feature_matrix(neg_x + pos_x), lo, hi)
    y_all = np.concatenate([np.zeros(len(neg_x)), np.ones(len(pos_x))])
    records["_risk_metrics"] = seval.risk_metrics(ck["risk"], x_all, y_all)
    _save_records(args, records)
    print(f"  risk head: {records['_risk_metrics']}", flush=True)

    # ---- DE fallback on failures ----
    failures = [r for r in subset if records[r["row_id"]]["status"]
                == "unresolved"]
    for r in failures[: args.n_refine]:
        specs = _specs_of(r)
        ref = seval.refine(ota, specs, seed=args.seed,
                           maxiter=args.refine_maxiter)
        records[r["row_id"]]["status_after_fallback"] = (
            "fallback_verified" if ref["passed"] else "unresolved")
        records[r["row_id"]]["fallback"] = ref
        print(f"  fallback {specs}: {'PASS' if ref['passed'] else 'FAIL'} "
              f"({ref['runtime_s']:.0f}s)", flush=True)
        _save_records(args, records)

    # ---- DE comparison on the same requests ----
    de_idx = rng.choice(len(subset),
                        size=min(args.n_de_compare, len(subset)),
                        replace=False)
    for i in de_idx:
        r = subset[int(i)]
        key = "de_" + r["row_id"]
        if key in records:
            continue
        specs = _specs_of(r)
        ref = seval.refine(ota, specs, seed=args.seed + 500,
                           maxiter=args.refine_maxiter)
        records[key] = {"request": specs, "passed": ref["passed"],
                        "objective": ref["objective"],
                        "n_evals": ref["n_evals"],
                        "runtime_s": ref["runtime_s"]}
        print(f"  DE-compare {specs}: {'PASS' if ref['passed'] else 'FAIL'}",
              flush=True)
        _save_records(args, records)

    # ---- goal sensitivity (G4) ----
    mid = {"Gain_min": 30.0, "GBW_min": 1e8, "CL_pF": 1.0,
           "Power_max": 1e-4}
    records["_goal_sensitivity"] = seval.goal_sensitivity(
        ota, model, mid, lo, hi)
    _save_records(args, records)
    print("  goal-sensitivity recorded", flush=True)

    # ---- five regression cases (verified + fallback) ----
    cases_dir = os.path.join("configs", "test_cases")
    for tf in sorted(os.listdir(cases_dir)):
        name = tf.replace(".json", "")
        key = "case_" + name
        if key in records:
            continue
        with open(os.path.join(cases_dir, tf)) as f:
            specs = json.load(f)
        out = seval.eval_request(ota, model, specs, lo, hi)
        entry = {"status": out["status"],
                 "worst_violation": out["worst_violation"],
                 "design": out["design"]}
        if out["status"] == "unresolved":
            ref = seval.refine(ota, specs, seed=args.seed, maxiter=30,
                               popsize=20)
            entry["status_after_fallback"] = (
                "fallback_verified" if ref["passed"] else "unresolved")
            entry["fallback"] = ref
        records[key] = entry
        print(f"  case {name}: "
              f"{entry.get('status_after_fallback', entry['status'])}",
              flush=True)
        _save_records(args, records)


def summarize(args):
    records = _load_records(args)
    rows = [v for k, v in records.items()
            if not k.startswith(("_", "de_", "case_"))]
    n = len(rows)
    if n == 0:
        print("no records yet")
        return
    def frac(pred):
        return sum(1 for r in rows if pred(r)) / n

    raw = frac(lambda r: r["status"] == "verified")
    bok = frac(lambda r: r["status"] in ("verified", "verified_best_of_k"))
    fb = frac(lambda r: r.get("status_after_fallback", r["status"])
              != "unresolved")
    nn = frac(lambda r: r["nn_status"] == "verified")
    worst = max((r["worst_violation"] or 0.0) for r in rows)
    evals = float(np.mean([r["n_oracle_evals"] for r in rows]))
    de_rows = [v for k, v in records.items() if k.startswith("de_")]
    de_pass = (sum(1 for r in de_rows if r["passed"]) / len(de_rows)
               if de_rows else None)
    cases = {k[5:]: v for k, v in records.items() if k.startswith("case_")}
    gs = records.get("_goal_sensitivity", {})
    lines = [
        f"# Surrogate PoC evaluation ({args.tag})", "",
        f"Held-out verified requests: n={n}", "",
        "| Metric | Value |", "|---|---|",
        f"| Raw head-0 pass rate | {raw:.3f} |",
        f"| Best-of-K pass rate | {bok:.3f} |",
        f"| After DE fallback | {fb:.3f} |",
        f"| Nearest-neighbor baseline pass | {nn:.3f} |",
        f"| Constant-median pass | "
        f"{rows[0]['constant_verdict'] if rows else None} |",
        f"| Worst normalized violation | {worst:.3f} |",
        f"| Avg oracle evals/request | {evals:.1f} |",
        f"| DE pass rate (same requests, n={len(de_rows)}) | {de_pass} |",
        "", "## Five regression cases", "",
        "| Case | Status |", "|---|---|",
    ]
    for name, v in sorted(cases.items()):
        lines.append(f"| {name} | "
                     f"{v.get('status_after_fallback', v['status'])} |")
    lines += ["", "## Goal sensitivity (G4)", ""]
    for dim, o in gs.items():
        lines.append(f"- {dim}: moves={o['moves']}, "
                     f"verified along sweep={sum(o['verdicts'])}/"
                     f"{len(o['verdicts'])}")
    out_md = os.path.join(args.out, f"{args.tag}_summary.md")
    with open(out_md, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nwrote {out_md}")
    print(f"raw={raw:.3f} best-of-K={bok:.3f} fallback={fb:.3f} nn={nn:.3f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", default="all",
                    choices=["select", "test", "summarize", "all"])
    ap.add_argument("--data", default=os.path.join("data", "pilot"))
    ap.add_argument("--ckpt-dir",
                    default=os.path.join("models", "surrogate", "poc"))
    ap.add_argument("--out", default="evaluation_results/canonical")
    ap.add_argument("--tag", default="surrogate_poc")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--select-seeds", default="0,1,2")
    ap.add_argument("--n-val", type=int, default=200)
    ap.add_argument("--n-eval", type=int, default=1500)
    ap.add_argument("--n-refine", type=int, default=5)
    ap.add_argument("--n-de-compare", type=int, default=10)
    ap.add_argument("--refine-maxiter", type=int, default=20)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    stages = (["select", "test", "summarize"] if args.stage == "all"
              else [args.stage])
    for s in stages:
        if s == "summarize":
            summarize(args)
            continue
        print("Loading LUTs (~5.5 GB)...", flush=True)
        from analog_ai.loader import load_engine
        _, ota = load_engine(op_point="solved")
        if s == "select":
            stage_select(ota, args)
        elif s == "test":
            stage_test(ota, args)


if __name__ == "__main__":
    main()

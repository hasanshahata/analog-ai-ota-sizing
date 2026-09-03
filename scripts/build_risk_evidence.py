"""Phase E: certified boundary evidence + separated risk-head report.

Three phases, resumable via incremental records:

  1. cheap ladder  - proposal + verify + local refinement (no global DE) on
                     two boundary cohorts (B1 independent corners, B2
                     boundary straddlers); records risk-head probabilities
  2. certify       - the first `--global-cap` cheap-ladder failures get a
                     global-DE run at a declared budget; evidence classes
                     are assigned ONLY here (requests never sent to global
                     DE stay uncertified and are excluded from cohort-B
                     metrics, counted as awaiting certification)
  3. report        - synthetic-OOD vs certified-boundary metrics, side by
                     side, with the verbatim caveat that
                     `unresolved_after_budget` is not infeasibility

  python scripts/build_risk_evidence.py            # full run
  python scripts/build_risk_evidence.py --limit 10 # smoke
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
from analog_ai.surrogate import risk_evidence as re_
from analog_ai.surrogate.evaluate import eval_request_staged, refine
from analog_ai.surrogate.train import load_checkpoint

DEFAULT_OUT = os.path.join("evaluation_results", "canonical",
                           "risk_evidence_records.json")


def _stage_runtime(rec: dict) -> float:
    return round(sum(s.get("runtime_s", 0) for s in rec.get("stages", [])), 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=os.path.join("data", "pilot"))
    ap.add_argument("--ckpt-dir", default=os.path.join("models", "surrogate",
                                                       "poc"))
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--n-corners", type=int, default=60)
    ap.add_argument("--n-straddle", type=int, default=60)
    ap.add_argument("--global-cap", type=int, default=25)
    ap.add_argument("--global-maxiter", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None,
                    help="cap total requests (smoke testing)")
    args = ap.parse_args()

    with open(os.path.join(args.ckpt_dir, "champion.json")) as f:
        champion = json.load(f)["champion"]
    ck = load_checkpoint(os.path.join(args.ckpt_dir,
                                      os.path.basename(champion)))
    lo = np.array(ck["meta"]["feat_lo"])
    hi = np.array(ck["meta"]["feat_hi"])
    model, risk = ck["proposal"], ck["risk"]

    requests, designs = sdata.load_dataset(args.data)
    test_neg = [r for r in requests if r["split"] == "test"
                and r["label"] == "beyond_sample_envelope"]
    if args.limit:
        test_neg = test_neg[:args.limit]

    done: dict = {}
    if os.path.exists(args.out):
        with open(args.out) as f:
            done = json.load(f)

    # ---- cohort S: synthetic OOD (no oracle cost) ----
    s_x = sdata.normalize(sdata.feature_matrix(test_neg), lo, hi)
    import torch
    with torch.no_grad():
        logits = risk(torch.as_tensor(s_x, dtype=torch.float32))
        # RiskNet label 1 means achievable-looking.  Reports use failure
        # probability, so reverse it here (same contract as
        # risk_evidence.failure_probability()).
        s_probs = (1.0 - torch.sigmoid(logits)).cpu().numpy()
    print(f"[cohort S] {len(test_neg)} synthetic-OOD rows scored", flush=True)

    # ---- boundary cohorts B1/B2 ----
    b1 = re_.sample_independent_corners(args.n_corners, args.seed)
    b2 = re_.sample_boundary_straddle(args.n_straddle, args.seed,
                                      list(designs.values()))
    if args.limit:
        b1, b2 = b1[:args.limit], b2[:args.limit]
    queue = ([("independent_corners", i, s) for i, s in enumerate(b1)]
             + [("boundary_straddle", i, s) for i, s in enumerate(b2)])
    print(f"[cohort B] {len(queue)} boundary requests "
          f"(corners {len(b1)}, straddle {len(b2)})", flush=True)

    from analog_ai.loader import load_engine
    print("Loading LUTs (~5.5 GB)...", flush=True)
    _, ota = load_engine(op_point="solved")

    t0 = time.time()
    n_new = 0
    for ci, (cohort, i, specs) in enumerate(queue):
        key = f"{cohort}-{i:04d}"
        if key in done and done[key].get("evidence_class") is not None:
            continue
        rec = done.setdefault(key, {"cohort": cohort, "request": specs})
        if "pipeline_status" not in rec:
            out = eval_request_staged(ota, model, specs, lo, hi,
                                      local=True, global_fallback=False,
                                      seed=args.seed)
            rec.update({
                "failure_probability": re_.failure_probability(
                    risk, specs, lo, hi),
                "pipeline_status": out["status"],
                "heads_invalid": out.get("heads_invalid"),
                "design": out["design"],
                "worst_violation": out["worst_violation"],
                "n_oracle_evals": out["n_oracle_evals"],
                "stage_runtime_s": _stage_runtime(out),
            })
        if rec["pipeline_status"] != "unresolved":
            rec["evidence_class"] = "verified_feasible"
        else:
            # certification pass (global DE at a declared budget) - the only
            # path to a negative-evidence class. Requests past the cap stay
            # evidence_class=None (awaiting certification) and are excluded
            # from cohort metrics rather than being mislabeled.
            n_global = sum(1 for v in done.values()
                           if v.get("global_de") is not None)
            if n_global < args.global_cap:
                ref = refine(ota, specs, seed=args.seed + 900 + i,
                             maxiter=args.global_maxiter)
                rec["global_de"] = {"passed": ref["passed"],
                                    "objective": ref["objective"],
                                    "n_evals": ref["n_evals"],
                                    "runtime_s": ref["runtime_s"],
                                    "budget_maxiter": args.global_maxiter}
                rec["n_oracle_evals"] = rec.get("n_oracle_evals",
                                                0) + ref["n_evals"]
                rec["evidence_class"] = ("verified_feasible"
                                         if ref["passed"]
                                         else "unresolved_after_budget")
            else:
                rec["evidence_class"] = None  # awaiting certification
        done[key] = rec
        n_new += 1
        with open(args.out, "w") as f:
            json.dump(done, f, indent=2, default=str)
        if n_new % 5 == 0 or n_new == len(queue):
            rate = n_new / max(time.time() - t0, 1e-9)
            print(f"  [{ci + 1}/{len(queue)}] {key}: "
                  f"{rec.get('evidence_class')} "
                  f"({rate:.2f} req/s)", flush=True)

    # ---- separated cohorts ----
    def cert_rows():
        rows = []
        for key, v in done.items():
            if v.get("evidence_class") in ("verified_feasible",
                                           "unresolved_after_budget"):
                # Backward-compatible resume: convert any records written by
                # the interrupted pre-fix script, whose value was actually
                # achievability probability.
                p_fail = (v.get("failure_probability")
                          if "failure_probability" in v
                          else 1.0 - v["risk_probability"])
                rows.append((p_fail,
                             1.0 if v["evidence_class"]
                             == "unresolved_after_budget" else 0.0,
                             v["pipeline_status"] != "unresolved"))
        return rows

    b_rows = cert_rows()
    if b_rows:
        b_arr = np.array(b_rows, dtype=float)
        b_metrics = re_.cohort_metrics(b_arr[:, 1], b_arr[:, 0],
                                       b_arr[:, 2])
    else:
        b_metrics = {"n": 0}
    s_metrics = re_.cohort_metrics(np.ones(len(s_probs)),
                                   np.asarray(s_probs, dtype=float))
    s_metrics["note"] = ("synthetic negatives: detection of the dataset's "
                         "negative-generation rules, not feasibility")

    awaiting = sum(1 for v in done.values()
                   if v.get("evidence_class") is None)
    report = {
        "champion": os.path.basename(champion),
        "synthetic_ood": s_metrics,
        "certified_boundary": b_metrics,
        "awaiting_certification": awaiting,
        "global_de_runs": sum(1 for v in done.values()
                              if v.get("global_de") is not None),
        "caveat": "unresolved_after_budget is evidence of optimizer "
                  "difficulty within the declared budget, NOT infeasibility",
    }
    out_json = args.out.replace("_records.json", "_report.json")
    out_md = args.out.replace("_records.json", "_report.md")
    re_.write_report(
        {"synthetic_ood": s_metrics, "certified_boundary": b_metrics},
        out_json, out_md,
        metadata={
            "champion": os.path.basename(champion),
            "awaiting_certification": awaiting,
            "global_de_runs": report["global_de_runs"],
            "global_maxiter": args.global_maxiter,
            "global_cap": args.global_cap,
            "seed": args.seed,
            "caveat": report["caveat"],
        })
    with open(args.out, "w") as f:
        json.dump(done, f, indent=2, default=str)
    print(f"\ncertified: {report['certified_boundary']['n']} "
          f"(failures {report['certified_boundary']['failures']}), "
          f"awaiting certification: {awaiting}")
    print(f"wrote {out_md}")


if __name__ == "__main__":
    main()

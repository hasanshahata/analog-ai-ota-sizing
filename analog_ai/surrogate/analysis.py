"""Phase B failure analysis: a taxonomy of unresolved surrogate requests.

For every unresolved held-out request this module re-proposes the champion's
K heads, verifies each under the full request (canonical verifier), and
records the complete residual vector - so the dominant failed constraint is
measured, not guessed. Everything else (distance to training support,
target-space region, candidate/source design distance) is computed from the
stored dataset. No result here is an oracle claim: failures are categorized,
not certified infeasible.
"""

from __future__ import annotations

import numpy as np

from ..dataset import splits as ds_splits
from . import data as sdata
from .evaluate import _verify, propose
from .train import load_checkpoint


def _dominant_constraint(residuals: dict) -> tuple[str, float]:
    active = {k: v for k, v in residuals.items() if v is not None}
    if not active:
        return "invalid_evaluation", float("nan")
    name = max(active, key=lambda k: active[k])
    return name.removeprefix("r_"), float(active[name])


def analyze_unresolved(ota, ckpt_path: str, records: dict,
                       requests: list[dict], designs: dict,
                       device: str = "cpu") -> list[dict]:
    """Re-evaluate every unresolved request; return the failure taxonomy."""
    ck = load_checkpoint(ckpt_path, device)
    meta = ck["meta"]
    lo, hi = np.array(meta["feat_lo"]), np.array(meta["feat_hi"])
    model = ck["proposal"]

    from .. import config
    d_lo = np.array([b[0] for b in config.DESIGN_BOUNDS])
    d_hi = np.array([b[1] for b in config.DESIGN_BOUNDS])
    train_pos = [r for r in requests if r["split"] == "train"
                 and r["label"] in sdata.POSITIVE_LABELS]
    x_train = sdata.normalize(sdata.feature_matrix(train_pos), lo, hi)

    req_by_id = {r["row_id"]: r for r in requests}
    failures = []
    from ..dataset import build as ds_build
    for key, rec in records.items():
        if key.startswith(("_", "de_", "case_")):
            continue
        if rec["status"] != "unresolved":
            continue
        specs = rec["request"]
        head_designs = propose(model, specs, lo, hi, device)
        head_results = []
        for d in head_designs:
            drow = _verify(ota, d, specs)
            rrow = ds_build.request_row(drow, specs, "feasible", "an",
                                        "surrogate", "solved", "analysis")
            res = {c: rrow[f"r_{c}"] for c in
                   ("Gain_min", "GBW_min", "Power_max", "PM_min",
                    "Sat_margin_min", "W_nmos_max", "W_pmos_max",
                    "L_domain")}
            head_results.append({
                "verdict": bool(rrow["verdict"]),
                "worst_violation": rrow["worst_violation"],
                "residuals": res,
                "invalid": not drow["valid"],
                "invalid_reason": drow["invalid_reason"],
            })
        ranked = sorted(range(len(head_results)),
                        key=lambda i: (not head_results[i]["verdict"],
                                       head_results[i]["worst_violation"]))
        b = ranked[0]
        dominant, dom_val = _dominant_constraint(
            head_results[b]["residuals"])
        q = sdata.normalize(sdata.feature_matrix([{
            "req_Gain_min": specs["Gain_min"],
            "req_GBW_min": specs["GBW_min"],
            "req_CL_pF": specs["CL_pF"],
            "req_Power_max": specs["Power_max"]}]), lo, hi)[0]
        nn_dist = float(np.min(np.linalg.norm(x_train - q[None, :], axis=1)))
        region = ds_splits.coarse_region(specs["Gain_min"], specs["GBW_min"],
                                         specs["CL_pF"], specs["Power_max"])
        src = designs.get(req_by_id[key]["design_row_id"])             if key in req_by_id else None
        u_all = (np.array(head_designs) - d_lo) / (d_hi - d_lo)
        if src is not None:
            src_u = (np.array([src[t] for t in
                               ("L1", "gmid1", "L3", "gmid3", "Itail")])
                     - d_lo) / (d_hi - d_lo)
            src_dist = float(np.linalg.norm(u_all[ranked[0]] - src_u))
        else:
            src_dist = None
        diffs = [np.linalg.norm(u_all[i] - u_all[j])
                 for i in range(len(u_all)) for j in range(i + 1, len(u_all))]
        failures.append({
            "row_id": key,
            "request": specs,
            "dominant_constraint": dominant,
            "dominant_residual": dom_val,
            "best_head": int(b),
            "n_heads_passing": sum(h["verdict"] for h in head_results),
            "all_heads_invalid": all(h["invalid"] for h in head_results),
            "worst_violation_best": head_results[b]["worst_violation"],
            "residuals_best": head_results[b]["residuals"],
            "nn_train_distance": nn_dist,
            "nn_record_distance": rec.get("nn_distance"),
            "candidate_source_distance": src_dist,
            "mean_head_distance": float(np.mean(diffs)),
            "region": list(region),
        })
    return failures


# ------------------------------------------------------------- grouping ----
def _bin(v, edges, labels):
    for e, lab in zip(edges, labels):
        if v < e:
            return lab
    return labels[-1]


def group_tables(failures: list[dict]) -> dict:
    from collections import Counter
    tables = {}

    def tally(name, keyfn):
        c = Counter(keyfn(f) for f in failures)
        tables[name] = dict(sorted(c.items(), key=lambda kv: -kv[1]))

    tally("dominant_constraint", lambda f: f["dominant_constraint"])
    tally("gain_bin", lambda f: _bin(f["request"]["Gain_min"],
                                     (25, 30, 35, 40),
                                     ("<25dB", "25-30dB", "30-35dB",
                                      "35-40dB", ">=40dB")))
    tally("gbw_bin", lambda f: _bin(f["request"]["GBW_min"] / 1e6,
                                    (20, 50, 100, 200, 400),
                                    ("<20MHz", "20-50MHz", "50-100MHz",
                                     "100-200MHz", "200-400MHz",
                                     ">=400MHz")))
    tally("cl_bin", lambda f: _bin(f["request"]["CL_pF"],
                                   (0.5, 2.0, 4.0),
                                   ("<0.5pF", "0.5-2pF", "2-4pF", ">=4pF")))
    tally("power_bin", lambda f: _bin(f["request"]["Power_max"] * 1e6,
                                      (50, 150, 300),
                                      ("<50uW", "50-150uW", "150-300uW",
                                       ">=300uW")))
    near = [f for f in failures if f["nn_train_distance"] < 0.05]
    tables["within_train_support"] = len(near)
    tables["outside_train_support"] = len(failures) - len(near)
    tables["all_heads_invalid"] = sum(1 for f in failures
                                      if f["all_heads_invalid"])
    tables["selection_failure"] = sum(1 for f in failures
                                      if f["n_heads_passing"] > 0)
    tables["mean_head_distance_median"] = float(np.median(
        [f["mean_head_distance"] for f in failures]))
    return tables


def write_report(failures: list[dict], tables: dict, out_json: str,
                 out_md: str) -> None:
    import json

    with open(out_json, "w") as f:
        json.dump({"n_failures": len(failures), "tables": tables,
                   "failures": failures}, f, indent=2, default=str)
    lines = ["# Surrogate failure taxonomy (Phase B)", "",
             f"Unresolved requests analyzed: **{len(failures)}**", ""]
    for section in ("dominant_constraint", "gain_bin", "gbw_bin", "cl_bin",
                    "power_bin"):
        lines += [f"## By {section.replace('_', ' ')}", "",
                  "| Category | Failures |", "|---|---|"]
        for k, v in tables[section].items():
            lines.append(f"| {k} | {v} |")
        lines.append("")
    lines += [
        "## Support and structure", "",
        f"- within train support (nn dist < 0.05): "
        f"{tables['within_train_support']}",
        f"- outside train support: {tables['outside_train_support']}",
        f"- all heads evaluate invalid: {tables['all_heads_invalid']}",
        f"- at least one head passes hard verify (selection failure): "
        f"{tables['selection_failure']}",
        f"- median pairwise head distance: "
        f"{tables['mean_head_distance_median']:.3f}", ""]
    with open(out_md, "w") as f:
        f.write("\n".join(lines) + "\n")

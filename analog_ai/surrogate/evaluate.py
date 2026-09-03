"""Verified evaluation of proposal models (Phase 5; gates G3/G4/G6).

The hard-constraint verifier is the only acceptance authority: statuses are
  verified             - the model's primary (head 0) design passes
  verified_best_of_k   - another head passes and was selected by residuals
  fallback_verified    - DE refinement found a passing design
  unresolved           - nothing passed (reported, never hidden)
Baselines (nearest-neighbor retrieval, constant median) and the DE optimizer
are run on exactly the same requests.
"""

from __future__ import annotations

import numpy as np
import torch

from .. import config
from ..dataset.build import evaluate_design_row
from ..optimization import optimize_specs
from . import data as sdata
from .model import ProposalNet

OP_POINT = "solved"


def spec_to_features(specs: dict) -> np.ndarray:
    row = {"req_Gain_min": specs.get("Gain_min", 20.0),
           "req_GBW_min": specs.get("GBW_min", 50e6),
           "req_CL_pF": specs.get("CL_pF", 1.0),
           "req_Power_max": specs.get("Power_max", 400e-6)}
    return sdata.feature_matrix([row])[0]


def _features_to_specs(feat: np.ndarray) -> dict:
    return {"Gain_min": float(feat[0]),
            "GBW_min": float(10.0 ** feat[1]),
            "CL_pF": float(10.0 ** feat[2]),
            "Power_max": float(10.0 ** feat[3])}


def normalize_one(specs: dict, feat_lo, feat_hi) -> np.ndarray:
    return sdata.normalize(spec_to_features(specs)[None, :],
                           feat_lo, feat_hi)[0]


def propose(model: ProposalNet, specs: dict, feat_lo, feat_hi,
            device: str = "cpu") -> np.ndarray:
    """K physical designs for one request, [K, 5]."""
    x = np.clip(normalize_one(specs, feat_lo, feat_hi), 0.0, 1.0)
    with torch.no_grad():
        u = model(torch.as_tensor(x, dtype=torch.float32,
                                  device=device).unsqueeze(0))
    u = u.squeeze(0).cpu().numpy()
    return sdata.denormalize_designs(u)


def _verify(ota, design, specs) -> dict:
    """Evaluate one candidate under the FULL request: verdict + residuals
    come from the canonical hard verifier (via the stored-row path), metrics
    stay flat on the returned row."""
    drow = evaluate_design_row(ota, design, float(specs.get("CL_pF", 1.0)),
                               "surrogate", "eval", OP_POINT, "eval")
    if not drow["valid"]:
        drow["worst_violation"] = float("inf")
        return drow
    from ..dataset import build as ds_build
    rrow = ds_build.request_row(drow, specs, "feasible", "eval_r",
                                "surrogate", OP_POINT, "eval")
    drow["verdict"] = rrow["verdict"]
    drow["worst_violation"] = rrow["worst_violation"]
    return drow


def eval_request(ota, model: ProposalNet, specs: dict,
                 feat_lo, feat_hi, device: str = "cpu") -> dict:
    """Propose K designs, verify all, pick by (pass, then min violation)."""
    designs = propose(model, specs, feat_lo, feat_hi, device)
    recs = [_verify(ota, d, specs) for d in designs]

    def _viol(r):
        return np.inf if r["worst_violation"] is None \
            else r["worst_violation"]

    order = sorted(range(len(recs)),
                   key=lambda i: (not recs[i]["verdict"], _viol(recs[i])))
    best = order[0]
    raw_pass = bool(recs[0]["verdict"])
    bok_pass = bool(recs[best]["verdict"])
    status = ("verified" if raw_pass else
              "verified_best_of_k" if bok_pass else "unresolved")
    return {
        "status": status,
        "design": designs[best].tolist(),
        "head": int(best),
        "heads_pass": [bool(r["verdict"]) for r in recs],
        "worst_violation": float(_viol(recs[best]))
        if np.isfinite(_viol(recs[best])) else None,
        "design_row": recs[best],
        "n_oracle_evals": len(recs),
    }


def nn_lookup(specs: dict, train_rows: list[dict],
              feat_lo, feat_hi) -> tuple[dict | None, float]:
    """Nearest train-split positive request in normalized target space."""
    pool = [r for r in train_rows if r["label"] in sdata.POSITIVE_LABELS]
    if not pool:
        return None, np.inf
    q = normalize_one(specs, feat_lo, feat_hi)
    x = sdata.normalize(sdata.feature_matrix(pool), feat_lo, feat_hi)
    i = int(np.argmin(np.linalg.norm(x - q[None, :], axis=1)))
    return pool[i], float(np.linalg.norm(x[i] - q))


def constant_design() -> np.ndarray:
    """Median-of-bounds design (the 'does anything at all work' baseline)."""
    return np.array([np.mean(b) for b in config.DESIGN_BOUNDS])


def refine(ota, specs: dict, seed: int = 0, maxiter: int = 20,
           popsize: int = 15) -> dict:
    """DE fallback on the same request (canonical Phase 4 objective)."""
    rec = optimize_specs(ota, specs, seed=seed, maxiter=maxiter,
                         popsize=popsize, n_starts=1)
    return {"passed": bool(rec["verdict"]),
            "objective": rec["baseline"]["objective"],
            "n_evals": rec["baseline"]["n_evals"],
            "runtime_s": rec["baseline"]["runtime_s"],
            "design": [rec["design"][n] for n in
                       ("L1", "gmid1", "L3", "gmid3", "Itail")]}


def select_champion(ota, ckpt_paths: list[str], requests: list[dict],
                    designs: dict, n_val: int = 300, device: str = "cpu",
                    seed: int = 0) -> dict:
    """Pick the seed with the best verified best-of-K pass rate on a fixed
    validation subsample (the plan requires verified selection, not loss)."""
    from .train import load_checkpoint
    rng = np.random.default_rng([seed, 11])
    val_rows = [r for r in requests if r["split"] == "val"
                and r["label"] in sdata.POSITIVE_LABELS
                and designs.get(r["design_row_id"], {}).get("valid")]
    idx = rng.choice(len(val_rows), size=min(n_val, len(val_rows)),
                     replace=False) if val_rows else []
    subset = [val_rows[i] for i in idx]
    results = {}
    for path in ckpt_paths:
        ck = load_checkpoint(path, device)
        meta = ck["meta"]
        lo, hi = np.array(meta["feat_lo"]), np.array(meta["feat_hi"])
        n_pass = 0
        for r in subset:
            specs = {"Gain_min": r["req_Gain_min"],
                     "GBW_min": r["req_GBW_min"],
                     "CL_pF": r["req_CL_pF"],
                     "Power_max": r["req_Power_max"]}
            out = eval_request(ota, ck["proposal"], specs, lo, hi, device)
            n_pass += out["status"] in ("verified", "verified_best_of_k")
        results[path] = {"pass_rate": n_pass / max(len(subset), 1),
                         "n": len(subset)}
    best_path = max(results, key=lambda p: results[p]["pass_rate"])
    return {"champion": best_path, "results": results}


def goal_sensitivity(ota, model: ProposalNet, specs: dict,
                     feat_lo, feat_hi, steps: int = 5,
                     device: str = "cpu") -> dict:
    """Sweep each request dimension across its normalized range with the
    others fixed (G4): report movement, physical trend, verified verdicts."""
    base = spec_to_features(specs)
    out = {}
    for j, name in enumerate(sdata.FEATURES):
        grid = np.linspace(feat_lo[j], feat_hi[j], steps)
        designs, verdicts, physical = [], [], []
        for v in grid:
            feat = base.copy()
            feat[j] = v
            specs_v = _features_to_specs(feat)
            d = propose(model, specs_v, feat_lo, feat_hi, device)[0]
            designs.append(d.tolist())
            physical.append(float(feat[j]))
            verdicts.append(bool(_verify(ota, d, specs_v)["verdict"]))
        arr = np.array(designs)
        out[name] = {
            "sweep_physical": physical, "designs": designs,
            "verdicts": verdicts,
            "moves": bool(np.ptp(arr, axis=0).max() > 0),
            "head0_movement": np.ptp(arr, axis=0).tolist(),
        }
    return out


def risk_metrics(risk_model, x_test: np.ndarray, y_test: np.ndarray,
                 device: str = "cpu") -> dict:
    """Precision/recall of the OOD head at the 0.5 threshold."""
    if len(y_test) == 0:
        return {"n": 0}
    with torch.no_grad():
        logits = risk_model(torch.as_tensor(x_test, dtype=torch.float32,
                                            device=device))
    pred = (logits.cpu().numpy() > 0.0).astype(float)
    tp = float(((pred == 0) & (y_test == 0)).sum())
    fp = float(((pred == 0) & (y_test == 1)).sum())
    fn = float(((pred == 1) & (y_test == 0)).sum())
    precision = tp / max(tp + fp, 1e-9)   # of flagged-negative, how many are
    recall = tp / max(tp + fn, 1e-9)      # of true negatives, how many flagged
    return {"n": int(len(y_test)), "neg_precision": precision,
            "neg_recall": recall,
            "accuracy": float((pred == y_test).mean())}


def eval_request_staged(ota, model, specs: dict, feat_lo, feat_hi,
                        device: str = "cpu", local: bool = True,
                        global_fallback: bool = True,
                        trust_fracs=(0.02, 0.05, 0.10),
                        n_heads_local: int = 2, global_maxiter: int = 20,
                        seed: int = 0) -> dict:
    """Full deployment ladder for one request (gate G6 statuses):

    verified -> verified_best_of_k -> local_refinement_verified ->
    global_fallback_verified -> unresolved. Each stage's oracle cost and
    provenance are recorded; the verifier alone decides every pass.
    """
    designs = propose(model, specs, feat_lo, feat_hi, device)
    rows = [_verify(ota, d, specs) for d in designs]

    def _viol(r):
        v = r.get("worst_violation")
        return np.inf if v is None else float(v)

    raw_pass = bool(rows[0]["verdict"])
    order = sorted(range(len(rows)),
                   key=lambda i: (not rows[i]["verdict"], _viol(rows[i])))
    bok_pass = bool(rows[order[0]]["verdict"])
    record = {
        "request": specs,
        "status": ("verified" if raw_pass else
                   "verified_best_of_k" if bok_pass else "unresolved"),
        "head": int(order[0]),
        "heads_pass": [bool(r["verdict"]) for r in rows],
        "heads_invalid": [not bool(r["valid"]) for r in rows],
        "design": designs[order[0]].tolist(),
        "worst_violation": _viol(rows[order[0]])
        if np.isfinite(_viol(rows[order[0]])) else None,
        "n_oracle_evals": len(rows),
        "stages": [],
    }
    if record["status"] != "unresolved":
        return record

    if local:
        from ..optimization.local_refine import local_refine
        candidates = [designs[i] for i in order]
        lr = local_refine(ota, specs, candidates, trust_fracs=trust_fracs,
                          n_heads=n_heads_local, verifier=_verify)
        record["n_oracle_evals"] += lr["n_evals"]
        record["stages"].append({
            "stage": "local_refinement", "status": lr["status"],
            "head": lr["head"], "trust_frac": lr["trust_frac"],
            "n_evals": lr["n_evals"], "runtime_s": lr["runtime_s"],
            "stages": lr["stages"]})
        if lr["status"] == "local_refinement_verified":
            record["status"] = "local_refinement_verified"
            record["design"] = lr["design"]
            record["worst_violation"] = 0.0
            record["refined_head"] = lr["head"]
            return record

    if global_fallback:
        ref = refine(ota, specs, seed=seed, maxiter=global_maxiter)
        record["n_oracle_evals"] += ref["n_evals"]
        record["stages"].append({
            "stage": "global_fallback", "passed": ref["passed"],
            "n_evals": ref["n_evals"], "runtime_s": ref["runtime_s"],
            "objective": ref["objective"]})
        if ref["passed"]:
            record["status"] = "global_fallback_verified"
            record["design"] = [ref["design"][n] for n in
                                ("L1", "gmid1", "L3", "gmid3", "Itail")]
            record["worst_violation"] = 0.0
    return record

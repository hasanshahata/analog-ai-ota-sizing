"""Phase E: real risk-head evidence from optimizer-certified boundary cases.

The risk head's 99.97% accuracy on synthetic negatives measures how well it
learned the dataset's negative-generation rules (points pushed far beyond
the observed envelope), not feasibility detection. This module builds the
missing evidence:

- two boundary cohorts of *independently sampled* requests (corner samples
  of the target ranges, and requests straddling the achieved-metrics
  envelope by [-2%, +2%] on one dimension);
- a certification ladder that assigns EVIDENCE classes, never feasibility
  truth: `verified_feasible` (a witness design was found and verified),
  `unresolved_after_budget` (the optimizer failed within its declared
  budget - evidence of difficulty, NOT proof of infeasibility),
  `invalid_or_out_of_domain`;
- calibration and separation metrics computed per cohort, so the easy
  synthetic-OOD number and the hard boundary number can never be blended.
"""

from __future__ import annotations

import numpy as np
import torch

from .. import config
from . import data as sdata
from .evaluate import eval_request_staged, spec_to_features

EVIDENCE_CLASSES = ("verified_feasible", "unresolved_after_budget",
                    "beyond_sample_envelope", "invalid_or_out_of_domain")


# ------------------------------------------------------------- sampling ----
def sample_independent_corners(n: int, seed: int) -> list[dict]:
    """Independently sampled TARGET_RANGES product (B1 cohort)."""
    rng = np.random.default_rng([seed, 41])
    g_lo, g_hi = config.TARGET_RANGES["Gain_min"]
    c_lo, c_hi = config.TARGET_RANGES["CL_pF"]
    specs = []
    for _ in range(n):
        specs.append({
            "Gain_min": float(rng.uniform(g_lo, g_hi)),
            "GBW_min": float(10 ** rng.uniform(
                np.log10(config.TARGET_RANGES["GBW_min"][0]),
                np.log10(config.TARGET_RANGES["GBW_min"][1]))),
            "CL_pF": float(rng.uniform(c_lo, c_hi)),
            "Power_max": float(10 ** rng.uniform(
                np.log10(config.TARGET_RANGES["Power_max"][0]),
                np.log10(config.TARGET_RANGES["Power_max"][1]))),
        })
    return specs


def sample_boundary_straddle(n: int, seed: int, design_rows: list[dict],
                             request_row_id_prefix: str = "be") -> list[dict]:
    """Requests straddling the achieved-metrics envelope (B2 cohort).

    Each picks a verified pilot design and exceeds ONE achieved metric by
    0-2% while relaxing the others by 5-15%: the source design fails the
    request by a hair; whether any neighbor design passes is exactly the
    boundary question the certification ladder answers.
    """
    rng = np.random.default_rng([seed, 42])
    valid = [r for r in design_rows
             if r["valid"] and r["verdict"] and r["GBW"] == r["GBW"]]
    if not valid:
        return []
    out = []
    for i in range(n):
        src = valid[int(rng.integers(len(valid)))]
        dim = int(rng.integers(3))
        # strictly beyond achieved (a 0% exceed would pass the source)
        m_exceed = float(rng.uniform(0.005, 0.02))
        m_safe = float(rng.uniform(0.05, 0.15))
        gain, gbw = src["DC_Gain_dB"], src["GBW"]
        power = src["Power"]
        vals = [gain * (1 - m_safe), gbw * (1 - m_safe), power * (1 + m_safe)]
        if dim == 0:
            vals[0] = gain * (1 + m_exceed)
        elif dim == 1:
            vals[1] = gbw * (1 + m_exceed)
        else:
            vals[2] = power * (1 - m_exceed)
        out.append({
            "Gain_min": float(vals[0]), "GBW_min": float(vals[1]),
            "Power_max": float(vals[2]), "CL_pF": float(src["cl_pf"]),
            "source_design_id": src["row_id"], "exceeded_dim": int(dim),
        })
    return out


def failure_probability(risk_model, specs: dict, feat_lo, feat_hi,
                        device: str = "cpu") -> float:
    """Return failure-evidence probability.

    ``RiskNet`` was trained with label 1 for achievable-looking requests, so
    sigmoid(logit) is an *achievability* probability.  Phase E reports and
    thresholds are expressed in the opposite direction: larger means more
    evidence of failure.  Keep that conversion at this interface so the
    calibration code cannot silently reverse AUC/precision semantics.
    """
    x = sdata.normalize(spec_to_features(specs)[None, :], feat_lo, feat_hi)
    with torch.no_grad():
        logit = risk_model(torch.as_tensor(x, dtype=torch.float32,
                                           device=device))
    return float(1.0 - torch.sigmoid(logit).item())


# ------------------------------------------------- calibration metrics ----
def reliability_bins(y_fail: np.ndarray, risk_p: np.ndarray,
                     n_bins: int = 5) -> list[dict]:
    """Predicted vs observed failure rate per risk-probability bin."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out = []
    for b in range(n_bins):
        m = (risk_p >= edges[b]) & (risk_p < edges[b + 1]
                                    if b < n_bins - 1
                                    else risk_p <= edges[b + 1])
        out.append({
            "bin": [float(edges[b]), float(edges[b + 1])],
            "n": int(m.sum()),
            "predicted_mean": float(risk_p[m].mean()) if m.any() else None,
            "observed_fail_rate": float(y_fail[m].mean()) if m.any() else None,
        })
    return out


def precision_recall_coverage(y_fail: np.ndarray, risk_p: np.ndarray,
                              thresholds=(0.3, 0.5, 0.7, 0.9)) -> list[dict]:
    """Flag (predict failure) when risk_p >= threshold; y_fail=1 = failure
    evidence. Reports each threshold's flagged fraction, precision, recall."""
    rows = []
    n = max(len(y_fail), 1)
    for t in thresholds:
        flagged = risk_p >= t
        tp = float((flagged & (y_fail == 1)).sum())
        fp = float((flagged & (y_fail == 0)).sum())
        fn = float((~flagged & (y_fail == 1)).sum())
        rows.append({
            "threshold": float(t),
            "flagged_fraction": float(flagged.sum()) / n,
            "precision": tp / max(tp + fp, 1e-9),
            "recall": tp / max(tp + fn, 1e-9),
        })
    return rows


def rank_auc(y_fail: np.ndarray, risk_p: np.ndarray) -> float | None:
    """AUC of risk score as a predictor of failure (Mann-Whitney)."""
    pos, neg = risk_p[y_fail == 1], risk_p[y_fail == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    order = np.argsort(np.concatenate([neg, pos]), kind="mergesort")
    ranks = np.empty(len(order), dtype=float)
    ranks[order] = np.arange(1, len(order) + 1)
    # average ranks handle ties
    vals = np.concatenate([neg, pos])
    for v in np.unique(vals):
        m = vals == v
        if m.sum() > 1:
            ranks[m] = ranks[m].mean()
    r_pos = ranks[len(neg):].sum()
    return float((r_pos - len(pos) * (len(pos) + 1) / 2)
                 / (len(pos) * len(neg)))


# -------------------------------------------------------------- report ----
def cohort_metrics(y_fail: np.ndarray, risk_p: np.ndarray,
                   pipeline_pass: np.ndarray | None = None) -> dict:
    """Per-cohort metrics. Never blended across cohorts; labels are evidence
    classes, not feasibility truth."""
    return {
        "n": int(len(y_fail)),
        "failures": int((y_fail == 1).sum()),
        "reliability_bins": reliability_bins(y_fail, risk_p),
        "thresholds": precision_recall_coverage(y_fail, risk_p),
        "auc": rank_auc(y_fail, risk_p),
        "pipeline_pass_flagged_vs_unflagged":
            flagged_hardness(y_fail, risk_p, pipeline_pass),
    }


def flagged_hardness(y_fail: np.ndarray, risk_p: np.ndarray,
                     pipeline_pass: np.ndarray | None,
                     threshold: float = 0.5) -> dict | None:
    """Do flagged requests actually fail the pipeline more often?"""
    if pipeline_pass is None or len(pipeline_pass) == 0:
        return None
    flagged = risk_p >= threshold
    out = {"threshold": threshold}
    for name, mask in (("flagged", flagged), ("unflagged", ~flagged)):
        n = int(mask.sum())
        out[name] = {
            "n": n,
            "pipeline_pass_rate": (float(pipeline_pass[mask].mean())
                                   if n else None),
        }
    return out


def write_report(cohorts: dict, out_json: str, out_md: str,
                 metadata: dict | None = None) -> None:
    """Write the two-cohort report. The word 'infeasible' must never appear:
    failed runs are 'unresolved_after_budget' - evidence, not proof."""
    import json

    payload = {"metadata": metadata or {}, "cohorts": cohorts}
    with open(out_json, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    def _md_table(rows, cols):
        head = "| " + " | ".join(cols) + " |"
        sep = "|" + "---|" * len(cols)
        body = ["| " + " | ".join(str(r[c]) for c in cols) + " |"
                for r in rows]
        return [head, sep] + body

    lines = ["# Risk-head evidence report (Phase E)", "",
             "Two cohorts, reported separately and never blended:", "",
             "- **synthetic_ood**: beyond-sample-envelope negatives - these",
             "  test detection of the dataset's negative-generation RULES;",
             "- **certified_boundary**: independently sampled requests with",
             "  optimizer-certified evidence classes.", "",
             "**`unresolved_after_budget` is not infeasibility**: a failed",
             "optimization run within a declared budget is evidence of",
             "difficulty, never proof that no design exists.", ""]
    for name, c in cohorts.items():
        lines += [f"## Cohort: {name}", "",
                  f"n = {c['n']}, failure-evidence = {c['failures']}, "
                  f"AUC = {c['auc']}", "",
                  "Reliability (predicted risk vs observed failure-evidence "
                  "rate):", ""]
        lines += _md_table(c["reliability_bins"],
                           ["bin", "n", "predicted_mean",
                            "observed_fail_rate"])
        lines += ["", "Precision / recall / coverage at thresholds:", ""]
        lines += _md_table(c["thresholds"],
                           ["threshold", "flagged_fraction", "precision",
                            "recall"])
        fh = c.get("pipeline_pass_flagged_vs_unflagged")
        if fh:
            lines += ["", "Are flagged requests genuinely harder?", "",
                      f"- flagged (p>={fh['threshold']}): n={fh['flagged']['n']},"
                      f" pipeline pass rate = {fh['flagged']['pipeline_pass_rate']}",
                      f"- unflagged: n={fh['unflagged']['n']}, pipeline pass "
                      f"rate = {fh['unflagged']['pipeline_pass_rate']}"]
        lines.append("")
    assert "infeasible" not in "\n".join(lines).lower(), \
        "report must never claim infeasibility"
    with open(out_md, "w") as f:
        f.write("\n".join(lines) + "\n")

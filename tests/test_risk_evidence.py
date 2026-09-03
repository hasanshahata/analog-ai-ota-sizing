"""Phase E risk-evidence tests (synthetic data + synthetic LUT)."""

from __future__ import annotations

import numpy as np
import torch

from analog_ai import config
from analog_ai.dataset import build as ds_build
from analog_ai.surrogate import risk_evidence as re_

GOOD_X = [0.6e-6, 10.0, 0.6e-6, 12.0, 50e-6]


def test_sample_corners_deterministic_and_in_range():
    a = re_.sample_independent_corners(20, seed=0)
    b = re_.sample_independent_corners(20, seed=0)
    assert a == b
    g_lo, g_hi = config.TARGET_RANGES["Gain_min"]
    w_lo, w_hi = config.TARGET_RANGES["GBW_min"]
    c_lo, c_hi = config.TARGET_RANGES["CL_pF"]
    p_lo, p_hi = config.TARGET_RANGES["Power_max"]
    for s in a:
        assert g_lo <= s["Gain_min"] <= g_hi
        assert w_lo <= s["GBW_min"] <= w_hi
        assert c_lo <= s["CL_pF"] <= c_hi
        assert p_lo <= s["Power_max"] <= p_hi


def _design_row(engine, row_id):
    _, ota = engine
    return ds_build.evaluate_design_row(ota, GOOD_X, 1.0, "sobol", row_id,
                                        "imposed", "test_build")


def test_boundary_straddle_source_fails(engine):
    drow = _design_row(engine, "d00000000")
    rows = re_.sample_boundary_straddle(12, seed=0, design_rows=[drow])
    assert len(rows) == 12
    assert all(r["source_design_id"] == "d00000000" for r in rows)
    for s in rows:
        specs = {k: s[k] for k in ("Gain_min", "GBW_min", "CL_pF",
                                   "Power_max")}
        rrow = ds_build.request_row(drow, specs, "feasible", "t", "t",
                                    "imposed", "test_build")
        # the SOURCE design must fail its own straddled request
        assert rrow["verdict"] is False, (specs, rrow["worst_violation"])
        assert rrow["worst_violation"] > 0


def test_reliability_and_thresholds_toy():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.8, 0.9])
    bins = re_.reliability_bins(y, p, n_bins=5)
    observed = [b["observed_fail_rate"] for b in bins if b["n"]]
    assert observed == sorted(observed)  # perfect detector: monotone
    rows = re_.precision_recall_coverage(y, p, thresholds=(0.5, 0.9))
    t05 = rows[0]
    assert t05["flagged_fraction"] == 0.5
    assert t05["precision"] == 1.0 and t05["recall"] == 1.0
    t09 = rows[1]
    assert t09["recall"] == 0.5 and t09["precision"] == 1.0


def test_rank_auc_hand_examples():
    y = np.array([0, 0, 1, 1])
    assert re_.rank_auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert re_.rank_auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0
    assert re_.rank_auc(y, np.array([0.5, 0.5, 0.5, 0.5])) == 0.5
    assert re_.rank_auc(np.array([1, 1]), np.array([0.3, 0.4])) is None


def test_failure_probability_reverses_achievability_logit():
    class FixedRisk(torch.nn.Module):
        def forward(self, x):
            return torch.full((len(x),), 2.0)

    specs = {"Gain_min": 30.0, "GBW_min": 100e6,
             "CL_pF": 1.0, "Power_max": 200e-6}
    p_fail = re_.failure_probability(
        FixedRisk(), specs, np.zeros(4), np.ones(4))
    assert np.isclose(p_fail, 1.0 - torch.sigmoid(torch.tensor(2.0)).item())
    assert p_fail < 0.5  # positive RiskNet logit means achievable-looking


def test_report_terminology_guard(tmp_path):
    cohorts = {
        "synthetic_ood": {"n": 4, "failures": 4,
                          "reliability_bins": [{"bin": [0, 1], "n": 4,
                                                "predicted_mean": 0.95,
                                                "observed_fail_rate": 1.0}],
                          "thresholds": [{"threshold": 0.5,
                                          "flagged_fraction": 1.0,
                                          "precision": 1.0,
                                          "recall": 1.0}],
                          "auc": 0.5,
                          "pipeline_pass_flagged_vs_unflagged": None},
        "certified_boundary": {"n": 2, "failures": 1,
                               "reliability_bins": [], "thresholds": [],
                               "auc": None,
                               "pipeline_pass_flagged_vs_unflagged": None},
    }
    j, m = tmp_path / "r.json", tmp_path / "r.md"
    re_.write_report(cohorts, str(j), str(m))
    payload = __import__("json").loads(j.read_text())
    assert set(payload) == {"metadata", "cohorts"}
    text = m.read_text().lower()
    assert "infeasible" not in text
    assert "unresolved_after_budget" in text
    assert "never proof that no design exists" in text

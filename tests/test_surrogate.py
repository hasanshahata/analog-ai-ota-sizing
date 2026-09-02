"""Phase 5 surrogate tests (synthetic data + synthetic LUT, fast)."""

from __future__ import annotations

import numpy as np
import torch

from analog_ai import config
from analog_ai.surrogate import data as sdata
from analog_ai.surrogate import evaluate as seval
from analog_ai.surrogate import train as strain
from analog_ai.surrogate.model import (ProposalNet, RiskNet, best_of_k_loss)


def _fake_request(i, label="feasible", split="train"):
    return {"row_id": f"r{i:08d}", "design_row_id": f"d{i:08d}",
            "label": label, "split": split,
            "req_Gain_min": 20.0 + i, "req_GBW_min": 1e8 + 1e6 * i,
            "req_CL_pF": 1.0, "req_Power_max": 1e-4}


def _fake_design(i, valid=True):
    row = {"row_id": f"d{i:08d}", "valid": valid, "verdict": valid,
           "L1": 0.5e-6, "gmid1": 12.0, "L3": 0.6e-6, "gmid3": 14.0,
           "Itail": 50e-6 + i * 1e-6, "cl_pf": 1.0}
    row.update({k: 1.0 for k in sdata.__dict__.keys() if False})
    return row


# ---------------------------------------------------------- data joins ----
def test_dataset_join_and_label_encoding():
    requests = [_fake_request(0, "feasible"),
                _fake_request(1, "near_boundary"),
                _fake_request(2, "beyond_sample_envelope"),
                _fake_request(3, "polish_failed"),
                _fake_request(4, "unresolved_by_optimizer")]
    designs = {f"d{i:08d}": _fake_design(i) for i in range(5)}
    lo = np.zeros(4)
    hi = np.ones(4)
    x, d, y, rows = sdata.build_split(requests, designs, "train", lo, hi)
    assert len(x) == 5 and len(d) == 5
    # polish_failed excluded from the risk labels, others encoded
    assert y.shape[0] == 4 and 1.0 not in y[2:]
    xp, dp, _, rows_p = sdata.build_split(requests, designs, "train", lo,
                                          hi, positive_only=True)
    assert len(xp) == 2  # feasible + near_boundary only
    # the design tensor is the joined design of each request, in order
    for row, dvec in zip(rows_p, dp):
        src = designs[row["design_row_id"]]
        expected = sdata.normalize_designs(
            np.array([[src["L1"], src["gmid1"], src["L3"], src["gmid3"],
                       src["Itail"]]]))[0]
        assert np.allclose(dvec, expected)
    assert np.isfinite(x).all() and np.isfinite(d).all()


def test_feature_normalization_roundtrip():
    rng = np.random.default_rng(0)
    rows = [{"req_Gain_min": 20 + 10 * rng.random(),
             "req_GBW_min": 10 ** (7 + 2 * rng.random()),
             "req_CL_pF": 10 ** (-1 + rng.random()),
             "req_Power_max": 10 ** (-4 + rng.random())} for _ in range(50)]
    x = sdata.feature_matrix(rows)
    lo, hi = sdata.fit_feature_ranges(x)
    n = sdata.normalize(x, lo, hi)
    assert n.min() >= 0.0 and n.max() <= 1.0
    assert np.allclose(sdata.denormalize(n, lo, hi), x, rtol=1e-9)
    physical = sdata.denormalize_features(n, lo, hi)
    assert np.allclose(physical[:, 1:], 10.0 ** x[:, 1:], rtol=1e-9)


def test_design_bounds_roundtrip():
    lo = np.array([b[0] for b in config.DESIGN_BOUNDS])
    hi = np.array([b[1] for b in config.DESIGN_BOUNDS])
    d = np.array([lo, hi, (lo + hi) / 2])
    n = sdata.normalize_designs(d)
    assert np.allclose(n[0], 0) and np.allclose(n[1], 1)
    assert np.allclose(sdata.denormalize_designs(n), d)


# ------------------------------------------------------------- model ------
def test_proposal_net_outputs_bounded_and_shaped():
    model = ProposalNet(k_heads=5)
    x = torch.randn(16, 4)
    u = model(x)
    assert u.shape == (16, 5, 5)
    assert u.min() >= 0.0 and u.max() <= 1.0
    designs = sdata.denormalize_designs(u.detach().numpy())
    bl = np.array([b[0] for b in config.DESIGN_BOUNDS])
    bh = np.array([b[1] for b in config.DESIGN_BOUNDS])
    assert designs.min() >= bl.min() - 1e-9
    assert designs.max() <= bh.max() + 1e-9
    assert ((designs >= bl) & (designs <= bh)).all()


def test_best_of_k_loss_semantics():
    target = torch.zeros(2, 5)
    pred = torch.zeros(2, 3, 5)
    pred[:, 1, :] = 0.5  # head 1 is exact for both rows
    loss = best_of_k_loss(pred, target)
    assert loss.item() == 0.0
    pred = torch.ones(1, 2, 5)
    pred[0, 0] = 0.5
    expected = 0.25  # best head: mean over 5 dims of (0.5)^2
    assert abs(best_of_k_loss(pred, target).item() - expected) < 1e-6


def test_tiny_training_decreases_loss():
    rng = np.random.default_rng(0)
    n = 256
    w = np.array([[0.8, -0.6, 0.5, 0.9], [0.3, 0.7, -0.8, 0.2],
                  [-0.9, 0.4, 0.6, 0.1], [0.2, 0.5, 0.3, -0.7],
                  [0.6, 0.1, 0.8, 0.4]])
    x = rng.random((n, 4)).astype(np.float32)
    d = (0.5 + 0.4 * np.tanh(x @ w.T)).astype(np.float32)  # smooth mapping
    model, hist = strain.train_proposal(x[:200], d[:200], x[200:], d[200:],
                                        seed=0, k_heads=2, epochs=60,
                                        batch=64, patience=50)
    assert hist["val"][-1] < hist["val"][0]
    assert hist["epochs_run"] <= 60


def test_risk_head_separates_toy_data():
    rng = np.random.default_rng(0)
    x_pos = rng.normal(loc=[0.8, 0.8, 0.8, 0.8], scale=0.05,
                       size=(100, 4)).astype(np.float32)
    x_neg = rng.normal(loc=[0.2, 0.2, 0.2, 0.2], scale=0.05,
                       size=(100, 4)).astype(np.float32)
    x = np.concatenate([x_pos, x_neg])
    y = np.concatenate([np.ones(100), np.zeros(100)]).astype(np.float32)
    model, hist = strain.train_risk(x[:150], y[:150], x[150:], y[150:],
                                    seed=0, epochs=80, batch=32,
                                    patience=80)
    m = seval.risk_metrics(model, x[150:], y[150:])
    assert m["accuracy"] > 0.9


def test_propose_verify_plumbing(engine):
    """End-to-end on the synthetic engine: untrained net still produces a
    full record with a status and bounded design."""
    _, ota = engine
    requests = [_fake_request(0, "feasible"), _fake_request(1, "feasible")]
    designs = {f"d{i:08d}": _fake_design(i) for i in range(2)}
    x = sdata.feature_matrix(requests)
    lo, hi = sdata.fit_feature_ranges(x)
    model = ProposalNet(k_heads=3)
    out = seval.eval_request(ota, model,
                             {"Gain_min": 20.0, "GBW_min": 1e8,
                              "CL_pF": 1.0, "Power_max": 1e-4},
                             lo, hi)
    assert out["status"] in ("verified", "verified_best_of_k", "unresolved")
    assert out["design_row"]["valid"] is True  # bounded design -> evaluates
    assert out["n_oracle_evals"] == 3
    nn_row, dist = seval.nn_lookup({"Gain_min": 20.0, "GBW_min": 1e8,
                                    "CL_pF": 1.0, "Power_max": 1e-4},
                                   requests, lo, hi)
    assert nn_row is not None and np.isfinite(dist)

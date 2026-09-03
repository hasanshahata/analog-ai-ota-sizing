"""Phase C local-refinement tests (synthetic LUT, fast)."""

from __future__ import annotations

import numpy as np

from analog_ai import config
from analog_ai.dataset import build as ds_build
from analog_ai.optimization.local_refine import (local_refine,
                                                 make_local_objective)
from analog_ai.surrogate.evaluate import _verify

GOOD_X = [0.6e-6, 10.0, 0.6e-6, 12.0, 50e-6]
SPECS = {"Gain_min": 10.0, "GBW_min": 1e6, "Power_max": 400e-6,
         "CL_pF": 1.0}


def test_local_objective_feasibility_first(engine):
    _, ota = engine
    obj = make_local_objective(ota, SPECS, cl=1e-12)
    passing = obj(np.array(GOOD_X))
    invalid = obj(np.array([0.6e-6, 10.0, 0.6e-6, 12.0, -1e-6]))
    assert passing < 1e3
    assert invalid == 1e3
    assert invalid > passing


def test_local_refine_recovers_near_miss(engine):
    """A design that misses Gain by a hair should be locally repairable."""
    _, ota = engine
    drow = _verify(ota, np.array(GOOD_X), SPECS)
    assert drow["verdict"]
    # request slightly more gain than GOOD_X achieves: a true near-miss.
    # (probed: within +-5% of GOOD_X the gain ceiling is ~+0.43 dB, so the
    # ask must sit comfortably inside that for a deterministic test)
    hard = {"Gain_min": drow["DC_Gain_dB"] + 0.15,
            "GBW_min": SPECS["GBW_min"], "Power_max": SPECS["Power_max"],
            "CL_pF": 1.0}
    assert not _verify(ota, np.array(GOOD_X), hard)["verdict"]
    out = local_refine(ota, hard, [np.array(GOOD_X)],
                       trust_fracs=(0.02, 0.05), n_heads=1, maxfev=600,
                       verifier=_verify)
    assert out["status"] == "local_refinement_verified", out
    assert out["n_evals"] < 1500  # far cheaper than full-domain DE
    assert _verify(ota, np.array(out["design"]), hard)["verdict"]


def test_local_refine_unresolved_reports_honestly(engine):
    _, ota = engine
    impossible = {"Gain_min": 1000.0, "GBW_min": 1e6,
                  "Power_max": 400e-6, "CL_pF": 1.0}
    out = local_refine(ota, impossible, [np.array(GOOD_X)],
                       trust_fracs=(0.02, 0.05), n_heads=1, maxfev=100,
                       verifier=_verify)
    assert out["status"] == "unresolved"
    assert len(out["stages"]) == 2  # one per trust region
    assert out["n_evals"] > 0
    d = np.array(out["design"])
    lo = np.array([b[0] for b in config.DESIGN_BOUNDS])
    hi = np.array([b[1] for b in config.DESIGN_BOUNDS])
    assert ((d >= lo) & (d <= hi)).all()
    assert out["worst_violation"] == out["worst_violation"]  # finite


def test_staged_ladder_never_false_success(engine):
    from analog_ai.surrogate import data as sdata
    from analog_ai.surrogate.evaluate import eval_request_staged
    from analog_ai.surrogate.model import ProposalNet
    _, ota = engine
    requests = [{"req_Gain_min": 20.0, "req_GBW_min": 1e8,
                 "req_CL_pF": 1.0, "req_Power_max": 1e-4}]
    lo = np.zeros(4)
    hi = np.ones(4)
    model = ProposalNet(k_heads=3)
    out = eval_request_staged(ota, model, SPECS, lo, hi,
                              local=True, global_fallback=False,
                              trust_fracs=(0.02,), n_heads_local=1,
                              global_maxiter=5)
    allowed = {"verified", "verified_best_of_k",
               "local_refinement_verified", "global_fallback_verified",
               "unresolved"}
    assert out["status"] in allowed
    assert out["stages"] == [] or out["status"] != "verified"
    if out["status"] != "unresolved":
        # no false success: a fresh full verification must pass
        assert _verify(ota, np.array(out["design"]), SPECS)["verdict"]

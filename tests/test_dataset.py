"""Phase 3 dataset-builder tests (synthetic LUT, no 5.5 GB files needed)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os

import numpy as np
import pytest

from analog_ai.dataset import build, io, sampling, splits
from analog_ai.evaluation.evaluator import evaluate_design

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A design known to verify on the synthetic engine (see test_evaluator.py).
GOOD_X = [0.6e-6, 10.0, 0.6e-6, 12.0, 50e-6]


def _make_design_row(engine, x=GOOD_X, cl_pf=1.0, row_id="d00000000"):
    _, ota = engine
    return build.evaluate_design_row(ota, x, cl_pf, "sobol", row_id,
                                     "imposed", "test_build")


# ------------------------------------------------------------- sampling ----
def test_sobol_bounds_determinism_uniqueness():
    X = sampling.sobol_designs(64, seed=0)
    X2 = sampling.sobol_designs(64, seed=0)
    assert np.array_equal(X, X2)  # deterministic, so resumable
    assert X.shape == (64, 5)
    for j, (lo, hi) in enumerate([(60e-9, 1.5e-6), (5, 25), (60e-9, 1.5e-6),
                                  (5, 25), (10e-6, 500e-6)]):
        assert X[:, j].min() >= lo and X[:, j].max() <= hi
    assert len({tuple(r) for r in X}) == 64  # no duplicate designs


def test_derived_requests_verify_and_infeasible_fails(engine):
    drow = _make_design_row(engine)
    assert drow["valid"] and drow["verdict"]
    stats = build.dataset_stats([drow])
    rng = np.random.default_rng(0)
    feasible, near_b, infeasible = sampling.derive_requests(
        drow, drow["cl_pf"], stats, rng)

    for specs, label in ((feasible, "feasible"), (near_b, "near_boundary")):
        rrow = build.request_row(drow, specs, label, "r00000000",
                                 "sobol", "imposed", "test_build")
        assert rrow["verdict"] is True, (label, rrow["worst_violation"])
        # the margin is respected: the request is strictly inside
        assert specs["Gain_min"] <= drow["DC_Gain_dB"]
        assert specs["GBW_min"] <= drow["GBW"]
        assert specs["Power_max"] >= drow["Power"]

    rrow = build.request_row(drow, infeasible, "beyond_sample_envelope",
                             "r00000001", "sobol", "imposed", "test_build")
    assert rrow["verdict"] is False
    assert rrow["worst_violation"] > 0.0
    assert infeasible["infeasible_dim"] in ("Gain_min", "GBW_min",
                                            "Power_max")


def test_request_residuals_match_fresh_evaluation(engine):
    _, ota = engine
    drow = _make_design_row(engine)
    specs = {"Gain_min": 10.0, "GBW_min": 1e6, "Power_max": 400e-6,
             "CL_pF": 1.0}
    rrow = build.request_row(drow, specs, "feasible", "r00000000",
                             "sobol", "imposed", "test_build")
    # residuals recomputed from the stored row must equal a fresh evaluation
    rec = evaluate_design(ota, GOOD_X, specs)
    fresh = {c["name"]: c["residual"] for c in rec["constraints"]}
    for k in ("Gain_min", "GBW_min", "Power_max", "PM_min", "Sat_margin_min",
              "W_nmos_max", "W_pmos_max", "L_domain"):
        assert rrow[f"r_{k}"] == pytest.approx(fresh[k], abs=1e-12)
    assert rrow["verdict"] == rec["verdict"]


def test_invalid_design_row_and_request_on_it(engine):
    _, ota = engine
    drow = build.evaluate_design_row(ota, [0.6e-6, 5.0, 0.6e-6, 12.0, -1e-6],
                                     1.0, "sobol", "d00000009", "imposed",
                                     "test_build")
    assert drow["valid"] is False
    assert drow["invalid_reason"]
    rrow = build.request_row(
        drow, {"Gain_min": 10.0, "GBW_min": 1e6, "Power_max": 400e-6,
               "CL_pF": 1.0}, "unresolved_by_optimizer", "r00000009",
        "de_certify", "imposed", "test_build")
    assert rrow["verdict"] is False
    assert rrow["worst_violation"] == float("inf")


def test_dataset_stats_extremes(engine):
    rows = [_make_design_row(engine, row_id="d00000000"),
            _make_design_row(engine, cl_pf=5.0, row_id="d00000001")]
    stats = build.dataset_stats(rows)
    assert set(stats) == {1.0, 5.0}
    for s in stats.values():
        assert np.isfinite(s["max_gain"]) and np.isfinite(s["min_power"])


# --------------------------------------------------------------- splits ----
def _mk_grouped_request_rows(n_groups=30):
    """n_groups design groups x 3 requests each (feasible/near/beyond)."""
    rows = []
    for g in range(n_groups):
        did = f"d{g:08d}"
        gain = 5.0 + 70.0 * (g % 6) / 5.0
        gbw = 10 ** (6.0 + 3.5 * (g // 6) / 4.0)
        for k, label in enumerate(("feasible", "near_boundary",
                                   "beyond_sample_envelope")):
            rows.append({
                "row_id": f"r{g:02d}{k}", "design_row_id": did,
                "label": label,
                "req_Gain_min": gain * (1.0 - 0.01 * (k + 1)),
                "req_GBW_min": gbw, "req_CL_pF": 1.0,
                "req_Power_max": 1e-4,
            })
    return rows


def test_assign_splits_by_design_no_leakage():
    """Regression: one design's requests must never straddle splits
    (measured 4,436 shared design IDs between pilot train and test)."""
    rows = _mk_grouped_request_rows()
    mapping = splits.assign_splits_by_design(rows, seed=0)
    by_split = {}
    for r in rows:
        by_split.setdefault(r["split"], set()).add(r["design_row_id"])
        assert r["split"] == mapping[r["design_row_id"]]
    assert not (by_split["train"] & by_split["val"])
    assert not (by_split["train"] & by_split["test"])
    assert not (by_split["val"] & by_split["test"])
    assert set(by_split) == {"train", "val", "test"}
    n = sum(len(v) for v in by_split.values())
    assert len(by_split["train"]) / n > 0.5  # ~70% of groups

    # deterministic per seed
    rows2 = _mk_grouped_request_rows()
    assert splits.assign_splits_by_design(rows2, seed=0) == mapping

    # identical requests of the same design share one split
    a, b = dict(rows[0]), dict(rows[0])
    splits.assign_splits_by_design([a, b], seed=1)
    assert a["split"] == b["split"]


def test_region_key_covers_extremes():
    # derived-infeasible extremes must not collapse into the same region as
    # ordinary requests of the same kind
    k_ord = splits.region_key(30.0, 1e8, 1.0, 1e-4)
    k_ext = splits.region_key(30.0, 1e10, 1.0, 1e-4)
    k_low = splits.region_key(30.0, 1e8, 1.0, 3e-7)
    assert k_ord != k_ext and k_ord != k_low


# ------------------------------------------------------------------- io ----
def test_io_roundtrip_and_manifest(tmp_path, engine):
    drow = _make_design_row(engine)
    io.append_rows(str(tmp_path), "design", [drow])
    rrow = build.request_row(
        drow, {"Gain_min": 10.0, "GBW_min": 1e6, "Power_max": 400e-6,
               "CL_pF": 1.0}, "feasible", "r00000000", "sobol",
        "imposed", "test_build")
    rrow["split"] = "train"
    io.append_rows(str(tmp_path), "request", [rrow])

    assert len(io.rows_of(str(tmp_path), "design")) == 1
    back = io.rows_of(str(tmp_path), "request")
    assert back[0]["row_id"] == "r00000000"
    assert back[0]["verdict"] is True

    manifest = io.finalize(str(tmp_path), seed=0,
                           config_summary={"tiny": True},
                           request_rows=[rrow], split_map={})
    assert (tmp_path / "designs.parquet").exists()
    assert (tmp_path / "requests.parquet").exists()
    assert manifest["counts"]["design_rows"] == 1
    assert manifest["counts"]["request_rows"] == 1
    assert manifest["counts"]["by_label"] == {"feasible": 1}
    assert len(manifest["files"]["designs.parquet"]["sha256"]) == 64
    assert manifest["environment"]["pyarrow"]
    m2 = json.loads((tmp_path / "manifest.json").read_text())
    assert m2["dataset_seed"] == 0


def test_certify_labels_from_request_verdict(engine):
    """Regression: certify/polish labels must follow the REQUEST verdict, not
    the best-effort design's structural verdict (a structurally-valid design
    can still miss the spec)."""
    _, ota = engine
    easy = {"Gain_min": 5.0, "GBW_min": 1e6, "Power_max": 400e-6, "CL_pF": 1.0}
    _, rrow = build.certify_request(ota, easy, seed=0, maxiter=40, popsize=8,
                                    design_row_id="d00000010",
                                    request_row_id="r00000010",
                                    op_point="imposed", build_id="t")
    assert rrow["label"] == "feasible" and rrow["verdict"] is True

    hard = {"Gain_min": 1000.0, "GBW_min": 1e6, "Power_max": 400e-6,
            "CL_pF": 1.0}  # physically impossible, any budget
    _, rrow = build.certify_request(ota, hard, seed=0, maxiter=40, popsize=8,
                                    design_row_id="d00000011",
                                    request_row_id="r00000011",
                                    op_point="imposed", build_id="t")
    assert rrow["label"] == "unresolved_by_optimizer"
    assert rrow["verdict"] is False and rrow["worst_violation"] > 0


# ------------------------------------------------- end-to-end (tiny) -------
def _load_builder_module():
    spec = importlib.util.spec_from_file_location(
        "build_dataset", os.path.join(ROOT, "scripts", "build_dataset.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pipeline_end_to_end_tiny(tmp_path, engine):
    _, ota = engine
    mod = _load_builder_module()
    args = argparse.Namespace(
        out_dir=str(tmp_path), seed=0, lut_dir=None, op_point="imposed",
        n_sobol=8,
        n_polish=1, n_certify=1, maxiter=3, popsize=5, cert_maxiter=3)
    state = mod.load_state(str(tmp_path), args.seed)

    mod.stage_sobol(ota, args, state)
    assert state["sobol_done"] == 8
    assert len(io.rows_of(str(tmp_path), "design")) == 8 * 3  # 3 CLs

    mod.stage_derive(args, state)
    derived = io.rows_of(str(tmp_path), "request")
    assert all(r["source"] == "sobol" for r in derived)

    mod.stage_polish(ota, args, state)
    mod.stage_certify(ota, args, state)
    assert state["certify_done"] == 1

    mod.stage_finalize(args, state)
    assert (tmp_path / "requests.parquet").exists()
    import pyarrow.parquet as pq
    consolidated = pq.read_table(str(tmp_path / "requests.parquet")).to_pylist()
    assert all(r["split"] in ("train", "val", "test") for r in consolidated)
    assert state["certify_done"] == 1
    # resumable: re-running a completed stage is a no-op
    mod.stage_sobol(ota, args, state)
    n_expected = 8 * 3 + state["polish_done"] + state["certify_done"]
    assert len(io.rows_of(str(tmp_path), "design")) == n_expected

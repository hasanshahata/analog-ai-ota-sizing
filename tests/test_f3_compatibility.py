"""Phase F3 tests: mode-aware record routing, public dispatch through the
supported loader, seven-parameter optimizer bounds, finite netlist round
trip, and explicit compatibility rejections at the ideal-only consumers.

Contract: docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md (Astra F3 handoff).
"""

import json
import importlib
from types import SimpleNamespace

import numpy as np
import pytest

from analog_ai import ORACLE_VERSION, config
from analog_ai.circuit.ota5t import InvalidDesignError, OTA5T
from analog_ai.correlation.campaign import expected_from_sizing
from analog_ai.dataset.build import evaluate_design_row
from analog_ai.evaluation.evaluator import (FINITE_SCHEMA_VERSION,
                                            evaluate_design,
                                            evaluate_design_finite)
from analog_ai.loader import load_engine_from_paths
from analog_ai.sizing import size_ideal_tail_ota
from analog_ai.utils.netlist import (export_netlist,
                                     verify_finite_netlist_round_trip)

NOMINAL = (0.6e-6, 15.0, 0.6e-6, 12.0, 0.6e-6, 10.0, 50e-6)
LOOSE_SPECS = {"Gain_min": 20.0, "GBW_min": 1e6, "CL_pF": 1.0,
               "Power_max": 400e-6}


# ------------------------------------------------- public dispatch/loader ---
def test_public_dispatch_through_supported_loader(lut_paths):
    """Public finite evaluation through the SUPPORTED loader entry point
    (Astra F3 handoff item 1)."""
    dm, ota = load_engine_from_paths(lut_paths[0], lut_paths[1],
                                     tail_device="finite",
                                     op_point="solved")
    assert ota.tail_device == "finite" and ota.op_point == "solved"
    perf = ota.evaluate(list(NOMINAL), CL=1e-12)
    assert perf["tail_device"] == "finite"
    assert perf["op_point_mode"] == "solved"
    assert perf["ac_model"] == "corrected_terminal_v1"
    assert perf["devices"]["M5"]["W"] > 0.0
    assert perf["Vbias_tail"] is not None


def test_default_loader_stays_ideal(lut_paths):
    """Default ideal behavior preserved: the loader defaults to an
    ideal-tail object and rejects seven-parameter designs by arity."""
    dm, ota = load_engine_from_paths(lut_paths[0], lut_paths[1])
    assert ota.tail_device == "ideal"
    with pytest.raises(InvalidDesignError):
        ota.evaluate(list(NOMINAL), CL=1e-12)


# ------------------------------------------------------ record routing ------
def test_generic_record_entry_routes_finite_to_finite_schema(engine):
    """The generic record entry point routes finite/solved calls to the
    finite schema (never the five-name historical record)."""
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    rec = evaluate_design(ota, list(NOMINAL), dict(LOOSE_SPECS))
    assert rec["schema_version"] == FINITE_SCHEMA_VERSION
    assert rec["schema_version"] != ORACLE_VERSION
    assert list(rec["design"]) == list(config.DESIGN_PARAM_NAMES_7)
    assert rec["op_point_mode"] == "solved"
    json.dumps(rec, allow_nan=False)


def test_generic_record_entry_keeps_historical_identity(engine):
    dm, ota = engine
    rec = evaluate_design(ota, [0.6e-6, 15.0, 0.6e-6, 12.0, 50e-6],
                          dict(LOOSE_SPECS))
    assert "oracle_version" in rec["provenance"]
    assert rec["provenance"]["oracle_version"] == ORACLE_VERSION
    assert list(rec["design"]) == ["L1", "gmid1", "L3", "gmid3", "Itail"]


def test_record_entry_rejects_mismatched_design_lengths(engine):
    """No truncation, no padding: a seven-value design on the historical
    path is rejected explicitly."""
    dm, ota = engine
    with pytest.raises(ValueError, match="five ideal-tail parameters"):
        evaluate_design(ota, list(NOMINAL), dict(LOOSE_SPECS))
    fin_imp = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="imposed")
    with pytest.raises(ValueError, match="five ideal-tail parameters"):
        evaluate_design(fin_imp, list(NOMINAL), dict(LOOSE_SPECS))


# --------------------------------------------- seven-parameter contract -----
def test_design_bounds_are_mode_aware():
    assert config.design_bounds("ideal") == config.DESIGN_BOUNDS
    assert config.design_bounds("finite") == config.DESIGN_BOUNDS_7
    assert len(config.design_bounds("finite")) == 7
    assert config.design_bounds("finite")[6] == config.DESIGN_BOUNDS[4]
    with pytest.raises(ValueError):
        config.design_bounds("triode")


def test_optimizer_bounds_follow_object_mode(engine):
    """DE bounds are chosen from the object's tail mode: a finite object
    optimizes the seven-parameter contract and returns a finite record."""
    from analog_ai.optimization.de_baseline import optimize_specs
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    rec = optimize_specs(ota, dict(LOOSE_SPECS), seed=0, maxiter=1,
                         popsize=2, n_starts=1)
    assert list(rec["design"]) == list(config.DESIGN_PARAM_NAMES_7)
    assert rec["schema_version"] == FINITE_SCHEMA_VERSION


def test_local_refine_bounds_are_mode_aware(engine):
    """local_refine derives its trust region from the mode-aware bounds:
    a seven-parameter candidate is accepted for a finite object."""
    from analog_ai.optimization.local_refine import local_refine
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")

    def verifier(o, design, specs):
        rec = evaluate_design(o, design, specs)
        return {"verdict": rec["verdict"],
                "worst_violation": 0.0 if rec["verdict"] else 1.0}

    out = local_refine(ota, dict(LOOSE_SPECS), [np.array(NOMINAL)],
                       n_heads=1, maxfev=8, verifier=verifier)
    assert len(out["design"]) == 7


def test_finite_local_refine_runs_in_normalized_coordinates(engine, monkeypatch):
    module = importlib.import_module("analog_ai.optimization.local_refine")
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    seen = {}

    def fake_minimize(objective, x0, method, bounds, options):
        seen.update(x0=np.asarray(x0), bounds=np.asarray(bounds), options=options)
        return SimpleNamespace(x=np.asarray(x0), fun=float(objective(x0)), nfev=1)

    monkeypatch.setattr(module, "minimize", fake_minimize)
    out = module.local_refine(
        ota, dict(LOOSE_SPECS), [np.asarray(NOMINAL)], trust_fracs=(1.0,),
        n_heads=1, maxfev=1,
        verifier=lambda o, x, s: {"verdict": False, "worst_violation": 1.0})
    lo = np.asarray([b[0] for b in config.DESIGN_BOUNDS_7])
    hi = np.asarray([b[1] for b in config.DESIGN_BOUNDS_7])
    assert np.allclose(seen["x0"], (np.asarray(NOMINAL) - lo) / (hi - lo))
    assert np.allclose(seen["bounds"][:, 0], 0.0)
    assert np.allclose(seen["bounds"][:, 1], 1.0)
    assert seen["options"]["xatol"] == 1e-6
    assert np.allclose(out["design"], NOMINAL)
    assert out["design"][6] == pytest.approx(NOMINAL[6])


def test_finite_local_refine_clips_all_seven_endpoints_in_normalized_space(engine, monkeypatch):
    module = importlib.import_module("analog_ai.optimization.local_refine")
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    bounds = np.asarray(config.DESIGN_BOUNDS_7)
    outside = np.where(np.arange(7) % 2 == 0,
                       bounds[:, 0] - (bounds[:, 1] - bounds[:, 0]),
                       bounds[:, 1] + (bounds[:, 1] - bounds[:, 0]))
    seen = {}

    def fake_minimize(objective, x0, method, bounds, options):
        seen["x0"] = np.asarray(x0)
        return SimpleNamespace(x=np.asarray(x0), fun=float(objective(x0)), nfev=1)

    monkeypatch.setattr(module, "minimize", fake_minimize)
    out = module.local_refine(
        ota, dict(LOOSE_SPECS), [outside], trust_fracs=(0.02,), n_heads=1,
        maxfev=1, verifier=lambda o, x, s: {"verdict": False,
                                            "worst_violation": 1.0})
    expected_u = np.where(np.arange(7) % 2 == 0, 0.0, 1.0)
    expected_x = np.where(np.arange(7) % 2 == 0, bounds[:, 0], bounds[:, 1])
    assert np.array_equal(seen["x0"], expected_u)
    assert np.allclose(out["design"], expected_x)
    assert out["design"][6] == pytest.approx(bounds[6, 0])


def test_finite_search_contract_applies_tightened_limits_and_prevalidates(engine):
    from analog_ai.optimization.de_baseline import make_objective, optimize_specs
    from analog_ai.optimization.local_refine import make_local_objective
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    loose = dict(LOOSE_SPECS)
    tight = dict(loose, PM_min=179.0, Sat_margin_min=0.3)
    assert make_objective(ota, tight, 1e-12)(NOMINAL) > make_objective(ota, loose, 1e-12)(NOMINAL)
    assert make_local_objective(ota, tight, 1e-12)(NOMINAL) > make_local_objective(ota, loose, 1e-12)(NOMINAL)

    class Sentinel:
        tail_device = "finite"
        def evaluate(self, *args, **kwargs):
            raise AssertionError("device work occurred")
    with pytest.raises(ValueError, match="Power_max"):
        optimize_specs(Sentinel(), dict(loose, Power_max=0.0), n_starts=1,
                       maxiter=1, popsize=2)


def test_finite_search_unavailable_metric_stays_finite_and_failed(engine):
    from analog_ai.optimization.de_baseline import make_objective
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    specs = dict(LOOSE_SPECS, Swing_min=0.1)
    value = make_objective(ota, specs, 1e-12)(NOMINAL)
    rec = evaluate_design_finite(ota, NOMINAL, specs)
    assert np.isfinite(value)
    row = next(c for c in rec["constraints"] if c["name"] == "Swing_min")
    assert rec["verdict"] is False and row["passed"] is False
    assert row["residual"] is None


# ------------------------------------------------- netlist round trip -------
def test_finite_netlist_carries_returned_geometry_and_bias(engine):
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    rec = evaluate_design_finite(ota, list(NOMINAL), dict(LOOSE_SPECS))
    netlist = export_netlist(rec)
    m5 = next(ln for ln in netlist.splitlines() if ln.startswith("M5 "))
    bias = next(ln for ln in netlist.splitlines()
                if ln.startswith("Vtailbias"))
    # M5 geometry survives at print precision (0.1 nm resolution).
    assert m5.split("w=")[1].split("u")[0] == \
        pytest.approx(f"{rec['devices']['M5']['W'] * 1e6:.4f}")
    assert m5.split("l=")[1].split("n")[0] == \
        pytest.approx(f"{rec['devices']['M5']['L'] * 1e9:.1f}")
    # The SOLVED gate bias is exported (never the historical zero volts).
    assert bias.endswith(f"dc={rec['dc_diagnostics']['Vbias_tail']:.6f}")
    assert not bias.rstrip().endswith("dc=0")
    assert "serialization is checked" in netlist
    assert "exported-circuit verdict is withheld" in netlist
    assert "VICM" in netlist             # effective supply/load context


def test_netlist_round_trip_verifies_complete_serialization(engine):
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    rec = evaluate_design_finite(ota, list(NOMINAL), dict(LOOSE_SPECS))
    netlist = export_netlist(rec)
    checked = verify_finite_netlist_round_trip(rec, netlist)
    assert checked["serialization_verified"] is True
    assert checked["exported_circuit_verdict"] is None
    assert rec["verdict"] is False
    assert rec["metrics"]["sat_m5"] < 0.0


@pytest.mark.parametrize("old,new", [
    ("Vdd (vdd! 0) vsource dc=1.3", "Vdd (vdd! 0) vsource dc=0.1"),
    ("M1 (vmirror inp vtail 0)", "M1 (vmirror inp vtail 0)"),
    ("M3 (vmirror vmirror vdd! vdd!)", "M3 (vmirror vout vdd! vdd!)"),
    ("Vtailbias (vbiastail 0) vsource dc=", "Vtailbias (vbiastail 0) vsource dc=0.1 //"),
    ("CL (vout 0) capacitor c=2.5p", "CL (vout 0) capacitor c=9p"),
    ("Vinp (inp vicm) vsource dc=0 mag=0.5 phase=0",
     "Vinp (inm vicm) vsource dc=0 mag=0.5 phase=0"),
    ("X1 (inp inm vout vbiastail) OTA5T",
     "X1 (inm inp vout vbiastail) OTA5T"),
])
def test_finite_round_trip_rejects_mutations(engine, old, new):
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.3, tail_device="finite", op_point="solved")
    specs = dict(LOOSE_SPECS, CL_pF=2.5)
    rec = evaluate_design_finite(ota, list(NOMINAL), specs)
    text = export_netlist(rec)
    if old.startswith("M1 "):
        line = next(x for x in text.splitlines() if x.startswith("M1 "))
        text = text.replace(line, line.replace("w=", "w=9", 1))
    else:
        assert old in text
        text = text.replace(old, new, 1)
    assert not verify_finite_netlist_round_trip(rec, text)["serialization_verified"]


def test_finite_round_trip_rejects_duplicate_device(engine):
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.3, tail_device="finite", op_point="solved")
    rec = evaluate_design_finite(ota, list(NOMINAL), dict(LOOSE_SPECS, CL_pF=2.5))
    text = export_netlist(rec)
    m1 = next(x for x in text.splitlines() if x.startswith("M1 "))
    assert not verify_finite_netlist_round_trip(rec, text + "\n" + m1)[
        "serialization_verified"]


def test_finite_export_uses_authoritative_context_and_rejects_conflicts(engine):
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.3, tail_device="finite", op_point="solved")
    rec = evaluate_design_finite(ota, list(NOMINAL), dict(LOOSE_SPECS, CL_pF=2.5))
    text = export_netlist(rec)
    assert "dc=1.3" in text and "dc=0.65" in text and "c=2.5p" in text
    with pytest.raises(ValueError, match="conflicts"):
        export_netlist(rec, vdd=1.2)
    with pytest.raises(ValueError, match="conflicts"):
        export_netlist(rec, vicm=0.6)
    with pytest.raises(ValueError, match="conflicts"):
        export_netlist(rec, cl=1e-12)


def test_finite_export_non_round_context_self_verifies(engine):
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.23456, tail_device="finite", op_point="solved")
    rec = evaluate_design_finite(
        ota, list(NOMINAL), dict(LOOSE_SPECS, CL_pF=2.3456))
    text = export_netlist(rec)
    assert verify_finite_netlist_round_trip(rec, text)["serialization_verified"]


def test_finite_netlist_requires_solved_bias(engine):
    """The historical zero-volt gate export is gone: an imposed-finite
    evaluation (no solved gate bias) refuses to export instead of emitting
    an unverifiable circuit."""
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="imposed")
    perf = ota.evaluate(list(NOMINAL), CL=1e-12)
    with pytest.raises(ValueError, match="complete finite evaluation record"):
        export_netlist(perf, cl=1e-12)


# ------------------------------------------------ compatibility rejections --
def test_dataset_path_rejects_finite_designs(engine):
    dm, ota = engine
    with pytest.raises(ValueError, match="five design parameters"):
        evaluate_design_row(ota, list(NOMINAL), 1.0, "t", "r", "solved", "b")
    fin = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    with pytest.raises(ValueError, match="finite.solved"):
        evaluate_design_row(fin, [0.6e-6, 15.0, 0.6e-6, 12.0, 50e-6], 1.0,
                            "t", "r", "solved", "b")


def test_sizing_entry_rejects_finite_objects(engine):
    dm, _ = engine
    fin = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    with pytest.raises(ValueError, match="ideal-tail abstraction only"):
        size_ideal_tail_ota(fin, model=None, user_specs=dict(LOOSE_SPECS),
                            feat_lo=np.zeros(4), feat_hi=np.ones(4))


def test_correlation_collector_rejects_finite_topology():
    rec = {"topology": "5t_ota_finite_tail", "lut_metrics": {"GBW": 1e8}}
    with pytest.raises(ValueError, match="finite correlation"):
        expected_from_sizing(rec)
    # historical ideal records keep working
    ok = expected_from_sizing({"topology": "5t_ota_ideal_tail",
                               "lut_metrics": {
                                   "DC_Gain_dB": 30.0, "GBW": 1e8,
                                   "PM": 60.0, "Power": 1e-4,
                                   "Vout": 0.6, "Vtail": 0.2,
                                   "Vmirror": 0.6}})
    assert ok["gbw_Hz"] == 1e8


def test_ideal_only_rl_and_surrogate_boundaries_reject_finite(engine, monkeypatch):
    from analog_ai.envs.sizing_env import OTA5tSizingEnv
    from analog_ai.surrogate.data import design_matrix
    from analog_ai.surrogate.evaluate import eval_request
    from analog_ai.surrogate.model import ProposalNet
    from analog_ai.surrogate import train as strain
    dm, _ = engine
    finite = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    with pytest.raises(ValueError, match="ideal-tail"):
        OTA5tSizingEnv(finite)
    with pytest.raises(ValueError, match="five design bounds"):
        OTA5tSizingEnv(object(), bounds=config.DESIGN_BOUNDS_7)
    row = dict(zip(config.DESIGN_PARAM_NAMES_7, NOMINAL))
    with pytest.raises(ValueError, match="finite seven-field"):
        design_matrix([row])
    with pytest.raises(ValueError, match="ideal-tail engines"):
        eval_request(finite, ProposalNet(k_heads=1), LOOSE_SPECS,
                     np.zeros(4), np.ones(4))
    monkeypatch.setattr(strain.torch, "load", lambda *a, **k: {
        "meta": {"tail_device": "finite"}, "proposal_state": {},
        "risk_state": None})
    with pytest.raises(ValueError, match="five-output ideal-tail"):
        strain.load_checkpoint("unused")


def test_public_record_examples_are_strict_json(engine):
    """Strict-JSON valid and invalid examples through the PUBLIC record
    path (Astra F3 handoff item 5)."""
    dm, _ = engine
    fin = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    valid = evaluate_design(fin, list(NOMINAL), dict(LOOSE_SPECS))
    json.dumps(valid, allow_nan=False)
    invalid = evaluate_design(fin, list(NOMINAL),
                              dict(LOOSE_SPECS, Power_max=-1.0))
    json.dumps(invalid, allow_nan=False)
    assert invalid["verdict"] is False
    assert "Power_max" in invalid["invalid_reason"]


def test_source_bound_f3_export_evidence():
    from scripts.probe_f3_export import ROOT, build_evidence
    import hashlib
    evidence = build_evidence()
    assert evidence["parsed_verification"]["serialization_verified"] is True
    assert evidence["corruption"]["parsed_verification"]["serialization_verified"] is False
    assert evidence["known_failed_diagnostic"]["pre_export_verdict"] is False
    assert evidence["known_failed_diagnostic"]["sat_m5"] < 0.0
    for name, digest in evidence["source_fingerprint"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    json.dumps(evidence, allow_nan=False)

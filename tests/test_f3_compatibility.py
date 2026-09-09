"""Phase F3 tests: mode-aware record routing, public dispatch through the
supported loader, seven-parameter optimizer bounds, finite netlist round
trip, and explicit compatibility rejections at the ideal-only consumers.

Contract: docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md (Astra F3 handoff).
"""

import json

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
from analog_ai.utils.netlist import export_netlist

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


# ------------------------------------------------- netlist round trip -------
def test_finite_netlist_carries_returned_geometry_and_bias(engine):
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    perf = ota.evaluate(list(NOMINAL), CL=1e-12)
    netlist = export_netlist(perf, cl=1e-12)
    m5 = next(ln for ln in netlist.splitlines() if ln.startswith("M5 "))
    bias = next(ln for ln in netlist.splitlines()
                if ln.startswith("Vtailbias"))
    # M5 geometry survives at print precision (0.1 nm resolution).
    assert m5.split("w=")[1].split("u")[0] == \
        pytest.approx(f"{perf['devices']['M5']['W'] * 1e6:.4f}")
    assert m5.split("l=")[1].split("n")[0] == \
        pytest.approx(f"{perf['devices']['M5']['L'] * 1e9:.1f}")
    # The SOLVED gate bias is exported (never the historical zero volts).
    assert bias.endswith(f"dc={perf['Vbias_tail']:.6f}")
    assert not bias.rstrip().endswith("dc=0")
    assert "re-verify" in netlist        # rounding warning present
    assert "VICM" in netlist             # effective supply/load context


def test_netlist_round_trip_rederives_verdict(engine):
    """The exported (rounded) M5 geometry, re-imported and re-evaluated,
    reproduces the exported design's verdict honestly - the verdict comes
    from the exported precision, not a stale pre-rounding value."""
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")
    perf = ota.evaluate(list(NOMINAL), CL=1e-12)
    netlist = export_netlist(perf, cl=1e-12)
    m5 = next(ln for ln in netlist.splitlines() if ln.startswith("M5 "))
    w5 = float(m5.split("w=")[1].split("u")[0]) * 1e-6
    l5 = float(m5.split("l=")[1].split("n")[0]) * 1e-9
    bias = float(next(ln for ln in netlist.splitlines()
                      if ln.startswith("Vtailbias")).split("dc=")[1])
    assert w5 == pytest.approx(perf["devices"]["M5"]["W"], abs=1e-10)
    assert l5 == pytest.approx(perf["devices"]["M5"]["L"], abs=1e-10)
    assert bias == pytest.approx(perf["Vbias_tail"], abs=5e-7)
    # Re-evaluation at the exported precision re-derives the saturation
    # verdict explicitly (a convergence-diagnostic fixture stays failing).
    rec = evaluate_design_finite(ota, list(NOMINAL), dict(LOOSE_SPECS))
    assert rec["verdict"] is False
    assert rec["metrics"]["sat_m5"] < 0.0


def test_finite_netlist_requires_solved_bias(engine):
    """The historical zero-volt gate export is gone: an imposed-finite
    evaluation (no solved gate bias) refuses to export instead of emitting
    an unverifiable circuit."""
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="imposed")
    perf = ota.evaluate(list(NOMINAL), CL=1e-12)
    with pytest.raises(ValueError, match="Vbias_tail"):
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

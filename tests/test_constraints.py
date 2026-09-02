import numpy as np
import pytest

from analog_ai.evaluation.constraints import evaluate_constraints


def _perf(gain=30.0, gbw=100e6, power=100e-6, pm=60.0, sat=0.1,
          w1=20e-6, w3=40e-6, swing=0.9):
    devices = {
        "M1": {"W": w1, "L": 0.5e-6}, "M2": {"W": w1, "L": 0.5e-6},
        "M3": {"W": w3, "L": 0.3e-6}, "M4": {"W": w3, "L": 0.3e-6},
        "M5": {"W": 0.0, "L": 0.0},
    }
    return {"DC_Gain_dB": gain, "GBW": gbw, "Power": power, "PM": pm,
            "min_sat_margin": sat, "SR": 50e6, "Swing": swing, "ICMR_min": 0.5,
            "devices": devices}


SPECS = {"Gain_min": 30.0, "GBW_min": 100e6, "Power_max": 100e-6, "CL_pF": 1.0}


def test_all_satisfied_passes():
    _, verdict = evaluate_constraints(_perf(), SPECS)
    assert verdict


def test_exact_boundary_passes():
    _, verdict = evaluate_constraints(_perf(), SPECS)
    # achieved == limit for every spec -> every residual is exactly 0
    cons, _ = evaluate_constraints(_perf(), SPECS)
    by_name = {c.name: c for c in cons}
    assert by_name["Gain_min"].residual == 0.0
    assert by_name["GBW_min"].residual == 0.0
    assert by_name["Power_max"].residual == 0.0
    assert verdict


def test_each_violation_fails():
    variants = [
        _perf(gain=29.999), _perf(gbw=99e6), _perf(power=100.001e-6),
        _perf(pm=44.9), _perf(sat=0.049), _perf(w1=250.1e-6), _perf(w3=750.1e-6),
    ]
    for perf in variants:
        _, verdict = evaluate_constraints(perf, SPECS)
        assert not verdict, f"expected FAIL for {perf}"


def test_nan_gbw_fails_with_detail():
    cons, verdict = evaluate_constraints(_perf(gbw=float("nan")), SPECS)
    gbw = {c.name: c for c in cons}["GBW_min"]
    assert not gbw.passed and not verdict
    assert "not available" in gbw.detail


def test_invalid_perf_fails():
    _, verdict = evaluate_constraints(None, SPECS)
    assert not verdict


def test_optional_specs_enforced_only_when_present():
    cons, _ = evaluate_constraints(_perf(swing=0.5),
                                   {**SPECS, "Swing_min": 0.8})
    names = {c.name for c in cons}
    assert "Swing_min" in names
    _, v2 = evaluate_constraints(_perf(swing=0.5), SPECS)
    assert v2  # without the spec, swing is not enforced

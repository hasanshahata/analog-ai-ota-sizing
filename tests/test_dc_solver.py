"""Tests for the LUT-based self-consistent DC operating-point solve.

These validate the "LUTs replace Spectre" chain end to end: the solved point
must satisfy KCL by construction, respect the LUT domain, and produce AC
metrics consistent with the solved bias.
"""

import numpy as np
import pytest

from analog_ai.circuit.ota5t import InvalidDesignError, OTA5T


@pytest.fixture(scope="module")
def solved_ota(engine):
    dm, _ = engine
    return OTA5T(dm, vdd=1.2, tail_device="ideal", op_point="solved")


def test_kcl_satisfied_at_solution(solved_ota):
    perf = solved_ota.evaluate([0.6e-6, 15.0, 0.6e-6, 12.0, 50e-6], CL=1e-12)
    r = perf["kcl_residuals"]
    assert abs(r["tail"]) < 1e-10
    assert abs(r["mirror"]) < 1e-10
    assert abs(r["output"]) < 1e-10


def test_solved_voltages_are_physical(solved_ota):
    perf = solved_ota.evaluate([0.6e-6, 15.0, 0.6e-6, 12.0, 50e-6], CL=1e-12)
    vt, vm, vo = perf["Vtail"], perf["Vmirror"], perf["Vout"]
    assert 0.0 < vt < 1.2
    assert 0.0 < vm < 1.2
    assert vt < vo < 1.2          # output node inside the supply rails
    assert perf["devices"]["M1"]["VDS"] > 0.0
    assert perf["devices"]["M2"]["VDS"] > 0.0


def test_solved_differs_from_imposed(engine, solved_ota):
    """The imposed point (Vout = VDD/2) is generally NOT the balanced point."""
    dm, imposed = engine
    x = [0.6e-6, 15.0, 0.6e-6, 12.0, 50e-6]
    p_imp = imposed.evaluate(x, CL=1e-12)
    p_sol = solved_ota.evaluate(x, CL=1e-12)
    # Imposed mode pins the output node to VDD/2 by construction (no Vout in
    # its record); the solved point must NOT generally sit there.
    assert p_sol["Vout"] != pytest.approx(0.6, abs=1e-6)
    # Currents balance at the solved point:
    itail = 50e-6
    i1 = p_sol["devices"]["M1"]["ID"]
    i2 = p_sol["devices"]["M2"]["ID"]
    assert i1 + i2 == pytest.approx(itail, rel=1e-6)
    assert p_sol["devices"]["M4"]["ID"] == pytest.approx(i2, rel=1e-6)


def test_matched_geometry_at_solved_point(solved_ota):
    perf = solved_ota.evaluate([0.42e-6, 14.0, 0.75e-6, 11.0, 87e-6], CL=2.2e-12)
    d = perf["devices"]
    assert d["M1"]["W"] == d["M2"]["W"]
    assert d["M3"]["W"] == d["M4"]["W"]


def test_solved_metrics_finite(solved_ota):
    perf = solved_ota.evaluate([0.6e-6, 15.0, 0.6e-6, 12.0, 50e-6], CL=1e-12)
    assert perf["gbw_valid"]
    assert np.isfinite([perf["DC_Gain_dB"], perf["GBW"], perf["PM"],
                        perf["min_sat_margin"]]).all()
    # gm/Id achieved at the solved bias is reported against the target.
    gs = perf["gmid_solved"]["M1"]
    assert abs(gs["achieved"] - gs["target"]) < 5.0


def test_unsolvable_design_rejected(solved_ota):
    # gmid1 = 5 demands more headroom than Vicm provides -> no valid op point.
    with pytest.raises((InvalidDesignError, ValueError)):
        solved_ota.evaluate([0.6e-6, 5.0, 0.6e-6, 12.0, 50e-6], CL=1e-12)
    with pytest.raises(InvalidDesignError):
        solved_ota.evaluate([0.6e-6, 15.0, 0.6e-6, 12.0, -1e-6], CL=1e-12)


def test_power_unchanged_by_op_point_mode(solved_ota, engine):
    _, imposed = engine
    x = [0.6e-6, 15.0, 0.6e-6, 12.0, 50e-6]
    assert solved_ota.evaluate(x, CL=1e-12)["Power"] == \
        pytest.approx(imposed.evaluate(x, CL=1e-12)["Power"])

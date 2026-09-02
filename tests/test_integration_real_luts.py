"""Integration test against the real TSMC 65nm LUTs.

Skipped automatically when the 2.76 GB pickles are not present (e.g. CI).
Requires ~6 GB of RAM and roughly half a minute to load.
"""

import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LUT_DIR = os.path.join(REPO_ROOT, "tech_luts")

pytestmark = pytest.mark.skipif(
    not (os.path.exists(os.path.join(LUT_DIR, "TSMC_fast_65nm_nch.pkl"))
         and os.path.getsize(os.path.join(LUT_DIR, "TSMC_fast_65nm_nch.pkl")) > 1_000_000),
    reason="real TSMC LUTs not present",
)


@pytest.fixture(scope="module")
def real_engine():
    from analog_ai.loader import load_engine
    return load_engine()


def test_real_lut_hand_design_passes(real_engine):
    """A hand-picked feasible design must fully verify on the real LUTs."""
    from analog_ai.evaluation.evaluator import evaluate_design

    _, ota = real_engine
    specs = {"Gain_min": 20.0, "GBW_min": 20e6, "Power_max": 400e-6, "CL_pF": 1.0}
    rec = evaluate_design(ota, [0.5e-6, 15.0, 1.0e-6, 12.0, 120e-6], specs)
    assert rec["metrics"] is not None, rec.get("invalid_reason")
    assert rec["verdict"] is True, rec["constraints"]
    assert rec["metrics"]["DC_Gain_dB"] == pytest.approx(31.4, abs=0.5)
    assert rec["metrics"]["GBW"] == pytest.approx(103e6, rel=0.05)
    assert rec["metrics"]["PM"] == pytest.approx(75.0, abs=3.0)
    # Matched pairs on real data too:
    assert rec["devices"]["M1"]["W"] == rec["devices"]["M2"]["W"]
    assert rec["devices"]["M3"]["W"] == rec["devices"]["M4"]["W"]


def test_real_lut_infeasible_bias_rejected(real_engine):
    """gm/Id = 10 at L=500nm demands VGS1 > Vicm -> must be rejected, not clamped."""
    from analog_ai.evaluation.evaluator import evaluate_design

    _, ota = real_engine
    specs = {"Gain_min": 20.0, "GBW_min": 20e6, "Power_max": 400e-6, "CL_pF": 1.0}
    rec = evaluate_design(ota, [0.5e-6, 10.0, 1.0e-6, 12.0, 120e-6], specs)
    assert rec["verdict"] is False
    assert rec["metrics"] is None
    assert "Vtail" in rec.get("invalid_reason", "")


def test_real_lut_solved_operating_point(real_engine):
    """KCL-solved mode: currents balance and the achieved gm/Id hits target."""
    from analog_ai.circuit.ota5t import OTA5T

    dm, _ = real_engine
    ota = OTA5T(dm, vdd=1.2, tail_device="ideal", op_point="solved")
    perf = ota.evaluate([0.5e-6, 15.0, 1.0e-6, 12.0, 120e-6], CL=1e-12)

    r = perf["kcl_residuals"]
    assert max(abs(v) for v in r.values()) < 1e-9
    i1 = perf["devices"]["M1"]["ID"]
    i2 = perf["devices"]["M2"]["ID"]
    assert i1 + i2 == pytest.approx(120e-6, rel=1e-6)
    assert perf["devices"]["M4"]["ID"] == pytest.approx(i2, rel=1e-6)
    gs = perf["gmid_solved"]
    assert gs["M1"]["achieved"] == pytest.approx(15.0, abs=0.5)
    assert gs["M3"]["achieved"] == pytest.approx(12.0, abs=0.5)
    assert 0.0 < perf["Vout"] < 1.2
    assert perf["gbw_valid"]
    assert perf["DC_Gain_dB"] == pytest.approx(31.7, abs=0.5)

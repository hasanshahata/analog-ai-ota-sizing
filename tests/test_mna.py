"""Analytical validation of the MNA stamps and metric extraction.

Reference solution (independent of the code under test): a symmetric 5T OTA
with an ideal tail (gds5 = 0), no body effect, no parasitic capacitances, and
a stiff mirror (gm3 = gm4 >> gm1) has

    Av0 = gm1 * (ro2 || ro4) = gm1 / (gds2 + gds4)
    fp  = 1 / (2*pi*CL*(ro2 || ro4))
    GBW = Av0 * fp = gm1 / (2*pi*CL)
    PM  = 90 deg    (single dominant pole)
"""

import numpy as np
import pytest

from analog_ai.circuit.mna import MNAEngine


def _device(gm, gds, gmbs=0.0, cgs=0.0, cgd=0.0, cdd=0.0):
    return {"gm": gm, "gds": gds, "gmbs": gmbs, "cgs": cgs, "cgd": cgd,
            "cdd": cdd, "W": 1e-6, "L": 0.5e-6, "VDSAT": 0.1, "VDS": 0.6}


def _ideal_tail():
    return {"gm": 0.0, "gds": 0.0, "gmbs": 0.0, "cgs": 0.0, "cgd": 0.0,
            "cdd": 0.0, "W": 0.0, "L": 0.0, "VDSAT": 0.0, "VDS": 0.2}


@pytest.fixture
def symmetric_case():
    gm1 = 1e-3          # 1 mS
    gds_in = 5e-5       # ro = 20 kOhm each -> Rout = 10 kOhm
    gm_mirror = 0.1     # stiff mirror
    gds_mirror = 5e-5
    CL = 10e-12
    m1 = m2 = _device(gm1, gds_in)
    m3 = m4 = _device(gm_mirror, gds_mirror)
    return m1, m2, m3, m4, _ideal_tail(), CL


def test_dc_gain_matches_textbook(symmetric_case):
    m1, m2, m3, m4, m5, CL = symmetric_case
    eng = MNAEngine()
    v = eng.solve_ac(m1, m2, m3, m4, m5, CL, np.array([1.0]))  # 1 Hz
    av0_expected = m1["gm"] / (m2["gds"] + m4["gds"])          # gm*(ro2||ro4)
    assert abs(v[0]) == pytest.approx(av0_expected, rel=0.05)


def test_single_pole_gbw_and_pm(symmetric_case):
    m1, m2, m3, m4, m5, CL = symmetric_case
    eng = MNAEngine()
    freqs = np.logspace(3, 10, 700)
    v = eng.solve_ac(m1, m2, m3, m4, m5, CL, freqs)
    met = eng.extract_metrics(freqs, v)
    gbw_expected = m1["gm"] / (2 * np.pi * CL)
    assert met["gbw_valid"]
    assert met["GBW"] == pytest.approx(gbw_expected, rel=0.05)
    # Exact single-pole phase at the 0 dB crossing: |H|=1 at f = fp*sqrt(A0^2-1),
    # so PM = 180 - atan(sqrt(A0^2-1)) -- above 90 deg for this low-gain case.
    av0 = m1["gm"] / (m2["gds"] + m4["gds"])
    pm_expected = 180.0 - np.degrees(np.arctan(np.sqrt(av0**2 - 1)))
    assert met["PM"] == pytest.approx(pm_expected, abs=1.0)


def test_body_effect_reduces_gain(symmetric_case):
    """Adding gmbs at the tail node must lower the differential gain."""
    m1, m2, m3, m4, m5, CL = symmetric_case
    eng = MNAEngine()
    freqs = np.array([1.0])
    v0 = abs(eng.solve_ac(m1, m2, m3, m4, m5, CL, freqs)[0])
    m1b = dict(m1, gmbs=0.2 * m1["gm"])
    m2b = dict(m2, gmbs=0.2 * m2["gm"])
    v1 = abs(eng.solve_ac(m1b, m2b, m3, m4, m5, CL, freqs)[0])
    assert v1 < v0


def test_capacitance_stamps_influence_solution(symmetric_case):
    """Regression guard: device capacitances must enter the solve.

    (The legacy engine carried dead zeroed terms; this catches any silent
    removal of the capacitive stamps.)
    """
    m1, m2, m3, m4, m5, CL = symmetric_case
    eng = MNAEngine()
    freqs = np.logspace(6, 9, 50)
    v0 = eng.solve_ac(m1, m2, m3, m4, m5, CL, freqs)
    m3c = dict(m3, cgs=300e-15)
    m4c = dict(m4, cgs=300e-15)
    m2c = dict(m2, cdd=50e-15)
    v1 = eng.solve_ac(m1, m2c, m3c, m4c, m5, CL, freqs)
    assert np.max(np.abs(v1 - v0)) > 1e-6


def _synthetic_two_pole(freqs, av0, p1, p2):
    s = 1j * 2 * np.pi * freqs
    return av0 / ((1.0 + s / p1) * (1.0 + s / p2))


def test_two_pole_pm_extraction_with_unwrap():
    """Multi-pole response crossing -180 deg: extraction must unwrap phase.

    A0 = 100, p1 = 2 MHz, p2 = 20 MHz: the 0 dB crossing lies where the
    accumulated phase is far past -90 deg, and np.angle wraps near -180,
    so this exercises the unwrapping path end to end.
    """
    eng = MNAEngine()
    freqs = np.logspace(4, 10, 4000)
    av0, p1, p2 = 100.0, 2e6, 20e6
    H = _synthetic_two_pole(freqs, av0, p1, p2)
    met = eng.extract_metrics(freqs, H)

    mags = np.abs(H)
    assert met["gbw_valid"]
    # Ground truth via the same transfer function: find |H| = 1 by bisection.
    from scipy.optimize import brentq

    def mag_db(f):
        return 20 * np.log10(abs(av0 / ((1 + 2j * np.pi * f / p1) * (1 + 2j * np.pi * f / p2))))

    f_gbw = brentq(mag_db, 1e6, 1e9)
    assert met["GBW"] == pytest.approx(f_gbw, rel=0.01)
    phase_at_gbw = np.degrees(np.angle(av0 / ((1 + 2j * np.pi * f_gbw / p1) * (1 + 2j * np.pi * f_gbw / p2))))
    assert met["PM"] == pytest.approx(180.0 + phase_at_gbw, abs=0.5)
    assert met["PM"] < 30.0  # decisively degraded by the second pole


def _synthetic_one_pole(freqs, av0, fp):
    return av0 / (1.0 + 1j * freqs / fp)


def test_extract_metrics_known_response():
    eng = MNAEngine()
    freqs = np.logspace(2, 9, 500)
    av0, fp = 100.0, 2e6
    met = eng.extract_metrics(freqs, _synthetic_one_pole(freqs, av0, fp))
    assert met["DC_Gain_dB"] == pytest.approx(40.0, abs=0.01)
    assert met["GBW"] == pytest.approx(av0 * fp, rel=0.01)
    # exact single-pole value: 180 - atan(sqrt(100^2-1)) = 90.57 deg
    pm_expected = 180.0 - np.degrees(np.arctan(np.sqrt(av0**2 - 1)))
    assert met["PM"] == pytest.approx(pm_expected, abs=0.5)


def test_extract_metrics_no_crossing_flagged():
    eng = MNAEngine()
    freqs = np.logspace(2, 9, 200)
    met = eng.extract_metrics(freqs, _synthetic_one_pole(freqs, 0.5, 1e6))
    assert not met["gbw_valid"]
    assert np.isnan(met["GBW"])

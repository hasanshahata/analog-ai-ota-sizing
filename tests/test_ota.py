import numpy as np
import pytest

from analog_ai.circuit.ota5t import InvalidDesignError


def test_power_is_vdd_times_itail(engine):
    _, ota = engine
    perf = ota.evaluate([0.6e-6, 10.0, 0.6e-6, 12.0, 50e-6], CL=1e-12)
    assert perf["Power"] == pytest.approx(1.2 * 50e-6)


def test_matched_pairs_share_geometry(engine):
    """The core physics fix: a 'matched pair' must come out with one width."""
    _, ota = engine
    perf = ota.evaluate([0.42e-6, 9.0, 0.75e-6, 13.0, 87e-6], CL=2.2e-12)
    d = perf["devices"]
    assert d["M1"]["W"] == d["M2"]["W"]
    assert d["M1"]["L"] == d["M2"]["L"]
    assert d["M3"]["W"] == d["M4"]["W"]
    assert d["M3"]["L"] == d["M4"]["L"]
    # ... while still being characterized at their own VDS:
    assert d["M2"]["VDS"] != d["M1"]["VDS"]


def test_metrics_reasonable(engine):
    _, ota = engine
    perf = ota.evaluate([0.6e-6, 10.0, 0.6e-6, 12.0, 50e-6], CL=1e-12)
    assert perf["DC_Gain_dB"] > 0.0
    assert perf["gbw_valid"]
    assert perf["GBW"] > 1e6
    assert 0.0 < perf["PM"] < 180.0
    assert np.isfinite(perf["pair_current_mismatch"])
    assert np.isfinite(perf["mirror_current_mismatch"])


def test_invalid_designs_rejected(engine):
    _, ota = engine
    with pytest.raises(InvalidDesignError):
        ota.evaluate([0.6e-6, 10.0, 0.6e-6, 12.0, -50e-6], CL=1e-12)  # negative Itail
    with pytest.raises(InvalidDesignError):
        ota.evaluate([0.6e-6, 10.0, 0.6e-6, 12.0, 50e-6], CL=0.0)     # zero load
    with pytest.raises(InvalidDesignError):
        ota.evaluate([0.6e-6, 10.0, 0.6e-6, 12.0], CL=1e-12)           # wrong arity


def test_vgs_beyond_common_mode_is_invalid(engine):
    """Very low gm/Id forces a large VGS1, leaving no headroom for Vtail."""
    _, ota = engine
    # gmid1 = 5 => overdrive ~0.4 V => VGS1 ~ 0.75 V > Vicm => Vtail < 0.
    with pytest.raises((InvalidDesignError, ValueError)):
        ota.evaluate([0.6e-6, 5.0, 0.6e-6, 12.0, 50e-6], CL=1e-12)


def test_finite_tail_mode(engine):
    dm, _ = engine
    from analog_ai.circuit.ota5t import OTA5T
    ota7 = OTA5T(dm, vdd=1.2, tail_device="finite")
    x = [0.6e-6, 10.0, 0.6e-6, 12.0, 0.5e-6, 10.0, 50e-6]
    perf = ota7.evaluate(x, CL=1e-12)
    assert perf["devices"]["M5"]["W"] > 0.0
    assert np.isfinite(perf["sat_m5"])
    assert perf["Area"] > 0
    with pytest.raises(InvalidDesignError):
        OTA5T(dm, tail_device="ideal").evaluate(x, CL=1e-12)  # wrong arity

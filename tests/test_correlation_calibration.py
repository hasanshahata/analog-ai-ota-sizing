from __future__ import annotations

import pytest

from analog_ai.correlation.calibration import (GBW_GUARD_BAND,
                                                analyze_gbw_calibration,
                                                guarded_specs)


def test_guarded_specs_changes_only_internal_gbw_target():
    user = {"Gain_min": 30.0, "GBW_min": 100e6,
            "CL_pF": 1.0, "Power_max": 100e-6}
    internal = guarded_specs(user)
    assert internal["GBW_min"] == pytest.approx(125e6)
    assert internal["Gain_min"] == user["Gain_min"]
    assert internal["CL_pF"] == user["CL_pF"]
    assert internal["Power_max"] == user["Power_max"]
    assert user["GBW_min"] == 100e6
    assert GBW_GUARD_BAND == 0.25


def test_calibration_uses_worst_one_sided_ratio_and_rounds_up():
    records = [
        {"status": "completed", "expected": {"gbw_Hz": 100.0},
         "spectre": {"gbw_Hz": 95.0}},
        {"status": "completed", "expected": {"gbw_Hz": 100.0},
         "spectre": {"gbw_Hz": 83.0}},
    ]
    out = analyze_gbw_calibration(records)
    assert out["spectre_over_lut_ratio"]["minimum"] == pytest.approx(0.83)
    assert out["required_lut_uplift"]["maximum_observed"] == \
        pytest.approx(1 / 0.83 - 1)
    assert out["required_lut_uplift"]["rounded_to_step"] == 0.25


def test_calibration_rejects_empty_or_invalid_evidence():
    with pytest.raises(ValueError, match="no completed"):
        analyze_gbw_calibration([])
    with pytest.raises(ValueError, match="positive and finite"):
        analyze_gbw_calibration([
            {"status": "completed", "expected": {"gbw_Hz": 100.0},
             "spectre": {"gbw_Hz": 0.0}}])


def test_tiered_band_v2_policy():
    from analog_ai.correlation.calibration import (
        BAND_IN_DOMAIN, BAND_OUT_OF_DOMAIN, DOMAIN_MAX_GBW_HZ,
        V2_POLICY_VERSION, tiered_guard_band, tiered_policy_record)
    # in-domain tier covers the whole app request range
    assert tiered_guard_band(50e6) == BAND_IN_DOMAIN == 0.18
    assert tiered_guard_band(300e6) == 0.18
    assert tiered_guard_band(300e6 + 1) == BAND_OUT_OF_DOMAIN == 0.25
    rec = tiered_policy_record(100e6)
    assert rec["version"] == V2_POLICY_VERSION == "tt-ideal-tail-gbw-v2-tiered"
    assert rec["gbw_guard_band"] == 0.18
    assert rec["tier"] == "in_domain"
    assert rec["provisional"] is True
    assert "pending" in rec["validation"]
    with pytest.raises(ValueError):
        tiered_guard_band(0.0)
    with pytest.raises(ValueError):
        tiered_guard_band(float("nan"))

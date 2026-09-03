from __future__ import annotations

import numpy as np
import pytest

import analog_ai.sizing as sizing


SPECS = {"Gain_min": 30.0, "GBW_min": 100e6,
         "CL_pF": 1.0, "Power_max": 100e-6}


class FakeOTA:
    def evaluate(self, design, CL):
        assert CL == pytest.approx(1e-12)
        return {
            "DC_Gain_dB": 31.0, "GBW": 126e6, "PM": 75.0,
            "Power": 90e-6, "Vout": 0.6, "Vtail": 0.2,
            "Vmirror": 0.6, "SR": 1e8, "Swing": 0.8,
            "ICMR_min": 0.5, "min_sat_margin": 0.1, "Area": 1e-10,
            "devices": {"M1": {"L": 0.5e-6, "W": 20e-6},
                        "M3": {"L": 0.6e-6, "W": 10e-6}},
        }


def test_guarded_sizing_uses_internal_contract_and_preserves_user(monkeypatch):
    seen = {}

    def fake_staged(ota, model, specs, lo, hi, **kwargs):
        seen.update(specs)
        return {"status": "verified", "design": [0.5e-6, 15, 0.6e-6, 12, 75e-6],
                "n_oracle_evals": 5}

    monkeypatch.setattr(sizing, "eval_request_staged", fake_staged)
    original = dict(SPECS)
    out = sizing.size_ideal_tail_ota(FakeOTA(), object(), SPECS,
                                     np.zeros(4), np.ones(4))
    assert SPECS == original
    assert seen["GBW_min"] == pytest.approx(125e6)
    assert out["user_specs"]["GBW_min"] == 100e6
    assert out["internal_specs"]["GBW_min"] == 125e6
    assert out["user_verdict"] and out["internal_verdict"]
    assert out["calibration"]["version"] == "tt-ideal-tail-gbw-v1"
    assert out["physical_design"]["W1"] == 20e-6


def test_unresolved_sizing_is_never_reported_as_success(monkeypatch):
    monkeypatch.setattr(sizing, "eval_request_staged", lambda *a, **k: {
        "status": "unresolved", "design": [0.5e-6, 15, 0.6e-6, 12, 75e-6],
        "n_oracle_evals": 100})
    out = sizing.size_ideal_tail_ota(FakeOTA(), object(), SPECS,
                                     np.zeros(4), np.ones(4))
    assert not out["user_verdict"] and not out["internal_verdict"]
    assert out["physical_design"] is None


def test_guarded_sizing_requires_complete_black_box_input():
    with pytest.raises(ValueError, match="Power_max"):
        sizing.size_ideal_tail_ota(FakeOTA(), object(),
                                   {k: v for k, v in SPECS.items()
                                    if k != "Power_max"},
                                   np.zeros(4), np.ones(4))

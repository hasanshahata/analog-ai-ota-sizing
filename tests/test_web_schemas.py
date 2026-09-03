"""Phase W0 schema tests: the browser cannot bypass the sizing contract."""

from __future__ import annotations

import math

import numpy as np
import pytest
from pydantic import ValidationError

from analog_ai.web import schemas as S

VALID = {"Gain_min_dB": 30.0, "GBW_min_MHz": 100.0, "CL_pF": 1.0,
         "Power_max_uW": 200.0}


def _record(**over):
    base = {
        "topology": "5t_ota_ideal_tail", "corner": "tt_lib",
        "user_specs": {"Gain_min": 30.0, "GBW_min": 1e8, "CL_pF": 1.0,
                       "Power_max": 2e-4},
        "internal_specs": {"Gain_min": 30.0, "GBW_min": 1.25e8, "CL_pF": 1.0,
                           "Power_max": 2e-4},
        "calibration": {"version": "tt-ideal-tail-gbw-v1",
                        "gbw_guard_band": 0.25},
        "status": "verified", "n_oracle_evals": 5,
        "pipeline": {"stages": []},
        "design_variables": {"L1": 0.5e-6, "gmid1": 12.0, "L3": 0.6e-6,
                             "gmid3": 14.0, "Itail": 75e-6},
        "physical_design": {"L1": 0.5e-6, "W1": 20e-6, "L3": 0.6e-6,
                            "W3": 10e-6, "Itail": 75e-6},
        "lut_metrics": {"DC_Gain_dB": 31.2, "GBW": 126.4e6, "PM": 74.5,
                        "Power": 9.0e-5, "Vout": 0.61, "Vtail": 0.21,
                        "Vmirror": 0.60},
        "user_constraints": [
            {"name": "Gain_min", "kind": "min", "limit": 30.0,
             "achieved": 31.2, "residual": -0.12, "scale": 10.0,
             "passed": True, "detail": ""},
            {"name": "PM_min", "kind": "min", "limit": 45.0,
             "achieved": float("nan"), "residual": float("inf"),
             "scale": 45.0, "passed": False, "detail": "metric not there"},
        ],
        "internal_constraints": [],
        "user_verdict": True,
        "internal_verdict": True,
    }
    base.update(over)
    return base


# ------------------------------------------------------------ valid input --
def test_valid_request_converts_units_exactly():
    canon = S.SizeRequest(**VALID).to_canonical()
    assert canon["Gain_min"] == 30.0
    assert canon["GBW_min"] == pytest.approx(1e8)
    assert canon["CL_pF"] == 1.0
    assert canon["Power_max"] == pytest.approx(2e-4)


def test_domain_boundaries_accepted():
    edges = [
        {"Gain_min_dB": 20.0}, {"Gain_min_dB": 45.0},
        {"GBW_min_MHz": 50.0}, {"GBW_min_MHz": 300.0},
        {"CL_pF": 0.1}, {"CL_pF": 5.0},
        {"Power_max_uW": 50.0}, {"Power_max_uW": 400.0},
    ]
    for over in edges:
        payload = {**VALID, **over}
        assert S.SizeRequest(**payload).to_canonical() is not None


# --------------------------------------------------------- invalid input --
def test_missing_field_rejected():
    for missing in VALID:
        payload = {k: v for k, v in VALID.items() if k != missing}
        with pytest.raises(ValidationError):
            S.SizeRequest(**payload)


def test_non_finite_rejected():
    for bad in (float("nan"), float("inf"), float("-inf")):
        for field in VALID:
            with pytest.raises(ValidationError):
                S.SizeRequest(**{**VALID, field: bad})


def test_out_of_range_rejected_never_clamped():
    bads = [
        {"Gain_min_dB": 10.0}, {"Gain_min_dB": 50.0},
        {"GBW_min_MHz": 49.0}, {"GBW_min_MHz": 301.0},
        {"CL_pF": 0.05}, {"CL_pF": 6.0},
        {"Power_max_uW": 10.0}, {"Power_max_uW": 500.0},
    ]
    for over in bads:
        with pytest.raises(ValidationError):
            S.SizeRequest(**{**VALID, **over})


def test_boolean_smuggling_rejected():
    with pytest.raises(ValidationError):
        S.SizeRequest(**{**VALID, "CL_pF": True})


# ------------------------------------------------------ response freezing --
def test_unresolved_response_carries_no_geometry():
    rec = _record(status="unresolved", design_variables=None,
                  physical_design=None, lut_metrics=None,
                  user_constraints=[], user_verdict=False,
                  internal_verdict=False)
    resp = S.build_unresolved_response(rec, "req-x")
    assert resp["status"] == "unresolved"
    assert resp["design"] is None and resp["design_variables"] is None
    assert resp["lut_metrics"] is None and resp["constraints"] is None
    assert "infeasib" not in resp["explanation"].lower()
    text = repr(resp).lower()
    for key in ("w1", "l1", "w3", "l3", "itail_a"):
        assert f'"{key}"' not in text


def test_success_response_freezing_rule():
    # user verdict False -> factory refuses
    rec = _record(user_verdict=False)
    with pytest.raises(ValueError):
        S.build_success_response(rec, "req-y")
    # missing design -> factory refuses
    with pytest.raises(ValueError):
        S.build_success_response(_record(physical_design=None), "req-y")
    # verified record -> full contract present
    resp = S.build_success_response(_record(), "req-z")
    assert resp["status"] == "success"
    assert resp["verdict"] == {"user_verdict": True, "internal_verdict": True}
    assert resp["calibration"]["version"] == "tt-ideal-tail-gbw-v1"
    assert resp["design"]["m1_m2"]["w_m"] == pytest.approx(20e-6)
    assert resp["sizing_path"]["n_oracle_evals"] == 5
    assert "Cadence" in resp["scope_warning"]


def test_constraint_margin_and_nan_sanitised():
    resp = S.build_success_response(_record(), "req-m")
    rows = {c["name"]: c for c in resp["constraints"]}
    assert rows["Gain_min"]["margin"] == pytest.approx(1.2)
    assert rows["PM_min"]["achieved"] is None       # NaN -> null
    assert rows["PM_min"]["margin"] is None
    assert rows["PM_min"]["passed"] is False
    # strict JSON must be producible (no NaN/Infinity tokens)
    import json as _json
    _json.dumps(resp, allow_nan=False)


def test_domain_constraint_tuple_fields_are_json_safe():
    rec = _record(user_constraints=[
        {"name": "L_domain", "kind": "domain", "limit": (60e-9, 1.5e-6),
         "achieved": (0.5e-6, 0.6e-6), "residual": 0.0, "scale": 1.0,
         "passed": True, "detail": ""},
        {"name": "Power_max", "kind": "max", "limit": 2e-4,
         "achieved": 1.8e-4, "residual": -0.1, "scale": 2e-4,
         "passed": True, "detail": ""},
    ])
    resp = S.build_success_response(rec, "req-d")
    rows = {c["name"]: c for c in resp["constraints"]}
    assert rows["L_domain"]["margin"] is None
    assert rows["L_domain"]["limit"] == [60e-9, 1.5e-6]
    assert rows["Power_max"]["margin"] == pytest.approx(2e-5)
    import json as _json
    _json.dumps(resp, allow_nan=False)


def test_derive_status_only_allows_verified_geometry():
    assert S.derive_status(_record()) == "success"
    assert S.derive_status(_record(status="unresolved",
                                   physical_design=None,
                                   design_variables=None)) == "unresolved"
    assert S.derive_status(_record(user_verdict=False)) == "unresolved"


def test_json_safe_numpy_and_non_finite():
    out = S.json_safe({"a": np.float32(1.5), "b": np.int64(2),
                       "c": float("nan"), "d": np.float64(float("inf")),
                       "e": [np.bool_(True)]})
    assert out["a"] == pytest.approx(1.5)
    assert out["b"] == 2
    assert out["c"] is None and out["d"] is None
    assert out["e"] == [True]


def test_presentation_rounding_units():
    p = S._presentation(_record())
    assert p["m1_m2"] == {"w_um": pytest.approx(20.0, abs=1e-6),
                          "l_um": pytest.approx(0.5, abs=1e-6)}
    assert p["itail_uA"] == pytest.approx(75.0, abs=1e-6)
    assert p["metrics"]["gbw_MHz"] == pytest.approx(126.4, abs=1e-6)
    assert p["metrics"]["power_uW"] == pytest.approx(90.0, abs=1e-6)


def test_error_response_shape():
    err = S.build_error_response("not_ready", "engine loading")
    assert set(err) == {"error"} and set(err["error"]) == {"code", "message"}

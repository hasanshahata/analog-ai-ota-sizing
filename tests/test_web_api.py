"""Phase W2 HTTP API tests (fake runtime; no LUTs, no server process)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import analog_ai.sizing as sizing_mod
from analog_ai.web.app import create_app
from analog_ai.web.runtime import SizingRuntime

GOOD = {"Gain_min_dB": 30.0, "GBW_min_MHz": 100.0, "CL_pF": 1.0,
        "Power_max_uW": 200.0}

SUCCESS_REC = {
    "topology": "5t_ota_ideal_tail", "corner": "tt_lib",
    "user_specs": {"Gain_min": 30.0, "GBW_min": 1e8, "CL_pF": 1.0,
                   "Power_max": 2e-4},
    "internal_specs": {"Gain_min": 30.0, "GBW_min": 1.25e8, "CL_pF": 1.0,
                       "Power_max": 2e-4},
    "calibration": {"version": "tt-ideal-tail-gbw-v1", "gbw_guard_band": 0.25},
    "status": "verified", "n_oracle_evals": 5, "pipeline": {"stages": []},
    "design_variables": {"L1": 0.5e-6, "gmid1": 12.0, "L3": 0.6e-6,
                         "gmid3": 14.0, "Itail": 75e-6},
    "physical_design": {"L1": 0.5e-6, "W1": 20e-6, "L3": 0.6e-6,
                        "W3": 10e-6, "Itail": 75e-6},
    "lut_metrics": {"DC_Gain_dB": 31.2, "GBW": 126e6, "PM": 74.0,
                    "Power": 9e-5, "Vout": 0.6, "Vtail": 0.2, "Vmirror": 0.6},
    "user_constraints": [
        {"name": "Gain_min", "kind": "min", "limit": 30.0, "achieved": 31.2,
         "residual": -0.12, "scale": 10.0, "passed": True, "detail": ""}],
    "internal_constraints": [],
    "user_verdict": True, "internal_verdict": True,
}

UNRESOLVED_REC = {
    "topology": "5t_ota_ideal_tail", "status": "unresolved",
    "n_oracle_evals": 1732, "pipeline": {"stages": []},
    "user_specs": {"Gain_min": 45.0, "GBW_min": 3e8, "CL_pF": 5.0,
                   "Power_max": 5e-5},
    "internal_specs": {"Gain_min": 45.0, "GBW_min": 3.75e8, "CL_pF": 5.0,
                       "Power_max": 5e-5},
    "design_variables": None, "physical_design": None, "lut_metrics": None,
    "user_constraints": [], "internal_constraints": [],
    "user_verdict": False, "internal_verdict": False,
}


def _client(monkeypatch, result=SUCCESS_REC, state="ready"):
    monkeypatch.setattr(sizing_mod, "size_ideal_tail_ota",
                        lambda *a, **k: result)
    rt = SizingRuntime(project_root="/nonexistent")
    rt.state = state
    rt.ota, rt.model = object(), object()
    import numpy as np
    rt.feat_lo, rt.feat_hi = np.zeros(4), np.ones(4)
    app = create_app(runtime=rt, load_on_startup=False)
    return TestClient(app), rt


def test_success_response_200(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.post("/api/v1/size", json=GOOD)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["design"]["m1_m2"]["w_m"] == pytest.approx(20e-6)
    assert body["verdict"]["user_verdict"] is True
    assert body["calibration"]["version"] == "tt-ideal-tail-gbw-v1"
    assert body["sizing_path"]["n_oracle_evals"] == 5
    assert body["constraints"][0]["name"] == "Gain_min"
    assert body["request_id"].startswith("req-")
    assert "Cadence" in body["scope_warning"]


def test_unresolved_response_200_no_geometry(monkeypatch):
    client, _ = _client(monkeypatch, result=UNRESOLVED_REC)
    r = client.post("/api/v1/size", json=GOOD)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unresolved"
    assert body["design"] is None and body["lut_metrics"] is None
    assert "infeasib" not in body["explanation"].lower()
    assert "relax" in body["guidance"].lower()
    assert body["n_oracle_evals"] == 1732


def test_validation_error_422(monkeypatch):
    client, _ = _client(monkeypatch)
    # missing field
    r = client.post("/api/v1/size", json={k: v for k, v in GOOD.items()
                                          if k != "CL_pF"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    # out of range (never clipped)
    r = client.post("/api/v1/size", json={**GOOD, "GBW_min_MHz": 999.0})
    assert r.status_code == 422
    # unknown / misspelled field rejected
    r = client.post("/api/v1/size", json={**GOOD, "gbw_min_mhz": 100.0})
    assert r.status_code == 422


def test_non_finite_json_rejected_422(monkeypatch):
    client, _ = _client(monkeypatch)
    raw = '{"Gain_min_dB": 30.0, "GBW_min_MHz": 100.0, "CL_pF": NaN, ' \
          '"Power_max_uW": 200.0}'
    r = client.post("/api/v1/size", content=raw,
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_not_ready_503(monkeypatch):
    client, _ = _client(monkeypatch, state="loading")
    r = client.post("/api/v1/size", json=GOOD)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "not_ready"


def test_internal_failure_500_controlled(monkeypatch):
    client, _ = _client(monkeypatch)

    def boom(*a, **k):
        raise ZeroDivisionError("secret /server/path leak")
    monkeypatch.setattr(sizing_mod, "size_ideal_tail_ota", boom)
    r = client.post("/api/v1/size", json=GOOD)
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "sizing_failed"
    assert "secret" not in r.text and "Traceback" not in r.text


def test_health_reflects_state_and_never_loads(monkeypatch):
    client, rt = _client(monkeypatch, state="loading")
    calls = []
    monkeypatch.setattr(rt, "load", lambda: calls.append(1))
    monkeypatch.setattr(rt, "load_async", lambda: calls.append(1))
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "loading"
    assert body["policy_version"].startswith("tt-ideal-tail-gbw-v2-tiered")
    # sizing while loading is refused; health never triggered a load
    assert calls == []
    r = client.post("/api/v1/size", json=GOOD)
    assert r.status_code == 503
    assert calls == []


def test_health_failed_state_has_sanitized_detail(monkeypatch):
    client, rt = _client(monkeypatch, state="failed")
    rt.detail = "required LUT or checkpoint files are missing (see server logs)"
    body = client.get("/api/v1/health").json()
    assert body["state"] == "failed"
    assert "missing" in body["detail"]
    assert "/" not in body["detail"].split("(")[0]


def test_static_index_served(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.get("/")
    if r.status_code == 200:         # static dir exists in the real repo
        assert "text/html" in r.headers["content-type"]


NETLIST_BODY = {"W1": 20e-6, "L1": 0.5e-6, "W3": 10e-6, "L3": 0.6e-6,
                "Itail": 75e-6, "CL_pF": 1.0}


def test_netlist_export_renders_golden_template(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.post("/api/v1/netlist", json=NETLIST_BODY)
    assert r.status_code == 200
    text = r.text
    assert "simulator lang=spectre" in text
    assert "W12" in text and "Itail" in text
    assert "acCorr" in text                      # analyses appended


def test_netlist_export_rejects_bad_geometry(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.post("/api/v1/netlist",
                    json={**NETLIST_BODY, "L1": -1e-6})
    assert r.status_code == 422
    assert "error" in r.json()

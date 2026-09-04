"""Phase W1 runtime tests with a fake engine (no LUTs, no torch load)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest

import analog_ai.sizing as sizing_mod
from analog_ai.web import runtime as rt_mod
from analog_ai.web.runtime import (RuntimeNotReady, SizingFailure,
                                   SizingRuntime)

CANON = {"Gain_min": 30.0, "GBW_min": 1e8, "CL_pF": 1.0, "Power_max": 2e-4}


def _ready_runtime(monkeypatch, captured: dict | None = None,
                   sizing_result: dict | None = None,
                   delay: float = 0.0) -> SizingRuntime:
    def fake_size(ota, model, user_specs, lo, hi, **kwargs):
        if captured is not None:
            captured.update({"ota": ota, "model": model, "specs": dict(user_specs),
                             "lo": lo, "hi": hi,
                             "kwargs": kwargs})
        if delay:
            time.sleep(delay)
        if sizing_result is not None:
            return sizing_result
        return {
            "topology": "5t_ota_ideal_tail", "corner": "tt_lib",
            "user_specs": dict(user_specs),
            "internal_specs": {**user_specs, "GBW_min": user_specs["GBW_min"] * 1.25},
            "calibration": {"version": "tt-ideal-tail-gbw-v1"},
            "status": "verified", "n_oracle_evals": 5, "pipeline": {"stages": []},
            "design_variables": {"L1": 0.5e-6, "gmid1": 12.0, "L3": 0.6e-6,
                                 "gmid3": 14.0, "Itail": 75e-6},
            "physical_design": {"L1": 0.5e-6, "W1": 20e-6, "L3": 0.6e-6,
                                "W3": 10e-6, "Itail": 75e-6},
            "lut_metrics": {"DC_Gain_dB": 31.2, "GBW": 126e6, "PM": 74.0,
                            "Power": 9e-5, "Vout": 0.6, "Vtail": 0.2,
                            "Vmirror": 0.6},
            "user_constraints": [], "internal_constraints": [],
            "user_verdict": True, "internal_verdict": True,
        }

    monkeypatch.setattr(sizing_mod, "size_ideal_tail_ota", fake_size)
    rt = SizingRuntime(project_root=Path(__file__).resolve().parents[1])
    rt.state = "ready"
    rt.ota = object()
    rt.model = object()
    rt.feat_lo = np.zeros(4)
    rt.feat_hi = np.ones(4)
    return rt


def test_project_root_is_repo_root_regardless_of_cwd():
    rt = SizingRuntime(project_root=None)
    assert rt.root == Path(rt_mod.__file__).resolve().parents[2]
    assert rt.lut_dir == rt.root / "tech_luts"
    assert rt.ckpt_dir == rt.root / "models" / "surrogate" / "poc"


def test_converted_request_reaches_sizing_api_verbatim(monkeypatch):
    captured: dict = {}
    rt = _ready_runtime(monkeypatch, captured)
    payload = dict(CANON)
    rec = rt.size(payload)
    assert captured["specs"] == CANON
    assert captured["kwargs"]["seed"] == 0
    assert payload == CANON                      # caller's dict preserved
    assert rec["user_specs"] == CANON
    assert rec["status"] == "verified"


def test_size_uses_tiered_v2_policy(monkeypatch):
    captured: dict = {}
    rt = _ready_runtime(monkeypatch, captured)
    rt.size(CANON, seed=7)
    # the runtime requests the v2 tiered policy; sizing.py picks the band
    assert captured["specs"]["GBW_min"] == 1e8
    assert captured["kwargs"]["tiered_band"] is True
    assert rt.health()["policy_version"] ==         "tt-ideal-tail-gbw-v2-tiered (provisional)"


def test_unresolved_result_has_no_geometry(monkeypatch):
    rec_in = {
        "topology": "5t_ota_ideal_tail", "status": "unresolved",
        "n_oracle_evals": 1732, "pipeline": {"stages": []},
        "user_specs": dict(CANON),
        "internal_specs": {**CANON, "GBW_min": 1.25e8},
        "design_variables": None, "physical_design": None,
        "lut_metrics": None, "user_constraints": [],
        "internal_constraints": [], "user_verdict": False,
        "internal_verdict": False,
    }
    rt = _ready_runtime(monkeypatch, sizing_result=rec_in)
    rec = rt.size(CANON)
    assert rec["design_variables"] is None
    assert rec["physical_design"] is None
    assert rec["lut_metrics"] is None


def test_exception_becomes_controlled_error(monkeypatch):
    rt = _ready_runtime(monkeypatch)

    def boom(*a, **k):
        raise ZeroDivisionError("internal detail /secret/path")

    monkeypatch.setattr(sizing_mod, "size_ideal_tail_ota", boom)
    with pytest.raises(SizingFailure) as ei:
        rt.size(CANON)
    assert "secret" not in str(ei.value)
    assert "sizing failed internally" in str(ei.value)


def test_not_ready_rejected_before_any_sizing(monkeypatch):
    rt = _ready_runtime(monkeypatch)
    rt.state = "loading"
    with pytest.raises(RuntimeNotReady):
        rt.size(CANON)
    rt.state = "failed"
    rt.detail = "required LUT or checkpoint files are missing (see server logs)"
    with pytest.raises(RuntimeNotReady):
        rt.size(CANON)


def test_health_does_not_touch_engine():
    rt = SizingRuntime(project_root=Path(__file__).resolve().parents[1])
    h = rt.health()          # state loading; no engine attributes touched
    assert h["state"] == "loading"
    assert h["policy_version"] == "tt-ideal-tail-gbw-v2-tiered (provisional)"
    rt.state = "failed"
    rt.detail = "required LUT or checkpoint files are missing (see server logs)"
    assert "missing" in rt.health()["detail"]
    rt.detail = "runtime initialization failed (see server logs)"
    assert rt.health()["detail"].endswith("(see server logs)")


def test_concurrent_sizing_is_serialized(monkeypatch):
    events: list[str] = []
    rt = _ready_runtime(monkeypatch, delay=0.05)
    real_size = sizing_mod.size_ideal_tail_ota

    def wrapped(*a, **k):
        events.append("enter")
        try:
            return real_size(*a, **k)
        finally:
            events.append("exit")

    monkeypatch.setattr(sizing_mod, "size_ideal_tail_ota", wrapped)
    threads = [threading.Thread(target=rt.size, args=(CANON,))
               for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # strictly alternating enter/exit proves the single-worker lock
    assert events == ["enter", "exit"] * 3


def test_load_failure_is_recorded_not_raised(monkeypatch, tmp_path):
    rt = SizingRuntime(project_root=tmp_path)
    monkeypatch.setattr(rt_mod, "ckpt_label", lambda p: "x")  # no-op guard
    rt.load()                # champion missing under tmp root -> failed state
    assert rt.state == "failed"
    assert "missing" in rt.detail or "failed" in rt.detail

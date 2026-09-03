from __future__ import annotations

import json

from analog_ai.correlation.campaign import (compare_measurements,
                                             collect_campaign,
                                             expected_from_sizing,
                                             select_campaign_requests,
                                             write_summary)
from scripts.stage_cadence_campaign import PUBLIC_FILES, stage


def _requests():
    rows = []
    for i in range(160):
        rows.append({
            "row_id": f"r{i:03d}", "split": "test", "verdict": True,
            "label": "near_boundary" if i % 3 == 0 else "feasible",
            "req_Gain_min": 20.0 + i / 10,
            "req_GBW_min": 10e6 + i * 1e6,
            "req_CL_pF": (0.2, 1.0, 5.0)[i % 3],
            "req_Power_max": 50e-6 + i * 2e-6,
            "r_Gain_min": -0.01 - i / 10000,
            "r_GBW_min": -0.02 - i / 10000,
            "r_Power_max": -0.03 - i / 10000,
        })
    return rows


def _metrics():
    return {"dc_gain_dB": 30.0, "gbw_Hz": 100e6,
            "phase_margin_deg": 80.0, "power_W": 60e-6,
            "vout_dc_V": 0.60, "vtail_dc_V": 0.20,
            "vmirror_dc_V": 0.60}


def test_selection_is_deterministic_stratified_and_disjoint():
    a = select_campaign_requests(_requests())
    b = select_campaign_requests(_requests())
    assert [(x["category"], x["row"]["row_id"]) for x in a] == [
        (x["category"], x["row"]["row_id"]) for x in b]
    assert len(a) == 25
    assert len({x["row"]["row_id"] for x in a}) == 25
    assert {c: sum(x["category"] == c for x in a) for c in
            {x["category"] for x in a}} == {
                "low_power": 5, "high_gain": 5, "high_gbw": 5,
                "heavy_load": 5, "boundary": 5}


def test_selection_excludes_calibration_source_rows():
    first = select_campaign_requests(_requests())
    excluded = {x["row"]["row_id"] for x in first}
    second = select_campaign_requests(_requests(), excluded_ids=excluded)
    second_ids = {x["row"]["row_id"] for x in second}
    assert len(second_ids) == 25
    assert excluded.isdisjoint(second_ids)


def test_comparison_applies_absolute_and_relative_tolerances():
    expected = _metrics()
    measured = {**expected, "dc_gain_dB": 30.9,
                "gbw_Hz": 91e6, "phase_margin_deg": 75.1}
    result = compare_measurements(expected, measured)
    assert result["correlation_passed"]
    measured["gbw_Hz"] = 89e6
    assert not compare_measurements(expected, measured)["correlation_passed"]


def test_guarded_sizing_metrics_convert_to_private_expected_schema():
    record = {"lut_metrics": {
        "DC_Gain_dB": 30.0, "GBW": 100e6, "PM": 80.0,
        "Power": 60e-6, "Vout": 0.6, "Vtail": 0.2, "Vmirror": 0.6}}
    assert expected_from_sizing(record) == _metrics()


def test_stage_excludes_private_evidence(tmp_path):
    case = tmp_path / "local" / "jobs" / "c1"
    case.mkdir(parents=True)
    for name in (*PUBLIC_FILES, "request_private.json", "expected_private.json"):
        (case / name).write_text("{}")
    assert stage(tmp_path / "local", tmp_path / "shared") == 1
    names = {p.name for p in (tmp_path / "shared" / "jobs" / "c1").iterdir()}
    assert names == set(PUBLIC_FILES)


def test_collector_joins_blind_result_with_private_evidence(tmp_path):
    case = tmp_path / "local" / "jobs" / "c1"
    results = tmp_path / "results"
    case.mkdir(parents=True)
    results.mkdir()
    request = {"Gain_min": 29.0, "GBW_min": 90e6,
               "Power_max": 70e-6, "CL_pF": 1.0}
    (case / "request_private.json").write_text(json.dumps(request))
    (case / "expected_private.json").write_text(json.dumps(_metrics()))
    (case / "job.json").write_text(json.dumps(
        {"category": "boundary", "source_row_id": "r1",
         "pipeline_status": "verified"}))
    (results / "c1.json").write_text(json.dumps(
        {"case_id": "c1", **_metrics()}))
    report = collect_campaign(tmp_path / "local", results)
    assert report["counts"] == {"total": 1, "completed": 1, "pending": 0,
                                "correlation_passed": 1,
                                "false_proxy_passes": 0}
    summary = tmp_path / "summary.md"
    write_summary(report, summary)
    assert "c1" in summary.read_text() and "PASS" in summary.read_text()

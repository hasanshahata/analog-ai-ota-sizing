from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from analog_ai.correlation.finite_spectre_job import (
    DEVICE_FIELDS, DEVICE_NAMES, FiniteCorrelationJobError,
    build_finite_manual_reference, classify_capacitance_provenance,
    compare_finite_measurements,
    load_tolerances, render_finite_netlist,
)
from scripts.cadence_guest.write_finite_result import build_result, verify_inputs
from scripts.stage_finite_cadence_reference import (PUBLIC_JOB_FILES,
                                                     RUNNER_FILES, stage_finite)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "cadence_templates/5T_OTA_finite_m5_tt.scs"
TOLERANCES = ROOT / "configs/finite_m5_cadence_tolerances_v1.json"
F4 = (ROOT / "evaluation_results/finite_m5" /
      "f4_baseline_20260909_170218/f4_baseline.json")
IDEAL_HASHES = {
    "5T_OTA_netlist_cadence.txt":
        "9e2014300171939e8ccc77781bb42a63b28b468d043bd2ec90890ab116a1351c",
    "analog_ai/correlation/spectre_job.py":
        "7d0dd3c1952eeb02549546a1b994bd176853a58c4b671df2cd5c27f75e90ce24",
    "scripts/cadence_guest/run_jobs.sh":
        "05ee3bc6c5a2a605ccaafd898fdfef0abd8ba116e2ba81c4d2c594de28b6c892",
}


def _record():
    campaign = json.loads(F4.read_text())
    return next(case["finite_record"] for case in campaign["cases"]
                if case["name"] == "test5_balanced")


def _enriched():
    result = {}
    for name, device in _record()["devices"].items():
        result[name] = {**device, "gmbs": 0.2 * device["gm"],
                        "cgd": 1e-15, "cdd": 3e-15}
    return result


def test_finite_template_is_separate_complete_and_preserves_geometry_convention():
    text = TEMPLATE.read_text()
    rendered = render_finite_netlist(text, _record())
    assert "I26 (" not in rendered and "isource dc=Itail" not in rendered
    assert "VTAILBIAS (vbias_tail 0) vsource dc=VbiasTail" in rendered
    assert "L5=1.10081716009e-06" in rendered
    assert "W5=9.32292326324e-05" in rendered
    assert "VbiasTail=0.457649158167" in rendered
    for device in DEVICE_NAMES:
        line = next(line for line in text.splitlines() if line.startswith(device + " ("))
        assert "sd=200n" in line
    for token in ("ad=", "as=", "pd=", "ps=", "nrd=", "nrs=", "sa=", "sb=",
                  "sca=0", "scb=0", "scc=0"):
        assert text.count(token) == 5
    assert rendered.count("dcFinite dc") == 1
    assert rendered.count("acFinite ac") == 1


def test_ideal_cadence_sources_remain_immutable():
    for name, digest in IDEAL_HASHES.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest


def test_build_manual_reference_is_source_bound_and_complete(tmp_path):
    case = build_finite_manual_reference(TEMPLATE, TOLERANCES, F4, tmp_path,
                                         enriched_devices=_enriched())
    expected_names = set(PUBLIC_JOB_FILES) | {
        "request_private.json", "expected_private.json"}
    assert {path.name for path in case.iterdir()} == expected_names
    job = json.loads((case / "job.json").read_text())
    assert job["topology"] == "5t_ota_finite_m5"
    assert job["validation_campaign_member"] is False
    assert job["pdk_identity"]["sha256"] is None
    assert job["pdk_identity"]["status"] == "measure_on_guest_before_run"
    assert job["lut_identity"]["nch"]["verified"] is True
    assert job["lut_identity"]["pch"]["verified"] is True
    for name in ("input.scs", "measure.ocn", "capacitance_probe.scs",
                 "measure_caps.ocn", "tolerances.json", "design.json"):
        assert hashlib.sha256((case / name).read_bytes()).hexdigest() == (
            job["source_binding"][name])
    expected = json.loads((case / "expected_private.json").read_text())
    assert set(expected["devices"]) == set(DEVICE_NAMES)
    assert expected["op_enrichment"]["optimization_performed"] is False
    assert all(set(DEVICE_FIELDS) <= set(expected["devices"][name])
               for name in DEVICE_NAMES)
    ocean = (case / "measure.ocn").read_text()
    assert "selectResult('finiteOpInfo)" in ocean
    for device in DEVICE_NAMES:
        for field in ("id", "gm", "gds", "gmbs", "vdsat", "vds"):
            assert f'OP("/{device}" "{field}")' in ocean
    cap = (case / "capacitance_probe.scs").read_text()
    assert "M5CAP (d g 0 0) nch l=L5 w=W5 m=1 nf=1 sd=200n \\\n" in cap
    assert "-raw ./psf_caps" not in cap
    for token in ("ad=", "as=", "pd=", "ps=", "nrd=", "nrs=", "sa=", "sb=",
                  "sca=0", "scb=0", "scc=0"):
        assert token in cap


def test_finite_record_and_tolerance_fail_closed(tmp_path):
    record = _record()
    with pytest.raises(FiniteCorrelationJobError, match="verified"):
        render_finite_netlist(TEMPLATE.read_text(), {**record, "verdict": False})
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "wrong"}))
    with pytest.raises(FiniteCorrelationJobError, match="schema"):
        load_tolerances(bad)


def test_result_writer_verifies_sources_pdk_and_marker_arity(tmp_path):
    case = build_finite_manual_reference(TEMPLATE, TOLERANCES, F4, tmp_path,
                                         enriched_devices=_enriched())
    pdk = tmp_path / "models.scs"
    pdk.write_text("model identity")
    job_path = case / "job.json"
    job = json.loads(job_path.read_text())
    job["pdk_identity"]["include_path"] = str(pdk)
    job_path.write_text(json.dumps(job))
    _, _, resolved, pdk_record = verify_inputs(case)
    assert Path(resolved) == pdk.resolve()
    assert pdk_record["sha256"] == hashlib.sha256(pdk.read_bytes()).hexdigest()
    main_count = 10 + len(DEVICE_NAMES) * len(DEVICE_FIELDS)
    ota_log = tmp_path / "ota.log"
    cap_log = tmp_path / "cap.log"
    ota_log.write_text("ANALOG_AI_FINITE_METRICS " + " ".join(
        str(i + 1.0) for i in range(main_count)) + "\n")
    cap_log.write_text("ANALOG_AI_FINITE_CAPS 1e-15 2e-15 3e-15 4e-15\n")
    result = build_result(case, ota_log, cap_log)
    assert result["status"] == "completed"
    assert set(result["devices"]) == set(DEVICE_NAMES)
    ota_log.write_text("ANALOG_AI_FINITE_METRICS 1 2\n")
    with pytest.raises(ValueError, match="expected"):
        build_result(case, ota_log, cap_log)


def test_separate_correlation_and_complete_measured_request_gates(tmp_path):
    case = build_finite_manual_reference(TEMPLATE, TOLERANCES, F4, tmp_path,
                                         enriched_devices=_enriched())
    expected = json.loads((case / "expected_private.json").read_text())
    request = json.loads((case / "request_private.json").read_text())
    design = json.loads((case / "design.json").read_text())
    tolerances, _ = load_tolerances(TOLERANCES)
    measured = {
        "metrics": dict(expected["metrics"]),
        "nodes": {"vtail_V": expected["nodes"]["Vtail"],
                  "vmirror_V": expected["nodes"]["Vmirror"],
                  "vout_V": expected["nodes"]["Vout"]},
        "devices": {name: dict(values)
                    for name, values in expected["devices"].items()},
        "capacitance_provenance": {
            "spectre_cdd_F": expected["devices"]["M5"]["cdd"],
            "spectre_cgd_F": expected["devices"]["M5"]["cgd"],
            "drain_admittance_F": expected["devices"]["M5"]["cdd"],
            "gate_transfer_F": expected["devices"]["M5"]["cgd"],
        },
    }
    result = compare_finite_measurements(expected, measured, tolerances,
                                         request, design)
    assert result["correlation"]["passed"]
    assert result["measured_request"]["passed"]
    assert result["capacitance_provenance"]["passed"]
    assert set(result["measured_request"]["checks"]) == {
        "Gain_min", "GBW_min", "Power_max", "PM_min", "Sat_margin_min",
        "W_nmos_max", "W_pmos_max", "L_domain"}
    measured["devices"]["M5"].pop("gmbs")
    measured.pop("capacitance_provenance")
    result = compare_finite_measurements(expected, measured, tolerances,
                                         request, design)
    assert not result["correlation"]["passed"]
    assert not result["capacitance_provenance"]["passed"]
    optional = {**request, "Swing_min": 0.3, "ICMR_max": 0.9}
    result = compare_finite_measurements(expected, measured, tolerances,
                                         optional, design)
    for name in ("Swing_min", "ICMR_max"):
        assert not result["measured_request"]["checks"][name]["available"]
        assert not result["measured_request"]["checks"][name]["passed"]
    assert not result["measured_request"]["passed"]


def test_finite_stager_keeps_private_expectations_local(tmp_path):
    source = tmp_path / "local"
    build_finite_manual_reference(TEMPLATE, TOLERANCES, F4, source,
                                  enriched_devices=_enriched())
    destination = tmp_path / "shared"
    assert stage_finite(source, destination,
                        ROOT / "scripts/cadence_guest") == 1
    staged = destination / "jobs/finite_manual_reference_001"
    assert {path.name for path in staged.iterdir()} == set(PUBLIC_JOB_FILES)
    assert not (staged / "expected_private.json").exists()
    assert {path.name for path in (destination / "runner").iterdir()} == set(RUNNER_FILES)


def test_capacitance_provenance_decision_is_explicit_and_fail_closed():
    tolerances, _ = load_tolerances(TOLERANCES)
    expected = {"cdd": 100e-15, "cgd": 20e-15}
    measured = {"spectre_cdd_F": 101e-15, "spectre_cgd_F": 19e-15,
                "drain_admittance_F": 101e-15, "gate_transfer_F": 19e-15}
    result = classify_capacitance_provenance(expected, measured, tolerances)
    assert result["passed"]
    assert result["interpretation"] == "cdd_is_total_grounded_drain_capacitance"
    assert not classify_capacitance_provenance(
        expected, {**measured, "drain_admittance_F": 110e-15},
        tolerances)["passed"]
    inconsistent = {**measured, "spectre_cdd_F": 500e-15,
                    "spectre_cgd_F": 200e-15}
    result = classify_capacitance_provenance(expected, inconsistent, tolerances)
    assert result["interpretation"] == "cdd_is_total_grounded_drain_capacitance"
    assert not result["consistency_passed"] and not result["passed"]
    assert not classify_capacitance_provenance(
        expected, {"spectre_cdd_F": 100e-15}, tolerances)["available"]


def test_finite_runner_uses_isolated_raw_data_and_prehashes_pdk():
    text = (ROOT / "scripts/cadence_guest/run_finite_jobs.sh").read_text()
    verify = text.index("--verify-only")
    ota = text.index('"$SPECTRE_BIN" input.scs')
    caps = text.index('"$SPECTRE_BIN" capacitance_probe.scs -raw ./psf_caps')
    assert verify < ota < caps
    assert "run_jobs.sh" not in text
    assert "expected_private" not in text and "request_private" not in text


def test_guest_result_writer_is_python35_grammar_and_legacy_runtime_safe():
    path = ROOT / "scripts/cadence_guest/write_finite_result.py"
    source = path.read_text()
    ast.parse(source, filename=str(path), feature_version=(3, 5))
    forbidden = ("from __future__ import annotations", "pathlib", "Path(",
                 "os.replace", "FileNotFoundError", "->", " | {")
    assert not any(token in source for token in forbidden)
    assert "f\"" not in source and "f'" not in source

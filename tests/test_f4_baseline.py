"""Phase F4 runner and immutable real-LUT evidence checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from analog_ai import config
from scripts.run_f4_baseline import CountingOTA, _initial_population

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (ROOT / "evaluation_results" / "finite_m5" /
            "f4_baseline_20260909_170218" / "f4_baseline.json")


def _reject_constant(value):
    raise ValueError(f"nonfinite JSON token {value}")


def test_f4_evidence_is_strict_source_bound_and_complete():
    campaign = json.loads(EVIDENCE.read_text(), parse_constant=_reject_constant)
    assert campaign["schema"] == "analog_ai-phase-f4-finite-baseline-v1"
    assert campaign["noncanonical"] is True
    assert campaign["frozen_saturation_floor_V"] == 0.05
    assert campaign["summary"] == {
        "verified_feasible": 5, "total": 5, "all_verified": True}
    assert len(campaign["cases"]) == 5
    for name, digest in campaign["source_fingerprint"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    for name, digest in campaign["request_fingerprint"].items():
        path = ROOT / "configs" / "test_cases" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert all(item["verified"]
               for item in campaign["lut_verification"].values())


def test_f4_records_are_genuinely_verified_under_frozen_contract():
    campaign = json.loads(EVIDENCE.read_text(), parse_constant=_reject_constant)
    for case in campaign["cases"]:
        record, search = case["finite_record"], case["search"]
        assert case["status"] == "verified_feasible"
        assert record["verdict"] is True
        assert not case["failed_constraints"]
        assert all(row["passed"] for row in record["constraints"])
        assert record["effective_constraints"]["limits"][
            "Sat_margin_min"] == config.SAT_MARGIN_MIN_DEFAULT
        assert record["metrics"]["min_sat_margin"] >= 0.05
        assert list(record["design"]) == list(config.DESIGN_PARAM_NAMES_7)
        assert search["full_oracle_call_count"] == (
            search["optimizer_evaluations"] +
            search["final_verification_evaluations"])
        for run in search["seed_runs"]:
            assert run["counted_calls"] == (
                run["successful_calls"] + sum(run["invalid_categories"].values()))


def test_f4_initial_population_is_seeded_and_within_all_seven_bounds():
    ideal = dict(zip(config.DESIGN_PARAM_NAMES,
                     (0.4e-6, 22.0, 0.7e-6, 11.0, 40e-6)))
    a = _initial_population(np.random.default_rng(7), 42, ideal)
    b = _initial_population(np.random.default_rng(7), 42, ideal)
    bounds = np.asarray(config.DESIGN_BOUNDS_7)
    assert a.shape == (42, 7) and np.array_equal(a, b)
    assert np.all(a >= bounds[:, 0]) and np.all(a <= bounds[:, 1])
    assert np.allclose(a[0, [0, 1, 2, 3, 6]],
                       [ideal[n] for n in config.DESIGN_PARAM_NAMES])
    assert a[0, 4] == pytest.approx(0.18e-6)
    assert a[0, 5] == pytest.approx(25.0)


def test_counting_ota_classifies_failed_calls():
    class Stub:
        tail_device = "finite"
        def evaluate(self, value):
            if value < 0:
                raise ValueError("bad")
            return value

    counted = CountingOTA(Stub())
    assert counted.evaluate(2) == 2
    with pytest.raises(ValueError):
        counted.evaluate(-1)
    assert counted.calls == 2 and counted.successes == 1
    assert counted.invalid == {"ValueError": 1}

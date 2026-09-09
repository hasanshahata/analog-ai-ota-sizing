"""Phase F2 tests: integrated finite metrics, hard constraints, and the
minimal finite record schema.

Public finite evaluation stays CLOSED (OTA5T.evaluate still rejects
finite+solved); these tests exercise the private integrated evaluator and
the dev/non-canonical finite record path directly.
Reference: docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md (Astra F2 handoff).
"""

import json

import numpy as np
import pytest

from analog_ai import ORACLE_VERSION, config
from analog_ai.circuit.ota5t import OTA5T
from analog_ai.evaluation.constraints import evaluate_constraints
from analog_ai.evaluation.evaluator import (FINITE_SCHEMA_VERSION,
                                            effective_constraint_limits,
                                            evaluate_design_finite)

NOMINAL = (0.6e-6, 15.0, 0.6e-6, 12.0, 0.6e-6, 10.0, 50e-6)
LOOSE_SPECS = {"Gain_min": 20.0, "GBW_min": 1e6, "CL_pF": 1.0,
               "Power_max": 400e-6}


@pytest.fixture(scope="module")
def finite_ota(engine):
    dm, _ = engine
    # finite + imposed constructor: allowed; public finite+solved stays
    # rejected (guarded in evaluate()); the private integrated evaluator is
    # exercised directly.
    return OTA5T(dm, vdd=1.2, tail_device="finite", op_point="imposed")


@pytest.fixture(scope="module")
def nominal_record(finite_ota):
    return evaluate_design_finite(finite_ota, NOMINAL, dict(LOOSE_SPECS))


# ------------------------------------------------------------- schema --------
def test_record_schema_identity_distinct_from_ideal(nominal_record):
    r = nominal_record
    assert r["schema_version"] == FINITE_SCHEMA_VERSION
    assert r["schema_version"] != ORACLE_VERSION
    assert r["oracle_identity"]["distinct_from_ideal_oracle"] == ORACLE_VERSION
    assert r["topology"] == "5t_ota"
    assert r["tail_device"] == "finite"
    assert r["op_point_mode"] == "solved"
    assert "gate-bias generator excluded" in r["external_bias_generator"]
    assert "unverified" in r["capacitance_assumption"]


def test_record_serializes_all_seven_named_parameters(nominal_record):
    """Astra R4 regression: mode-aware names, exact order, no five-value
    truncation (L5 must not masquerade as Itail)."""
    design = nominal_record["design"]
    assert list(design) == list(config.DESIGN_PARAM_NAMES_7)
    assert design["L1"] == NOMINAL[0]
    assert design["gmid1"] == NOMINAL[1]
    assert design["L5"] == NOMINAL[4]
    assert design["gmid5"] == NOMINAL[5]
    assert design["Itail"] == NOMINAL[6]


def test_record_is_strict_json_compliant(nominal_record):
    text = json.dumps(nominal_record, allow_nan=False)
    assert "NaN" not in text and "Infinity" not in text


def test_record_carries_complete_finite_evidence(nominal_record):
    dd = nominal_record["dc_diagnostics"]
    for key in ("Vtail", "Vmirror", "Vout", "Vbias_tail", "ID5",
                "kcl_residuals", "m5_current_error_rel",
                "m5_gmid_forward_error", "m5_gmid_forward", "m5_gmid_table",
                "convergence", "clip_diagnostics"):
        assert key in dd, key
    assert dd["kcl_residuals"]["tail"] is not None
    m5 = nominal_record["devices"]["M5"]
    assert m5["VSB"] == 0.0
    assert m5["gmid_forward"] is not None
    assert nominal_record["metrics"]["sat_m5"] is not None


# ------------------------------------------------- constraints (hard gate) ---
def test_negative_saturation_probe_case_is_rejected(nominal_record):
    """Astra F2 handoff item 2: the converged-but-triode M5 diagnostic
    points must FAIL the frozen saturation floor as feasible designs."""
    r = nominal_record
    assert r["metrics"]["sat_m5"] < 0.0
    assert r["metrics"]["min_sat_margin"] == r["metrics"]["sat_m5"]
    assert r["verdict"] is False
    sat_row = next(c for c in r["constraints"] if c["name"] == "Sat_margin_min")
    assert sat_row["passed"] is False
    assert sat_row["limit"] == pytest.approx(config.SAT_MARGIN_MIN_DEFAULT)
    assert any("M5" in w for w in r["warnings"])


def test_fully_saturated_design_can_pass():
    """Complement case: a perf record whose five devices all meet the
    floors passes the hard verifier - the rejection above is physical, not
    structural."""
    perf = {
        "DC_Gain_dB": 40.0, "GBW": 1e8, "PM": 60.0, "Power": 100e-6,
        "min_sat_margin": 0.08,
        "devices": {"M1": {"W": 20e-6, "L": 0.6e-6},
                    "M2": {"W": 20e-6, "L": 0.6e-6},
                    "M3": {"W": 30e-6, "L": 0.6e-6},
                    "M4": {"W": 30e-6, "L": 0.6e-6},
                    "M5": {"W": 15e-6, "L": 0.6e-6}},
    }
    specs = {"Gain_min": 30.0, "GBW_min": 5e7, "CL_pF": 1.0,
             "Power_max": 200e-6}
    constraints, verdict = evaluate_constraints(perf, specs)
    assert verdict is True
    assert all(c.passed for c in constraints)


def test_effective_pm_request_tightens_and_relaxation_is_clamped(
        finite_ota):
    # Tightened request: the constraint row must carry the requested limit.
    tight = evaluate_design_finite(
        finite_ota, NOMINAL, dict(LOOSE_SPECS, PM_min=89.0))
    row = next(c for c in tight["constraints"] if c["name"] == "PM_min")
    assert row["limit"] == 89.0
    assert tight["effective_constraints"]["limits"]["PM_min"] == 89.0

    # Attempted relaxation below the frozen default: clamped up, recorded.
    relaxed = evaluate_design_finite(
        finite_ota, NOMINAL, dict(LOOSE_SPECS, PM_min=10.0))
    row = next(c for c in relaxed["constraints"] if c["name"] == "PM_min")
    assert row["limit"] == config.PM_MIN_DEFAULT
    assert any("no relaxation" in n for n in relaxed["warnings"])
    assert relaxed["effective_constraints"]["limits"]["PM_min"] == \
        config.PM_MIN_DEFAULT


def test_effective_sat_margin_tightening(finite_ota):
    tight = evaluate_design_finite(
        finite_ota, NOMINAL, dict(LOOSE_SPECS, Sat_margin_min=0.30))
    row = next(c for c in tight["constraints"]
               if c["name"] == "Sat_margin_min")
    assert row["limit"] == 0.30
    assert tight["verdict"] is False


def test_effective_constraint_limits_validation():
    with pytest.raises(ValueError):
        effective_constraint_limits({"PM_min": float("inf")})
    with pytest.raises(ValueError):
        effective_constraint_limits({"Sat_margin_min": -1.0})


def test_requested_range_metrics_fail_closed(finite_ota):
    """A5 policy: optional range requests are NOT accepted on nominal
    estimates - the acceptance keys serialize as null and the constraint
    rows fail with 'metric not available'."""
    r = evaluate_design_finite(
        finite_ota, NOMINAL, dict(LOOSE_SPECS, Swing_min=0.3, ICMR_max=0.9))
    assert r["metrics"]["Swing"] is None
    assert r["metrics"]["ICMR_min"] is None
    assert r["metrics"]["Swing_est"] is not None      # labeled estimate kept
    assert r["metrics"]["ICMR_low_est"] is not None
    swing_row = next(c for c in r["constraints"] if c["name"] == "Swing_min")
    icmr_row = next(c for c in r["constraints"] if c["name"] == "ICMR_max")
    assert swing_row["passed"] is False
    assert "not available" in swing_row["detail"]
    assert icmr_row["passed"] is False
    assert r["verdict"] is False


# ------------------------------------------------------------ metrics --------
def test_power_is_core_power_with_kcl_crosscheck(nominal_record):
    """Finite core power = VDD*(ID3+ID4), cross-checked against VDD*ID5;
    the requested VDD*Itail is recorded separately."""
    m = nominal_record["metrics"]
    dd = nominal_record["dc_diagnostics"]
    id3 = nominal_record["devices"]["M3"]["ID"]
    id4 = nominal_record["devices"]["M4"]["ID"]
    assert m["Power_core"] == pytest.approx(1.2 * (id3 + id4), rel=1e-12)
    # The cross-check error is bounded by the accepted KCL residuals
    # (|R1 - R2 - R3| <= ~3e-9 A) relative to the core power.
    assert m["power_kcl_error"] < 3e-9 / m["Power_core"] * 1.5
    assert m["power_requested_vdd_times_itail"] == pytest.approx(
        1.2 * NOMINAL[6], rel=1e-12)
    assert dd["ID5"] == pytest.approx(NOMINAL[6],
                                      rel=1e-3)


def test_ac_uses_corrected_stamp_model(finite_ota):
    """The finite AC response must come from the corrected stamps: the
    reported gain equals an independent corrected-model recomputation from
    the returned device points, and differs from the legacy model (which
    mis-stamps cgd/gmbs)."""
    perf = finite_ota._evaluate_solved_finite(list(NOMINAL), 1e-12, None)
    devices = perf["devices"]
    eng = finite_ota.mna
    freq = np.array([1.0])
    v_corr = eng.solve_ac_corrected(devices["M1"], devices["M2"],
                                    devices["M3"], devices["M4"],
                                    devices["M5"], 1e-12, freq)
    v_leg = eng.solve_ac(devices["M1"], devices["M2"], devices["M3"],
                         devices["M4"], devices["M5"], 1e-12, freq)
    assert perf["ac_model"] == "corrected_terminal_v1"
    assert abs(v_corr[0]) == pytest.approx(10 ** (
        perf["DC_Gain_dB"] / 20.0), rel=1e-9)
    # the two models genuinely differ on real device data (audit sanity)
    assert abs(v_corr[0] - v_leg[0]) > 1e-12


def test_headroom_estimates_are_labeled_not_clamped(finite_ota):
    perf = finite_ota._evaluate_solved_finite(list(NOMINAL), 1e-12, None)
    assert perf["Swing"] != perf["Swing"]          # acceptance key NaN
    assert np.isfinite(perf["Swing_est"])          # estimate present
    assert perf["ICMR_upper"] is None              # not derivable
    assert perf["ICMR_low_est"] == pytest.approx(
        perf["devices"]["M1"]["VGS"] + perf["devices"]["M5"]["VDSAT"])
    assert perf["Vout_low_est"] == pytest.approx(
        perf["Vtail"] + perf["devices"]["M2"]["VDSAT"])
    assert perf["Vout_high_est"] == pytest.approx(
        1.2 - perf["devices"]["M4"]["VDSAT"])
    assert isinstance(perf["Vout_in_estimated_range"], bool)


def test_area_and_saturation_include_m5(finite_ota):
    perf = finite_ota._evaluate_solved_finite(list(NOMINAL), 1e-12, None)
    d = perf["devices"]
    expected = (2 * d["M1"]["W"] * d["M1"]["L"]
                + 2 * d["M3"]["W"] * d["M3"]["L"]
                + d["M5"]["W"] * d["M5"]["L"])
    assert perf["Area"] == pytest.approx(expected, rel=1e-12)
    assert perf["min_sat_margin"] == min(perf["sat_m1"], perf["sat_m2"],
                                         perf["sat_m3"], perf["sat_m4"],
                                         perf["sat_m5"])


# ---------------------------------------------------- fail-closed records ----
def test_wrong_arity_produces_invalid_record(finite_ota):
    r = evaluate_design_finite(finite_ota,
                               [0.6e-6, 15.0, 0.6e-6, 12.0, 50e-6],
                               dict(LOOSE_SPECS))
    assert r["verdict"] is False
    assert "7 parameters" in r["invalid_reason"]
    assert r["metrics"] is None and r["devices"] is None
    assert r["constraints"] == []


def test_nonfinite_design_produces_invalid_record(finite_ota):
    bad = list(NOMINAL)
    bad[5] = float("nan")
    r = evaluate_design_finite(finite_ota, bad, dict(LOOSE_SPECS))
    assert r["verdict"] is False
    assert "gmid5" in r["invalid_reason"]


def test_invalid_specs_produce_invalid_record(finite_ota):
    r = evaluate_design_finite(
        finite_ota, NOMINAL, dict(LOOSE_SPECS, PM_min=float("inf")))
    assert r["verdict"] is False
    assert "PM_min" in r["invalid_reason"]


def test_domain_rejection_produces_invalid_record(finite_ota):
    bad = list(NOMINAL)
    bad[4] = 179.5e-9                    # below the synthetic LUT L minimum
    r = evaluate_design_finite(finite_ota, bad, dict(LOOSE_SPECS))
    assert r["verdict"] is False
    assert "LUT domain" in r["invalid_reason"]


# ---------------------------------------------------- public surface closed --
def test_public_finite_evaluation_still_closed(engine):
    dm, _ = engine
    ota = OTA5T(dm, vdd=1.2, tail_device="finite", op_point="imposed")
    with pytest.raises(NotImplementedError):
        ota.evaluate(list(NOMINAL), CL=1e-12, op_point="solved")
    with pytest.raises(NotImplementedError):
        OTA5T(dm, vdd=1.2, tail_device="finite", op_point="solved")

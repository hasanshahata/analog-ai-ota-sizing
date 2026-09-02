from analog_ai.evaluation.constraints import evaluate_constraints
from analog_ai.evaluation.evaluator import evaluate_design


def test_record_for_valid_design(engine):
    _, ota = engine
    specs = {"Gain_min": 10.0, "GBW_min": 1e6, "Power_max": 400e-6, "CL_pF": 1.0}
    rec = evaluate_design(ota, [0.6e-6, 10.0, 0.6e-6, 12.0, 50e-6], specs)
    assert rec["metrics"] is not None
    assert rec["verdict"] is True
    names = {c["name"] for c in rec["constraints"]}
    assert {"Gain_min", "GBW_min", "Power_max", "PM_min", "Sat_margin_min",
            "W_nmos_max", "W_pmos_max"} <= names
    assert "oracle_version" in rec["provenance"]
    assert rec["devices"]["M1"]["W"] == rec["devices"]["M2"]["W"]


def test_record_for_invalid_design_does_not_raise(engine):
    _, ota = engine
    specs = {"Gain_min": 30.0, "GBW_min": 100e6, "Power_max": 50e-6, "CL_pF": 1.0}
    rec = evaluate_design(ota, [0.6e-6, 5.0, 0.6e-6, 12.0, -1e-6], specs)
    assert rec["verdict"] is False
    assert rec["metrics"] is None
    assert rec.get("invalid_reason")
    # constraints module agrees the perf-less record must fail
    _, verdict = evaluate_constraints(None, specs)
    assert not verdict

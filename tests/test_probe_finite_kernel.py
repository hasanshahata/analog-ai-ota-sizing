"""Lightweight tests for the finite-kernel probe helpers (Astra R5b).

No LUT is loaded: only pure helper behavior, source fingerprinting, and
the controlled comparison-budget rule are checked.
"""

import hashlib
import importlib.util
from pathlib import Path

import pytest

PROBE_PATH = (Path(__file__).resolve().parents[1]
              / "scripts" / "probe_finite_kernel.py")


@pytest.fixture(scope="module")
def probe():
    spec = importlib.util.spec_from_file_location("probe_finite_kernel",
                                                  PROBE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_comparison_budgets_preserve_other_controls(probe):
    """The before/after comparison must isolate max_outer: supplied tol and
    max_newton are preserved, only max_outer is overridden."""
    assert probe.comparison_budgets(
        {"tol": 5e-13, "max_newton": 7, "max_outer": 99}) == {
        "tol": 5e-13, "max_newton": 7,
        "max_outer": probe.COMPARISON_BUDGET}
    assert probe.comparison_budgets({}) == {
        "max_outer": probe.COMPARISON_BUDGET}


def test_source_fingerprint_covers_executed_sources(probe):
    fp = probe.source_fingerprint()
    required = ("analog_ai", "analog_ai.config", "analog_ai.devices.lut",
                "analog_ai.devices.device_model",
                "analog_ai.circuit.dc_solver", "analog_ai.loader",
                "scripts.probe_finite_kernel")
    for key in required:
        assert key in fp, key
        assert len(fp[key]["sha256"]) == 64
        int(fp[key]["sha256"], 16)          # valid hex digest
    # spot-check one hash against an independent computation
    import analog_ai.circuit.dc_solver as ds
    direct = hashlib.sha256(Path(ds.__file__).read_bytes()).hexdigest()
    assert fp["analog_ai.circuit.dc_solver"]["sha256"] == direct


def test_source_identity_shape(probe):
    identity = probe.source_identity()
    assert set(identity) >= {"git_commit", "git_tracked_changes", "python",
                             "source_fingerprint"}
    commit = identity["git_commit"]
    assert commit is None or (len(commit) == 40 and int(commit, 16) >= 0)
    assert isinstance(identity["git_tracked_changes"], bool)
    if identity["git_tracked_changes"]:
        assert len(identity["git_diff_sha256"]) == 64


def test_source_fingerprint_f2_covers_evaluator_and_constraints(probe):
    """Astra F2-R5: the F2 archive must fingerprint the modules that
    produce its verdicts/schema and its ACTUAL entry point."""
    fp = probe.source_fingerprint_f2()
    for key in ("analog_ai.evaluation.evaluator",
                "analog_ai.evaluation.constraints",
                "scripts/probe_finite_evaluator.py",
                "analog_ai.circuit.dc_solver",
                "analog_ai.circuit.mna",
                "scripts.probe_finite_kernel"):
        assert key in fp, key
        assert len(fp[key]["sha256"]) == 64
        int(fp[key]["sha256"], 16)
    # independent content-hash spot checks against the delivered files
    import analog_ai.evaluation.constraints as cons
    import analog_ai.evaluation.evaluator as ev
    assert fp["analog_ai.evaluation.evaluator"]["sha256"] == \
        hashlib.sha256(Path(ev.__file__).read_bytes()).hexdigest()
    assert fp["analog_ai.evaluation.constraints"]["sha256"] == \
        hashlib.sha256(Path(cons.__file__).read_bytes()).hexdigest()
    f2_probe = (Path(probe.__file__).resolve().parent
                / "probe_finite_evaluator.py")
    assert fp["scripts/probe_finite_evaluator.py"]["sha256"] == \
        hashlib.sha256(f2_probe.read_bytes()).hexdigest()


def test_source_fingerprint_default_keeps_f1_contract(probe):
    """The default fingerprint set is unchanged (the accepted F1
    contract): no F2 extensions leak into it."""
    fp = probe.source_fingerprint()
    assert "analog_ai.evaluation.evaluator" not in fp
    assert "analog_ai.evaluation.constraints" not in fp
    assert "scripts/probe_finite_evaluator.py" not in fp
    assert "analog_ai.circuit.dc_solver" in fp
    assert "scripts.probe_finite_kernel" in fp


def test_sha256_of_matches_hashlib(probe, tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"analog-ai-probe")
    assert probe.sha256_of(f) == hashlib.sha256(b"analog-ai-probe").hexdigest()

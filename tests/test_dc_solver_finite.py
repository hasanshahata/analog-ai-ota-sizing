"""Phase F1 focused tests for the finite-tail solved DC kernel.

Public finite evaluation stays rejected in F1 (the ota5t dispatch bypass is
closed); these tests exercise ``solve_operating_point_finite`` directly on
the synthetic LUT, plus the ``DESIGN_BOUNDS_7`` contract. Contract and
tolerances: docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md (Astra A1/A2/A3).
"""

import types

import numpy as np
import pytest

from analog_ai import config
from analog_ai.circuit.dc_solver import (FINITE_TOLERANCES,
                                          DCConvergenceError,
                                          solve_operating_point,
                                          solve_operating_point_finite,
                                          validate_finite_design)
from analog_ai.circuit.ota5t import InvalidDesignError, OTA5T
from analog_ai.devices.lut import DomainError

VDD = 1.2
VICM = 0.6
NOMINAL = (0.6e-6, 15.0, 0.6e-6, 12.0, 0.6e-6, 10.0, 50e-6)


# --------------------------------------------------------------- helpers ---
class _FakeLUT:
    """Minimal duck-typed LUT for deterministic degenerate-case tests."""

    W = 2e-6
    L_min, L_max = 60e-9, 1.5e-6

    def __init__(self, ids_fn, gm_fn, gmid_curve):
        self.L = np.array([0.18e-6, 0.6e-6, 1.5e-6])
        self.VGS = np.linspace(0.45, 1.2, 16)
        self.VDS = np.linspace(0.02, 1.2, 24)
        self.VSB = np.array([0.0, 0.2, 0.4])
        self._ids = ids_fn
        self._gm = gm_fn
        self._gmid_curve = gmid_curve
        self.interpolators = {"gmid": lambda pts: gmid_curve(pts[:, 1])}

    def in_domain(self, L, VGS, VDS, VSB, tol=1e-9):
        L, VGS, VDS, VSB = (np.atleast_1d(np.asarray(v, dtype=float))
                            for v in (L, VGS, VDS, VSB))
        L, VGS, VDS, VSB = np.broadcast_arrays(L, VGS, VDS, VSB)
        return ((L >= self.L_min - tol) & (L <= self.L_max + tol)
                & (VGS >= self.VGS.min() - tol) & (VGS <= self.VGS.max() + tol)
                & (VDS >= self.VDS.min() - tol) & (VDS <= self.VDS.max() + tol)
                & (VSB >= self.VSB.min() - tol) & (VSB <= self.VSB.max() + tol))

    def lookup(self, param, L, VGS, VDS, VSB):
        L, VGS, VDS, VSB = np.broadcast_arrays(
            *[np.atleast_1d(np.asarray(v, dtype=float))
              for v in (L, VGS, VDS, VSB)])
        fns = {
            "ids": lambda v, d, b: self._ids(v, d, b),
            "gm": lambda v, d, b: self._gm(v, d, b),
            "gds": lambda v, d, b: 1e-5,
            "vth": lambda v, d, b: 0.35,
            "vdsat": lambda v, d, b: max(v - 0.35, 1e-3),
            "gmid": lambda v, d, b: (self._gm(v, d, b)
                                     / max(self._ids(v, d, b), 1e-300)),
        }
        fn = fns[param]
        return np.array([fn(v, d, b) for v, d, b in
                         zip(VGS.ravel(), VDS.ravel(), VSB.ravel())]).reshape(L.shape)

    def lookup_vgs(self, L, gmid_target, VDS, VSB):
        curve = self._gmid_curve(self.VGS)
        return np.array([
            float(np.interp(float(g), curve[::-1], self.VGS[::-1]))
            for g in np.atleast_1d(np.asarray(gmid_target, dtype=float))])


def _fake_dm(nch, pch):
    return types.SimpleNamespace(nch=nch, pch=pch)


# ------------------------------------------------------ contract / bounds ---
def test_bounds_7_contract_complete():
    assert len(config.DESIGN_PARAM_NAMES_7) == 7
    assert len(config.DESIGN_BOUNDS_7) == 7
    assert config.DESIGN_PARAM_NAMES_7 == (
        "L1", "gmid1", "L3", "gmid3", "L5", "gmid5", "Itail")
    # The first four entries and Itail share the frozen five-parameter bounds.
    assert config.DESIGN_BOUNDS_7[:4] == config.DESIGN_BOUNDS[:4]
    assert config.DESIGN_BOUNDS_7[6] == config.DESIGN_BOUNDS[4]
    for name, (lo, hi) in zip(config.DESIGN_PARAM_NAMES_7,
                              config.DESIGN_BOUNDS_7):
        assert np.isfinite(lo) and np.isfinite(hi) and lo < hi, name


def test_validate_finite_design_accepts_nominal():
    assert validate_finite_design(NOMINAL) == tuple(float(v) for v in NOMINAL)


@pytest.mark.parametrize("bad", [
    (0.6e-6, 15.0, 0.6e-6, 12.0, 0.6e-6, 10.0),                # arity 6
    (0.6e-6, 15.0, 0.6e-6, 12.0, 0.6e-6, 10.0, 50e-6, 1.0),    # arity 8
    (float("nan"), 15.0, 0.6e-6, 12.0, 0.6e-6, 10.0, 50e-6),
    (float("inf"), 15.0, 0.6e-6, 12.0, 0.6e-6, 10.0, 50e-6),
    (0.6e-6, 15.0, 0.6e-6, 12.0, 0.6e-6, 10.0, -50e-6),        # negative Itail
    (0.6e-6, 15.0, 0.6e-6, 12.0, 0.6e-6, 10.0, 0.0),
    (0.6e-6, 40.0, 0.6e-6, 12.0, 0.6e-6, 10.0, 50e-6),         # gmid1 above bounds
])
def test_validate_finite_design_rejects_deterministically(bad):
    with pytest.raises(ValueError):
        validate_finite_design(bad)


# ------------------------------------------------------- nominal behavior ---
@pytest.fixture(scope="module")
def finite_nominal(engine):
    dm, _ = engine
    return dm, solve_operating_point_finite(dm, *NOMINAL, vdd=VDD, vicm=VICM)


def test_nominal_convergence_and_determinism(engine):
    dm, _ = engine
    a = solve_operating_point_finite(dm, *NOMINAL, vdd=VDD, vicm=VICM)
    b = solve_operating_point_finite(dm, *NOMINAL, vdd=VDD, vicm=VICM)
    assert a == b  # zero randomness in the kernel: bit-identical repeat


def test_kcl_and_m5_current_consistency(finite_nominal):
    dm, op = finite_nominal
    r = op["kcl_residuals"]
    assert max(abs(v) for v in r.values()) <= FINITE_TOLERANCES["kcl_acceptance_a"]
    assert op["kcl_max_abs"] <= FINITE_TOLERANCES["kcl_acceptance_a"]
    assert op["kcl_max_over_itail"] == pytest.approx(
        op["kcl_max_abs"] / NOMINAL[6])
    i1, i2 = op["M1"]["ID"], op["M2"]["ID"]
    # Current-balance relative windows are consistent with the declared
    # 1e-9 A KCL acceptance (not tighter).
    assert i1 + i2 == pytest.approx(op["M5"]["ID"], rel=1e-3)
    assert op["M5"]["ID"] == pytest.approx(
        NOMINAL[6], rel=FINITE_TOLERANCES["id5_rel_error"])
    assert op["M3"]["ID"] == pytest.approx(i1, rel=1e-3)
    assert op["M4"]["ID"] == pytest.approx(i2, rel=1e-3)


def test_returned_geometry_and_bias(finite_nominal):
    dm, op = finite_nominal
    assert 0.0 < op["W1"] <= config.W_NMOS_MAX
    assert 0.0 < op["W3"] <= config.W_PMOS_MAX
    assert 0.0 < op["W5"] <= config.W_NMOS_MAX
    assert 0.0 < op["Vbias_tail"] < VDD
    for node in ("Vtail", "Vmirror", "Vout"):
        assert 0.0 < op[node] < VDD
    m5 = op["M5"]
    assert m5["W"] == op["W5"] and m5["L"] == NOMINAL[4]
    assert m5["VGS"] == op["Vbias_tail"]
    assert m5["VDS"] == pytest.approx(op["Vtail"])
    assert m5["VSB"] == 0.0            # legal grid endpoint
    # matched pairs share geometry
    assert op["M1"]["W"] == op["M2"]["W"]
    assert op["M3"]["W"] == op["M4"]["W"]


def test_forward_gmid5_gate_and_table_discrepancy(finite_nominal):
    dm, op = finite_nominal
    m5 = op["M5"]
    # The acceptance gate uses the FORWARD ratio of the returned gm and ID.
    assert abs(m5["gmid_forward"] - NOMINAL[5]) <= \
        FINITE_TOLERANCES["gmid5_abs_error_inv"]
    assert m5["gmid_forward"] == pytest.approx(m5["gm"] / m5["ID"])
    assert op["m5_gmid_forward_error"] == pytest.approx(
        m5["gmid_forward"] - NOMINAL[5])
    # The interpolated table ratio is recorded separately under its own name
    # (interpolating a ratio is not the ratio of interpolated quantities).
    assert np.isfinite(m5["gmid_table"])
    assert m5["gmid_achieved"] == m5["gmid_table"]


def test_final_point_in_closed_domain_including_m5(finite_nominal):
    dm, op = finite_nominal
    nch, pch = dm.nch, dm.pch
    vt, vm, vo, vb5 = op["Vtail"], op["Vmirror"], op["Vout"], op["Vbias_tail"]
    assert bool(np.all(nch.in_domain(NOMINAL[0], VICM - vt, vm - vt, vt)))
    assert bool(np.all(nch.in_domain(NOMINAL[0], VICM - vt, vo - vt, vt)))
    assert bool(np.all(pch.in_domain(NOMINAL[2], VDD - vm, VDD - vm, 0.0)))
    assert bool(np.all(pch.in_domain(NOMINAL[2], VDD - vm, VDD - vo, 0.0)))
    # M5 coordinates: VDS = Vtail, VGS = Vbias_tail, VSB = 0 (legal endpoint).
    assert bool(np.all(nch.in_domain(NOMINAL[4], vb5, vt, 0.0)))
    assert op["clip_diagnostics"]["voltage_line_search_clips"] >= 0
    assert set(op["clip_diagnostics"]["lut_axis_clamps"]) <= {"VGS", "VDS", "VSB"}


def test_convergence_and_clip_diagnostics_recorded(finite_nominal):
    dm, op = finite_nominal
    c = op["convergence"]
    assert c["outer_iterations"] >= 1
    assert c["inner_newton_steps"] >= 1
    assert c["final_width_rel_change"] < FINITE_TOLERANCES["width_rel_change"]
    assert c["final_bias_abs_change_v"] <= FINITE_TOLERANCES["bias_abs_change_v"]
    assert c["tolerances"] == FINITE_TOLERANCES
    assert "sat_m5" in op and np.isfinite(op["sat_m5"])
    assert op["topology_mode"] == "finite_tail_solved"


def test_m5_participation_by_fixed_device_perturbation(finite_nominal):
    """A1 evidence: the physical M5 current, not a constant Itail, closes KCL.

    Perturbing the FIXED returned W5 by +2% at the fixed gate bias must move
    the tail residual by about 2% of Itail.
    """
    dm, op = finite_nominal
    i1, i2 = op["M1"]["ID"], op["M2"]["ID"]
    i5 = op["M5"]["ID"]
    assert abs(i1 + i2 - i5) < 1e-9
    i5_perturbed = (float(np.abs(dm.nch.lookup(
        "ids", [NOMINAL[4]], [op["Vbias_tail"]], [op["Vtail"]], [0.0])[0]))
        * (op["W5"] * 1.02 / dm.nch.W))
    assert abs(i1 + i2 - i5_perturbed) > 1e-3 * NOMINAL[6]


def test_ideal_solved_point_is_reference_for_finite(engine):
    """A1 cross-check: with M5 sized and biased to conduct Itail at the
    operating point, the finite KCL system coincides with the ideal one."""
    dm, _ = engine
    ideal = solve_operating_point(dm, NOMINAL[0], NOMINAL[1], NOMINAL[2],
                                  NOMINAL[3], NOMINAL[6], vdd=VDD, vicm=VICM)
    finite = solve_operating_point_finite(dm, *NOMINAL, vdd=VDD, vicm=VICM)
    for k in ("Vtail", "Vmirror", "Vout"):
        assert finite[k] == pytest.approx(ideal[k], abs=2e-3)


def test_ideal_solved_kernel_unchanged(engine):
    """Regression lock (snapshot 2026-09-09, Phase F1): the ideal kernel
    must be byte-stable across the finite-kernel addition."""
    dm, _ = engine
    op = solve_operating_point(dm, 0.6e-6, 15.0, 0.6e-6, 12.0, 50e-6,
                               vdd=VDD, vicm=VICM)
    assert op["Vtail"] == 0.0854324297792604
    assert op["Vmirror"] == 0.6300000000008928
    assert op["Vout"] == 0.6300000000008928
    assert op["W1"] == 1.5349299762731556e-05
    assert op["W3"] == 3.3328389622559995e-05
    assert op["kcl_residuals"]["tail"] == pytest.approx(8.391432480250784e-12)


# ------------------------------------------------------ boundary currents ---
def test_boundary_tail_currents_converge(engine):
    dm, _ = engine
    for itail in (10e-6, 300e-6):        # lower bound and a wide-width case
        op = solve_operating_point_finite(dm, 0.6e-6, 15.0, 0.6e-6, 12.0,
                                          0.6e-6, 10.0, itail,
                                          vdd=VDD, vicm=VICM)
        assert max(abs(v) for v in op["kcl_residuals"].values()) <= 1e-9
        assert op["m5_current_error_rel"] <= FINITE_TOLERANCES["id5_rel_error"]
        assert 0.0 < op["W5"] <= config.W_NMOS_MAX


def test_unsizable_tail_hits_hard_width_limit(engine):
    """Itail = 500 uA at gmid5 = 10 needs W5 ~ 392 um > 250 um: the final
    hard-width check must reject the design deterministically (an excessive
    intermediate W5 never rejects; only the final geometry does)."""
    dm, _ = engine
    with pytest.raises(DCConvergenceError, match="hard limit"):
        solve_operating_point_finite(dm, 0.6e-6, 15.0, 0.6e-6, 12.0,
                                     0.6e-6, 10.0, 500e-6,
                                     vdd=VDD, vicm=VICM)


# --------------------------------------------------------- failure modes ----
def test_headroom_exhaustion_fails_closed(engine):
    dm, _ = engine
    with pytest.raises((DCConvergenceError, DomainError)):
        solve_operating_point_finite(dm, 0.6e-6, 5.0, 0.6e-6, 12.0,
                                     0.6e-6, 10.0, 50e-6,
                                     vdd=VDD, vicm=VICM)


def test_insufficient_outer_budget_fails_deterministically(engine):
    dm, _ = engine
    with pytest.raises(DCConvergenceError, match="did not converge"):
        solve_operating_point_finite(dm, *NOMINAL, vdd=VDD, vicm=VICM,
                                     max_outer=1)


def test_m5_gmid_target_not_achievable_rejected(engine):
    # gmid5 = 24.5 is inside the bounds but above the synthetic branch max:
    # the forward gate must reject it, not clamp to an endpoint.
    dm, _ = engine
    with pytest.raises(DomainError):
        solve_operating_point_finite(dm, 0.6e-6, 15.0, 0.6e-6, 12.0,
                                     0.6e-6, 24.5, 50e-6,
                                     vdd=VDD, vicm=VICM)


def test_m5_length_outside_lut_domain_rejected(engine):
    # L5 = 0.1 um is inside the contract bounds (60 nm floor) but below the
    # synthetic LUT's characterized L box [0.18, 1.5] um: closed-domain
    # rejection, not silent extrapolation. (L values BETWEEN characterized
    # lengths are legitimately interpolated and must NOT raise.)
    dm, _ = engine
    with pytest.raises(DomainError):
        solve_operating_point_finite(dm, 0.6e-6, 15.0, 0.6e-6, 12.0,
                                     0.1e-6, 10.0, 50e-6,
                                     vdd=VDD, vicm=VICM)


def test_nonfinite_device_data_fails_closed():
    # ids becomes NaN above VDS = 0.3 V: the kernel must raise its explicit
    # nonfinite guard instead of propagating NaNs or reporting success.
    def ids_nan_hi_vds(v, d, b):
        return float("nan") if d > 0.3 else 150e-6 * max(v - 0.35, 0.0) ** 2

    def gm_ok(v, d, b):
        return 300e-6 * max(v - 0.35, 0.0)

    lut = _FakeLUT(ids_nan_hi_vds, gm_ok,
                   lambda vgs: 2.0 / np.maximum(vgs - 0.35, 1e-9))
    dm = _fake_dm(lut, lut)
    with pytest.raises(DCConvergenceError, match="nonfinite"):
        solve_operating_point_finite(dm, 0.6e-6, 15.0, 0.6e-6, 12.0,
                                     0.6e-6, 10.0, 50e-6,
                                     vdd=VDD, vicm=VICM)


def test_exact_sizing_gives_exact_balance():
    """Position-independent device data: the sizing rules make every branch
    current exact, so the kernel must converge in one outer iteration with
    an identically zero residual (the A1 fixed-point consistency argument,
    verified numerically)."""
    lut = _FakeLUT(
        lambda v, d, b: 5e-6,             # ids constant
        lambda v, d, b: 5e-5,             # gm constant -> forward ratio 10
        lambda vgs: np.full_like(np.asarray(vgs, dtype=float), 10.0),
    )
    dm = _fake_dm(lut, lut)
    op = solve_operating_point_finite(dm, 0.6e-6, 15.0, 0.6e-6, 12.0,
                                      0.6e-6, 10.0, 50e-6,
                                      vdd=VDD, vicm=VICM)
    assert op["convergence"]["outer_iterations"] == 1
    assert op["kcl_max_abs"] == 0.0
    assert op["M5"]["ID"] == pytest.approx(50e-6)
    assert op["W5"] == pytest.approx(50e-6 / 5e-6 * lut.W)


# ------------------------------------------------- public surface (closed) --
def test_public_finite_solved_calls_stay_rejected(engine):
    dm, _ = engine
    x5 = [0.6e-6, 15.0, 0.6e-6, 12.0, 50e-6]
    x7 = list(NOMINAL)
    # Constructor guard.
    with pytest.raises(NotImplementedError):
        OTA5T(dm, vdd=VDD, tail_device="finite", op_point="solved")
    # Per-call override bypass (closed in F1): a finite/imposed object must
    # never receive ideal-tail solved results.
    fin_imp = OTA5T(dm, vdd=VDD, tail_device="finite", op_point="imposed")
    with pytest.raises(NotImplementedError):
        fin_imp.evaluate(x5, CL=1e-12, op_point="solved")
    with pytest.raises(NotImplementedError):
        fin_imp.evaluate(x7, CL=1e-12, op_point="solved")
    # Ideal + solved still requires exactly five parameters ...
    ideal_solved = OTA5T(dm, vdd=VDD, tail_device="ideal", op_point="solved")
    with pytest.raises(InvalidDesignError):
        ideal_solved.evaluate(x7, CL=1e-12)
    # ... and still evaluates (public ideal behavior preserved).
    perf = ideal_solved.evaluate(x5, CL=1e-12)
    assert perf["gbw_valid"]

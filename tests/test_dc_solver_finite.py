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
                                          _canonical_coord,
                                          _forward_gmid_vgs,
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
    L = np.array([0.18e-6, 0.6e-6, 1.5e-6])
    VGS = np.linspace(0.45, 1.2, 16)
    VDS = np.linspace(0.02, 1.2, 24)
    VSB = np.array([0.0, 0.2, 0.4])

    def __init__(self, ids_fn, gm_fn, gmid_curve, gmid_table_fn=None,
                 scalar_gm_nan_at=None):
        self._ids = ids_fn
        self._gm = gm_fn
        self._gmid_curve = gmid_curve
        self._table_fn = gmid_table_fn
        self._scalar_gm_nan_at = scalar_gm_nan_at
        self.interpolators = {
            "gmid": (gmid_table_fn if gmid_table_fn is not None
                     else (lambda pts: gmid_curve(pts[:, 1])))}

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
        out = np.array([fn(v, d, b) for v, d, b in
                        zip(VGS.ravel(), VDS.ravel(), VSB.ravel())]).reshape(L.shape)
        if (param == "gm" and self._scalar_gm_nan_at is not None
                and out.size == 1
                and float(VGS.ravel()[0]) == self._scalar_gm_nan_at):
            out = np.full_like(out, np.nan)
        return out

    def lookup_vgs(self, L, gmid_target, VDS, VSB):
        L, g, d, b = (np.atleast_1d(np.asarray(v, dtype=float))
                      for v in (L, gmid_target, VDS, VSB))
        out = []
        for li, gi, di, bi in zip(L, g, d, b):
            if self._table_fn is not None:
                curve = self._table_fn(np.column_stack([
                    np.full_like(self.VGS, li), self.VGS,
                    np.full_like(self.VGS, di), np.full_like(self.VGS, bi)]))
            else:
                curve = self._gmid_curve(self.VGS)
            out.append(float(np.interp(float(gi), curve[::-1],
                                       self.VGS[::-1])))
        return np.array(out)


def _fake_dm(nch, pch):
    return types.SimpleNamespace(nch=nch, pch=pch)


def _ratio_curve_lut(ratios):
    """Fake LUT whose forward gm/Id ratio equals the given per-grid-node
    array (ids constant; gm = ratio * ids; table = forward ratio)."""
    ratios = np.asarray(ratios, dtype=float)
    ids = 5e-6
    return _FakeLUT(
        lambda v, d, b: ids,
        lambda v, d, b: ids * float(np.interp(v, _FakeLUT.VGS, ratios)),
        lambda vgs: np.interp(vgs, _FakeLUT.VGS, ratios),
    )


def _vgs_only_lut(table_gain=1.0):
    """Device whose current depends on VGS only.

    With VGS-only currents, R2 = i1 - i3 and R3 = i4 - i2 become EXACT
    negatives, so the KCL Jacobian is rank-deficient (a true singular
    case). The gm/Id TABLE carries a VDS-dependent gain so the sizing rule
    and the residual evaluation disagree at the initial guess - without
    that, exact-sizing consistency gives a zero residual and Newton never
    runs.
    """
    def ids_fn(v, d, b):
        return 150e-6 * max(v - 0.35, 0.0) ** 2

    def gm_fn(v, d, b):
        return 300e-6 * max(v - 0.35, 0.0)

    def table_fn(pts):
        od = np.maximum(pts[:, 1] - 0.35, 1e-9)
        return (2.0 / od) * (1.0 + table_gain * (pts[:, 2] - 0.5))

    return _FakeLUT(ids_fn, gm_fn, None, gmid_table_fn=table_fn)


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
    assert c["tolerances"]["kcl_newton_target_a"] == \
        FINITE_TOLERANCES["kcl_newton_target_a"]
    assert c["effective_settings"] == {"tol": 1e-12, "max_newton": 60,
                                       "max_outer": 60}
    assert "sat_m5" in op and np.isfinite(op["sat_m5"])
    assert op["topology_mode"] == "finite_tail_solved"
    assert op["clip_diagnostics"]["coordinate_snaps"] == []


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
    """Position-independent current with a UNIQUE forward root: the sizing
    rules make every branch current exact, so the kernel converges in one
    outer iteration with an identically zero residual (the A1 fixed-point
    consistency argument), while the unique-root rule (F1-R2) admits the
    well-posed case."""
    vgs_grid = _FakeLUT.VGS
    ratios = np.linspace(14.0, 9.0, vgs_grid.size)   # decreasing, unique root
    ids0 = 5e-6

    lut = _FakeLUT(
        lambda v, d, b: ids0,
        lambda v, d, b: ids0 * float(np.interp(v, vgs_grid, ratios)),
        lambda vgs: np.interp(vgs, vgs_grid, ratios),
    )
    dm = _fake_dm(lut, lut)
    op = solve_operating_point_finite(dm, 0.6e-6, 15.0, 0.6e-6, 12.0,
                                      0.6e-6, 10.0, 50e-6,
                                      vdd=VDD, vicm=VICM)
    assert op["convergence"]["outer_iterations"] == 1
    assert op["kcl_max_abs"] == 0.0
    assert op["M5"]["ID"] == pytest.approx(50e-6)
    assert op["W5"] == pytest.approx(50e-6 / ids0 * lut.W)
    assert op["M5"]["gmid_forward"] == pytest.approx(10.0, abs=1e-6)


# ------------------------------------------- F1-R1: canonical coordinates ---
def test_canonical_coord_interior_and_exact_edges():
    grid = np.array([0.45, 0.6, 1.2])
    assert _canonical_coord(0.5, grid, "VGS") == 0.5
    assert _canonical_coord(0.45, grid, "VGS") == 0.45
    assert _canonical_coord(1.2, grid, "VGS") == 1.2


def test_canonical_coord_nextafter_allowance_both_sides():
    grid = np.array([0.45, 0.6, 1.2])
    lo, hi = 0.45, 1.2
    # One ULP outside either edge is float representation noise -> snap to
    # the edge itself (the allowance is two ULPs; the two-ULP case sits on
    # the acceptance boundary and is intentionally not asserted).
    below = float(np.nextafter(lo, -np.inf))
    above = float(np.nextafter(hi, np.inf))
    assert _canonical_coord(below, grid, "VGS") == lo
    assert _canonical_coord(above, grid, "VGS") == hi
    # Three ULPs out is a genuine violation.
    below3 = float(np.nextafter(np.nextafter(np.nextafter(lo, -np.inf),
                                             -np.inf), -np.inf))
    above3 = float(np.nextafter(np.nextafter(np.nextafter(hi, np.inf),
                                             np.inf), np.inf))
    with pytest.raises(DomainError):
        _canonical_coord(below3, grid, "VGS")
    with pytest.raises(DomainError):
        _canonical_coord(above3, grid, "VGS")


def test_canonical_coord_rejects_absolute_excursions():
    vgrid = np.array([0.45, 0.6, 1.2])
    with pytest.raises(DomainError):
        _canonical_coord(0.45 - 1e-9, vgrid, "VGS")   # 1 nm-class excursion
    lgrid = np.array([0.18e-6, 0.6e-6, 1.5e-6])
    with pytest.raises(DomainError):
        _canonical_coord(0.18e-6 - 0.5e-9, lgrid, "L")  # 0.5 nm below


def test_kernel_rejects_half_nm_below_lut_length_minimum(engine):
    """Astra F1-R1 reproduction: L5 0.5 nm below the LUT's 180 nm minimum
    is billions of ULPs outside the characterized grid and must be
    rejected, not snapped and not extrapolated."""
    dm, _ = engine
    with pytest.raises(DomainError):
        solve_operating_point_finite(dm, 0.6e-6, 15.0, 0.6e-6, 12.0,
                                     179.5e-9, 10.0, 50e-6,
                                     vdd=VDD, vicm=VICM)


def test_kernel_snaps_nextafter_length_and_records_it(engine):
    dm, _ = engine
    l5 = float(np.nextafter(0.18e-6, -np.inf))  # one ULP below the L minimum
    op = solve_operating_point_finite(dm, 0.6e-6, 15.0, 0.6e-6, 12.0,
                                      l5, 10.0, 50e-6, vdd=VDD, vicm=VICM)
    snaps = op["clip_diagnostics"]["coordinate_snaps"]
    assert any(s["axis"] == "L" and s["requested"] == l5
               and s["canonical"] == 0.18e-6 for s in snaps)
    assert op["M5"]["L"] == 0.18e-6   # returned evidence at the canonical edge


def test_kcl_matches_returned_device_points_bitwise(finite_nominal):
    """F1-R1: acceptance KCL is recomputed FROM the returned device points,
    so the reported residuals and the returned IDs are one evaluation."""
    dm, op = finite_nominal
    i1, i2 = op["M1"]["ID"], op["M2"]["ID"]
    i3, i4, i5 = op["M3"]["ID"], op["M4"]["ID"], op["M5"]["ID"]
    assert op["kcl_residuals"]["tail"] == i1 + i2 - i5
    assert op["kcl_residuals"]["mirror"] == i1 - i3
    assert op["kcl_residuals"]["output"] == i4 - i2
    assert op["kcl_max_abs"] == max(abs(i1 + i2 - i5), abs(i1 - i3),
                                    abs(i4 - i2))


# ------------------------------------- F1-R2: unique forward gm/Id root -----
def test_forward_gmid_rejects_multiple_crossings():
    """Astra F1-R2 reproduction curve: passes the small-wiggle check but
    crosses the target three times - must be rejected, not proximity-
    selected."""
    lut = _ratio_curve_lut([12, 10.005, 9.995, 10.005, 9, 8, 7, 6,
                            5, 4, 3.8, 3.6, 3.4, 3.2, 3, 2.8])
    with pytest.raises(DomainError, match="ambiguous"):
        _forward_gmid_vgs(lut, 0.6e-6, 10.0, 0.5, 0.0)


def test_forward_gmid_rejects_target_plateau():
    lut = _ratio_curve_lut([12, 10, 10, 9, 8, 7, 6, 5,
                            4, 3.8, 3.6, 3.4, 3.2, 3, 2.8, 2.6])
    with pytest.raises(DomainError, match="ambiguous"):
        _forward_gmid_vgs(lut, 0.6e-6, 10.0, 0.5, 0.0)


def test_forward_gmid_accepts_unique_endpoint_root():
    lut = _ratio_curve_lut([10, 9.5, 9, 8.5, 8, 7.5, 7, 6.5,
                            6, 5.5, 5, 4.5, 4, 3.5, 3, 2.5])
    vgs = _forward_gmid_vgs(lut, 0.6e-6, 10.0, 0.5, 0.0)
    assert vgs == _FakeLUT.VGS[0]


def test_forward_gmid_accepts_unique_interior_root():
    lut = _ratio_curve_lut([12, 11.4, 10.8, 10.2, 9.6, 9.0, 8.4, 7.8,
                            7.2, 6.6, 6.0, 5.4, 4.8, 4.2, 3.6, 3.0])
    vgs = _forward_gmid_vgs(lut, 0.6e-6, 10.0, 0.5, 0.0)
    assert _FakeLUT.VGS[3] < vgs < _FakeLUT.VGS[4]
    gm = float(lut.lookup("gm", [0.6e-6], [vgs], [0.5], [0.0])[0])
    ids = float(lut.lookup("ids", [0.6e-6], [vgs], [0.5], [0.0])[0])
    assert gm / ids == pytest.approx(10.0, abs=1e-6)


def test_forward_gmid_rejects_unbracketed():
    lut = _ratio_curve_lut(np.linspace(20.0, 10.5, _FakeLUT.VGS.size))
    with pytest.raises(DomainError):
        _forward_gmid_vgs(lut, 0.6e-6, 10.0, 0.5, 0.0)


# ------------------------------- F1-R3: finite returned operating points ----
def test_nonfinite_gm_in_returned_pmos_points_rejected(engine, monkeypatch):
    """Astra F1-R3 reproduction: NaN gm in the PMOS table is invisible to
    the DC solve but must not reach the returned M3/M4 evidence."""
    dm, _ = engine
    original = dm.pch.lookup

    def poisoned(param, L, VGS, VDS, VSB):
        out = original(param, L, VGS, VDS, VSB)
        if param == "gm":
            out = np.full_like(np.asarray(out, dtype=float), np.nan)
        return out

    monkeypatch.setattr(dm.pch, "lookup", poisoned)
    with pytest.raises(DCConvergenceError, match="M3 .*gm is not finite"):
        solve_operating_point_finite(dm, *NOMINAL, vdd=VDD, vicm=VICM)


def test_nonfinite_gds_in_returned_points_rejected(engine, monkeypatch):
    dm, _ = engine
    original = dm.pch.lookup

    def poisoned(param, L, VGS, VDS, VSB):
        out = original(param, L, VGS, VDS, VSB)
        if param == "gds":
            out = np.full_like(np.asarray(out, dtype=float), np.nan)
        return out

    monkeypatch.setattr(dm.pch, "lookup", poisoned)
    with pytest.raises(DCConvergenceError, match="gds is not finite"):
        solve_operating_point_finite(dm, *NOMINAL, vdd=VDD, vicm=VICM)


def test_nonfinite_vdsat_in_returned_points_rejected(engine, monkeypatch):
    # VDSAT is consumed only when building the returned points: this is the
    # final-only nonfinite case.
    dm, _ = engine
    original = dm.pch.lookup

    def poisoned(param, L, VGS, VDS, VSB):
        out = original(param, L, VGS, VDS, VSB)
        if param == "vdsat":
            out = np.full_like(np.asarray(out, dtype=float), np.nan)
        return out

    monkeypatch.setattr(dm.pch, "lookup", poisoned)
    with pytest.raises(DCConvergenceError, match="VDSAT is not finite"):
        solve_operating_point_finite(dm, *NOMINAL, vdd=VDD, vicm=VICM)


def test_nonfinite_m5_point_rejected_final_only():
    """Healthy through the whole solve, poisoned only for the scalar
    per-point evaluation at M5's returned gate voltage: a present-but-NaN
    value must not masquerade as a successful OP."""
    vgs_grid = _FakeLUT.VGS
    ratios = np.array([12, 11, 10, 9.5, 9.0, 8.5, 8.0, 7.5,
                       7.0, 6.5, 6.0, 5.5, 5.0, 4.5, 4.0, 3.5])
    ids0 = 5e-6
    vgs5 = float(vgs_grid[2])    # the unique grid-node root -> M5's VGS

    lut = _FakeLUT(
        lambda v, d, b: ids0,
        lambda v, d, b: ids0 * float(np.interp(v, vgs_grid, ratios)),
        lambda vgs: np.interp(vgs, vgs_grid, ratios),
        scalar_gm_nan_at=vgs5,
    )
    dm = _fake_dm(lut, lut)
    with pytest.raises(DCConvergenceError, match="M5 .*gm is not finite"):
        solve_operating_point_finite(dm, 0.6e-6, 15.0, 0.6e-6, 12.0,
                                     0.6e-6, 10.0, 50e-6,
                                     vdd=VDD, vicm=VICM)


def test_singular_jacobian_reported_explicitly():
    """VGS-only currents make R3 the exact negative of R2: a genuinely
    singular KCL Jacobian must be reported as such, not as a generic
    failure (required explicit guard coverage, F1-R3)."""
    lut = _vgs_only_lut(table_gain=0.1)
    dm = _fake_dm(lut, lut)
    with pytest.raises(DCConvergenceError, match="singular KCL Jacobian"):
        solve_operating_point_finite(dm, 0.6e-6, 15.0, 0.6e-6, 12.0,
                                     0.6e-6, 10.0, 50e-6,
                                     vdd=VDD, vicm=VICM)


def test_ill_conditioned_jacobian_reported_explicitly():
    """Same rank deficiency with a tiny VDS dependence: the rows are ALMOST
    dependent. Where the value lands relative to the finite-difference
    noise floor decides between the ill-conditioned and singular guards -
    both are the explicit deterministic rejection the contract requires."""
    lut = _vgs_only_lut(table_gain=0.1)
    ids_base = lut._ids
    lut._ids = lambda v, d, b: ids_base(v, d, b) * (1.0 + 1e-13 * (d - 0.5))
    dm = _fake_dm(lut, lut)
    with pytest.raises(DCConvergenceError, match="ill-conditioned|singular"):
        solve_operating_point_finite(dm, 0.6e-6, 15.0, 0.6e-6, 12.0,
                                     0.6e-6, 10.0, 50e-6,
                                     vdd=VDD, vicm=VICM)


# ------------------------------- F1-R4 / F1-R5: surface and recordation -----
def test_invalid_op_point_override_rejected(engine):
    dm, _ = engine
    ota = OTA5T(dm, vdd=VDD, tail_device="ideal", op_point="solved")
    x5 = [0.6e-6, 15.0, 0.6e-6, 12.0, 50e-6]
    with pytest.raises(ValueError, match="op_point"):
        ota.evaluate(x5, CL=1e-12, op_point="solvde")
    with pytest.raises(ValueError, match="op_point"):
        ota.evaluate(x5, CL=1e-12, op_point="")
    # None still means "use the constructor mode"; valid overrides work.
    assert ota.evaluate(x5, CL=1e-12)["gbw_valid"]
    assert ota.evaluate(x5, CL=1e-12, op_point="imposed")["gbw_valid"] is not None


def test_effective_settings_recorded(engine):
    dm, _ = engine
    op = solve_operating_point_finite(dm, *NOMINAL, vdd=VDD, vicm=VICM,
                                      tol=5e-13, max_newton=7, max_outer=15)
    c = op["convergence"]
    assert c["effective_settings"] == {"tol": 5e-13, "max_newton": 7,
                                       "max_outer": 15}
    assert c["tolerances"]["kcl_newton_target_a"] == 5e-13


@pytest.mark.parametrize("bad", [
    {"tol": float("inf")},      # Astra R5a reproduction: previously returned
    {"tol": float("nan")},
    {"tol": 0.0},
    {"tol": -1e-12},
    {"tol": True},              # booleans are not numbers here
    {"tol": "1e-12"},           # nonnumeric
    {"max_outer": 7.5},         # fraction: never silently truncated
    {"max_outer": True},
    {"max_outer": 0},
    {"max_newton": 0},
    {"max_newton": 60.5},
])
def test_invalid_numerical_settings_rejected_before_solving(engine, bad):
    dm, _ = engine
    with pytest.raises(ValueError):
        solve_operating_point_finite(dm, *NOMINAL, vdd=VDD, vicm=VICM, **bad)


def test_normal_record_is_strict_json_compliant(finite_nominal):
    import json
    dm, op = finite_nominal
    text = json.dumps(op, allow_nan=False)   # must not raise
    assert "NaN" not in text and "Infinity" not in text


# ------------------------------------------------- public surface (closed) --
def test_public_finite_solved_dispatch(engine):
    """Since the F3 compatibility package, finite+solved evaluates publicly
    through the accepted finite implementation (dispatch, not bypass)."""
    dm, _ = engine
    x5 = [0.6e-6, 15.0, 0.6e-6, 12.0, 50e-6]
    x7 = list(NOMINAL)
    # Constructor combination is now supported.
    ota = OTA5T(dm, vdd=VDD, tail_device="finite", op_point="solved")
    perf = ota.evaluate(x7, CL=1e-12)
    assert perf["tail_device"] == "finite"
    assert perf["op_point_mode"] == "solved"
    assert perf["ac_model"] == "corrected_terminal_v1"
    assert perf["devices"]["M5"]["W"] > 0.0
    # Per-call override still routes correctly in both directions.
    fin_imp = OTA5T(dm, vdd=VDD, tail_device="finite", op_point="imposed")
    with pytest.raises(InvalidDesignError):
        fin_imp.evaluate(x5, CL=1e-12, op_point="solved")  # arity: 5 != 7
    perf_override = fin_imp.evaluate(x7, CL=1e-12, op_point="solved")
    assert perf_override["Vbias_tail"] == perf["Vbias_tail"]
    # invalid per-call mode values raise before any dispatch (F1-R4)
    with pytest.raises(ValueError):
        fin_imp.evaluate(x5, CL=1e-12, op_point="")
    # Ideal + solved still requires exactly five parameters ...
    ideal_solved = OTA5T(dm, vdd=VDD, tail_device="ideal", op_point="solved")
    with pytest.raises(InvalidDesignError):
        ideal_solved.evaluate(x7, CL=1e-12)
    # ... and still evaluates (public ideal behavior preserved).
    perf = ideal_solved.evaluate(x5, CL=1e-12)
    assert perf["gbw_valid"]

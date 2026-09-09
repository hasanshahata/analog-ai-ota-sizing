"""Self-consistent DC operating-point solve using only the LUT device curves.

This is what makes "the LUTs replace Spectre" true at the circuit level: the
device I-V data is Spectre-characterized, and this module completes the chain
by finding the circuit's actual node voltages from KCL instead of imposing
them. No simulator is involved at any point.

Method
------
Outer fixed-point loop (sizing consistency):
    W1 is sized so M1 would pass Itail/2 at the target gm/Id *at its own
    solved bias*; W3 is sized the same way for the diode-connected M3.
Inner damped Newton solve over (Vtail, Vmirror, Vout) with frozen W1/W3,
    driving the three KCL residuals to zero:

    R1 (tail node):   Id_M1 + Id_M2 - Itail = 0
    R2 (mirror node): Id_M1 - Id_M3 = 0
    R3 (output node): Id_M4 - Id_M2 = 0

At the solution the achieved currents and gm/Id generally deviate slightly
from the design targets (channel-length modulation gives M1 and M2 different
currents at shared VGS) - that deviation is physical and is reported, not
hidden. Convergence failure or an out-of-domain solution marks the design
invalid.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
from scipy.optimize import brentq

from .. import config
from ..devices.lut import LUT, DomainError


class DCConvergenceError(ValueError):
    """The KCL solve did not converge to a physically valid operating point."""


def solve_operating_point(dm, L1: float, gmid1: float, L3: float, gmid3: float,
                          Itail: float, vdd: float, vicm: float,
                          x0: tuple[float, float, float] | None = None,
                          tol: float = 1e-12, max_newton: int = 60,
                          max_outer: int = 8):
    """Solve (Vtail, Vmirror, Vout) with matched-pair sizing consistency.

    Returns a dict with the solved voltages, W1/W3, per-device operating
    points (incl. achieved gm/Id), KCL residuals, and any domain-clamp flags.
    Raises DCConvergenceError / DomainError when no valid operating point
    exists.
    """
    w_ref_n, w_ref_p = dm.nch.W, dm.pch.W
    clamps: list[str] = []

    def idn(w: float, vgs: float, vds: float, vsb: float, clamp: bool = True) -> float:
        return _ids(dm.nch, w, w_ref_n, L1, vgs, vds, vsb, clamps, clamp)

    def idp(w: float, vsg: float, vsd: float, clamp: bool = True) -> float:
        return _ids(dm.pch, w, w_ref_p, L3, vsg, vsd, 0.0, clamps, clamp)

    def gmid_n(vgs: float, vds: float, vsb: float) -> float:
        return float(dm.nch.lookup("gmid", [L1], [vgs], [vds], [vsb])[0])

    def gmid_p(vsg: float, vsd: float) -> float:
        return float(dm.pch.lookup("gmid", [L3], [vsg], [vsd], [0.0])[0])

    # ---- sizing helpers -------------------------------------------------
    def size_w1(vtail: float, vmirror: float) -> float:
        vds1 = max(vmirror - vtail, 1e-3)
        vsb1 = max(vtail, 0.0)
        vgs1 = float(dm.nch.lookup_vgs([L1], [gmid1], [vds1], [vsb1])[0])
        id_char = _ids(dm.nch, w_ref_n, w_ref_n, L1, vgs1, vds1, vsb1, clamps)
        return (Itail / 2.0) / max(id_char, 1e-18) * w_ref_n

    def size_w3(vmirror: float) -> float:
        # Diode-connected PMOS: VSG = VSD, found self-consistently.
        vsg = max(vdd - vmirror, 1e-3)
        for _ in range(20):
            vsg_new = float(dm.pch.lookup_vgs([L3], [gmid3], [vsg], [0.0])[0])
            if abs(vsg_new - vsg) < 1e-9:
                break
            vsg = vsg_new
        id_char = _ids(dm.pch, w_ref_p, w_ref_p, L3, vsg, vsg, 0.0, clamps)
        # Mirror carries M1's current, nominally Itail/2 (outer loop refines).
        return (Itail / 2.0) / max(id_char, 1e-18) * w_ref_p

    # ---- KCL residuals (frozen geometry) --------------------------------
    def residuals(z, w1: float, w3: float) -> np.ndarray:
        vt, vm, vo = z
        vgs = vicm - vt
        i1 = idn(w1, vgs, vm - vt, vt)
        i2 = idn(w1, vgs, vo - vt, vt)
        i3 = idp(w3, vdd - vm, vdd - vm)
        i4 = idp(w3, vdd - vm, vdd - vo)
        return np.array([i1 + i2 - Itail, i1 - i3, i4 - i2])

    # ---- initial guess: imposed-style estimate ---------------------------
    if x0 is None:
        vgs1_0 = float(dm.nch.lookup_vgs([L1], [gmid1], [vicm / 2.0], [0.0])[0])
        vt = max(vicm - vgs1_0, 0.05)
        vgs3_0 = float(dm.pch.lookup_vgs([L3], [gmid3], [0.6], [0.0])[0])
        vm = max(vdd - vgs3_0, 0.05)
        vo = vdd / 2.0
        x0 = (min(max(vt, 0.02), vdd - 0.02),
              min(max(vm, 0.02), vdd - 0.02),
              min(max(vo, 0.02), vdd - 0.02))

    z = np.array(x0, dtype=float)
    w1, w3 = size_w1(z[0], z[1]), size_w3(z[1])

    for _outer in range(max_outer):
        # ---------- inner damped Newton ----------
        r = residuals(z, w1, w3)
        for _ in range(max_newton):
            nrm = float(np.max(np.abs(r)))
            if nrm < tol:
                break
            # numeric Jacobian
            J = np.zeros((3, 3))
            for j in range(3):
                h = 1e-7
                zp = z.copy()
                zp[j] += h
                J[:, j] = (residuals(zp, w1, w3) - r) / h
            try:
                dz = np.linalg.solve(J, -r)
            except np.linalg.LinAlgError:
                raise DCConvergenceError("singular KCL Jacobian")
            # backtracking line search with voltage clamping
            alpha = 1.0
            for _bt in range(30):
                z_new = np.clip(z + alpha * dz, 1e-3, vdd - 1e-3)
                r_new = residuals(z_new, w1, w3)
                if float(np.max(np.abs(r_new))) < nrm or alpha < 1e-4:
                    break
                alpha *= 0.5
            z, r = z_new, r_new
        else:
            raise DCConvergenceError(
                f"KCL solve did not converge (max |residual| = {float(np.max(np.abs(r))):.3g} A)")

        # ---------- sizing consistency fixed point ----------
        vt, vm, vo = (float(v) for v in z)
        w1_new = size_w1(vt, vm)
        w3_new = size_w3(vm)
        if (abs(w1_new - w1) / max(w1, 1e-18) < 1e-6
                and abs(w3_new - w3) / max(w3, 1e-18) < 1e-6):
            w1, w3 = w1_new, w3_new
            break
        w1, w3 = w1_new, w3_new
    else:
        raise DCConvergenceError("sizing fixed point did not converge")

    # Final consistency: geometry must satisfy the sizing rules at the
    # solution, and the solution must lie inside the LUT domain.
    r_final = residuals(z, w1, w3)
    if float(np.max(np.abs(r_final))) > 1e-9:
        raise DCConvergenceError(
            f"KCL residual after sizing loop: {float(np.max(np.abs(r_final))):.3g} A")

    vt, vm, vo = (float(v) for v in z)
    _verify_in_domain(dm, L1, L3, vicm, vdd, vt, vm, vo, vdd)

    # ---- solved operating points per device ------------------------------
    vgs1 = vicm - vt
    vds1, vds2 = vm - vt, vo - vt
    vsb1 = vt
    vsg34 = vdd - vm
    vsd3, vsd4 = vsg34, vdd - vo

    op = {
        "Vtail": vt, "Vmirror": vm, "Vout": vo,
        "W1": w1, "W3": w3,
        "M1": _point(dm.nch, w1, w_ref_n, L1, vgs1, vds1, vsb1, gmid1),
        "M2": _point(dm.nch, w1, w_ref_n, L1, vgs1, vds2, vsb1, gmid1),
        "M3": _point(dm.pch, w3, w_ref_p, L3, vsg34, vsd3, 0.0, gmid3),
        "M4": _point(dm.pch, w3, w_ref_p, L3, vsg34, vsd4, 0.0, gmid3),
        "kcl_residuals": {
            "tail": float(r_final[0]), "mirror": float(r_final[1]),
            "output": float(r_final[2]),
        },
        "domain_clamps": sorted(set(clamps)),
    }
    return op


def _ids(lut: LUT, w: float, w_ref: float, L: float, vgs: float, vds: float,
         vsb: float, clamps: list, clamp: bool = True) -> float:
    """|Ids| for width w via LUT interpolation at the reference width."""
    axes = ((vgs, lut.VGS, "VGS"), (vds, lut.VDS, "VDS"), (vsb, lut.VSB, "VSB"))
    q = []
    for val, grid, name in axes:
        lo, hi = float(grid.min()), float(grid.max())
        if clamp:
            if val < lo or val > hi:
                clamps.append(name)
            q.append(min(max(val, lo), hi))
        else:
            if not (lo <= val <= hi):
                raise LUTDomainError(name, val, lo, hi)
            q.append(val)
    return float(abs(lut.lookup("ids", [L], [q[0]], [q[1]], [q[2]])[0])) * (w / w_ref)


class LUTDomainError(ValueError):
    def __init__(self, axis: str, val: float, lo: float, hi: float):
        super().__init__(
            f"solved operating point leaves LUT domain: {axis}={val:.3g} "
            f"outside [{lo:.3g}, {hi:.3g}]")


def _verify_in_domain(dm, L1, L3, vicm, vdd, vt, vm, vo, vdd_):
    """Strict (unclamped) domain check at the solution."""
    vgs1 = vicm - vt
    _ids(dm.nch, 1.0, 1.0, L1, vgs1, vm - vt, vt, [], clamp=False)
    _ids(dm.nch, 1.0, 1.0, L1, vgs1, vo - vt, vt, [], clamp=False)
    _ids(dm.pch, 1.0, 1.0, L3, vdd - vm, vdd - vm, 0.0, [], clamp=False)
    _ids(dm.pch, 1.0, 1.0, L3, vdd - vm, vdd - vo, 0.0, [], clamp=False)


def _point(lut: LUT, w: float, w_ref: float, L: float, vgs: float, vds: float,
           vsb: float, gmid_target: float) -> dict:
    """Small-signal-safe description of one device's solved operating point."""
    scale = w / w_ref
    point = {
        "W": w, "L": L, "VGS": vgs, "VDS": vds, "VSB": vsb,
        "ID": float(abs(lut.lookup("ids", [L], [vgs], [vds], [vsb])[0])) * scale,
        "gm": float(abs(lut.lookup("gm", [L], [vgs], [vds], [vsb])[0])) * scale,
        "gds": float(abs(lut.lookup("gds", [L], [vgs], [vds], [vsb])[0])) * scale,
        "VDSAT": float(abs(lut.lookup("vdsat", [L], [vgs], [vds], [vsb])[0])),
        "gmid_achieved": float(lut.lookup("gmid", [L], [vgs], [vds], [vsb])[0]),
    }
    point["gmid_target"] = gmid_target
    point["gmid_error"] = point["gmid_achieved"] - gmid_target
    if "gmbs" in lut.interpolators:
        point["gmbs"] = float(abs(lut.lookup("gmbs", [L], [vgs], [vds], [vsb])[0])) * scale
    for cap in ("cgg", "cgs", "cgd", "cdd"):
        if cap in lut.interpolators:
            point[cap] = float(abs(lut.lookup(cap, [L], [vgs], [vds], [vsb])[0])) * scale
    return point


# ---------------------------------------------------------------------------
# Finite-tail (physical M5) solved kernel - Phase F1.
#
# Public finite evaluation is NOT available yet: OTA5T still rejects every
# finite+solved call, including per-call op_point overrides, until the F2
# integration gate. This kernel is exposed for focused tests and development
# probes only. Contract: docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md
# (Astra directions A1/A2/A3, 2026-09-09).
# ---------------------------------------------------------------------------

# Declared numerical contract (A2). Recorded verbatim in every kernel record.
FINITE_TOLERANCES = {
    "kcl_newton_target_a": 1e-12,    # inner Newton stop, max |residual| [A]
    "kcl_acceptance_a": 1e-9,        # final max |residual| [A]
    "width_rel_change": 1e-6,        # outer fixed point over (W1, W3, W5)
    "bias_abs_change_v": 1e-8,       # outer Vbias_tail fixed point [V]
    "id5_rel_error": 1e-3,           # |ID5 - Itail| / Itail at acceptance
    "gmid5_abs_error_inv": 1e-3,     # |gm5/ID5 - gmid5| [1/V], forward ratio
}
_COND_REJECT = 1e12                # Jacobian condition-number guard (upper bound)


def _canonical_coord(val: float, grid: np.ndarray, name: str) -> float:
    """Canonical LUT coordinate for the finite kernel (F1-R1).

    Values strictly inside the characterized grid pass through unchanged.
    A value outside the grid is accepted ONLY within a floating-point
    representation allowance of two ULPs of the violated edge: a single
    subtraction of two grid-edge-scale operands can miss the edge by that
    much (e.g. 1.2 - 0.7500000000000001 against a 0.45 grid minimum), and
    the returned value is the EDGE itself, so every downstream lookup sees
    the characterized endpoint and nothing is ever extrapolated. Anything
    further outside raises DomainError - a 0.5 nm excursion on a length
    axis is billions of ULPs and is rejected, so no historical absolute
    tolerance is copied into the finite contract (A2).
    """
    lo, hi = float(grid.min()), float(grid.max())
    if lo <= val <= hi:
        return float(val)
    edge = lo if val < lo else hi
    allowance = 2.0 * float(np.spacing(abs(edge)))
    if abs(val - edge) <= allowance:
        return edge
    raise DomainError(
        f"finite operating point outside the characterized LUT domain: "
        f"{name}={val:.17g} outside [{lo:.17g}, {hi:.17g}]")


def _validate_point_finite(name: str, point: dict) -> None:
    """Reject a returned device operating point whose mandatory data is
    nonfinite or nonphysical (F1-R3). Applied to the finite path only: a
    present-but-NaN value must never masquerade as a successful OP, and
    finiteness is checked BEFORE any threshold comparison.
    """
    def bad(detail: str) -> None:
        raise DCConvergenceError(
            f"returned {name} operating point: {detail}")

    for key in ("W", "L", "VGS", "VDS", "VSB", "ID", "gm", "gds", "VDSAT"):
        v = point.get(key)
        if v is None or not np.isfinite(v):
            bad(f"{key} is not finite (got {v!r})")
    if not point["W"] > 0.0:
        bad(f"W must be positive (got {point['W']:.6g})")
    if not point["L"] > 0.0:
        bad(f"L must be positive (got {point['L']:.6g})")
    if not point["ID"] > 0.0:
        bad(f"ID must be positive (got {point['ID']:.6g})")
    for key in ("gmid_achieved", "gmid_target", "gmid_error", "gmbs",
                "cgg", "cgs", "cgd", "cdd"):
        v = point.get(key)
        if v is not None and not np.isfinite(v):
            bad(f"{key} is not finite (got {v!r})")


def validate_finite_design(x) -> tuple:
    """Validate a seven-parameter finite design vector (F1 contract).

    Deterministic ValueError for wrong arity, non-finite values, bound
    violations, or a non-positive Itail. Never clips or coerces.
    """
    names = config.DESIGN_PARAM_NAMES_7
    bounds = config.DESIGN_BOUNDS_7
    if len(names) != 7 or len(bounds) != 7:
        raise ValueError(
            "finite design contract must define seven names and bounds")
    if len(x) != 7:
        raise ValueError(
            f"finite design vector requires 7 parameters, got {len(x)}")
    values = []
    for name, raw, (lo, hi) in zip(names, x, bounds):
        v = float(raw)
        if not np.isfinite(v):
            raise ValueError(f"{name} must be finite, got {raw!r}")
        if not lo <= v <= hi:
            raise ValueError(f"{name}={v:.6g} outside bounds [{lo:.6g}, {hi:.6g}]")
        values.append(v)
    if not values[6] > 0.0:
        raise ValueError("Itail must be positive")
    return tuple(values)


def _forward_gmid_vgs(lut: LUT, L: float, gmid_target: float, vds: float,
                      vsb: float) -> float:
    """VGS at which the FORWARD ratio |gm|/|ids| equals ``gmid_target``.

    The strict reverse lookup interpolates the gm/Id *table* and disagrees
    with the forward ratio of separately interpolated gm and ids on real
    data (Astra A2), so the accepted tail bias solves the FORWARD ratio.

    Domain (F1-R1): L, VDS, and VSB are canonicalized with
    :func:`_canonical_coord` before every lookup - no lookup ever runs
    outside the validated domain, and no lookup ever extrapolates.

    Uniqueness (F1-R2): the target must have EXACTLY ONE root on the
    post-peak decreasing branch of the table gm/Id curve. Exact grid-node
    hits, sign-change intervals, and flat target plateaus are counted
    together; a grid-node root shared by neighboring intervals is counted
    once because strict sign products never include a zero endpoint. Zero
    roots raise as unbracketed; more than one root - including a two-node
    target plateau - raises as ambiguous. No proximity or first-hit
    selection exists, so no initial estimate is needed.
    """
    Lc = _canonical_coord(L, lut.L, "L")
    vdsc = _canonical_coord(vds, lut.VDS, "VDS")
    vsbc = _canonical_coord(vsb, lut.VSB, "VSB")

    vgs_grid = lut.VGS
    pts = np.column_stack([
        np.full_like(vgs_grid, Lc), vgs_grid,
        np.full_like(vgs_grid, vdsc), np.full_like(vgs_grid, vsbc)])
    table = lut.interpolators["gmid"](pts)
    i_peak = int(np.argmax(table))
    branch = table[i_peak:]
    span = float(branch.max() - branch.min())
    if np.any(np.diff(branch) > max(0.01 * span, 1e-6)):
        raise DomainError(
            f"gm/Id(VGS) curve not decreasing after its peak "
            f"(L={Lc:.3g}, VDS={vdsc:.3g}, VSB={vsbc:.3g}) - "
            "characterization problem")

    vgs_b = np.asarray(vgs_grid[i_peak:], dtype=float)
    one = np.ones_like(vgs_b)
    gm_b = np.abs(lut.lookup("gm", one * Lc, vgs_b, one * vdsc, one * vsbc))
    ids_b = np.abs(lut.lookup("ids", one * Lc, vgs_b, one * vdsc, one * vsbc))
    ratio = np.where(ids_b > 0.0, gm_b / np.where(ids_b > 0.0, ids_b, 1.0),
                     np.inf)
    resid = ratio - gmid_target
    finite = np.isfinite(resid)
    if finite.any():
        ok = ratio[finite]
        slack = 1e-6 * max(1.0, abs(gmid_target))
        if not (ok.min() - slack <= gmid_target <= ok.max() + slack):
            raise DomainError(
                f"forward gm/Id target {gmid_target:.6g} 1/V not achievable "
                f"on the decreasing branch (range [{ok.min():.6g}, "
                f"{ok.max():.6g}]) at L={Lc:.3g}, VDS={vdsc:.3g}, "
                f"VSB={vsbc:.3g}")

    node_roots = np.flatnonzero(finite & (resid == 0.0))
    brackets = [i for i in range(len(resid) - 1)
                if finite[i] and finite[i + 1]
                and resid[i] * resid[i + 1] < 0.0]
    n_roots = int(node_roots.size) + len(brackets)
    if n_roots == 0:
        raise DomainError(
            f"forward gm/Id target {gmid_target:.6g} 1/V not bracketed on "
            f"the decreasing branch at L={Lc:.3g}, VDS={vdsc:.3g}, "
            f"VSB={vsbc:.3g}")
    if n_roots > 1:
        detail = ("repeated target hits / plateau on the branch"
                  if node_roots.size >= 2 else f"{n_roots} distinct roots")
        raise DomainError(
            f"ambiguous forward gm/Id root ({detail}) for target "
            f"{gmid_target:.6g} 1/V at L={Lc:.3g}, VDS={vdsc:.3g}, "
            f"VSB={vsbc:.3g}; the decreasing branch must cross the target "
            "exactly once")

    def _ratio(vgs: float) -> float:
        gm_v = float(abs(lut.lookup("gm", [Lc], [vgs], [vdsc], [vsbc])[0]))
        ids_v = float(abs(lut.lookup("ids", [Lc], [vgs], [vdsc], [vsbc])[0]))
        if not (np.isfinite(gm_v) and np.isfinite(ids_v) and ids_v > 0.0):
            raise DomainError(
                f"nonpositive or nonfinite device current while solving the "
                f"forward gm/Id root (VGS={vgs:.6g}, VDS={vdsc:.6g})")
        return gm_v / ids_v

    if node_roots.size == 1:
        return float(vgs_b[node_roots[0]])
    a = float(vgs_b[brackets[0]])
    b = float(vgs_b[brackets[0] + 1])
    return float(brentq(lambda v: _ratio(v) - gmid_target, a, b,
                        xtol=1e-12, maxiter=100))


def _validate_numeric_settings(tol, max_newton, max_outer):
    """Validate the numerical controls BEFORE any lookup or iteration
    (Astra R5a): the effective tolerance must be a positive finite real
    scalar and the iteration budgets positive integer scalars - fractions
    are never truncated, and booleans are rejected even though they
    subclass ``int``. Deterministic ValueError messages.
    """
    def number(name: str, v) -> float:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{name} must be a real number, got {v!r}")
        v = float(v)
        if not np.isfinite(v):
            raise ValueError(f"{name} must be finite, got {v!r}")
        return v

    tol_n = number("tol", FINITE_TOLERANCES["kcl_newton_target_a"]
                   if tol is None else tol)
    if not tol_n > 0.0:
        raise ValueError(f"tol must be positive, got {tol_n!r}")
    budgets = {}
    for name, v in (("max_newton", max_newton), ("max_outer", max_outer)):
        n = number(name, v)
        if not float(n).is_integer():
            raise ValueError(f"{name} must be an integer, got {v!r}")
        n = int(n)
        if n < 1:
            raise ValueError(f"{name} must be >= 1, got {v!r}")
        budgets[name] = n
    return tol_n, budgets["max_newton"], budgets["max_outer"]


def solve_operating_point_finite(dm, L1: float, gmid1: float, L3: float,
                                 gmid3: float, L5: float, gmid5: float,
                                 Itail: float, vdd: float, vicm: float,
                                 x0: tuple[float, float, float] | None = None,
                                 tol: float | None = None,
                                 max_newton: int = 60,
                                 max_outer: int = 60,
                                 trace: list | None = None) -> dict:
    """Finite-tail counterpart of :func:`solve_operating_point` (Phase F1).

    Nested solve over ``z = (Vtail, Vmirror, Vout)``:

    * inner damped Newton with W1, W3, W5 AND ``Vbias_tail`` frozen (fixed
      device, fixed gate - Jacobian probes and line search included),
      driving the same three KCL residuals as ideal mode with
      ``R1 = Id_M1 + Id_M2 - Id_M5`` using the actual LUT M5 current;
    * outer fixed-point loop re-sizing the three widths at the solved
      voltages and re-deriving ``Vbias_tail`` from the FORWARD gm/Id
      target (the table reverse lookup is a branch-aware initial estimate
      only).

    ``max_outer`` default is 60, not the A2 initial value 8: the finite
    outer loop converges geometrically but at a design-dependent rate.
    Measured evidence (2026-09-09, before/after per A2):
      * synthetic LUT nominal: rate ~0.2/iteration, needs 10 iterations
        (8 stalls at width change 3.7e-6);
      * real TSMC nominal/boundary designs: converge within 20;
      * real TSMC wide design (gmid1=12, gmid5=12, Itail=100 uA): rate
        ~0.64/iteration with Vtail ~ 30 mV, needs 31 iterations (20 stalls
        at width change 3.3e-5, bias 8.7e-7 V).
    Outer iterations past the first cost 1-3 Newton steps each, so the
    budget raise is nearly free in wall time. Evidence and trajectories
    are recorded in docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md and
    evaluation_results/finite_m5/f1_probe_*/.

    Fails closed: invalid inputs and invalid numerical controls
    (nonfinite/zero/negative ``tol``, fractional or sub-1 budgets) raise
    ValueError before any lookup or iteration; no converged in-domain
    point raises DCConvergenceError; genuinely out-of-grid final coordinates
    raise DomainError. Trial-point clipping is permitted only inside the
    line search and is counted in the returned diagnostics. The final
    verification canonicalizes every LUT coordinate of all five devices
    (F1-R1: ULP-scale representation allowance, edge-snap recorded, never
    extrapolated), builds the returned device points from those canonical
    coordinates, validates every point for finite physical data (F1-R3),
    and recomputes the acceptance KCL FROM the returned points - the
    accepted evaluation and the returned evidence are one evaluation.
    """
    L1, gmid1, L3, gmid3, L5, gmid5, Itail = validate_finite_design(
        (L1, gmid1, L3, gmid3, L5, gmid5, Itail))
    tol, max_newton, max_outer = _validate_numeric_settings(
        tol, max_newton, max_outer)

    w_ref_n, w_ref_p = dm.nch.W, dm.pch.W
    clamps: list[str] = []      # LUT-axis clamps (ideal-mode diagnostic name)
    n_vclip = 0                 # line-search voltage clips (A2 diagnostic)
    n_newton = 0

    def ids_n(w, vgs, vds, vsb):
        return _ids(dm.nch, w, w_ref_n, L1, vgs, vds, vsb, clamps)

    def ids_p(w, vsg, vsd):
        return _ids(dm.pch, w, w_ref_p, L3, vsg, vsd, 0.0, clamps)

    def residuals(z, w1, w3, w5, vb5):
        vt, vm, vo = z
        vgs = vicm - vt
        i1 = ids_n(w1, vgs, vm - vt, vt)
        i2 = ids_n(w1, vgs, vo - vt, vt)
        i3 = ids_p(w3, vdd - vm, vdd - vm)
        i4 = ids_p(w3, vdd - vm, vdd - vo)
        i5 = _ids(dm.nch, w5, w_ref_n, L5, vb5, vt, 0.0, clamps)
        return np.array([i1 + i2 - i5, i1 - i3, i4 - i2])

    # ---- sizing helpers (same rules as ideal mode for W1/W3) -------------
    def size_w1(vt, vm):
        vds1 = max(vm - vt, 1e-3)
        vsb1 = max(vt, 0.0)
        vgs1 = float(dm.nch.lookup_vgs([L1], [gmid1], [vds1], [vsb1])[0])
        id_char = _ids(dm.nch, w_ref_n, w_ref_n, L1, vgs1, vds1, vsb1, clamps)
        return (Itail / 2.0) / max(id_char, 1e-18) * w_ref_n

    def size_w3(vm):
        # Diode-connected PMOS: VSG = VSD, found self-consistently.
        vsg = max(vdd - vm, 1e-3)
        for _ in range(20):
            vsg_new = float(dm.pch.lookup_vgs([L3], [gmid3], [vsg], [0.0])[0])
            if abs(vsg_new - vsg) < 1e-9:
                break
            vsg = vsg_new
        id_char = _ids(dm.pch, w_ref_p, w_ref_p, L3, vsg, vsg, 0.0, clamps)
        return (Itail / 2.0) / max(id_char, 1e-18) * w_ref_p

    def derive_vb5(vt):
        return _forward_gmid_vgs(dm.nch, L5, gmid5, vt, 0.0)

    def size_w5(vt, vb5):
        id_char = _ids(dm.nch, w_ref_n, w_ref_n, L5, vb5, vt, 0.0, clamps)
        # A2: no current floor. An unsizable tail is a deterministic
        # numerical failure, never an apparently valid huge width.
        if not (np.isfinite(id_char) and id_char > 0.0):
            raise DCConvergenceError(
                f"M5 characterization current not positive/finite at "
                f"L5={L5:.3g} m, VGS5={vb5:.3g} V, VDS5={vt:.3g} V; "
                "tail cannot be sized")
        return Itail / id_char * w_ref_n

    # ---- initial guess: same recipe as ideal mode -------------------------
    if x0 is None:
        vgs1_0 = float(dm.nch.lookup_vgs([L1], [gmid1], [vicm / 2.0], [0.0])[0])
        vt = max(vicm - vgs1_0, 0.05)
        vgs3_0 = float(dm.pch.lookup_vgs([L3], [gmid3], [0.6], [0.0])[0])
        vm = max(vdd - vgs3_0, 0.05)
        vo = vdd / 2.0
        x0 = (min(max(vt, 0.02), vdd - 0.02),
              min(max(vm, 0.02), vdd - 0.02),
              min(max(vo, 0.02), vdd - 0.02))
    z = np.array(x0, dtype=float)
    if z.shape != (3,) or not np.isfinite(z).all():
        raise ValueError("x0 must be three finite voltages")
    if np.any(z <= 0.0) or np.any(z >= vdd):
        raise ValueError("x0 voltages must lie strictly inside (0, VDD)")

    vb5 = derive_vb5(float(z[0]))
    w1, w3 = size_w1(z[0], z[1]), size_w3(z[1])
    w5 = size_w5(float(z[0]), vb5)

    w_rel = dvb = float("nan")
    for _outer in range(max_outer):
        # ---- inner damped Newton, frozen (w1, w3, w5, vb5) ----------------
        r = residuals(z, w1, w3, w5, vb5)
        for _ in range(max_newton):
            nrm = float(np.max(np.abs(r)))
            if nrm < tol:
                break
            J = np.zeros((3, 3))
            for j in range(3):
                h = 1e-7
                zp = z.copy()
                zp[j] += h
                J[:, j] = (residuals(zp, w1, w3, w5, vb5) - r) / h
            if not (np.isfinite(J).all() and np.isfinite(r).all()):
                raise DCConvergenceError(
                    "nonfinite KCL residual or Jacobian in the finite solve")
            sv = np.linalg.svd(J, compute_uv=False)
            if not np.isfinite(sv).all() or float(sv.min()) <= 0.0:
                raise DCConvergenceError("singular KCL Jacobian (finite tail)")
            cond = float(sv.max() / sv.min())
            if cond > _COND_REJECT:
                raise DCConvergenceError(
                    f"ill-conditioned KCL Jacobian (cond ~ {cond:.3g})")
            try:
                dz = np.linalg.solve(J, -r)
            except np.linalg.LinAlgError:
                raise DCConvergenceError("singular KCL Jacobian (finite tail)")
            if not np.isfinite(dz).all():
                raise DCConvergenceError(
                    "nonfinite Newton step in the finite solve")
            alpha = 1.0
            for _bt in range(30):
                z_trial = z + alpha * dz
                if np.any(z_trial <= 1e-3) or np.any(z_trial >= vdd - 1e-3):
                    n_vclip += 1
                z_new = np.clip(z_trial, 1e-3, vdd - 1e-3)
                r_new = residuals(z_new, w1, w3, w5, vb5)
                if not np.isfinite(r_new).all():
                    raise DCConvergenceError(
                        "nonfinite KCL residual during line search")
                if float(np.max(np.abs(r_new))) < nrm or alpha < 1e-4:
                    break
                alpha *= 0.5
            z, r = z_new, r_new
            n_newton += 1
        else:
            raise DCConvergenceError(
                f"finite KCL solve did not converge "
                f"(max |residual| = {float(np.max(np.abs(r))):.3g} A)")

        # ---- outer geometry + gate-bias update at the solved voltages ----
        vt, vm, vo = (float(v) for v in z)
        vb5_new = derive_vb5(vt)
        w1_new, w3_new = size_w1(vt, vm), size_w3(vm)
        w5_new = size_w5(vt, vb5_new)
        w_rel = max(abs(a - b) / max(a, 1e-18)
                    for a, b in ((w1_new, w1), (w3_new, w3), (w5_new, w5)))
        dvb = abs(vb5_new - vb5)
        if trace is not None:
            trace.append({
                "outer_iteration": _outer + 1,
                "Vtail": vt, "Vmirror": vm, "Vout": vo,
                "W1": w1_new, "W3": w3_new, "W5": w5_new,
                "Vbias_tail": vb5_new,
                "width_rel_change": float(w_rel),
                "bias_abs_change_v": float(dvb),
            })
        w1, w3, w5, vb5 = w1_new, w3_new, w5_new, vb5_new
        if (w_rel < FINITE_TOLERANCES["width_rel_change"]
                and dvb <= FINITE_TOLERANCES["bias_abs_change_v"]):
            break
    else:
        raise DCConvergenceError(
            f"finite sizing fixed point did not converge in {max_outer} "
            f"outer iterations (final width rel change {w_rel:.3g}, "
            f"bias change {dvb:.3g} V)")

    # ---- final verification: FIXED returned device, canonical domain ------
    # (F1-R1) One canonical coordinate set feeds the acceptance KCL
    # recomputation AND every returned device point, so the accepted
    # evaluation and the returned evidence are the same evaluation by
    # construction. Genuine out-of-grid coordinates raise; only ULP-scale
    # representation excursions are snapped, and every snap is recorded.
    vt, vm, vo = (float(v) for v in z)
    for nm, val in (("Vtail", vt), ("Vmirror", vm), ("Vout", vo),
                    ("Vbias_tail", vb5)):
        if not 0.0 < val < vdd:
            raise DCConvergenceError(f"{nm}={val:.6g} V outside (0, VDD)")

    snaps: list[dict] = []

    def canon(val, grid, name):
        before = float(val)
        q = _canonical_coord(val, grid, name)
        if q != before:
            snaps.append({"axis": name, "requested": before, "canonical": q})
        return q

    L1c = canon(L1, dm.nch.L, "L")
    vg1 = canon(vicm - vt, dm.nch.VGS, "VGS")
    vsb1 = canon(vt, dm.nch.VSB, "VSB")
    vd1 = canon(vm - vt, dm.nch.VDS, "VDS")
    vd2 = canon(vo - vt, dm.nch.VDS, "VDS")
    L3c = canon(L3, dm.pch.L, "L")
    vg3 = canon(vdd - vm, dm.pch.VGS, "VGS")
    vd3 = canon(vdd - vm, dm.pch.VDS, "VDS")
    vd4 = canon(vdd - vo, dm.pch.VDS, "VDS")
    L5c = canon(L5, dm.nch.L, "L")
    vg5 = canon(vb5, dm.nch.VGS, "VGS")
    vd5 = canon(vt, dm.nch.VDS, "VDS")

    # Hard width limits bind on the FINAL geometry only (A2: an excessive
    # intermediate W5 is diagnostic, not proof of impossibility).
    for nm, wv, lim in (("W1", w1, config.W_NMOS_MAX),
                        ("W3", w3, config.W_PMOS_MAX),
                        ("W5", w5, config.W_NMOS_MAX)):
        if not 0.0 < wv <= lim:
            raise DCConvergenceError(
                f"final {nm}={wv * 1e6:.1f} um outside hard limit "
                f"{lim * 1e6:.1f} um")

    # Returned device points at the canonical coordinates; acceptance KCL is
    # recomputed FROM these points (F1-R1), and every point is validated for
    # finite, physical mandatory data before acceptance (F1-R3).
    points = {
        "M1": _point(dm.nch, w1, w_ref_n, L1c, vg1, vd1, vsb1, gmid1),
        "M2": _point(dm.nch, w1, w_ref_n, L1c, vg1, vd2, vsb1, gmid1),
        "M3": _point(dm.pch, w3, w_ref_p, L3c, vg3, vd3, 0.0, gmid3),
        "M4": _point(dm.pch, w3, w_ref_p, L3c, vg3, vd4, 0.0, gmid3),
        "M5": _point(dm.nch, w5, w_ref_n, L5c, vg5, vd5, 0.0, gmid5),
    }
    for name, point in points.items():
        _validate_point_finite(name, point)

    i1, i2 = points["M1"]["ID"], points["M2"]["ID"]
    i3, i4 = points["M3"]["ID"], points["M4"]["ID"]
    i5 = points["M5"]["ID"]
    r_final = np.array([i1 + i2 - i5, i1 - i3, i4 - i2])
    if not np.isfinite(r_final).all():
        raise DCConvergenceError("nonfinite KCL residual at the final point")
    kcl_max = float(np.max(np.abs(r_final)))
    if kcl_max > FINITE_TOLERANCES["kcl_acceptance_a"]:
        raise DCConvergenceError(
            f"KCL residual after finite sizing loop: {kcl_max:.3g} A")

    # Forward-ratio evidence (A2/F1-R3): gm/ID from the returned gm and ID,
    # NOT the interpolated gmid table value, which is recorded separately
    # under its own name. Finiteness is checked before any comparison.
    m5 = points["M5"]
    gmid5_forward = m5["gm"] / m5["ID"]
    if not np.isfinite(gmid5_forward):
        raise DCConvergenceError(
            f"forward gm/Id5 not finite (gm={m5['gm']!r}, ID={m5['ID']!r})")
    m5["gmid_table"] = m5["gmid_achieved"]
    m5["gmid_forward"] = gmid5_forward
    m5["gmid_forward_error"] = gmid5_forward - gmid5
    id5_err = abs(m5["ID"] - Itail) / Itail
    if not np.isfinite(id5_err):
        raise DCConvergenceError("M5 current error not finite")
    gmid5_err = abs(gmid5_forward - gmid5)
    if id5_err > FINITE_TOLERANCES["id5_rel_error"]:
        raise DCConvergenceError(
            f"ID5 {m5['ID']:.6g} A deviates {id5_err:.3g} (rel) from Itail")
    if gmid5_err > FINITE_TOLERANCES["gmid5_abs_error_inv"]:
        raise DCConvergenceError(
            f"forward gm/Id5 {gmid5_forward:.6g} deviates {gmid5_err:.3g} "
            f"1/V from target {gmid5}")

    return {
        "topology_mode": "finite_tail_solved",
        "Vtail": vt, "Vmirror": vm, "Vout": vo,
        "W1": w1, "W3": w3, "W5": w5,
        "Vbias_tail": vb5,
        "M1": points["M1"], "M2": points["M2"], "M3": points["M3"],
        "M4": points["M4"], "M5": m5,
        "kcl_residuals": {
            "tail": float(r_final[0]), "mirror": float(r_final[1]),
            "output": float(r_final[2]),
        },
        "kcl_max_abs": kcl_max,
        "kcl_max_over_itail": kcl_max / Itail,
        "m5_current_error_rel": float(id5_err),
        "m5_gmid_forward_error": float(gmid5_err),
        "sat_m5": float(vd5 - m5["VDSAT"]),
        "convergence": {
            "outer_iterations": _outer + 1,
            "inner_newton_steps": n_newton,
            "final_width_rel_change": float(w_rel),
            "final_bias_abs_change_v": float(dvb),
            "tolerances": {**FINITE_TOLERANCES,
                           "kcl_newton_target_a": float(tol)},
            "effective_settings": {"tol": float(tol),
                                   "max_newton": int(max_newton),
                                   "max_outer": int(max_outer)},
        },
        "clip_diagnostics": {
            "lut_axis_clamps": {k: v for k, v in sorted(Counter(clamps).items())},
            "voltage_line_search_clips": n_vclip,
            "coordinate_snaps": snaps,
        },
    }

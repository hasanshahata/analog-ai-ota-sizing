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

import numpy as np

from ..devices.lut import LUT


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

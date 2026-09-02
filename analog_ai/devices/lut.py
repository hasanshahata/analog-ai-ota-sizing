"""gm/Id lookup tables with explicit domain validation.

Fixes vs. the legacy `tech_luts/lut_utils.py`:
- Out-of-grid queries raise `DomainError` by default instead of silently
  extrapolating (`RegularGridInterpolator(bounds_error=False, fill_value=None)`).
- The reverse gm/Id lookup validates that the target gm/Id is achievable at
  the queried (L, VDS, VSB) and detects non-monotonic gm/Id(VGS) curves
  instead of silently clamping via `np.interp`.
- Optional SHA-256 verification of the pickle file.
"""

from __future__ import annotations

import hashlib
import pickle
from typing import Sequence

import numpy as np
from scipy.interpolate import RegularGridInterpolator

_LUT_PARAMS = (
    "ids", "gm", "gds", "cgg", "cgs", "cgd", "cdd", "vth", "vdsat", "gmbs", "gmid",
)


class DomainError(ValueError):
    """A query falls outside the characterized LUT domain."""


class LUT:
    def __init__(self, filepath: str, verify_sha256: str | None = None,
                 allow_extrapolation: bool = False):
        with open(filepath, "rb") as f:
            self.data = pickle.load(f)

        if verify_sha256 is not None:
            digest = self.sha256(filepath)
            if digest != verify_sha256:
                raise ValueError(
                    f"LUT checksum mismatch for {filepath}: expected {verify_sha256}, got {digest}"
                )

        for axis in ("L", "VGS", "VDS", "VSB"):
            if axis not in self.data:
                raise KeyError(f"LUT file {filepath} is missing the '{axis}' axis")
        self.L = np.asarray(self.data["L"], dtype=float)
        self.VGS = np.asarray(self.data["VGS"], dtype=float)
        self.VDS = np.asarray(self.data["VDS"], dtype=float)
        self.VSB = np.asarray(self.data["VSB"], dtype=float)
        # Reference width the characterization was run at.
        self.W = float(self.data.get("W", 5e-6))
        self.allow_extrapolation = allow_extrapolation

        # gm/Id derived from |gm| / |Ids| (PMOS currents may be negative).
        ids_abs = np.abs(self.data["ids"])
        gm_abs = np.abs(self.data["gm"])
        self.gmid = gm_abs / np.maximum(ids_abs, 1e-15)

        grid = (self.L, self.VGS, self.VDS, self.VSB)
        self.interpolators: dict[str, RegularGridInterpolator] = {}
        for key in _LUT_PARAMS:
            table = self.data[key] if key in self.data else (self.gmid if key == "gmid" else None)
            if table is None:
                continue
            self.interpolators[key] = RegularGridInterpolator(
                grid, np.asarray(table, dtype=float),
                bounds_error=False, fill_value=None,
            )

    # ------------------------------------------------------------ domain ---
    @staticmethod
    def sha256(filepath: str) -> str:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        return h.hexdigest()

    def in_domain(self, L, VGS, VDS, VSB, tol: float = 1e-9) -> np.ndarray:
        """Element-wise mask of whether query points lie inside the characterized grid."""
        L_a, VGS_a, VDS_a, VSB_a = np.broadcast_arrays(
            np.atleast_1d(np.asarray(L, dtype=float)),
            np.atleast_1d(np.asarray(VGS, dtype=float)),
            np.atleast_1d(np.asarray(VDS, dtype=float)),
            np.atleast_1d(np.asarray(VSB, dtype=float)),
        )
        inside = (
            (L_a >= self.L.min() - tol) & (L_a <= self.L.max() + tol)
            & (VGS_a >= self.VGS.min() - tol) & (VGS_a <= self.VGS.max() + tol)
            & (VDS_a >= self.VDS.min() - tol) & (VDS_a <= self.VDS.max() + tol)
            & (VSB_a >= self.VSB.min() - tol) & (VSB_a <= self.VSB.max() + tol)
        )
        return inside

    def _check_domain(self, L, VGS, VDS, VSB) -> None:
        if self.allow_extrapolation:
            return
        inside = self.in_domain(L, VGS, VDS, VSB)
        if not np.all(inside):
            bad = int(np.size(inside) - np.count_nonzero(inside))
            raise DomainError(
                f"{bad} query point(s) outside LUT domain "
                f"(L=[{self.L.min():.3g},{self.L.max():.3g}], "
                f"VGS=[{self.VGS.min():.3g},{self.VGS.max():.3g}], "
                f"VDS=[{self.VDS.min():.3g},{self.VDS.max():.3g}], "
                f"VSB=[{self.VSB.min():.3g},{self.VSB.max():.3g}])"
            )

    # ----------------------------------------------------------- lookups ---
    def lookup(self, param: str, L, VGS, VDS, VSB) -> np.ndarray:
        """Forward lookup of `param` at absolute bias coordinates."""
        if param not in self.interpolators:
            raise KeyError(f"Parameter '{param}' not present in this LUT")
        L, VGS, VDS, VSB = self._broadcast(L, VGS, VDS, VSB)
        self._check_domain(L, VGS, VDS, VSB)
        pts = np.column_stack([L.ravel(), VGS.ravel(), VDS.ravel(), VSB.ravel()])
        return self.interpolators[param](pts).reshape(L.shape)

    def lookup_vgs(self, L, gmid_target, VDS, VSB) -> np.ndarray:
        """Reverse lookup: VGS required to reach a target gm/Id at (L, VDS, VSB).

        Raises DomainError when the target gm/Id is not achievable on the
        characterized curve (the legacy code silently clamped here).
        """
        L, gmid_t, VDS, VSB = self._broadcast(L, gmid_target, VDS, VSB)
        self._check_domain(L, VGS=np.full_like(L, float(np.mean(self.VGS))), VDS=VDS, VSB=VSB)
        # Any VGS is fine for the domain check above; per-point checks happen below.
        out = np.empty(L.shape, dtype=float)
        for idx in np.ndindex(L.shape):
            l, g, vd, vsb = L[idx], gmid_t[idx], VDS[idx], VSB[idx]
            pts = np.column_stack([
                np.full_like(self.VGS, l), self.VGS,
                np.full_like(self.VGS, vd), np.full_like(self.VGS, vsb),
            ])
            curve = self.interpolators["gmid"](pts)
            vgs_grid = self.VGS

            # Standard gm/Id-methodology reverse lookup: gm/Id rises through
            # weak inversion to a plateau (peak) and then decreases with VGS.
            # Real characterization data has small non-monotonic wiggles near
            # the peak, so we interpolate on the decreasing branch after the
            # peak instead of assuming global monotonicity (the legacy code
            # re-sorted the whole curve, which can select a nonphysical branch,
            # or silently clamp via np.interp).
            i_peak = int(np.argmax(curve))
            branch = curve[i_peak:]
            vgs_branch = vgs_grid[i_peak:]
            span = float(branch.max() - branch.min())
            increases = np.diff(branch)
            tol = max(0.01 * span, 1e-6)
            if np.any(increases > tol):
                raise DomainError(
                    f"gm/Id(VGS) curve not decreasing after its peak "
                    f"(L={l:.3g}, VDS={vd:.3g}, VSB={vsb:.3g}) - characterization problem"
                )
            lo, hi = float(branch[-1]), float(branch[0])
            if not (lo - tol <= g <= hi + tol):
                raise DomainError(
                    f"gm/Id target {g:.3g} outside achievable range [{lo:.3g}, {hi:.3g}] "
                    f"at L={l:.3g}, VDS={vd:.3g}, VSB={vsb:.3g}"
                )
            out[idx] = np.interp(g, branch[::-1], vgs_branch[::-1])  # increasing xp
        return out

    def lookup_with_gmid(self, param: str, L, gmid, VDS, VSB) -> np.ndarray:
        """Forward lookup at a gm/Id bias point (returns `param` values only)."""
        vgs = self.lookup_vgs(L, gmid, VDS, VSB)
        return self.lookup(param, L, vgs, VDS, VSB)

    # ---------------------------------------------------------- helpers ----
    @staticmethod
    def _broadcast(*coords):
        return tuple(
            np.atleast_1d(np.asarray(c, dtype=float)) for c in coords
        )

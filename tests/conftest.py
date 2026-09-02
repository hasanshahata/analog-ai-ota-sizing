"""Shared fixtures: a synthetic square-law LUT so the whole stack is testable
without the 5.5 GB TSMC characterization files.

The toy LUT stores positive (absolute) values for both device types, exactly
like the real pipeline (the legacy code applies abs() everywhere). gm, gds,
and gmbs are computed as numerical derivatives of the same ids() used to fill
the table, so forward and reverse lookups are self-consistent.
"""

from __future__ import annotations

import pickle

import numpy as np
import pytest

W_REF = 2e-6
GRID_L = np.array([0.18e-6, 0.6e-6, 1.5e-6])
GRID_VGS = np.linspace(0.45, 1.2, 16)
GRID_VDS = np.linspace(0.02, 1.2, 24)
GRID_VSB = np.array([0.0, 0.2, 0.4])


def _vth(vth0, vsb, gamma=0.5, phif2=0.8):
    return vth0 + gamma * (np.sqrt(phif2 + vsb) - np.sqrt(phif2))


def _ids(vgs, vds, vsb, L, kp, vth0, lamp_ref=0.1, l_ref=0.18e-6):
    """Square-law drain current (positive magnitudes), with CLM."""
    vt = _vth(vth0, vsb)
    lam = lamp_ref * (l_ref / L)
    od = vgs - vt
    od = np.maximum(od, 0.0)
    sat = kp / 2.0 * od**2 * (1.0 + lam * vds)
    lin = kp * (od * vds - vds**2 / 2.0) * (1.0 + lam * vds)
    return np.where(vds > od, sat, lin)


def _caps(L, cox=8e-3):
    # per reference width, in farads
    wl = W_REF * L
    cgs = 2.0 / 3.0 * cox * wl
    cgd = cox * W_REF * 10e-9          # gate-drain overlap
    cdd = cgd + 0.2 * cox * wl
    cgg = cgs + cgd + cox * W_REF * L * (1.0 / 3.0)
    return cgs, cgd, cdd, cgg


def build_lut_data(kp, vth0, l_ref=0.18e-6, lamp_ref=0.1):
    shape = (len(GRID_L), len(GRID_VGS), len(GRID_VDS), len(GRID_VSB))
    out = {k: np.zeros(shape) for k in
           ("ids", "gm", "gds", "gmbs", "cgg", "cgs", "cgd", "cdd", "vth", "vdsat")}
    eps = 1e-5
    for i, L in enumerate(GRID_L):
        cgs, cgd, cdd, cgg = _caps(L)
        for j, vgs in enumerate(GRID_VGS):
            for k, vds in enumerate(GRID_VDS):
                for m, vsb in enumerate(GRID_VSB):
                    args = (vgs, vds, vsb, L, kp, vth0, lamp_ref, l_ref)
                    ids = float(_ids(*args))
                    gm = float((_ids(vgs + eps, vds, vsb, L, kp, vth0, lamp_ref, l_ref)
                                - _ids(vgs - eps, vds, vsb, L, kp, vth0, lamp_ref, l_ref)) / (2 * eps))
                    gds = float((_ids(vgs, vds + eps, vsb, L, kp, vth0, lamp_ref, l_ref)
                                 - _ids(vgs, vds - eps, vsb, L, kp, vth0, lamp_ref, l_ref)) / (2 * eps))
                    gmbs = float((_ids(vgs, vds, vsb + eps, L, kp, vth0, lamp_ref, l_ref)
                                  - _ids(vgs, vds, vsb - eps, L, kp, vth0, lamp_ref, l_ref)) / (2 * eps))
                    vt = float(_vth(vth0, vsb))
                    out["ids"][i, j, k, m] = abs(ids)
                    out["gm"][i, j, k, m] = abs(gm)
                    out["gds"][i, j, k, m] = abs(gds)
                    out["gmbs"][i, j, k, m] = abs(gmbs)
                    out["cgg"][i, j, k, m] = cgg
                    out["cgs"][i, j, k, m] = cgs
                    out["cgd"][i, j, k, m] = cgd
                    out["cdd"][i, j, k, m] = cdd
                    out["vth"][i, j, k, m] = vt
                    out["vdsat"][i, j, k, m] = max(vgs - vt, 1e-3)
    out["gmid"] = out["gm"] / np.maximum(out["ids"], 1e-15)
    out["L"], out["VGS"], out["VDS"], out["VSB"], out["W"] = (
        GRID_L, GRID_VGS, GRID_VDS, GRID_VSB, W_REF)
    return out


@pytest.fixture(scope="session")
def lut_paths(tmp_path_factory):
    d = tmp_path_factory.mktemp("luts")
    nch = build_lut_data(kp=300e-6, vth0=0.35)
    pch = build_lut_data(kp=100e-6, vth0=0.40)
    pn, pp = d / "nch.pkl", d / "pch.pkl"
    with open(pn, "wb") as f:
        pickle.dump(nch, f)
    with open(pp, "wb") as f:
        pickle.dump(pch, f)
    return str(pn), str(pp)


@pytest.fixture(scope="session")
def engine(lut_paths):
    from analog_ai.loader import load_engine_from_paths
    return load_engine_from_paths(lut_paths[0], lut_paths[1])

"""3x3 Modified Nodal Analysis AC solver for the 5T OTA (proxy, not ground truth).

Topology (identical to the V2-V12 proxy so results remain comparable):

    node 1: V_tail   - source of M1/M2, drain of M5
    node 2: V_mirror - drain of M1, gate/drain of M3, gate of M4
    node 3: V_out    - drain of M2, drain of M4, C_L

Fixes vs. the legacy `core/mna_engine.py`:
- Body effect uses the LUT's `gmbs` value (key `gmbs`). The legacy engine read
  `m.get('gmb', ...)`, a key the device model never produced, so a flat
  0.2*gm stand-in was silently substituted in every evaluation ever run.
- Dead zeroed capacitance terms removed.
- Metric extraction unwraps phase before interpolation and reports an explicit
  no-crossing status instead of returning the sweep's maximum frequency as GBW.

Known, documented approximations (see docs/DESIGN_CONTRACT.md):
- DC operating point is imposed, not solved.
- Source-bulk capacitances are neglected (not characterized in the LUT keys used).
- First 0 dB crossing only; higher-order crossing handling is out of scope.
"""

from __future__ import annotations

import numpy as np

from ..config import AC_FREQ_MAX_HZ, AC_FREQ_MIN_HZ, AC_POINTS_PER_DECADE


class MNAEngine:
    def default_freqs(self) -> np.ndarray:
        decades = np.log10(AC_FREQ_MAX_HZ) - np.log10(AC_FREQ_MIN_HZ)
        n = int(round(decades * AC_POINTS_PER_DECADE)) + 1
        return np.logspace(np.log10(AC_FREQ_MIN_HZ), np.log10(AC_FREQ_MAX_HZ), n)

    # -------------------------------------------------------------- solve ---
    def solve_ac(self, m1, m2, m3, m4, m5, CL: float, freqs) -> np.ndarray:
        freqs = np.atleast_1d(np.asarray(freqs, dtype=float))
        s = 1j * 2.0 * np.pi * freqs
        n = len(s)

        Y = np.zeros((n, 3, 3), dtype=np.complex128)
        I = np.zeros((n, 3, 1), dtype=np.complex128)

        gmb1 = m1.get("gmbs", 0.2 * m1["gm"])
        gmb2 = m2.get("gmbs", 0.2 * m2["gm"])

        # Node 1 (V_tail)
        Y[:, 0, 0] = (m5["gds"] + m1["gds"] + m2["gds"]
                      + m1["gm"] + m2["gm"] + gmb1 + gmb2
                      + s * (m1["cgs"] + m2["cgs"] + m5["cdd"]))
        Y[:, 0, 1] = -m1["gds"] - s * m1["cgd"]
        Y[:, 0, 2] = -m2["gds"] - s * m2["cgd"]

        # Node 2 (V_mirror)
        Y[:, 1, 0] = -(m1["gds"] + m1["gm"]) - s * m1["cgs"]
        Y[:, 1, 1] = (m1["gds"] + m3["gds"] + m3["gm"]
                      + s * (m1["cdd"] + m1["cgd"] + m3["cdd"] + m3["cgs"] + m4["cgs"] + m3["cgd"]))
        Y[:, 1, 2] = 0.0

        # Node 3 (V_out)
        Y[:, 2, 0] = -(m2["gds"] + m2["gm"]) - s * m2["cgs"]
        Y[:, 2, 1] = m4["gm"] + s * m4["cgd"]
        Y[:, 2, 2] = m2["gds"] + m4["gds"] + s * (m2["cdd"] + m2["cgd"] + m4["cdd"] + m4["cgd"] + CL)

        # Differential drive: vg1 = +0.5, vg2 = -0.5 (1 V differential).
        I[:, 0, 0] = 0.5 * m1["gm"] - 0.5 * m2["gm"]
        I[:, 1, 0] = -0.5 * m1["gm"]
        I[:, 2, 0] = 0.5 * m2["gm"]

        V = np.linalg.solve(Y, I)
        return V[:, 2, 0]

    # ----------------------------------------------------------- metrics ---
    def extract_metrics(self, freqs, V_out) -> dict:
        """DC gain [dB], GBW [Hz], phase margin [deg], and extraction status.

        `gbw_valid=False` means no 0 dB crossing below `freqs[-1]`; in that case
        GBW is reported as NaN (the legacy code returned the sweep maximum,
        presenting "no crossing below 10 GHz" as a real 10 GHz GBW).
        """
        freqs = np.atleast_1d(np.asarray(freqs, dtype=float))
        V_out = np.asarray(V_out)
        mags = np.abs(V_out)
        phase = np.rad2deg(np.unwrap(np.angle(V_out)))  # unwrapped, continuous

        gain_db = 20.0 * np.log10(mags[0])

        result = {
            "DC_Gain_dB": float(gain_db),
            "GBW": float("nan"),
            "PM": float("nan"),
            "gbw_valid": False,
            "A_v0_mag": float(mags[0]),
        }

        if mags[0] < 1.0:
            return result  # unity gain never reached from the start

        below = np.where(mags < 1.0)[0]
        if len(below) == 0:
            return result  # no crossing below sweep max -> flagged, GBW = NaN

        i = int(below[0])
        if i == 0:
            gbw = float(freqs[0])
            pm = float(180.0 + phase[0])
        else:
            f1, f2 = np.log10(freqs[i - 1]), np.log10(freqs[i])
            g1, g2 = 20.0 * np.log10(mags[i - 1]), 20.0 * np.log10(mags[i])
            # 0 dB crossing in log-frequency vs. dB-magnitude (linear in both).
            log_gbw = f1 + (f2 - f1) * (0.0 - g1) / (g2 - g1)
            gbw = float(10.0 ** log_gbw)
            frac = (log_gbw - f1) / (f2 - f1) if f2 > f1 else 0.0
            pm = float(180.0 + (phase[i - 1] + (phase[i] - phase[i - 1]) * frac))

        result.update(GBW=gbw, PM=pm, gbw_valid=True)
        return result

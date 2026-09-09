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

Phase F2 terminal-stamp audit (Astra R7, 2026-09-09): the legacy
:meth:`MNAEngine.solve_ac` is FROZEN for the historical ideal oracle. A
corrected assembly :meth:`MNAEngine.solve_ac_corrected` - derived
independently from the device terminal equations - is provided for the
finite path. Audited discrepancies of the legacy stamps, all reproduced in
tests/test_mna_audit.py:
  1. M1/M2 body transconductance entered the tail diagonal but was absent
     from the drain rows (Y[1,0], Y[2,0]); one controlled current must act
     at both terminals.
  2. M1/M2 cgs was stamped as a tail->drain coupling instead of a
     gate-driven capacitor with its excitation on the right-hand side.
  3. M1/M2 cgd was stamped as a tail->drain coupling although their gates
     are externally driven (those caps connect gates to drains).
  4. M4's gate-drain capacitance was stamped as a single +s*C off-diagonal
     (inductor-like) instead of a true two-terminal capacitor.
  5. M3's gate-drain overlap was added on top of cdd although its gate and
     drain are the same node (no inter-node admittance under any
     convention; double-counts under the fixture convention where
     cdd = cgd + junction).

Capacitance convention assumption (Astra A4, recorded limitation): the
corrected model stamps M5 drain loading as `gds5 + s*Cdd5` under the
assumption that `Cdd` is the complete drain self-capacitance for
gate/source/body at AC ground. The repo's synthetic fixture follows this
convention, but the real TSMC pickle's characterization is not available
in-repository (the files originate from a Google Drive download with no
deck/save expressions), so the convention is UNRESOLVED for real data; the
device-level Spectre experiment that would settle it belongs to F5. No
physical AC claim is made until then.
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

    # --------------------------------------------- corrected (F2, finite) ---
    def assemble_ac_corrected(self, m1, m2, m3, m4, m5, CL: float, freqs):
        """Assemble the corrected finite (Y, I) per frequency (F2 audit).

        Returns (Y, I) with shapes (n, 3, 3) and (n, 3, 1): the admittance
        matrix and the driven-gate excitation vector of the corrected
        terminal-equation model. Exposed for independent audit tests.
        See :meth:`solve_ac_corrected` for the model description.
        """
        freqs = np.atleast_1d(np.asarray(freqs, dtype=float))
        s = 1j * 2.0 * np.pi * freqs
        n = len(s)

        gmb1 = m1.get("gmbs", 0.2 * m1["gm"])
        gmb2 = m2.get("gmbs", 0.2 * m2["gm"])

        # Capacitance convention (declared lumped model, F2-R1): each Cdd is
        # the TOTAL drain capacitance = gate-drain overlap (Cgd) + junction
        # (Cdb = Cdd - Cgd). The gate-drain ELEMENT is stamped per its true
        # connectivity; only the derived JUNCTION lands on the drain
        # diagonal - never the total plus the element (which would count the
        # overlap twice). Inconsistent inputs (Cdd < Cgd) are rejected, not
        # clipped. Per device:
        #   M1/M2 (driven gate): overlap -> drain diagonal + RHS excitation;
        #                        junction -> drain diagonal. Drain diagonal
        #                        total equals Cdd either way; the RHS uses
        #                        the overlap element only.
        #   M3   (gate = drain): overlap is a same-node no-op; junction only.
        #   M4   (gate = mirror): overlap -> true two-terminal element
        #                         (mirror<->output); junction -> output.
        #   M5   (gate/source/body AC ground): overlap and junction both
        #                        terminate at AC ground -> the TOTAL Cdd is
        #                        the drain loading; no decomposition needed.
        def junction(total, overlap, name):
            c = float(total) - float(overlap)
            if c < 0.0:
                raise ValueError(
                    f"{name}: inconsistent capacitance convention (Cdd "
                    f"{total:.6g} F < Cgd {overlap:.6g} F under the declared "
                    "cdd = cgd + junction lumped model)")
            return c

        cdb1 = junction(m1["cdd"], m1["cgd"], "M1")
        cdb2 = junction(m2["cdd"], m2["cgd"], "M2")
        cdb3 = junction(m3["cdd"], m3["cgd"], "M3")
        cdb4 = junction(m4["cdd"], m4["cgd"], "M4")

        Y = np.zeros((n, 3, 3), dtype=np.complex128)
        I = np.zeros((n, 3, 1), dtype=np.complex128)

        # Node 1 (V_tail): M1/M2 sources, M5 drain.
        Y[:, 0, 0] = (m5["gds"] + m1["gds"] + m2["gds"]
                      + m1["gm"] + m2["gm"] + gmb1 + gmb2
                      + s * (m1["cgs"] + m2["cgs"] + m5["cdd"]))
        Y[:, 0, 1] = -m1["gds"]
        Y[:, 0, 2] = -m2["gds"]

        # Node 2 (V_mirror): M1 drain, M3 gate+drain, M4 gate.
        Y[:, 1, 0] = -(m1["gm"] + gmb1 + m1["gds"])
        Y[:, 1, 1] = (m1["gds"] + m3["gds"] + m3["gm"]
                      + s * m1["cdd"]                  # M1 overlap + junction
                      + s * (cdb3 + m3["cgs"])         # M3 junction + cgs
                      + s * (m4["cgs"] + m4["cgd"]))   # M4 cgs + overlap el.
        Y[:, 1, 2] = -s * m4["cgd"]

        # Node 3 (V_out): M2 drain, M4 drain, C_L.
        Y[:, 2, 0] = -(m2["gm"] + gmb2 + m2["gds"])
        Y[:, 2, 1] = m4["gm"] - s * m4["cgd"]
        Y[:, 2, 2] = (m2["gds"] + m4["gds"]
                      + s * m2["cdd"]                  # M2 overlap + junction
                      + s * (m4["cgd"] + cdb4)         # M4 overlap el. + jct
                      + s * CL)

        # Right-hand side: the two driven gates inject transconductance AND
        # capacitive currents. Cap terms vanish at DC and cancel between
        # matched devices under differential drive; they matter for
        # asymmetric pairs.
        I[:, 0, 0] = (0.5 * m1["gm"] - 0.5 * m2["gm"]
                      + 0.5 * s * (m1["cgs"] - m2["cgs"]))
        I[:, 1, 0] = -0.5 * m1["gm"] + 0.5 * s * m1["cgd"]
        I[:, 2, 0] = 0.5 * m2["gm"] - 0.5 * s * m2["cgd"]
        return Y, I

    def solve_ac_corrected(self, m1, m2, m3, m4, m5, CL: float, freqs,
                           ) -> np.ndarray:
        """Corrected finite AC assembly (Phase F2 terminal-stamp audit).

        Same 3-node topology and differential drive as :meth:`solve_ac`, but
        with every device stamped from its terminal equations:

        NMOS (M1/M2, current drain->source, |V| magnitudes):
            i_d = gm*(vg-vs) + gmbs*(vb-vs) + gds*(vd-vs)   [+ caps]
        PMOS (M3/M4, source at the AC-grounded vdd rail, |V| magnitudes):
            current into the drain node = -gm*vg - gds*vd   [+ caps]

        Capacitor connectivity and convention (source-bulk neglected,
        documented; F2-R1): each Cdd is treated as the TOTAL drain
        capacitance under the declared lumped model Cdd = Cgd + Cdb. The
        gate-drain ELEMENT (Cgd) is stamped per its true connectivity and
        the derived junction (Cdb = Cdd - Cgd) lands on the drain diagonal;
        the two are never both added at the same node. Inconsistent inputs
        (Cdd < Cgd) raise ValueError.
          - M1/M2 (driven gates): their cgs/cgd elements contribute a
            diagonal term at the drain/source node AND a right-hand-side
            excitation; they never couple two circuit nodes. The drain
            diagonal carries Cgd + Cdb = Cdd.
          - M4's cgd (gate at mirror, drain at output) is a true two-terminal
            capacitor: +s*C on both diagonals, -s*C on both off-diagonals;
            its junction Cdb lands on the output diagonal. Net output
            contribution: Cgd + Cdb = Cdd.
          - M3 (gate = drain = mirror): the overlap is a same-node no-op;
            only the junction Cdd - Cgd reaches the mirror diagonal.
          - M5 (gate/source/body AC-ground) contributes drain loading
            gds5 + s*Cdd5 only - overlap and junction both terminate at AC
            ground, so the total is correct; no transconductance exists.

        The legacy :meth:`solve_ac` is untouched and remains the frozen
        historical ideal oracle; see the module docstring for the audited
        differences and the recorded Cdd convention limitation.
        """
        Y, I = self.assemble_ac_corrected(m1, m2, m3, m4, m5, CL, freqs)
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

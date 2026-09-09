"""Canonical 5T-OTA evaluator.

Fixes vs. the legacy V2-V12 `circuits/ota5t.py`:
- **Matched devices stay matched.** M2 reuses M1's geometry (W/L) and M4 reuses
  M3's; each is only re-characterized at its own VDS. The legacy code called
  `size_device` independently per device, so the "matched" pair could end up
  with different widths (visible in the archived netlists: M1=289.9um vs
  M2=292.5um).
- **Invalid operating points are rejected, not silently clamped.** Negative
  VDS/Vtail used to be clamped to 10 mV and evaluated anyway; that now marks
  the design invalid.
- **Two operating-point modes** (see `evaluate`):
  * `imposed` (legacy semantics, V9-V12 comparability) with explicit
    self-consistency diagnostics (`pair/mirror_current_mismatch`);
  * `solved` - the DC operating point is computed from the LUT device curves
    by Newton iteration on the KCL residuals (`dc_solver.py`). Since the LUTs
    are Spectre-characterized, this mode contains no simulator and no imposed
    bias: it is device data + circuit laws, end to end.
- Optional finite tail device (`tail_device="finite"`, 7-parameter vector).

The AC stage is a small-signal MNA in both modes, with documented
approximations (see `mna.py`): source-bulk capacitances neglected,
first 0 dB crossing only.
"""

from __future__ import annotations

import numpy as np

from ..config import VDD, VICM, VOCM
from ..devices.device_model import DeviceModel
from ..devices.lut import DomainError
from .dc_solver import (DCConvergenceError, solve_operating_point,
                        solve_operating_point_finite)
from .mna import MNAEngine


class InvalidDesignError(ValueError):
    """The design vector does not admit a consistent operating point."""


class OTA5T:
    def __init__(self, device_model: DeviceModel, vdd: float = VDD,
                 tail_device: str = "ideal", op_point: str = "imposed"):
        if tail_device not in ("ideal", "finite"):
            raise ValueError("tail_device must be 'ideal' or 'finite'")
        if op_point not in ("imposed", "solved"):
            raise ValueError("op_point must be 'imposed' or 'solved'")
        if tail_device == "finite" and op_point == "solved":
            raise NotImplementedError(
                "finite-tail solved evaluation is not available yet; "
                "public finite metrics open at the Phase F2 gate "
                "(docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md)")
        self.dm = device_model
        self.mna = MNAEngine()
        self.VDD = vdd
        self.Vicm = vdd / 2.0
        self.Vocm = vdd / 2.0
        self.tail_device = tail_device
        self.op_point = op_point

    # ------------------------------------------------------------ public ---
    def evaluate(self, x, CL: float, freqs=None, op_point: str | None = None) -> dict:
        """Evaluate the OTA for a design vector.

        x = [L1, gmid1, L3, gmid3, Itail]              (tail_device="ideal")
        x = [L1, gmid1, L3, gmid3, L5, gmid5, Itail]   (tail_device="finite")

        op_point:
          "imposed" - legacy proxy semantics (Vicm=Vocm=VDD/2, Itail/2 per
                      branch). Kept for V9-V12 comparability; reports the
                      current-mismatch diagnostics of the imposed point.
          "solved"  - the DC operating point is *solved* from the LUT device
                      curves by driving KCL residuals to zero
                      (circuit/dc_solver.py). The LUTs are Spectre-derived,
                      so this chain contains no simulator and no imposed
                      bias assumptions; the output node settles where the
                      currents actually balance.

        Raises InvalidDesignError / DomainError for designs with no consistent
        operating point or out-of-LUT-domain parameters, ValueError for an
        invalid explicit ``op_point`` value (only None falls back to the
        constructor mode), and NotImplementedError for every finite+solved
        combination - including per-call ``op_point`` overrides, which
        previously bypassed the constructor guard and returned ideal-tail
        results for a finite-tail object (closed in Phase F1; public finite
        evaluation opens only at the F2 integration gate - see
        docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md).
        Callers (RL env, optimizer) treat invalid designs as invalid
        evaluations with a finite penalty.
        """
        if op_point is None:
            op_point = self.op_point
        if op_point not in ("imposed", "solved"):
            raise ValueError(
                f"op_point must be 'imposed' or 'solved', got {op_point!r}")
        if op_point == "solved":
            if self.tail_device == "finite":
                raise NotImplementedError(
                    "finite-tail solved evaluation is not available yet; "
                    "public finite metrics open at the Phase F2 gate "
                    "(docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md)")
            return self._evaluate_solved(x, CL, freqs)
        return self._evaluate_imposed(x, CL, freqs)

    # ---------------------------------------------------- imposed (legacy) --
    def _evaluate_imposed(self, x, CL: float, freqs) -> dict:
        if self.tail_device == "finite":
            if len(x) != 7:
                raise InvalidDesignError(
                    f"tail_device='finite' requires 7 parameters, got {len(x)}")
            L1, gmid1, L3, gmid3, L5, gmid5, Itail = map(float, x)
        else:
            if len(x) != 5:
                raise InvalidDesignError(
                    f"tail_device='ideal' requires 5 parameters, got {len(x)}")
            L1, gmid1, L3, gmid3, Itail = map(float, x)
            L5 = gmid5 = None

        if not (Itail > 0.0) or CL <= 0.0:
            raise InvalidDesignError("Itail and CL must be positive")

        warnings: list[str] = []

        Id_branch = Itail / 2.0

        # --- imposed operating point (documented approximation) -----------
        # First pass: assume VDS1 = VDD/2 to find VGS1.
        temp_m1 = self.dm.size_device("nch", gmid1, L1, Id_branch,
                                      VDS=self.VDD / 2.0, VSB=0.0)
        VGS1 = temp_m1["VGS"]
        Vtail = self.Vicm - VGS1
        if Vtail <= 0.0:
            raise InvalidDesignError(f"Vtail = {Vtail*1e3:.1f} mV <= 0 "
                                     "(VGS1 exceeds input common mode)")

        # Tail device.
        if self.tail_device == "finite":
            VDS5 = Vtail
            m5 = self.dm.size_device("nch", gmid5, L5, Itail, VDS=VDS5, VSB=0.0)
        else:
            m5 = ideal_tail(Vtail)

        # PMOS mirror: M3 is diode-connected (VDS3 = VGS3).
        temp_m3 = self.dm.size_device("pch", gmid3, L3, Id_branch, VDS=0.6, VSB=0.0)
        VGS3 = temp_m3["VGS"]
        Vmirror = self.VDD - VGS3
        if Vmirror <= 0.0:
            raise InvalidDesignError(f"Vmirror = {Vmirror*1e3:.1f} mV <= 0")
        m3 = self.dm.size_device("pch", gmid3, L3, Id_branch,
                                 VDS=VGS3, VSB=0.0)

        # M4: SAME geometry and gate-source voltage as M3, own VDS.
        VDS4 = self.VDD - self.Vocm
        m4 = self.dm.params_at_geometry("pch", m3["W"], m3["L"],
                                        VGS=VGS3, VDS=VDS4, VSB=0.0)

        # Input pair: M1 sets the geometry; M2 reuses it at its own VDS.
        VDS1 = Vmirror - Vtail
        if VDS1 <= 0.0:
            raise InvalidDesignError(f"VDS1 = {VDS1*1e3:.1f} mV <= 0")
        VSB1 = Vtail
        m1 = self.dm.size_device("nch", gmid1, L1, Id_branch,
                                 VDS=VDS1, VSB=VSB1)

        VDS2 = self.Vocm - Vtail
        if VDS2 <= 0.0:
            raise InvalidDesignError(f"VDS2 = {VDS2*1e3:.1f} mV <= 0")
        m2 = self.dm.params_at_geometry("nch", m1["W"], m1["L"],
                                        VGS=VGS1, VDS=VDS2, VSB=Vtail)

        # --- DC / large-signal quantities ---------------------------------
        Power = self.VDD * Itail
        SR = Itail / CL

        sat_m1 = m1["VDS"] - m1["VDSAT"]
        sat_m2 = m2["VDS"] - m2["VDSAT"]
        sat_m3 = m3["VDS"] - m3["VDSAT"]
        sat_m4 = m4["VDS"] - m4["VDSAT"]
        if self.tail_device == "finite":
            sat_m5 = m5["VDS"] - m5["VDSAT"]
        else:
            sat_m5 = float("inf")  # ideal tail: no device to leave saturation
        min_sat_margin = float(min(sat_m1, sat_m2, sat_m3, sat_m4, sat_m5))

        Swing = self.VDD - m4["VDSAT"] - m2["VDSAT"] - (
            m5["VDSAT"] if self.tail_device == "finite" else 0.0)
        ICMR_min = m1["VGS"] + (m5["VDSAT"] if self.tail_device == "finite" else 0.0)

        # DC self-consistency diagnostics for the imposed operating point.
        pair_current_mismatch = (m2["id_at_bias"] - Id_branch) / Id_branch
        mirror_current_mismatch = (m4["id_at_bias"] - Id_branch) / Id_branch
        if abs(pair_current_mismatch) > 0.2:
            warnings.append(
                f"pair current mismatch {100*pair_current_mismatch:.0f}% vs assumed Itail/2")
        if abs(mirror_current_mismatch) > 0.2:
            warnings.append(
                f"mirror current mismatch {100*mirror_current_mismatch:.0f}% vs assumed Itail/2")
        if min_sat_margin < 0.0:
            warnings.append("device out of saturation (negative saturation margin)")

        # --- AC small-signal proxy ----------------------------------------
        if freqs is None:
            freqs = self.mna.default_freqs()
        V_out = self.mna.solve_ac(m1, m2, m3, m4, m5, CL, freqs)
        ac = self.mna.extract_metrics(freqs, V_out)
        if not ac["gbw_valid"]:
            warnings.append("no 0 dB crossing below sweep maximum")

        if self.tail_device == "finite":
            Area = 2 * m1["W"] * m1["L"] + 2 * m3["W"] * m3["L"] + m5["W"] * m5["L"]
        else:
            Area = 2 * m1["W"] * m1["L"] + 2 * m3["W"] * m3["L"]

        return {
            "Power": Power,
            "SR": SR,
            "Swing": Swing,
            "ICMR_min": ICMR_min,
            "min_sat_margin": min_sat_margin,
            "sat_m1": sat_m1, "sat_m2": sat_m2, "sat_m3": sat_m3,
            "sat_m4": sat_m4, "sat_m5": sat_m5,
            "DC_Gain_dB": ac["DC_Gain_dB"],
            "GBW": ac["GBW"],
            "gbw_valid": ac["gbw_valid"],
            "PM": ac["PM"],
            "Area": Area,
            "CL": CL,
            "Vtail": Vtail,
            "Vmirror": Vmirror,
            "pair_current_mismatch": float(pair_current_mismatch),
            "mirror_current_mismatch": float(mirror_current_mismatch),
            "warnings": warnings,
            "devices": {"M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5},
        }

    # ----------------------------------------------------- solved (KCL) -----
    def _evaluate_solved(self, x, CL: float, freqs) -> dict:
        if len(x) != 5:
            raise InvalidDesignError(
                f"op_point='solved' requires 5 parameters, got {len(x)}")
        L1, gmid1, L3, gmid3, Itail = map(float, x)
        if not (Itail > 0.0) or CL <= 0.0:
            raise InvalidDesignError("Itail and CL must be positive")

        try:
            op = solve_operating_point(self.dm, L1, gmid1, L3, gmid3, Itail,
                                       vdd=self.VDD, vicm=self.Vicm)
        except DCConvergenceError as exc:
            raise InvalidDesignError(str(exc)) from exc

        warnings: list[str] = []
        if op["domain_clamps"]:
            warnings.append("operating point reached a LUT axis limit: "
                            + ", ".join(op["domain_clamps"]))

        # Device dicts for the small-signal solve, from the SOLVED bias.
        def dev(p, name):
            d = dict(p)
            d.update(type="nch" if name in ("M1", "M2") else "pch",
                     id_at_bias=p["ID"], VDSAT=p["VDSAT"])
            d.setdefault("gmbs", 0.2 * p["gm"])
            d.setdefault("cgs", 0.0)
            d.setdefault("cgd", 0.0)
            d.setdefault("cdd", 0.0)
            return d

        m1, m2 = dev(op["M1"], "M1"), dev(op["M2"], "M2")
        m3, m4 = dev(op["M3"], "M3"), dev(op["M4"], "M4")
        m5 = ideal_tail(op["Vtail"])

        vt, vm, vo = op["Vtail"], op["Vmirror"], op["Vout"]

        # Large-signal quantities at the solved point.
        Power = self.VDD * Itail
        SR = Itail / CL
        sat = {n: d["VDS"] - d["VDSAT"] for n, d in
               (("M1", m1), ("M2", m2), ("M3", m3), ("M4", m4))}
        min_sat_margin = float(min(sat.values()))
        Swing = self.VDD - m4["VDSAT"] - m2["VDSAT"]
        ICMR_min = m1["VGS"]

        gmid_dev = max(abs(op[n]["gmid_error"]) for n in ("M1", "M3"))
        if gmid_dev > 2.0:
            warnings.append(
                f"achieved gm/Id deviates up to {gmid_dev:.1f} from target "
                "(op-point feedback through channel-length modulation)")
        if min_sat_margin < 0.0:
            worst = min(sat, key=sat.get)
            warnings.append(f"{worst} out of saturation at the solved point")

        # AC small-signal at the solved bias.
        if freqs is None:
            freqs = self.mna.default_freqs()
        V_out = self.mna.solve_ac(m1, m2, m3, m4, m5, CL, freqs)
        ac = self.mna.extract_metrics(freqs, V_out)
        if not ac["gbw_valid"]:
            warnings.append("no 0 dB crossing below sweep maximum")

        Area = 2 * m1["W"] * m1["L"] + 2 * m3["W"] * m3["L"]

        return {
            "Power": Power,
            "SR": SR,
            "Swing": Swing,
            "ICMR_min": ICMR_min,
            "min_sat_margin": min_sat_margin,
            "sat_m1": sat["M1"], "sat_m2": sat["M2"],
            "sat_m3": sat["M3"], "sat_m4": sat["M4"], "sat_m5": float("inf"),
            "DC_Gain_dB": ac["DC_Gain_dB"],
            "GBW": ac["GBW"],
            "gbw_valid": ac["gbw_valid"],
            "PM": ac["PM"],
            "Area": Area,
            "CL": CL,
            "Vtail": vt,
            "Vmirror": vm,
            "Vout": vo,
            "pair_current_mismatch": float((m2["ID"] - Itail / 2.0) / (Itail / 2.0)),
            "mirror_current_mismatch": float((m4["ID"] - Itail / 2.0) / (Itail / 2.0)),
            "kcl_residuals": op["kcl_residuals"],
            "gmid_solved": {n: {"target": op[n]["gmid_target"],
                                "achieved": op[n]["gmid_achieved"]}
                            for n in ("M1", "M3")},
            "warnings": warnings,
            "devices": {"M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5},
        }

    # --------------------------------------- solved finite (F2, DEV ONLY) ---
    def _evaluate_solved_finite(self, x, CL: float, freqs) -> dict:
        """Integrated finite-M5 evaluation (Phase F2 - development access
        only; PUBLIC FINITE EVALUATION IS STILL CLOSED).

        evaluate() raises NotImplementedError for every finite+solved call
        until the F2 integration gate is accepted by Astra; this private
        method exists for the focused suite and the finite record path.

        Semantics:
        - DC operating point from the accepted F1 kernel
          (solve_operating_point_finite: strict fixed-device verification,
          forward gm/Id5 gate, canonical LUT domain).
        - AC small-signal from the CORRECTED terminal-stamp model
          (MNAEngine.solve_ac_corrected) with the solved M5 as pure drain
          loading - see mna.py for the audit and the recorded Cdd
          convention limitation.
        - Power is the finite core power VDD*(ID3+ID4), cross-checked
          against VDD*ID5 by KCL; the external gate-bias generator's power
          is excluded (outside the sized boundary).
        - SR is the slew-rate PROXY ID5/CL, not a transient measurement.
        - Swing/ICMR: nominal frozen-operating-point ESTIMATES only
          (Astra A5); the acceptance keys Swing/ICMR_min are NaN so any
          requested range constraint fails closed instead of passing on an
          estimate. The upper ICMR limit is not derivable and stays
          unreported.
        - Saturation evidence covers all five devices; the frozen
          Sat_margin_min floor applies unchanged (converged DC diagnostics
          with negative sat_m5 are NOT feasible designs).
        """
        if len(x) != 7:
            raise InvalidDesignError(
                f"finite solved evaluation requires 7 parameters, got {len(x)}")
        L1, gmid1, L3, gmid3, L5, gmid5, Itail = map(float, x)
        if not (Itail > 0.0) or CL <= 0.0:
            raise InvalidDesignError("Itail and CL must be positive")

        try:
            op = solve_operating_point_finite(self.dm, L1, gmid1, L3, gmid3,
                                              L5, gmid5, Itail,
                                              vdd=self.VDD, vicm=self.Vicm)
        except DCConvergenceError as exc:
            raise InvalidDesignError(str(exc)) from exc
        # DomainError propagates: deterministic invalid record upstream.

        warnings: list[str] = []

        def dev(point, name):
            d = dict(point)
            d.update(type="nch" if name in ("M1", "M2", "M5") else "pch",
                     id_at_bias=point["ID"])
            d.setdefault("gmbs", 0.2 * point["gm"])
            d.setdefault("cgs", 0.0)
            d.setdefault("cgd", 0.0)
            d.setdefault("cdd", 0.0)
            return d

        m1 = dev(op["M1"], "M1")
        m2 = dev(op["M2"], "M2")
        m3 = dev(op["M3"], "M3")
        m4 = dev(op["M4"], "M4")
        m5 = dev(op["M5"], "M5")
        devices = {"M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5}

        vt, vm, vo = op["Vtail"], op["Vmirror"], op["Vout"]
        id5 = op["M5"]["ID"]

        # ---- large-signal quantities --------------------------------------
        power_core = self.VDD * (op["M3"]["ID"] + op["M4"]["ID"])
        power_requested = self.VDD * Itail
        power_kcl_error = abs(power_core - self.VDD * id5) / power_core
        sr_proxy = id5 / CL

        sat = {name: d["VDS"] - d["VDSAT"] for name, d in devices.items()}
        min_sat_margin = float(min(sat.values()))
        if min_sat_margin < 0.0:
            worst = min(sat, key=sat.get)
            warnings.append(f"{worst} out of saturation at the solved point")
        gmid_dev = max(abs(op[n]["gmid_error"]) for n in ("M1", "M3"))
        if gmid_dev > 2.0:
            warnings.append(
                f"achieved gm/Id deviates up to {gmid_dev:.1f} from target "
                "(op-point feedback through channel-length modulation)")

        # ---- AC small-signal (corrected terminal-stamp model) -------------
        if freqs is None:
            freqs = self.mna.default_freqs()
        v_out = self.mna.solve_ac_corrected(m1, m2, m3, m4, m5, CL, freqs)
        ac = self.mna.extract_metrics(freqs, v_out)
        if not ac["gbw_valid"]:
            warnings.append("no 0 dB crossing below sweep maximum")

        # ---- nominal headroom ESTIMATES (Astra A5; not validated ranges) --
        vout_low_est = vt + op["M2"]["VDSAT"]
        vout_high_est = self.VDD - op["M4"]["VDSAT"]
        swing_est = vout_high_est - vout_low_est   # never clamped
        icmr_low_est = op["M1"]["VGS"] + op["M5"]["VDSAT"]

        area = (2 * m1["W"] * m1["L"] + 2 * m3["W"] * m3["L"]
                + m5["W"] * m5["L"])

        return {
            "op_point_mode": "solved",
            "tail_device": "finite",
            "ac_model": "corrected_terminal_v1",
            "capacitance_assumption": (
                "cdd treated as the complete drain self-capacitance for "
                "grounded gate/source/body; real-pickle convention "
                "unverified (F5 device-level experiment pending)"),
            "Power": power_core,
            "power_requested_vdd_times_itail": power_requested,
            "power_kcl_error": float(power_kcl_error),
            "SR": sr_proxy,
            "SR_note": "slew-rate proxy ID5/CL, not a transient measurement",
            "Swing": float("nan"),            # acceptance key: fails closed
            "ICMR_min": float("nan"),         # acceptance key: fails closed
            "Swing_est": float(swing_est),
            "Vout_low_est": float(vout_low_est),
            "Vout_high_est": float(vout_high_est),
            "Vout_in_estimated_range": bool(vout_low_est <= vo <= vout_high_est),
            "ICMR_low_est": float(icmr_low_est),
            "ICMR_upper": None,               # not derivable: unreported
            "min_sat_margin": min_sat_margin,
            "sat_m1": sat["M1"], "sat_m2": sat["M2"], "sat_m3": sat["M3"],
            "sat_m4": sat["M4"], "sat_m5": sat["M5"],
            "DC_Gain_dB": ac["DC_Gain_dB"],
            "GBW": ac["GBW"],
            "gbw_valid": ac["gbw_valid"],
            "PM": ac["PM"],
            "Area": area,
            "CL": CL,
            "Vtail": vt, "Vmirror": vm, "Vout": vo,
            "Vbias_tail": op["Vbias_tail"],
            "ID5": id5,
            "pair_current_mismatch": float(
                (m2["ID"] - Itail / 2.0) / (Itail / 2.0)),
            "mirror_current_mismatch": float(
                (m4["ID"] - Itail / 2.0) / (Itail / 2.0)),
            "kcl_residuals": op["kcl_residuals"],
            "m5_current_error_rel": op["m5_current_error_rel"],
            "m5_gmid_forward_error": op["m5_gmid_forward_error"],
            "m5_gmid_forward": op["M5"]["gmid_forward"],
            "m5_gmid_table": op["M5"]["gmid_table"],
            "convergence": op["convergence"],
            "clip_diagnostics": op["clip_diagnostics"],
            "external_bias_generator": (
                "gate-bias generator excluded from power/area/noise/mismatch"),
            "warnings": warnings,
            "devices": devices,
        }


def ideal_tail(VDS: float) -> dict:
    """Ideal tail current source: infinite output resistance, no parasitics."""
    return {
        "type": "ideal_tail", "W": 0.0, "L": 0.0,
        "VGS": float("nan"), "VDS": VDS, "VSB": 0.0,
        "VDSAT": 0.0, "VTH": float("nan"), "ID": float("nan"),
        "gm": 0.0, "gds": 0.0, "gmbs": 0.0,
        "cgg": 0.0, "cgs": 0.0, "cgd": 0.0, "cdd": 0.0,
        "id_at_bias": 0.0,
    }

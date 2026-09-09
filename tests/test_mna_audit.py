"""Independent terminal-by-terminal audit of the corrected finite AC model
(Phase F2, Astra R7).

The reference assembler below is deliberately structured differently from
the engine: it stamps generic two-terminal elements (capacitors) and
4-terminal controlled sources from a per-device connectivity table, the way
a SPICE-like stamping loop would. The engine's assembly must agree with it
entry-for-entry. The legacy ``solve_ac`` is frozen and is only inspected to
document the audited differences.
"""

import numpy as np
import pytest

from analog_ai.circuit.mna import MNAEngine

FREQS = np.array([1.0, 1e3, 1e6, 1e9])
CL = 7e-12


def _device(gm, gds, gmbs=0.0, cgs=0.0, cgd=0.0, cdd=0.0):
    return {"gm": gm, "gds": gds, "gmbs": gmbs, "cgs": cgs, "cgd": cgd,
            "cdd": cdd, "W": 1e-6, "L": 0.5e-6, "VDSAT": 0.1, "VDS": 0.6}


# --------------------------------------------------------- reference model ---
def _add_capacitor(Y, I, s, node_a, node_b, cap, drive_b=None):
    """Two-terminal capacitor between node_a and node_b. If node_b is an
    externally driven gate, its known voltage ``drive_b`` is injected
    through the right-hand side instead of the matrix."""
    Y[:, node_a, node_a] += s * cap
    if drive_b is not None:                  # cap to a known voltage source:
        I[:, node_a, 0] += s * cap * drive_b  # +sC*VB injected into node_a
        return
    if node_b is None:                       # to ground
        return
    Y[:, node_b, node_b] += s * cap
    Y[:, node_a, node_b] -= s * cap
    Y[:, node_b, node_a] -= s * cap


def _add_nmos_vccs(Y, I, drain, source, bulk, gate_drive, gm, gmbs):
    """NMOS controlled drain current i_d = gm*vgs + gmbs*vbs + ...
    stamped at both the drain and the source terminal (current
    continuity). gate_drive None means the gate is a matrix node."""
    rows = (drain, source)
    for r, sign in ((drain, +1.0), (source, -1.0)):
        if gate_drive is None:               # gate is a matrix node
            pass                             # not used in this circuit
        else:                                # driven gate -> RHS
            I[:, r, 0] -= sign * gm * gate_drive
        Y[:, r, source] -= sign * gm
        Y[:, r, drain] += sign * 0.0         # no direct vd term in gm
        # body transconductance: control (bulk, source)
        Y[:, r, source] -= sign * gmbs
        if bulk is not None:
            Y[:, r, bulk] += sign * gmbs


def _add_gds(Y, node_a, node_b, g):
    """Two-terminal conductance between two matrix nodes."""
    Y[:, node_a, node_a] += g
    Y[:, node_b, node_b] += g
    Y[:, node_a, node_b] -= g
    Y[:, node_b, node_a] -= g


def reference_assembly(m1, m2, m3, m4, m5, cl, s):
    """Independent element-level assembly of the corrected finite model.

    Nodes: 0=tail, 1=mirror, 2=out. Gates of M1/M2 are driven at +0.5/-0.5;
    the vdd rail and ground are AC ground. Derivations live in the device
    equations, not in the engine under test.
    """
    n = len(s)
    Y = np.zeros((n, 3, 3), dtype=np.complex128)
    I = np.zeros((n, 3, 1), dtype=np.complex128)

    gmb1 = m1.get("gmbs", 0.0)
    gmb2 = m2.get("gmbs", 0.0)

    # M1: d=mirror(1), g=driven +0.5, s=tail(0), b=ground.
    _add_nmos_vccs(Y, I, 1, 0, None, +0.5, m1["gm"], gmb1)
    _add_gds(Y, 1, 0, m1["gds"])
    _add_capacitor(Y, I, s, 0, None, m1["cgs"], drive_b=+0.5)   # g-s cap
    _add_capacitor(Y, I, s, 1, None, m1["cgd"], drive_b=+0.5)   # g-d cap
    _add_capacitor(Y, I, s, 1, None, m1["cdd"])                 # drain self

    # M2: d=out(2), g=driven -0.5, s=tail(0), b=ground.
    _add_nmos_vccs(Y, I, 2, 0, None, -0.5, m2["gm"], gmb2)
    _add_gds(Y, 2, 0, m2["gds"])
    _add_capacitor(Y, I, s, 0, None, m2["cgs"], drive_b=-0.5)
    _add_capacitor(Y, I, s, 2, None, m2["cgd"], drive_b=-0.5)
    _add_capacitor(Y, I, s, 2, None, m2["cdd"])

    # M3: PMOS diode, d=g=mirror(1), s=vdd (AC ground). Drain-row stamp of
    # the magnitude current into node 1: +gm*v_g + gds*v_d (both node 1).
    Y[:, 1, 1] += m3["gm"] + m3["gds"]
    _add_capacitor(Y, I, s, 1, None, m3["cgs"])     # g=1, s=ground
    # cgd3 (g=d=1) is a same-node cap: contributes nothing under any
    # convention; the reference stamps its two equal and opposite halves,
    # which cancel identically.
    _add_capacitor(Y, I, s, 1, None, m3["cdd"])

    # M4: PMOS, d=out(2), g=mirror(1), s=vdd (AC ground).
    Y[:, 2, 1] += m4["gm"]
    Y[:, 2, 2] += m4["gds"]
    _add_capacitor(Y, I, s, 1, None, m4["cgs"])     # g=mirror
    _add_capacitor(Y, I, s, 2, 1, m4["cgd"])        # true two-terminal cap
    _add_capacitor(Y, I, s, 2, None, m4["cdd"])

    # M5: d=tail(0), g=s=b=ground: pure drain loading.
    Y[:, 0, 0] += m5["gds"]
    _add_capacitor(Y, I, s, 0, None, m5["cdd"])

    # Load.
    _add_capacitor(Y, I, s, 2, None, cl)
    return Y, I


def _devices_asymmetric():
    return (
        _device(1.0e-3, 6.0e-5, gmbs=2.1e-4, cgs=90e-15, cgd=12e-15,
                cdd=104e-15),
        _device(0.9e-3, 4.0e-5, gmbs=1.3e-4, cgs=80e-15, cgd=9e-15,
                cdd=95e-15),
        _device(0.3e-3, 3.0e-5, cgs=200e-15, cgd=15e-15, cdd=210e-15),
        _device(0.4e-3, 7.0e-5, cgs=180e-15, cgd=22e-15, cdd=260e-15),
        _device(0.0, 2.0e-5, cdd=40e-15),   # M5: grounded gate, no gm term
    )


# -------------------------------------------------------------------- tests --
def test_corrected_assembly_matches_independent_reference():
    """Full-matrix audit on ASYMMETRIC devices with all capacitances and
    body effect present: the engine must agree entry-for-entry with the
    independent element-level assembler."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    Y_eng, I_eng = eng.assemble_ac_corrected(m1, m2, m3, m4, m5, CL, FREQS)
    Y_ref, I_ref = reference_assembly(m1, m2, m3, m4, m5, CL,
                                      1j * 2 * np.pi * FREQS)
    # entries agree to float associativity noise (different summation order)
    assert np.allclose(Y_eng, Y_ref, rtol=1e-8, atol=1e-21)
    assert np.allclose(I_eng, I_ref, rtol=1e-8, atol=1e-21)


def test_body_current_conservation_at_both_terminals():
    """The same controlled gmbs current must appear at the source (tail)
    and the drain rows: zeroing gmbs changes exactly Y[0,0] (+), Y[1,0]
    (-), and Y[2,0] (-) - never any other entry."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    Y_with, _ = eng.assemble_ac_corrected(m1, m2, m3, m4, m5, CL, FREQS)
    m1z, m2z = dict(m1, gmbs=0.0), dict(m2, gmbs=0.0)
    Y_without, _ = eng.assemble_ac_corrected(m1z, m2z, m3, m4, m5, CL, FREQS)
    diff = Y_with - Y_without
    expected = np.zeros_like(diff)
    expected[:, 0, 0] = m1["gmbs"] + m2["gmbs"]
    expected[:, 1, 0] = -m1["gmbs"]
    expected[:, 2, 0] = -m2["gmbs"]
    assert np.allclose(diff, expected, rtol=1e-8, atol=1e-21)


def test_driven_gate_caps_excite_through_rhs():
    """Gate-driven capacitors never couple two circuit nodes: M1's cgd must
    appear only on the mirror diagonal and in the mirror-row RHS, and M2's
    only on the output diagonal and output-row RHS."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    Y_with, I_with = eng.assemble_ac_corrected(m1, m2, m3, m4, m5, CL, FREQS)
    m1n, m2n = dict(m1, cgd=0.0), dict(m2, cgd=0.0)
    Y_wo, I_wo = eng.assemble_ac_corrected(m1n, m2n, m3, m4, m5, CL, FREQS)
    s = 1j * 2 * np.pi * FREQS
    assert np.allclose((Y_with - Y_wo)[:, 1, 1], s * m1["cgd"], atol=0)
    assert np.allclose((I_with - I_wo)[:, 1, 0], 0.5 * s * m1["cgd"], atol=0)
    assert np.allclose((Y_with - Y_wo)[:, 2, 2], s * m2["cgd"], atol=0)
    assert np.allclose((I_with - I_wo)[:, 2, 0], -0.5 * s * m2["cgd"], atol=0)
    # no other entry may change
    dY = Y_with - Y_wo
    dY[:, 2, 2] = 0
    dY[:, 1, 1] = 0
    assert np.allclose(dY, 0, atol=0)


def test_m4_gate_drain_cap_is_true_two_terminal():
    """M4's cgd must be stamped +s*C at both diagonals and -s*C at both
    off-diagonals (the legacy code put a single +s*C on Y[2,1])."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    Y_with, _ = eng.assemble_ac_corrected(m1, m2, m3, m4, m5, CL, FREQS)
    m4n = dict(m4, cgd=0.0)
    Y_wo, _ = eng.assemble_ac_corrected(m1, m2, m3, m4n, m5, CL, FREQS)
    s = 1j * 2 * np.pi * FREQS
    c = s * m4["cgd"]
    expected = np.zeros_like(Y_with)
    expected[:, 1, 1] += c
    expected[:, 2, 2] += c
    expected[:, 1, 2] -= c
    expected[:, 2, 1] -= c
    assert np.allclose(Y_with - Y_wo, expected, rtol=1e-8, atol=1e-21)


def test_m3_gate_drain_cap_never_stamped():
    """M3's gate and drain are the same node: adding cgd3 must not change
    any matrix entry (its two stamp halves cancel identically)."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    Y_a, _ = eng.assemble_ac_corrected(m1, m2, m3, m4, m5, CL, FREQS)
    # the engine simply never reads a cgd key of M3; verify by construction:
    m3x = dict(m3, cgd=123e-15)
    Y_b, _ = eng.assemble_ac_corrected(m1, m2, m3x, m4, m5, CL, FREQS)
    assert np.allclose(Y_a, Y_b, rtol=1e-8, atol=1e-21)


def test_m5_contributes_drain_loading_only():
    """M5's gate/source/body are AC ground: gm5/gmbs5 must never enter the
    matrix; only gds5 + s*Cdd5 appears on the tail diagonal."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    m5x = dict(m5, gm=5e-3, gmbs=1e-3)   # must be ignored entirely
    Y_a, _ = eng.assemble_ac_corrected(m1, m2, m3, m4, m5, CL, FREQS)
    Y_b, _ = eng.assemble_ac_corrected(m1, m2, m3, m4, m5x, CL, FREQS)
    assert np.allclose(Y_a, Y_b, rtol=1e-8, atol=1e-21)


def test_ideal_limit_within_corrected_model():
    """Zeroing M5's admittance inside the CORRECTED model gives the ideal-
    tail corrected model (no demand of equality with the legacy matrix)."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    Y_finite, _ = eng.assemble_ac_corrected(m1, m2, m3, m4, m5, CL, FREQS)
    Y_ideal, _ = eng.assemble_ac_corrected(
        m1, m2, m3, m4, dict(m5, gds=0.0, cdd=0.0), CL, FREQS)
    diff = Y_finite - Y_ideal
    expected = np.zeros_like(diff)
    expected[:, 0, 0] = m5["gds"] + 1j * 2 * np.pi * FREQS * m5["cdd"]
    assert np.allclose(diff, expected, rtol=1e-8, atol=1e-21)


def test_legacy_model_documented_differences():
    """Pin the exact audited differences between the FROZEN legacy stamps
    and the corrected stamps (Astra R7 items 1-5): the legacy matrix must
    differ from the corrected one by exactly these entries."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    Yc, Ic = eng.assemble_ac_corrected(m1, m2, m3, m4, m5, CL, FREQS)

    # Rebuild the legacy matrix with the same devices (legacy equations).
    s = 1j * 2 * np.pi * FREQS
    gmb1, gmb2 = m1["gmbs"], m2["gmbs"]
    Yl = np.zeros_like(Yc)
    Yl[:, 0, 0] = (m5["gds"] + m1["gds"] + m2["gds"] + m1["gm"] + m2["gm"]
                   + gmb1 + gmb2 + s * (m1["cgs"] + m2["cgs"] + m5["cdd"]))
    Yl[:, 0, 1] = -m1["gds"] - s * m1["cgd"]
    Yl[:, 0, 2] = -m2["gds"] - s * m2["cgd"]
    Yl[:, 1, 0] = -(m1["gds"] + m1["gm"]) - s * m1["cgs"]
    Yl[:, 1, 1] = (m1["gds"] + m3["gds"] + m3["gm"]
                   + s * (m1["cdd"] + m1["cgd"] + m3["cdd"] + m3["cgs"]
                          + m4["cgs"] + m3["cgd"]))
    Yl[:, 1, 2] = 0.0
    Yl[:, 2, 0] = -(m2["gds"] + m2["gm"]) - s * m2["cgs"]
    Yl[:, 2, 1] = m4["gm"] + s * m4["cgd"]
    Yl[:, 2, 2] = (m2["gds"] + m4["gds"]
                   + s * (m2["cdd"] + m2["cgd"] + m4["cdd"] + m4["cgd"] + CL))
    diff = Yl - Yc
    expected = np.zeros_like(diff)
    expected[:, 0, 1] = -s * m1["cgd"]          # R7-3: tail<-cgd coupling
    expected[:, 0, 2] = -s * m2["cgd"]
    expected[:, 1, 0] = (-s * m1["cgs"]) - (-m1["gmbs"])   # R7-1+2
    expected[:, 2, 0] = (-s * m2["cgs"]) - (-m2["gmbs"])
    expected[:, 1, 1] = s * (m3["cgd"] - m4["cgd"])  # R7-5 double count
    # on the legacy side AND the corrected cgd4 mirror-diagonal term
    expected[:, 1, 2] = 0.0 - (-s * m4["cgd"])  # R7-4: missing M4 cgd
    expected[:, 2, 1] = (s * m4["cgd"]) - (-s * m4["cgd"])
    assert np.allclose(diff, expected, rtol=1e-8, atol=1e-21)


def test_corrected_dc_gain_matches_textbook_and_legacy_at_dc():
    """With zero capacitances and zero body effect the corrected model must
    reproduce the textbook response exactly (Av0 = gm1*(ro2||ro4)) and must
    coincide with the legacy model - the models differ only in cap/gmbs
    handling."""
    gm1 = 1e-3
    gds = 5e-5
    m = lambda g: _device(g, gds)
    m1 = m2 = m(gm1)
    m3 = m4 = m(1.0)    # stiff mirror: second-order loading ~ gds/gm3 = 5e-5
    m5 = _device(0.0, 0.0)
    eng = MNAEngine()
    v_corr = eng.solve_ac_corrected(m1, m2, m3, m4, m5, CL, np.array([1.0]))
    v_leg = eng.solve_ac(m1, m2, m3, m4, m5, CL, np.array([1.0]))
    av0 = gm1 / (gds + gds)
    assert abs(v_corr[0]) == pytest.approx(av0, rel=1e-4)
    assert v_corr[0] == v_leg[0]   # models differ only in cap/gmbs handling


def test_nodal_current_closure_on_solved_response():
    """Strongest audit: solve the corrected model, then compute every
    device's terminal currents from the SOLUTION using independent device
    equations; each node's current sum must vanish (circuit-law closure)."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    freqs = np.array([1e3, 1e6])
    Y, I = eng.assemble_ac_corrected(m1, m2, m3, m4, m5, CL, freqs)
    V = np.linalg.solve(Y, I)[:, :, 0]
    v1, v2, v3 = V[:, 0], V[:, 1], V[:, 2]
    s = 1j * 2 * np.pi * freqs

    # Device terminal currents (into the named node), from the equations.
    gmb1, gmb2 = m1["gmbs"], m2["gmbs"]
    i1_into_source = m1["gm"] * (+0.5 - v1) + gmb1 * (0 - v1) \
        + m1["gds"] * (v2 - v1)
    i2_into_source = m2["gm"] * (-0.5 - v1) + gmb2 * (0 - v1) \
        + m2["gds"] * (v3 - v1)
    i5_out_of_drain = m5["gds"] * v1 + s * m5["cdd"] * v1
    # node 1: in from M1/M2 sources, out into M5 and gate caps
    kcl1 = i1_into_source + i2_into_source + (s * m1["cgs"] * (+0.5 - v1)) \
        + (s * m2["cgs"] * (-0.5 - v1)) - i5_out_of_drain
    # node 2: in from M3, out into M1 drain and caps
    kcl2 = (-(m3["gm"] + m3["gds"]) * v2) \
        - (m1["gm"] * (+0.5 - v1) + gmb1 * (-v1) + m1["gds"] * (v2 - v1)) \
        - s * v2 * (m1["cdd"] + m3["cdd"] + m3["cgs"] + m4["cgs"]) \
        - s * m1["cgd"] * (v2 - +0.5) \
        - s * m4["cgd"] * (v2 - v3)
    # node 3: in from M4, out into M2 drain, caps, CL
    kcl3 = (-m4["gm"] * v2 - m4["gds"] * v3) \
        - (m2["gm"] * (-0.5 - v1) + gmb2 * (-v1) + m2["gds"] * (v3 - v1)) \
        - s * v3 * (m2["cdd"] + m4["cdd"] + CL) \
        - s * m2["cgd"] * (v3 - (-0.5)) \
        - s * m4["cgd"] * (v3 - v2)
    for kcl in (kcl1, kcl2, kcl3):
        assert np.max(np.abs(kcl)) < 1e-18

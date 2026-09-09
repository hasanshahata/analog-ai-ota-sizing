"""Independent terminal-by-terminal audit of the corrected finite AC model
(Phase F2, Astra R7 + F2-R1).

The reference assembler below is deliberately structured differently from
the engine: it stamps generic two-terminal elements (capacitors) and
4-terminal controlled sources from PRIMITIVE capacitances - Cgs, Cgd, and
the junction Cdb - the way a SPICE-like stamping loop would. The engine's
input device dicts carry the TOTAL Cdd = Cgd + Cdb (the LUT's declared
convention); the tests construct that total FROM the primitives, so the
engine's junction decomposition is verified against primitive truth, not
against a restatement of itself (F2-R1). The legacy ``solve_ac`` is frozen
and only inspected to document the audited differences.
"""

import numpy as np
import pytest

from analog_ai.circuit.mna import MNAEngine

FREQS = np.array([1.0, 1e3, 1e6, 1e9])
CL = 7e-12


def _primitive_device(gm=0.0, gds=0.0, gmbs=0.0, cgs=0.0, cgd=0.0, cdb=0.0):
    """Device defined by PRIMITIVE capacitances (Cgs, Cgd, junction Cdb)."""
    return {"gm": gm, "gds": gds, "gmbs": gmbs, "cgs": cgs, "cgd": cgd,
            "cdb": cdb, "W": 1e-6, "L": 0.5e-6, "VDSAT": 0.1, "VDS": 0.6}


def _engine_device(dev):
    """Build the engine's input dict: total Cdd = Cgd + Cdb (the declared
    LUT convention)."""
    out = dict(dev)
    out["cdd"] = dev["cgd"] + dev["cdb"]
    return out


def _engine_devices(m1, m2, m3, m4, m5):
    return tuple(_engine_device(d) for d in (m1, m2, m3, m4, m5))


# --------------------------------------------------------- reference model ---
def _add_capacitor(Y, I, s, node_a, node_b, cap, drive_b=None):
    """Two-terminal capacitor between node_a and node_b. If node_b is an
    externally driven gate, +s*cap*drive_b is injected into node_a (SPICE
    stamp for a capacitor to a known voltage source)."""
    Y[:, node_a, node_a] += s * cap
    if drive_b is not None:
        I[:, node_a, 0] += s * cap * drive_b
        return
    if node_b is None:                       # to ground
        return
    Y[:, node_b, node_b] += s * cap
    Y[:, node_a, node_b] -= s * cap
    Y[:, node_b, node_a] -= s * cap


def _add_nmos_vccs(Y, I, drain, source, gate_drive, gm, gmbs):
    """NMOS controlled drain current i_d = gm*vgs + gmbs*vbs + ...
    stamped at both the drain and the source terminal (current
    continuity); bulk at ground."""
    for r, sign in ((drain, +1.0), (source, -1.0)):
        I[:, r, 0] -= sign * gm * gate_drive
        Y[:, r, source] -= sign * gm
        Y[:, r, source] -= sign * gmbs


def _add_gds(Y, node_a, node_b, g):
    Y[:, node_a, node_a] += g
    Y[:, node_b, node_b] += g
    Y[:, node_a, node_b] -= g
    Y[:, node_b, node_a] -= g


def reference_assembly(m1, m2, m3, m4, m5, cl, s):
    """Independent element-level assembly from PRIMITIVE capacitances.

    Nodes: 0=tail, 1=mirror, 2=out. Gates of M1/M2 are driven at +0.5/-0.5;
    the vdd rail and ground are AC ground.
    """
    n = len(s)
    Y = np.zeros((n, 3, 3), dtype=np.complex128)
    I = np.zeros((n, 3, 1), dtype=np.complex128)

    # M1: d=mirror(1), g=driven +0.5, s=tail(0), b=ground.
    _add_nmos_vccs(Y, I, 1, 0, +0.5, m1["gm"], m1["gmbs"])
    _add_gds(Y, 1, 0, m1["gds"])
    _add_capacitor(Y, I, s, 0, None, m1["cgs"], drive_b=+0.5)   # Cgs: g-s
    _add_capacitor(Y, I, s, 1, None, m1["cgd"], drive_b=+0.5)   # Cgd: g-d
    _add_capacitor(Y, I, s, 1, None, m1["cdb"])                 # junction

    # M2: d=out(2), g=driven -0.5, s=tail(0), b=ground.
    _add_nmos_vccs(Y, I, 2, 0, -0.5, m2["gm"], m2["gmbs"])
    _add_gds(Y, 2, 0, m2["gds"])
    _add_capacitor(Y, I, s, 0, None, m2["cgs"], drive_b=-0.5)
    _add_capacitor(Y, I, s, 2, None, m2["cgd"], drive_b=-0.5)
    _add_capacitor(Y, I, s, 2, None, m2["cdb"])

    # M3: PMOS diode, d=g=mirror(1), s=vdd (AC ground).
    Y[:, 1, 1] += m3["gm"] + m3["gds"]
    _add_capacitor(Y, I, s, 1, None, m3["cgs"])     # Cgs: g=1, s=ground
    # Cgd3 (g=d=1): both terminals the same node - stamps cancel identically.
    _add_capacitor(Y, I, s, 1, 1, m3["cgd"])
    _add_capacitor(Y, I, s, 1, None, m3["cdb"])     # junction

    # M4: PMOS, d=out(2), g=mirror(1), s=vdd (AC ground).
    Y[:, 2, 1] += m4["gm"]
    Y[:, 2, 2] += m4["gds"]
    _add_capacitor(Y, I, s, 1, None, m4["cgs"])     # Cgs: g=mirror
    _add_capacitor(Y, I, s, 2, 1, m4["cgd"])        # Cgd: true two-terminal
    _add_capacitor(Y, I, s, 2, None, m4["cdb"])     # junction

    # M5: d=tail(0), g=s=b=ground: Cgd and Cdb both terminate at ground, so
    # the total drain loading is Cgd + Cdb; gm/gmbs have no drive.
    Y[:, 0, 0] += m5["gds"]
    _add_capacitor(Y, I, s, 0, None, m5["cgd"])
    _add_capacitor(Y, I, s, 0, None, m5["cdb"])

    _add_capacitor(Y, I, s, 2, None, cl)
    return Y, I


def _devices_asymmetric():
    """Asymmetric devices with all primitives nonzero."""
    return (
        _primitive_device(1.0e-3, 6.0e-5, gmbs=2.1e-4, cgs=90e-15,
                          cgd=12e-15, cdb=92e-15),
        _primitive_device(0.9e-3, 4.0e-5, gmbs=1.3e-4, cgs=80e-15,
                          cgd=9e-15, cdb=86e-15),
        _primitive_device(0.3e-3, 3.0e-5, cgs=200e-15, cgd=15e-15,
                          cdb=195e-15),
        _primitive_device(0.4e-3, 7.0e-5, cgs=180e-15, cgd=22e-15,
                          cdb=238e-15),
        _primitive_device(0.0, 2.0e-5, cgd=8e-15, cdb=32e-15),
    )


_TOL = dict(rtol=1e-8, atol=1e-21)   # float associativity noise only


# -------------------------------------------------------------------- tests --
def test_corrected_assembly_matches_primitive_reference():
    """Full-matrix audit on ASYMMETRIC devices built from primitives: the
    engine's junction decomposition must reproduce the primitive-truth
    assembly entry-for-entry."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    Y_eng, I_eng = eng.assemble_ac_corrected(*_engine_devices(m1, m2, m3,
                                                              m4, m5),
                                             CL, FREQS)
    Y_ref, I_ref = reference_assembly(m1, m2, m3, m4, m5, CL,
                                      1j * 2 * np.pi * FREQS)
    assert np.allclose(Y_eng, Y_ref, **_TOL)
    assert np.allclose(I_eng, I_ref, **_TOL)


def test_lone_overlap_capacitor_limiting_cases():
    """Astra F2-R1 reproduction: all coefficients zero except the named
    device's Cgd = Cdd = 1 pF (junction zero). One physical 1 pF gate-drain
    capacitor must contribute exactly 1 pF, not 2 pF:
      M1 -> mirror diagonal s*1pF and RHS +0.5*s*1pF, nothing elsewhere;
      M3 -> NOTHING (both terminals are the same node);
      M4 -> mirror/output block [[1,-1],[-1,1]] pF."""
    p = 1e-12
    base = (_primitive_device(),) * 5
    freqs = np.array([1.0 / (2 * np.pi)])        # engine s = 1j
    s = 1j * freqs
    eng = MNAEngine()

    # M1
    m1 = _primitive_device(cgd=p, cdb=0.0)
    Y, I = eng.assemble_ac_corrected(*_engine_devices(m1, *base[1:]), 0.0, freqs)
    assert Y[0, 1, 1] == pytest.approx(1j * p)
    assert I[0, 1, 0] == pytest.approx(0.5j * p)
    Y_rest = Y.copy()
    Y_rest[0, 1, 1] = 0
    assert np.allclose(Y_rest, 0, atol=1e-24)
    I_rest = I.copy()
    I_rest[0, 1, 0] = 0
    assert np.allclose(I_rest, 0, atol=1e-24)

    # M3: same-node overlap contributes nothing.
    m3 = _primitive_device(cgd=p, cdb=0.0)
    Y, I = eng.assemble_ac_corrected(*_engine_devices(*base[:2], m3,
                                                      *base[3:]), 0.0, freqs)
    assert np.allclose(Y, 0, atol=1e-24)
    assert np.allclose(I, 0, atol=1e-24)

    # M4: two-terminal block [[1,-1],[-1,1]] pF, no RHS.
    m4 = _primitive_device(cgd=p, cdb=0.0)
    Y, I = eng.assemble_ac_corrected(*_engine_devices(*base[:3], m4,
                                                      base[4]), 0.0, freqs)
    expected = np.zeros_like(Y)
    expected[0, 1, 1] = 1j * p
    expected[0, 2, 2] = 1j * p
    expected[0, 1, 2] = -1j * p
    expected[0, 2, 1] = -1j * p
    assert np.allclose(Y, expected, rtol=1e-12, atol=1e-24)
    assert np.allclose(I, 0, atol=1e-24)


def test_lone_junction_capacitor_limiting_cases():
    """Complement: Cdb only (Cgd = 0). M1/M3/M4 junctions are simple
    ground capacitors at their drain nodes."""
    p = 1e-12
    base = (_primitive_device(),) * 5
    freqs = np.array([1.0 / (2 * np.pi)])        # engine s = 1j
    s = 1j * freqs
    eng = MNAEngine()

    m1 = _primitive_device(cgd=0.0, cdb=p)
    Y, _ = eng.assemble_ac_corrected(*_engine_devices(m1, *base[1:]), 0.0, freqs)
    assert Y[0, 1, 1] == pytest.approx(1j * p)
    Y[0, 1, 1] = 0
    assert np.allclose(Y, 0, atol=1e-24)

    m3 = _primitive_device(cgd=0.0, cdb=p)
    Y, _ = eng.assemble_ac_corrected(*_engine_devices(*base[:2], m3,
                                                      *base[3:]), 0.0, freqs)
    assert Y[0, 1, 1] == pytest.approx(1j * p)

    m4 = _primitive_device(cgd=0.0, cdb=p)
    Y, _ = eng.assemble_ac_corrected(*_engine_devices(*base[:3], m4,
                                                      base[4]), 0.0, freqs)
    assert Y[0, 2, 2] == pytest.approx(1j * p)
    Y[0, 2, 2] = 0
    assert np.allclose(Y, 0, atol=1e-24)


def test_inconsistent_total_capacitance_rejected():
    """Cdd < Cgd is impossible under the declared convention: reject with
    a clear error instead of clipping a negative junction."""
    m1 = _primitive_device(cgd=2e-12, cdb=-1e-12)   # cdd total = 1pF < cgd
    base = (_primitive_device(),) * 5
    eng = MNAEngine()
    with pytest.raises(ValueError, match="M1.*inconsistent capacitance"):
        eng.assemble_ac_corrected(*_engine_devices(m1, *base[1:]), 0.0,
                                  1j * np.array([1.0]))


def test_m5_total_capacitance_is_drain_loading():
    """M5's overlap and junction both terminate at AC ground: the total
    Cgd + Cdb (= Cdd) is the drain loading; no decomposition needed."""
    eng = MNAEngine()
    freqs = np.array([1.0 / (2 * np.pi)])        # engine s = 1j
    m5a = _primitive_device(cgd=3e-15, cdb=27e-15)
    m5b = _primitive_device(cgd=0.0, cdb=30e-15)
    base = (_primitive_device(),) * 4
    Ya, _ = eng.assemble_ac_corrected(*_engine_devices(*base, m5a), 0.0, freqs)
    Yb, _ = eng.assemble_ac_corrected(*_engine_devices(*base, m5b), 0.0, freqs)
    assert Ya[0, 0, 0] == Yb[0, 0, 0] == 1j * 30e-15


def test_body_current_conservation_at_both_terminals():
    """The same controlled gmbs current must appear at the source (tail)
    and the drain rows: zeroing gmbs changes exactly Y[0,0] (+), Y[1,0]
    (-), and Y[2,0] (-) - never any other entry."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    devs = _engine_devices(m1, m2, m3, m4, m5)
    Y_with, _ = eng.assemble_ac_corrected(*devs, CL, FREQS)
    m1z, m2z = dict(m1, gmbs=0.0), dict(m2, gmbs=0.0)
    Y_without, _ = eng.assemble_ac_corrected(*_engine_devices(m1z, m2z, m3,
                                                              m4, m5),
                                             CL, FREQS)
    diff = Y_with - Y_without
    expected = np.zeros_like(diff)
    expected[:, 0, 0] = m1["gmbs"] + m2["gmbs"]
    expected[:, 1, 0] = -m1["gmbs"]
    expected[:, 2, 0] = -m2["gmbs"]
    assert np.allclose(diff, expected, **_TOL)


def test_driven_gate_overlap_excites_through_rhs_only():
    """Varying M1's PRIMITIVE Cgd with its junction fixed changes the
    mirror-row RHS (+0.5*s*dCgd) and the mirror diagonal (the total cdd
    grows by dCgd) - and nothing else."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    m1b = dict(m1, cgd=m1["cgd"] + 5e-15)   # junction unchanged, cdd grows
    Ya, Ia = eng.assemble_ac_corrected(*_engine_devices(m1, m2, m3, m4, m5),
                                       CL, FREQS)
    Yb, Ib = eng.assemble_ac_corrected(*_engine_devices(m1b, m2, m3, m4, m5),
                                       CL, FREQS)
    s = 1j * 2 * np.pi * FREQS
    d = 5e-15
    assert np.allclose((Yb - Ya)[:, 1, 1], s * d, **_TOL)
    assert np.allclose((Ib - Ia)[:, 1, 0], 0.5 * s * d, **_TOL)
    dY = Ya - Yb
    dY[:, 1, 1] = 0
    assert np.allclose(dY, 0, atol=1e-24)
    dI = Ia - Ib
    dI[:, 1, 0] = 0
    assert np.allclose(dI, 0, atol=1e-24)


def test_m4_junction_decomposition():
    """Varying M4's PRIMITIVE Cgd with its junction fixed: the overlap
    element's four stamps appear, while the output diagonal is INVARIANT
    (it carries Cgd + Cdb = cdd either way)."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    m4b = dict(m4, cgd=m4["cgd"] + 6e-15)   # junction unchanged, cdd grows
    Ya, _ = eng.assemble_ac_corrected(*_engine_devices(m1, m2, m3, m4, m5),
                                      CL, FREQS)
    Yb, _ = eng.assemble_ac_corrected(*_engine_devices(m1, m2, m3, m4b, m5),
                                      CL, FREQS)
    s = 1j * 2 * np.pi * FREQS
    c = s * 6e-15
    expected = np.zeros_like(Ya)
    expected[:, 1, 1] += c          # overlap element, mirror side
    expected[:, 1, 2] -= c
    expected[:, 2, 1] -= c
    expected[:, 2, 2] += c          # element out-diagonal (junction fixed)
    assert np.allclose(Yb - Ya, expected, **_TOL)


def test_m5_gm_terms_never_enter():
    """M5's gate/source/body are AC ground: gm5/gmbs5 must never enter the
    matrix; only gds5 + s*Cdd5 appears on the tail diagonal."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    m5x = dict(m5, gm=5e-3, gmbs=1e-3)   # must be ignored entirely
    Ya, _ = eng.assemble_ac_corrected(*_engine_devices(m1, m2, m3, m4, m5),
                                      CL, FREQS)
    Yb, _ = eng.assemble_ac_corrected(*_engine_devices(m1, m2, m3, m4, m5x),
                                      CL, FREQS)
    assert np.allclose(Ya, Yb, **_TOL)


def test_ideal_limit_within_corrected_model():
    """Zeroing M5's admittance inside the CORRECTED model gives the ideal-
    tail corrected model (no demand of equality with the legacy matrix)."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    Ya, _ = eng.assemble_ac_corrected(*_engine_devices(m1, m2, m3, m4, m5),
                                      CL, FREQS)
    Yb, _ = eng.assemble_ac_corrected(*_engine_devices(m1, m2, m3, m4,
                                                       dict(m5, gds=0.0,
                                                            cgd=0.0,
                                                            cdb=0.0)),
                                      CL, FREQS)
    diff = Ya - Yb
    expected = np.zeros_like(diff)
    expected[:, 0, 0] = m5["gds"] + 1j * 2 * np.pi * FREQS * (m5["cgd"]
                                                              + m5["cdb"])
    assert np.allclose(diff, expected, **_TOL)


def test_legacy_model_documented_differences():
    """Pin the exact audited differences between the FROZEN legacy stamps
    and the corrected stamps (R7 items 1-5 plus the F2-R1 junction fix)."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    Yc, _ = eng.assemble_ac_corrected(*_engine_devices(m1, m2, m3, m4, m5),
                                      CL, FREQS)

    s = 1j * 2 * np.pi * FREQS
    gmb1, gmb2 = m1["gmbs"], m2["gmbs"]
    # Legacy equations on the same (total-cdd) engine inputs.
    Yl = np.zeros_like(Yc)
    Yl[:, 0, 0] = (m5["gds"] + m1["gds"] + m2["gds"] + m1["gm"] + m2["gm"]
                   + gmb1 + gmb2
                   + s * (m1["cgs"] + m2["cgs"] + m5["cgd"] + m5["cdb"]))
    Yl[:, 0, 1] = -m1["gds"] - s * m1["cgd"]
    Yl[:, 0, 2] = -m2["gds"] - s * m2["cgd"]
    Yl[:, 1, 0] = -(m1["gds"] + m1["gm"]) - s * m1["cgs"]
    Yl[:, 1, 1] = (m1["gds"] + m3["gds"] + m3["gm"]
                   + s * (m1["cgd"] + m1["cdb"] + m1["cgd"]
                          + m3["cgd"] + m3["cdb"] + m3["cgs"]
                          + m4["cgs"] + m3["cgd"]))
    Yl[:, 1, 2] = 0.0
    Yl[:, 2, 0] = -(m2["gds"] + m2["gm"]) - s * m2["cgs"]
    Yl[:, 2, 1] = m4["gm"] + s * m4["cgd"]
    Yl[:, 2, 2] = (m2["gds"] + m4["gds"]
                   + s * (m2["cgd"] + m2["cdb"] + m2["cgd"]
                          + m4["cgd"] + m4["cdb"] + m4["cgd"] + CL))
    diff = Yl - Yc
    expected = np.zeros_like(diff)
    expected[:, 0, 1] = -s * m1["cgd"]              # R7-3 tail coupling
    expected[:, 0, 2] = -s * m2["cgd"]
    expected[:, 1, 0] = (-s * m1["cgs"]) - (-m1["gmbs"])   # R7-1+2
    expected[:, 2, 0] = (-s * m2["cgs"]) - (-m2["gmbs"])
    # R7-5 + F2-R1: legacy carries M1's overlap extra and M3's FULL cdd
    # (overlap double-counted); corrected carries M4's overlap element on
    # the mirror diagonal instead.
    expected[:, 1, 1] = s * (m1["cgd"] + 2 * m3["cgd"] - m4["cgd"])
    expected[:, 1, 2] = s * m4["cgd"]               # R7-4 mutual
    expected[:, 2, 1] = 2 * s * m4["cgd"]           # R7-4 sign+mutual
    expected[:, 2, 2] = s * (m2["cgd"] + m4["cgd"])  # F2-R1 overlap counts
    # atol 1e-18: absorbs 1e-19 associativity noise on zero-expected
    # entries; every genuine difference is >= 1e-13.
    assert np.allclose(diff, expected, rtol=1e-8, atol=1e-18)


def test_corrected_dc_gain_matches_textbook_and_legacy_at_dc():
    """With zero capacitances and zero body effect the corrected model must
    reproduce the textbook response (Av0 = gm1*(ro2||ro4), up to the
    second-order mirror-loading term ~ gds/gm3) and coincide with the
    legacy model - the models differ only in cap/gmbs handling."""
    gm1 = 1e-3
    gds = 5e-5
    m = lambda g: _primitive_device(gm=g, gds=gds)
    m1 = m2 = m(gm1)
    m3 = m4 = m(1.0)    # stiff mirror
    m5 = _primitive_device()
    eng = MNAEngine()
    v_corr = eng.solve_ac_corrected(*_engine_devices(m1, m2, m3, m4, m5),
                                    CL, np.array([1.0]))
    v_leg = eng.solve_ac(*_engine_devices(m1, m2, m3, m4, m5),
                         CL, np.array([1.0]))
    av0 = gm1 / (gds + gds)
    assert abs(v_corr[0]) == pytest.approx(av0, rel=1e-4)
    assert v_corr[0] == v_leg[0]   # models differ only in cap/gmbs handling


def test_nodal_current_closure_on_solved_response():
    """Strongest audit: solve the corrected model, then compute every
    device's terminal currents from the SOLUTION using independent
    PRIMITIVE device equations; each node's current sum must vanish."""
    m1, m2, m3, m4, m5 = _devices_asymmetric()
    eng = MNAEngine()
    freqs = np.array([1e3, 1e6])
    Y, I = eng.assemble_ac_corrected(*_engine_devices(m1, m2, m3, m4, m5),
                                     CL, freqs)
    V = np.linalg.solve(Y, I)[:, :, 0]
    v1, v2, v3 = V[:, 0], V[:, 1], V[:, 2]
    s = 1j * 2 * np.pi * freqs

    def id_n(dev, vg, vs, vd):
        return (dev["gm"] * (vg - vs) + dev["gmbs"] * (0 - vs)
                + dev["gds"] * (vd - vs))

    # Node 1 (tail): in from M1/M2 sources and gate caps; out into M5.
    kcl1 = (id_n(m1, +0.5, v1, v2) + id_n(m2, -0.5, v1, v3)
            + s * m1["cgs"] * (+0.5 - v1) + s * m2["cgs"] * (-0.5 - v1)
            - m5["gds"] * v1
            - s * (m5["cgd"] + m5["cdb"]) * v1)
    # Node 2 (mirror): in from M3; out into M1 drain, caps, M4 cgd element.
    kcl2 = (-(m3["gm"] * v2 + m3["gds"] * v2)
            - id_n(m1, +0.5, v1, v2)
            - s * (m1["cdb"] + m3["cdb"] + m3["cgs"] + m4["cgs"]) * v2
            - s * m1["cgd"] * (v2 - 0.5)
            - s * m4["cgd"] * (v2 - v3))
    # Node 3 (out): in from M4; out into M2 drain, caps, M4 cgd element, CL.
    kcl3 = (-(m4["gm"] * v2 + m4["gds"] * v3)
            - id_n(m2, -0.5, v1, v3)
            - s * (m2["cdb"] + m4["cdb"] + CL) * v3
            - s * m2["cgd"] * (v3 - (-0.5))
            - s * m4["cgd"] * (v3 - v2))
    for kcl in (kcl1, kcl2, kcl3):
        assert np.max(np.abs(kcl)) < 1e-18

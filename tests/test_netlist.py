from analog_ai.utils.netlist import export_netlist


def test_netlist_matches_pairs_and_parameters(engine):
    _, ota = engine
    perf = ota.evaluate([0.6e-6, 10.0, 0.6e-6, 12.0, 50e-6], CL=2.5e-12)
    netlist = export_netlist(perf, cl=2.5e-12, vdd=1.2,
                             model_include="pdk/models.scs", corner_section="tt")

    lines = [ln for ln in netlist.splitlines() if ln.startswith("M")]
    m1 = next(ln for ln in lines if ln.startswith("M1 "))
    m2 = next(ln for ln in lines if ln.startswith("M2 "))
    m3 = next(ln for ln in lines if ln.startswith("M3 "))
    m4 = next(ln for ln in lines if ln.startswith("M4 "))

    # Matched pairs share the exported geometry (the legacy exporter did not).
    assert m1.split("w=")[1] == m2.split("w=")[1]
    assert m1.split("l=")[1] == m2.split("l=")[1]
    assert m3.split("w=")[1] == m4.split("w=")[1]
    assert m3.split("l=")[1] == m4.split("l=")[1]

    # Parameters are honored, not hardcoded.
    assert "c=2.5p" in netlist
    assert "dc=1.2" in netlist
    assert "pdk/models.scs" in netlist and "section=tt" in netlist
    # Differential drive: positive magnitudes, explicit 180-degree phase.
    assert "mag=0.5 phase=0" in netlist
    assert "mag=0.5 phase=180" in netlist


def test_netlist_ideal_tail_uses_evaluated_vtail(engine):
    _, ota = engine
    perf = ota.evaluate([0.6e-6, 10.0, 0.6e-6, 12.0, 50e-6], CL=1e-12)
    netlist = export_netlist(perf, cl=1e-12)
    assert f"dc={perf['Vtail']:.4f}" in netlist

from __future__ import annotations

import hashlib
import json

import pytest

from analog_ai.correlation.spectre_job import (
    CorrelationJobError, build_job, render_netlist,
)


TEMPLATE = """simulator lang=spectre
global 0 vdd!
parameters VDD Vincm cL L34 W34 L12 W12 Itail
include \"models.scs\" section=tt_lib
subckt ideal_balun d c p n
ends ideal_balun
I16 (Vin net8 Vin\\+ Vin\\-) ideal_balun
C0 (Vout 0) capacitor c=cL
M1 (net04 net04 vdd! vdd!) pch l=L34 w=W34*1 m=1 nf=1
M0 (Vout net04 vdd! vdd!) pch l=L34 w=W34*1 m=1 nf=1
M9 (net04 Vin\\+ net02 0) nch l=L12 w=W12*1 m=1 nf=1
M8 (Vout Vin\\- net02 0) nch l=L12 w=W12*1 m=1 nf=1
I26 (net02 0) isource dc=Itail type=dc
saveOptions options save=allpub
"""

DESIGN = {"L1": 242e-9, "W1": 107.34e-6,
          "L3": 500e-9, "W3": 7.27e-6, "Itail": 56.7e-6}


def test_render_preserves_ideal_tail_and_assigns_si_values():
    out = render_netlist(TEMPLATE, DESIGN, 1e-12)
    assert "I26 (net02 0) isource dc=Itail" in out
    assert "M7 (" not in out and "W5" not in out
    assert "VDD=1.2" in out and "Vincm=0.6" in out
    assert "cL=1e-12" in out
    assert "L12=2.42e-07" in out and "W12=0.00010734" in out
    assert "L34=5e-07" in out and "W34=7.27e-06" in out
    assert "Itail=5.67e-05" in out
    assert out.count("dcCorr dc") == 1
    assert out.count("acCorr ac") == 1
    assert "dec=30" in out


def test_render_rejects_finite_tail_or_existing_analyses():
    with pytest.raises(CorrelationJobError, match="finite-M5"):
        render_netlist(TEMPLATE + "M7 (x y 0 0) nch\n", DESIGN, 1e-12)
    with pytest.raises(CorrelationJobError, match="contains analyses"):
        render_netlist(TEMPLATE + "ac ac start=1 stop=1G dec=10\n",
                       DESIGN, 1e-12)


def test_build_job_writes_manifest_and_private_evidence(tmp_path):
    template = tmp_path / "golden.scs"
    template.write_text(TEMPLATE)
    out = build_job(template, tmp_path / "out", "case_001", DESIGN, 1e-12,
                    request={"Gain_min": 30.0},
                    expected={"GBW": 101e6})
    assert {p.name for p in out.iterdir()} == {
        "input.scs", "measure.ocn", "design.json", "job.json",
        "request_private.json", "expected_private.json"}
    job = json.loads((out / "job.json").read_text())
    netlist = (out / "input.scs").read_bytes()
    assert job["status"] == "pending" and job["corner"] == "tt_lib"
    assert job["netlist_sha256"] == hashlib.sha256(netlist).hexdigest()
    design = json.loads((out / "design.json").read_text())
    assert design["geometry"]["W1"] == DESIGN["W1"]
    ocean = (out / "measure.ocn").read_text()
    assert "selectResult('ac)" in ocean and "selectResult('dc)" in ocean
    assert 'v("Vout") / (v("Vin+") - v("Vin-"))' in ocean
    assert 'v("/Vout")' not in ocean
    assert "ANALOG_AI_METRICS" in ocean
    assert "outfile(" not in ocean
    assert "ocnWaveformTool" not in ocean
    assert 'voutDc = v("Vout")' in ocean
    assert 'vddCurrent = i("V4:p")' in ocean
    assert "average(" not in ocean
    with pytest.raises(FileExistsError):
        build_job(template, tmp_path / "out", "case_001", DESIGN, 1e-12)


def test_build_job_accepts_provenance_but_protects_contract(tmp_path):
    template = tmp_path / "golden.scs"
    template.write_text(TEMPLATE)
    out = build_job(template, tmp_path / "out", "case_meta", DESIGN, 1e-12,
                    metadata={"category": "high_gain",
                              "source_row_id": "request_7"})
    job = json.loads((out / "job.json").read_text())
    assert job["category"] == "high_gain"
    with pytest.raises(CorrelationJobError, match="canonical job fields"):
        build_job(template, tmp_path / "bad", "case_bad", DESIGN, 1e-12,
                  metadata={"corner": "ff_lib"})


def test_render_rejects_bad_contract_values():
    with pytest.raises(CorrelationJobError, match="design is missing"):
        render_netlist(TEMPLATE, {"L1": 1e-6}, 1e-12)
    with pytest.raises(CorrelationJobError, match="positive"):
        render_netlist(TEMPLATE, {**DESIGN, "Itail": 0.0}, 1e-12)
    with pytest.raises(CorrelationJobError, match="Vincm"):
        render_netlist(TEMPLATE, DESIGN, 1e-12, vicm=1.2)

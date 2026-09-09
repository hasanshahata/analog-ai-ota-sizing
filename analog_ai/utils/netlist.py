"""Spectre netlist exporter for an evaluated 5T-OTA design.

Fixes vs. the legacy `utils/netlist_exporter.py`:
- Matched geometry is enforced in the netlist itself: M1/M2 share W/L, M3/M4
  share W/L (the legacy exporter wrote the independently-sized widths, which
  is what made the "matched" pairs differ on silicon: 289.9u vs 292.5u).
- CL, VDD, and the input common mode are parameters, not hardcoded values.
- The differential drive uses positive magnitudes with an explicit 180-degree
  phase on one side (`mag=-0.5, phase=180` is ambiguous/wrong in many
  simulators).
- Optional PDK model include line and corner section.
- `save` statements so AC/OP results are actually written.

NOTE: a tail bias *voltage source* is emitted from the evaluated Vtail. This
reproduces the proxy's imposed operating point; it does not verify that a
mirrored tail current would land at the same point (that requires transistor-
level simulation - gate G1 of docs/codex_plan.md).
"""

from __future__ import annotations

import json
import math
import re

from .. import config


def export_netlist(perf: dict, cl: float | None = None, vdd: float | None = None,
                   vicm: float | None = None,
                   model_include: str | None = None,
                   corner_section: str | None = None) -> str:
    finite_record = perf.get("schema_version", "").endswith("finite-solved-dev")
    if finite_record:
        if perf.get("devices") is None or perf.get("dc_diagnostics") is None:
            raise ValueError("finite netlist export requires a valid evaluated record")
        authoritative = {
            "vdd": float(perf["vdd"]), "vicm": float(perf["vicm"]),
            "cl": float(perf["request"].get("CL_pF", 1.0)) * 1e-12,
        }
        for name, supplied, expected in (("VDD", vdd, authoritative["vdd"]),
                                         ("VICM", vicm, authoritative["vicm"]),
                                         ("CL", cl, authoritative["cl"])):
            if supplied is not None and not math.isclose(float(supplied), expected,
                                                          rel_tol=0.0, abs_tol=1e-18):
                raise ValueError(f"finite export {name} override conflicts with evaluated context")
        vdd, vicm, cl = authoritative["vdd"], authoritative["vicm"], authoritative["cl"]
        devices = perf["devices"]
        vbias_tail = perf["dc_diagnostics"]["Vbias_tail"]
    else:
        devices = perf["devices"]
        # A raw finite performance dictionary has no authoritative request
        # context.  It must not inherit a verdict into an arbitrary circuit.
        if devices.get("M5", {}).get("W", 0.0) > 0.0:
            raise ValueError("finite netlist export requires the complete finite evaluation record")
        if cl is None:
            raise ValueError("ideal netlist export requires CL")
        vdd = config.VDD if vdd is None else float(vdd)
        vicm = vicm if vicm is not None else vdd / 2.0
        vbias_tail = perf.get("Vbias_tail")
    m1, m3 = devices["M1"], devices["M3"]
    m5 = devices.get("M5")
    finite_m5 = m5 is not None and m5.get("W", 0.0) > 0.0
    lines = [
        "// 5T OTA sized by analog_ai",
        f"// Exported CL = {cl*1e12:.17g} pF, VDD = {vdd:.17g} V, VICM = {vicm:.17g} V",
    ]
    if finite_m5:
        # F3: export the ACTUAL finite circuit - the returned M5 geometry
        # and the SOLVED gate bias (the historical zero-volt gate source was
        # not a verifiable circuit).
        if vbias_tail is None:
            raise ValueError(
                "finite netlist export requires a solved Vbias_tail; the "
                "imposed operating point does not produce one")
        lines += [
            f"// Tail: finite NMOS M5, gate bias from the solved evaluation "
            f"(Vbias_tail = {vbias_tail:.6f} V).",
            "// NOTE: exported geometry/bias are rounded to print precision -",
            "// serialization is checked; exported-circuit verdict is withheld.",
        ]
        metadata = {
            "schema_version": perf["schema_version"],
            "oracle_identity": perf.get("oracle_identity"),
            "request": perf.get("request"),
            "capacitance_assumption": perf.get("capacitance_assumption"),
            "pre_export_verdict": bool(perf.get("verdict", False)),
            "serialization_verification": "required_after_export",
            "exported_circuit_verdict": None,
        }
        lines.append("// analog_ai_export_meta=" + json.dumps(metadata, separators=(",", ":")))
    lines += [
        "",
        "simulator lang=spectre",
        "global 0 vdd!",
        "",
    ]
    if model_include:
        lines.append(f'include "{model_include}"'
                     + (f" section={corner_section}" if corner_section else ""))
        lines.append("")

    lines.append("subckt OTA5T (inp inm vout vbiastail)")
    # Matched pairs: one geometry per pair.
    lines.append(f"M1 (vmirror inp vtail 0) nch w={m1['W']*1e6:.4f}u l={m1['L']*1e9:.1f}n")
    lines.append(f"M2 (vout inm vtail 0) nch w={m1['W']*1e6:.4f}u l={m1['L']*1e9:.1f}n")
    lines.append(f"M3 (vmirror vmirror vdd! vdd!) pch w={m3['W']*1e6:.4f}u l={m3['L']*1e9:.1f}n")
    lines.append(f"M4 (vout vmirror vdd! vdd!) pch w={m3['W']*1e6:.4f}u l={m3['L']*1e9:.1f}n")
    if finite_m5:
        lines.append(f"M5 (vtail vbiastail 0 0) nch w={m5['W']*1e6:.4f}u l={m5['L']*1e9:.1f}n")
        lines.append(f"Vtailbias (vbiastail 0) vsource dc={vbias_tail:.6f}")
    else:
        # Ideal tail: bias the tail node directly at the proxy's operating point.
        lines.append(f"Vtailbias (vtail 0) vsource dc={perf['Vtail']:.4f}")
    lines.append("ends OTA5T")
    lines.append("")

    lines += [
        "// Testbench",
        f"Vdd (vdd! 0) vsource dc={vdd}",
        f"Vcm (vicm 0) vsource dc={vicm}",
        "Vinp (inp vicm) vsource dc=0 mag=0.5 phase=0",
        "Vinm (inm vicm) vsource dc=0 mag=0.5 phase=180",
        f"CL (vout 0) capacitor c={cl*1e12:.17g}p",
        "X1 (inp inm vout vbiastail) OTA5T",
        "",
        "// Analyses",
        "dcOp dc",
        "acSweep ac start=1 stop=10G dec=20",
        "save vout vtail vmirror vdb(vout) vp(vout)",
        "",
    ]
    return "\n".join(lines)


def verify_finite_netlist_round_trip(record: dict, netlist: str) -> dict:
    """Verify serialization of the complete finite circuit.

    This is deliberately not a transistor-level post-export verdict.  It
    checks geometry, connectivity, sources, load, and embedded provenance
    against the authoritative pre-export record.
    """
    result = {"serialization_verified": False,
              "exported_circuit_verdict": None, "mismatches": []}
    try:
        lines = netlist.splitlines()
        devices = {}
        device_counts = {}
        pat = re.compile(r"^(M[1-5]) \(([^)]+)\) (nch|pch) w=([0-9.eE+-]+)u l=([0-9.eE+-]+)n$")
        for line in lines:
            match = pat.match(line)
            if match:
                device_counts[match.group(1)] = device_counts.get(match.group(1), 0) + 1
                devices[match.group(1)] = {
                    "nodes": match.group(2).split(), "type": match.group(3),
                    "W": float(match.group(4)) * 1e-6,
                    "L": float(match.group(5)) * 1e-9,
                }
        expected_nodes = {
            "M1": ["vmirror", "inp", "vtail", "0"],
            "M2": ["vout", "inm", "vtail", "0"],
            "M3": ["vmirror", "vmirror", "vdd!", "vdd!"],
            "M4": ["vout", "vmirror", "vdd!", "vdd!"],
            "M5": ["vtail", "vbiastail", "0", "0"],
        }
        source = record["devices"]
        for name in expected_nodes:
            if device_counts.get(name, 0) != 1:
                result["mismatches"].append(f"{name} count")
            if name not in devices:
                result["mismatches"].append(f"missing {name}")
                continue
            got, exp = devices[name], source[name]
            if got["nodes"] != expected_nodes[name] or got["type"] != exp["type"]:
                result["mismatches"].append(f"{name} connectivity/type")
            if not math.isclose(got["W"], float(exp["W"]), rel_tol=0.0, abs_tol=5.1e-11):
                result["mismatches"].append(f"{name} W")
            if not math.isclose(got["L"], float(exp["L"]), rel_tol=0.0, abs_tol=5.1e-11):
                result["mismatches"].append(f"{name} L")

        def value(prefix, marker="dc=", suffix=""):
            line = next(x for x in lines if x.startswith(prefix))
            raw = line.split(marker, 1)[1]
            if suffix:
                raw = raw.split(suffix, 1)[0]
            return float(raw)

        checks = {
            "VDD": (value("Vdd "), float(record["vdd"]), 1e-15),
            "VICM": (value("Vcm "), float(record["vicm"]), 1e-15),
            "Vbias_tail": (value("Vtailbias"), float(record["dc_diagnostics"]["Vbias_tail"]), 5.1e-7),
            "CL": (value("CL ", "c=", "p") * 1e-12,
                   float(record["request"].get("CL_pF", 1.0)) * 1e-12,
                   max(5.1e-19, abs(float(record["request"].get(
                       "CL_pF", 1.0)) * 1e-12) * 5.1e-6)),
        }
        for name, (got, expected, tol) in checks.items():
            if not math.isclose(got, expected, rel_tol=0.0, abs_tol=tol):
                result["mismatches"].append(name)
        exact_lines = (
            "Vinp (inp vicm) vsource dc=0 mag=0.5 phase=0",
            "Vinm (inm vicm) vsource dc=0 mag=0.5 phase=180",
            "X1 (inp inm vout vbiastail) OTA5T",
            "subckt OTA5T (inp inm vout vbiastail)",
            "ends OTA5T",
        )
        for expected in exact_lines:
            if lines.count(expected) != 1:
                result["mismatches"].append(f"connectivity: {expected.split()[0]}")
        meta_line = next(x for x in lines if x.startswith("// analog_ai_export_meta="))
        meta = json.loads(meta_line.split("=", 1)[1])
        if (meta.get("schema_version") != record.get("schema_version") or
                meta.get("oracle_identity") != record.get("oracle_identity") or
                meta.get("request") != record.get("request") or
                meta.get("capacitance_assumption") != record.get("capacitance_assumption") or
                meta.get("pre_export_verdict") != bool(record.get("verdict", False)) or
                meta.get("exported_circuit_verdict") is not None):
            result["mismatches"].append("metadata")
    except (KeyError, ValueError, StopIteration, TypeError) as exc:
        result["mismatches"].append(f"parse: {exc}")
    result["serialization_verified"] = not result["mismatches"]
    return result

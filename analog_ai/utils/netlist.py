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

from .. import config


def export_netlist(perf: dict, cl: float, vdd: float = config.VDD,
                   vicm: float | None = None,
                   model_include: str | None = None,
                   corner_section: str | None = None) -> str:
    devices = perf["devices"]
    m1, m3 = devices["M1"], devices["M3"]
    m5 = devices.get("M5")
    finite_m5 = m5 is not None and m5.get("W", 0.0) > 0.0
    vicm = vicm if vicm is not None else vdd / 2.0

    lines = [
        "// 5T OTA sized by analog_ai (proxy-verified design, see docs/DESIGN_CONTRACT.md)",
        f"// Exported CL = {cl*1e12:.4g} pF, VDD = {vdd:.3g} V",
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
        lines.append("Vtailbias (vbiastail 0) vsource dc=0")
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
        f"CL (vout 0) capacitor c={cl*1e12:.6g}p",
        "X1 (inp inm vout vbiastail) OTA5T",
        "",
        "// Analyses",
        "dcOp dc",
        "acSweep ac start=1 stop=10G dec=20",
        "save vout vtail vmirror vdb(vout) vp(vout)",
        "",
    ]
    return "\n".join(lines)

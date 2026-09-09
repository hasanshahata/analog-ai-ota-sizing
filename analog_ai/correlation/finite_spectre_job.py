"""Build isolated finite-M5 Spectre manual-reference packages for Phase F5."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path

from .. import __version__, config

FINITE_ORACLE = "analog_ai-0.2.0-finite-solved-dev"
FINITE_JOB_SCHEMA = "analog_ai-f5-finite-manual-reference-v1"
PARAMETER_ORDER = ("VDD", "Vincm", "cL", "L1", "W1", "L3", "W3",
                   "L5", "W5", "VbiasTail")
DEVICE_NAMES = ("M1", "M2", "M3", "M4", "M5")
DEVICE_FIELDS = ("ID", "gm", "gds", "gmbs", "VDSAT", "VDS")
_PARAMETER_LINE = re.compile(
    r"(?m)^parameters\s+VDD\s+Vincm\s+cL\s+L1\s+W1\s+L3\s+W3\s+"
    r"L5\s+W5\s+VbiasTail\s*$")
_ANALYSIS_MARKER = "// ANALOG_AI_FINITE_M5_ANALYSES"
_PDK_INCLUDE = re.compile(r'(?m)^include\s+"([^"]+)"\s+section=(\S+)\s*$')


class FiniteCorrelationJobError(ValueError):
    """Finite record, template, or measurement contract is invalid."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _number(value: float) -> str:
    return f"{float(value):.12g}"


def _finite_float(value, name: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FiniteCorrelationJobError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or (positive and result <= 0.0):
        qualifier = "positive and finite" if positive else "finite"
        raise FiniteCorrelationJobError(f"{name} must be {qualifier}")
    return result


def load_tolerances(path: str | os.PathLike) -> tuple[dict, bytes]:
    raw = Path(path).read_bytes()
    try:
        tolerances = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(
            FiniteCorrelationJobError(f"nonfinite tolerance token {value}")))
    except json.JSONDecodeError as exc:
        raise FiniteCorrelationJobError("invalid tolerance JSON") from exc
    if tolerances.get("schema") != "analog_ai-finite-m5-cadence-tolerances-v1":
        raise FiniteCorrelationJobError("unexpected finite tolerance schema")
    if tolerances.get("status") != "frozen_before_manual_reference":
        raise FiniteCorrelationJobError("finite tolerances are not frozen")
    required = {"node_voltage_V", "device_current", "gm", "gds", "gmbs",
                "vdsat_V", "dc_gain_dB", "gbw_Hz", "phase_margin_deg",
                "power_W", "saturation_margin_V"}
    if set(tolerances.get("correlation", {})) != required:
        raise FiniteCorrelationJobError("finite tolerance metric set is incomplete")
    return tolerances, raw


def _validate_template(template: str) -> tuple[str, str]:
    required = (
        "M1 (vmirror vin_p vtail 0) nch", "M2 (vout vin_n vtail 0) nch",
        "M3 (vmirror vmirror vdd! vdd!) pch",
        "M4 (vout vmirror vdd! vdd!) pch",
        "M5 (vtail vbias_tail 0 0) nch",
        "VTAILBIAS (vbias_tail 0) vsource dc=VbiasTail",
        "CLOAD (vout 0) capacitor c=cL",
        "BALUN (vin vicm vin_p vin_n) ideal_balun",
    )
    missing = [token for token in required if token not in template]
    if missing:
        raise FiniteCorrelationJobError(
            "finite template is missing topology tokens: " + ", ".join(missing))
    if "I26 (" in template or "isource dc=Itail" in template:
        raise FiniteCorrelationJobError("ideal-tail source found in finite template")
    if len(_PARAMETER_LINE.findall(template)) != 1:
        raise FiniteCorrelationJobError(
            "expected one unassigned finite parameter declaration")
    if _ANALYSIS_MARKER in template or re.search(
            r"(?m)^\s*(?:ac\w*\s+ac|dc\w*\s+dc)\b", template):
        raise FiniteCorrelationJobError("finite template already contains analyses")
    include = _PDK_INCLUDE.findall(template)
    if len(include) != 1 or include[0][1] != "tt_lib":
        raise FiniteCorrelationJobError("expected one tt_lib PDK include")
    return include[0]


def _extract_record(record: dict) -> dict:
    if record.get("schema_version") != FINITE_ORACLE:
        raise FiniteCorrelationJobError("manual reference requires finite solved schema")
    if record.get("tail_device") != "finite" or record.get("op_point_mode") != "solved":
        raise FiniteCorrelationJobError("manual reference requires finite solved mode")
    if record.get("verdict") is not True:
        raise FiniteCorrelationJobError("manual reference must be a verified finite design")
    devices = record.get("devices", {})
    if set(DEVICE_NAMES) - set(devices):
        raise FiniteCorrelationJobError("manual reference lacks complete M1-M5 evidence")
    context = {
        "VDD": _finite_float(record.get("vdd"), "vdd", positive=True),
        "Vincm": _finite_float(record.get("vicm"), "vicm"),
        "cL": _finite_float(record.get("request", {}).get("CL_pF"),
                            "CL_pF", positive=True) * 1e-12,
        "L1": _finite_float(devices["M1"].get("L"), "M1.L", positive=True),
        "W1": _finite_float(devices["M1"].get("W"), "M1.W", positive=True),
        "L3": _finite_float(devices["M3"].get("L"), "M3.L", positive=True),
        "W3": _finite_float(devices["M3"].get("W"), "M3.W", positive=True),
        "L5": _finite_float(devices["M5"].get("L"), "M5.L", positive=True),
        "W5": _finite_float(devices["M5"].get("W"), "M5.W", positive=True),
        "VbiasTail": _finite_float(record.get("dc_diagnostics", {}).get(
            "Vbias_tail"), "Vbias_tail", positive=True),
    }
    if not 0.0 < context["Vincm"] < context["VDD"]:
        raise FiniteCorrelationJobError("vicm must lie strictly inside the supply")
    if not context["VbiasTail"] < context["VDD"]:
        raise FiniteCorrelationJobError("Vbias_tail must lie below VDD")
    for left, right in (("M1", "M2"), ("M3", "M4")):
        for key in ("L", "W"):
            if not math.isclose(float(devices[left][key]), float(devices[right][key]),
                                rel_tol=1e-12, abs_tol=0.0):
                raise FiniteCorrelationJobError(
                    f"{left}/{right} {key} mismatch cannot be represented")
    return context


def render_finite_netlist(template: str, record: dict) -> str:
    """Render an F5 finite-M5 OTA netlist from an accepted finite record."""
    _validate_template(template)
    values = _extract_record(record)
    parameters = "parameters " + " ".join(
        f"{name}={_number(values[name])}" for name in PARAMETER_ORDER)
    rendered = _PARAMETER_LINE.sub(parameters, template)
    analyses = "\n".join((
        "", _ANALYSIS_MARKER,
        'dcFinite dc write="spectre.dc" maxiters=150 maxsteps=10000 annotate=status',
        "acFinite ac start=1 stop=10G dec=30 annotate=status",
        "save vout vtail vmirror vdd! vin_p vin_n VDDsrc:p",
        "finiteOpInfo info what=oppoint where=rawfile",
        "// END_ANALOG_AI_FINITE_M5_ANALYSES", "",
    ))
    return rendered.rstrip() + analyses


def render_measurement_script(case_id: str, vdd: float) -> str:
    """Return an IC617 OCEAN script with metrics and complete M1-M5 OP data."""
    op_lines = []
    values = []
    for device in DEVICE_NAMES:
        prefix = device.lower()
        for field in ("id", "gm", "gds", "gmbs", "vdsat", "vds"):
            var = prefix + field.capitalize()
            op_lines.append(f'{var} = abs(OP("/{device}" "{field}"))')
            values.append(var)
    return f'''/* Phase F5 finite-M5 measurements for {case_id}. */
openResults("./psf")
selectResult('ac)
gain = v("vout") / (v("vin_p") - v("vin_n"))
gainDbWave = db20(gain)
phaseWave = phase(gain)
gainDb = value(gainDbWave 1.0)
ugf = cross(gainDbWave 0.0 1 "falling")
bw3 = cross(gainDbWave (gainDb - 3.0) 1 "falling")
phaseAtUgf = value(phaseWave ugf)
phaseMargin = 180.0 + phaseAtUgf

selectResult('dc)
voutDc = v("vout")
vtailDc = v("vtail")
vmirrorDc = v("vmirror")
vddCurrent = i("VDDsrc:p")
powerDc = {float(vdd):.12g} * abs(vddCurrent)

selectResult('finiteOpInfo)
printf("ANALOG_AI_FINITE_OP_OUTPUTS_BEGIN\\n")
printf("%L\\n" outputs())
printf("ANALOG_AI_FINITE_OP_OUTPUTS_END\\n")
{chr(10).join(op_lines)}

printf("ANALOG_AI_FINITE_METRICS "
       "%.15g %.15g %.15g %.15g %.15g %.15g %.15g %.15g %.15g %.15g "
       "{('%.15g ' * len(values)).rstrip()}\\n"
       gainDb bw3 ugf phaseAtUgf phaseMargin voutDc vtailDc vmirrorDc
       vddCurrent powerDc {' '.join(values)})
exit()
'''


def render_capacitance_probe(record: dict, pdk_path: str, corner: str) -> str:
    """Bias M5 alone and measure grounded-terminal drain/gate admittance."""
    values = _extract_record(record)
    m5 = record["devices"]["M5"]
    return f'''// Phase F5 device-level M5 capacitance provenance probe.
simulator lang=spectre
global 0
parameters L5={_number(values["L5"])} W5={_number(values["W5"])} VGS5={_number(values["VbiasTail"])} VDS5={_number(m5["VDS"])} Fprobe=1e6
include "{pdk_path}" section={corner}
VG (g 0) vsource dc=VGS5 type=dc
VD (d 0) vsource dc=VDS5 mag=1 type=dc
M5CAP (d g 0 0) nch l=L5 w=W5 m=1 nf=1 sd=200n \\
    ad=((1-int(1/2)*2)*(1.75e-07+((1-1)*2e-07)/2)+(1+1-int((1+1)/2)*2)*((1/2)*2e-07))*W5 \\
    as=((1-int(1/2)*2)*(1.75e-07+((1-1)*2e-07)/2)+(1+1-int((1+1)/2)*2)*(1.75e-07+1.75e-07+(1/2-1)*2e-07))*W5 \\
    pd=(1-int(1/2)*2)*((1.75e-07+((1-1)*2e-07)/2)*2+(1+1)*W5)+(1+1-int((1+1)/2)*2)*(((1/2)*2e-07)*2+W5) \\
    ps=(1-int(1/2)*2)*((1.75e-07+((1-1)*2e-07)/2)*2+(1+1)*W5)+(1+1-int((1+1)/2)*2)*((1.75e-07+1.75e-07+(1/2-1)*2e-07)*2+(1+2)*W5) \\
    nrd=(1-int(1/2)*2)*(1e-07*1e-07/(1e-07+1e-07*(1-1))/W5)+(1+1-int((1+1)/2)*2)*(1e-07/W5) \\
    nrs=(1-int(1/2)*2)*(1e-07*1e-07/(1e-07+1e-07*(1-1))/W5)+(1+1-int((1+1)/2)*2)*(1e-21/(1e-07*1e-07*(1-2)+1e-07*(1e-07+1e-07))/W5) \\
    sa=1/(1/(1.75e-07+0.5*L5))-0.5*L5 sb=1/(1/(1.75e-07+0.5*L5))-0.5*L5 sca=0 scb=0 scc=0
simulatorOptions options reltol=1e-5 vabstol=1e-8 iabstol=1e-15 temp=27 tnom=27
saveOptions options save=allpub
dcCap dc annotate=status
acCap ac start=Fprobe stop=Fprobe lin=1 annotate=status
capOpInfo info what=oppoint where=rawfile
'''


def render_capacitance_script(case_id: str) -> str:
    return f'''/* Phase F5 capacitance provenance measurements for {case_id}. */
openResults("./psf_caps")
selectResult('ac)
drainCurrent = value(i("VD:p") 1e6)
gateCurrent = value(i("VG:p") 1e6)
cDrainY = abs(imag(drainCurrent)) / (2.0 * 3.141592653589793 * 1e6)
cGdY = abs(imag(gateCurrent)) / (2.0 * 3.141592653589793 * 1e6)
selectResult('capOpInfo)
cddOp = abs(OP("/M5CAP" "cdd"))
cgdOp = abs(OP("/M5CAP" "cgd"))
printf("ANALOG_AI_FINITE_CAPS %.15g %.15g %.15g %.15g\\n"
       cddOp cgdOp cDrainY cGdY)
exit()
'''


def expected_from_record(record: dict,
                         enriched_devices: dict | None = None) -> dict:
    """Create private finite proxy expectations for manual correlation."""
    _extract_record(record)
    metrics = record["metrics"]
    dc = record["dc_diagnostics"]
    devices = {}
    for name in DEVICE_NAMES:
        source = dict(record["devices"][name])
        if enriched_devices:
            source.update(enriched_devices.get(name, {}))
        devices[name] = {field: _finite_float(source.get(field), f"{name}.{field}")
                         for field in DEVICE_FIELDS}
        for cap in ("cdd", "cgd"):
            if cap in source:
                devices[name][cap] = _finite_float(source[cap], f"{name}.{cap}")
    return {
        "schema": "analog_ai-f5-finite-expected-v1",
        "metrics": {
            "dc_gain_dB": _finite_float(metrics.get("DC_Gain_dB"), "DC_Gain_dB"),
            "gbw_Hz": _finite_float(metrics.get("GBW"), "GBW", positive=True),
            "phase_margin_deg": _finite_float(metrics.get("PM"), "PM"),
            "power_W": _finite_float(metrics.get("Power_core"), "Power_core", positive=True),
        },
        "nodes": {key: _finite_float(dc.get(key), key)
                  for key in ("Vtail", "Vmirror", "Vout")},
        "devices": devices,
        "effective_constraints": record.get("effective_constraints", {}),
    }


def compare_finite_measurements(expected: dict, measured: dict,
                                tolerances: dict, request: dict,
                                design: dict) -> dict:
    """Apply frozen correlation and measured-request gates independently."""
    rules = tolerances["correlation"]
    comparisons = {}

    def compare(label: str, expected_value, measured_value, rule_name: str):
        rule = rules[rule_name]
        try:
            exp, got = float(expected_value), float(measured_value)
        except (TypeError, ValueError):
            comparisons[label] = {"available": False, "passed": False}
            return
        if not math.isfinite(exp) or not math.isfinite(got):
            comparisons[label] = {"available": False, "passed": False}
            return
        signed = got - exp
        if rule["kind"] == "absolute":
            error = abs(signed)
        else:
            floor = float(rule.get("absolute_floor_A",
                                   rule.get("absolute_floor_S", 1e-30)))
            error = abs(signed) / max(abs(exp), floor)
        comparisons[label] = {
            "available": True, "expected": exp, "measured": got,
            "signed_difference": signed, "error": error,
            "error_kind": rule["kind"], "tolerance": float(rule["limit"]),
            "passed": bool(error <= float(rule["limit"])),
        }

    metric_rules = {"dc_gain_dB": "dc_gain_dB", "gbw_Hz": "gbw_Hz",
                    "phase_margin_deg": "phase_margin_deg", "power_W": "power_W"}
    for name, rule in metric_rules.items():
        compare(name, expected.get("metrics", {}).get(name),
                measured.get("metrics", {}).get(name), rule)
    node_map = {"Vtail": "vtail_V", "Vmirror": "vmirror_V", "Vout": "vout_V"}
    for expected_name, measured_name in node_map.items():
        compare(expected_name, expected.get("nodes", {}).get(expected_name),
                measured.get("nodes", {}).get(measured_name), "node_voltage_V")
    device_rules = {"ID": "device_current", "gm": "gm", "gds": "gds",
                    "gmbs": "gmbs", "VDSAT": "vdsat_V"}
    for device in DEVICE_NAMES:
        for field, rule in device_rules.items():
            compare(f"{device}.{field}",
                    expected.get("devices", {}).get(device, {}).get(field),
                    measured.get("devices", {}).get(device, {}).get(field), rule)
    correlation_passed = bool(comparisons) and all(
        item["passed"] for item in comparisons.values())

    limits = expected.get("effective_constraints", {}).get("limits", {})
    required_measured = {
        "Gain_min": measured.get("metrics", {}).get("dc_gain_dB"),
        "GBW_min": measured.get("metrics", {}).get("gbw_Hz"),
        "Power_max": measured.get("metrics", {}).get("power_W"),
        "PM_min": measured.get("metrics", {}).get("phase_margin_deg"),
    }
    checks = {}
    for name, achieved in required_measured.items():
        limit = request.get(name, limits.get(name))
        available = limit is not None and achieved is not None
        passed = False
        if available:
            limit, achieved = float(limit), float(achieved)
            available = math.isfinite(limit) and math.isfinite(achieved)
            if available:
                passed = achieved <= limit if name.endswith("_max") else achieved >= limit
        checks[name] = {"available": bool(available), "limit": limit,
                        "achieved": achieved, "passed": bool(passed)}
    # These optional finite-mode quantities require dedicated physical sweeps.
    # This first manual DC/AC package does not measure them, so a request that
    # contains one must remain explicitly unavailable and fail closed.
    for name in ("SR_min", "Swing_min", "ICMR_max"):
        if name in request:
            checks[name] = {"available": False, "limit": request[name],
                            "achieved": None, "passed": False,
                            "detail": "not measured by the F5 manual-reference deck"}

    saturation = {}
    for device in DEVICE_NAMES:
        op = measured.get("devices", {}).get(device, {})
        vds, vdsat = op.get("VDS"), op.get("VDSAT")
        available = vds is not None and vdsat is not None
        margin = None
        if available:
            vds, vdsat = float(vds), float(vdsat)
            available = math.isfinite(vds) and math.isfinite(vdsat)
            if available:
                margin = vds - vdsat
        saturation[device] = margin
    sat_limit = request.get("Sat_margin_min",
                            limits.get("Sat_margin_min", config.SAT_MARGIN_MIN_DEFAULT))
    sat_available = all(value is not None and math.isfinite(value)
                        for value in saturation.values())
    min_sat = min(saturation.values()) if sat_available else None
    checks["Sat_margin_min"] = {
        "available": sat_available, "limit": sat_limit, "achieved": min_sat,
        "per_device": saturation,
        "passed": bool(sat_available and min_sat >= float(sat_limit)),
    }

    geometry = design.get("geometry", {})
    width_checks = {
        "W_nmos_max": max(float(geometry.get("W1", math.nan)),
                           float(geometry.get("W5", math.nan))),
        "W_pmos_max": float(geometry.get("W3", math.nan)),
    }
    for name, achieved in width_checks.items():
        limit = request.get(name, limits.get(name))
        available = limit is not None and math.isfinite(achieved)
        checks[name] = {"available": bool(available), "limit": limit,
                        "achieved": achieved,
                        "passed": bool(available and achieved <= float(limit))}
    lengths = [float(geometry.get(name, math.nan)) for name in ("L1", "L3", "L5")]
    lo, hi = config.DESIGN_BOUNDS_7[0]
    available = all(math.isfinite(value) for value in lengths)
    checks["L_domain"] = {
        "available": available, "limit": [lo, hi], "achieved": lengths,
        "passed": bool(available and all(lo <= value <= hi for value in lengths)),
    }
    measured_passed = all(item["passed"] for item in checks.values())
    capacitance = classify_capacitance_provenance(
        expected.get("devices", {}).get("M5", {}),
        measured.get("capacitance_provenance", {}), tolerances)
    return {"correlation": {"metrics": comparisons,
                            "passed": correlation_passed},
            "measured_request": {"checks": checks,
                                 "passed": bool(measured_passed)},
            "capacitance_provenance": capacitance}


def classify_capacitance_provenance(expected_m5: dict, measured: dict,
                                    tolerances: dict) -> dict:
    """Decide whether LUT cdd is the total grounded-drain capacitance."""
    rule = tolerances["capacitance_provenance"]
    limit = float(rule["relative_limit"])
    floor = float(rule["absolute_floor_F"])
    separation = float(rule["decision_separation_fraction"])
    names = ("cdd", "cgd")
    if any(name not in expected_m5 for name in names) or any(
            name not in measured for name in
            ("spectre_cdd_F", "spectre_cgd_F", "drain_admittance_F",
             "gate_transfer_F")):
        return {"available": False, "passed": False,
                "interpretation": "missing_required_capacitance"}
    values = [float(expected_m5["cdd"]), float(expected_m5["cgd"]),
              float(measured["spectre_cdd_F"]), float(measured["spectre_cgd_F"]),
              float(measured["drain_admittance_F"]),
              float(measured["gate_transfer_F"])]
    if not all(math.isfinite(value) and value >= 0.0 for value in values):
        return {"available": False, "passed": False,
                "interpretation": "nonfinite_or_negative_capacitance"}
    lut_cdd, lut_cgd, spectre_cdd, spectre_cgd, drain_y, gate_y = values

    def rel(got, reference):
        return abs(got - reference) / max(abs(reference), floor)

    error_total = rel(drain_y, lut_cdd)
    error_additive = rel(drain_y, lut_cdd + lut_cgd)
    if error_total <= limit and error_additive - error_total >= separation:
        interpretation = "cdd_is_total_grounded_drain_capacitance"
        decisive = True
    elif error_additive <= limit and error_total - error_additive >= separation:
        interpretation = "cdd_excludes_cgd"
        decisive = True
    else:
        interpretation = "ambiguous"
        decisive = False
    consistency = {
        "spectre_cdd_vs_drain_admittance": rel(drain_y, spectre_cdd),
        "lut_cgd_vs_gate_transfer": rel(gate_y, lut_cgd),
        "spectre_cgd_vs_gate_transfer": rel(gate_y, spectre_cgd),
    }
    consistency_passed = all(error <= limit for error in consistency.values())
    return {
        "available": True, "passed": bool(decisive and consistency_passed),
        "interpretation": interpretation,
        "relative_errors": {"lut_cdd": error_total,
                            "lut_cdd_plus_cgd": error_additive,
                            **consistency},
        "relative_limit": limit, "decision_separation_fraction": separation,
        "consistency_passed": consistency_passed,
    }


def build_finite_manual_reference(
        template_path: str | os.PathLike, tolerance_path: str | os.PathLike,
        source_artifact: str | os.PathLike, output_root: str | os.PathLike,
        case_name: str = "test5_balanced", case_id: str = "finite_manual_reference_001",
        overwrite: bool = False,
        enriched_devices: dict | None = None) -> Path:
    """Build one source-bound local manual-reference and M5 cap-probe package."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", case_id):
        raise FiniteCorrelationJobError("invalid case_id")
    source_path = Path(source_artifact)
    source_raw = source_path.read_bytes()
    campaign = json.loads(source_raw)
    matches = [case for case in campaign.get("cases", []) if case.get("name") == case_name]
    if len(matches) != 1:
        raise FiniteCorrelationJobError(f"expected one F4 case named {case_name}")
    record = matches[0]["finite_record"]
    values = _extract_record(record)
    template_path = Path(template_path)
    template_raw = template_path.read_bytes()
    template = template_raw.decode("utf-8")
    pdk_path, corner = _validate_template(template)
    tolerances, tolerance_raw = load_tolerances(tolerance_path)
    netlist = render_finite_netlist(template, record)
    measure = render_measurement_script(case_id, values["VDD"])
    cap_netlist = render_capacitance_probe(record, pdk_path, corner)
    cap_measure = render_capacitance_script(case_id)
    expected = expected_from_record(record, enriched_devices)
    expected["op_enrichment"] = {
        "method": "one_point_real_lut_replay_at_archived_f4_winner",
        "optimization_performed": False,
    }

    case_dir = Path(output_root) / "jobs" / case_id
    if case_dir.exists() and any(case_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"job already exists: {case_dir}")
    case_dir.mkdir(parents=True, exist_ok=True)
    design = {
        "schema": "analog_ai-f5-finite-design-v1", "case_id": case_id,
        "vdd_V": values["VDD"], "vicm_V": values["Vincm"],
        "cl_F": values["cL"], "Vbias_tail_V": values["VbiasTail"],
        "geometry": {key: values[key] for key in ("L1", "W1", "L3", "W3",
                                                        "L5", "W5")},
    }
    public = {
        "input.scs": netlist,
        "measure.ocn": measure,
        "capacitance_probe.scs": cap_netlist,
        "measure_caps.ocn": cap_measure,
        "tolerances.json": tolerance_raw.decode("utf-8"),
        "design.json": json.dumps(design, indent=2) + "\n",
    }
    binding = {name: sha256_bytes(content.encode("utf-8"))
               for name, content in public.items()}
    builder_path = Path(__file__)
    job = {
        "schema": FINITE_JOB_SCHEMA, "case_id": case_id, "status": "prepared",
        "topology": "5t_ota_finite_m5", "oracle_version": FINITE_ORACLE,
        "package_version": __version__, "corner": corner,
        "source_case": case_name,
        "source_binding": {
            **binding,
            "template_source_sha256": sha256_bytes(template_raw),
            "tolerance_source_sha256": sha256_bytes(tolerance_raw),
            "f4_artifact_sha256": sha256_bytes(source_raw),
            "builder_sha256": sha256_bytes(builder_path.read_bytes()),
        },
        "pdk_identity": {"include_path": pdk_path, "section": corner,
                         "sha256": None, "status": "measure_on_guest_before_run"},
        "lut_identity": campaign.get("lut_verification"),
        "required_outputs": {"ota": "ANALOG_AI_FINITE_METRICS",
                             "capacitance": "ANALOG_AI_FINITE_CAPS"},
        "external_bias_generator": "excluded_from_power_area_noise_mismatch",
        "validation_campaign_member": False,
    }
    files = {**public,
             "job.json": json.dumps(job, indent=2) + "\n",
             "request_private.json": json.dumps(record["request"], indent=2) + "\n",
             "expected_private.json": json.dumps(expected, indent=2) + "\n"}
    for name, content in files.items():
        temp = case_dir / (name + ".tmp")
        temp.write_text(content, encoding="utf-8", newline="\n")
        temp.replace(case_dir / name)
    return case_dir

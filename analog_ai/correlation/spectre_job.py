"""Create reproducible Spectre jobs from the golden Cadence netlist.

The Cadence-exported topology is treated as immutable source material.  For
each job we replace only its unassigned ``parameters`` declaration and append
the analyses required by the correlation contract.  The ideal tail current
source and PDK-generated geometry expressions therefore remain byte-for-byte
identical to the known-good schematic export.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .. import ORACLE_VERSION, __version__
from .ocean import render_measurement_script

PARAMETER_ORDER = ("VDD", "Vincm", "cL", "L34", "W34", "L12", "W12",
                   "Itail")
DESIGN_KEYS = ("L1", "W1", "L3", "W3", "Itail")
_PARAMETER_LINE = re.compile(r"(?m)^parameters\s+VDD\s+Vincm\s+cL\s+L34\s+W34\s+L12\s+W12\s+Itail\s*$")
_ANALYSIS_MARKER = "// ANALOG_AI_CORRELATION_ANALYSES"


class CorrelationJobError(ValueError):
    """The template or supplied job data violates the correlation contract."""


def _spectre_number(value: float) -> str:
    """Emit an unambiguous SI-valued Spectre number."""
    return f"{float(value):.12g}"


def _validate_template(template: str) -> None:
    required = (
        "section=tt_lib",
        "I26 (net02 0) isource dc=Itail",
        "M9 (net04 Vin\\+ net02 0) nch",
        "M8 (Vout Vin\\- net02 0) nch",
        "M1 (net04 net04 vdd! vdd!) pch",
        "M0 (Vout net04 vdd! vdd!) pch",
        "C0 (Vout 0) capacitor c=cL",
        "I16 (Vin net8 Vin\\+ Vin\\-) ideal_balun",
    )
    missing = [token for token in required if token not in template]
    if missing:
        raise CorrelationJobError(
            "golden netlist is missing required ideal-tail topology tokens: "
            + ", ".join(missing))
    if "M7 (" in template or "W5" in template or "L5" in template:
        raise CorrelationJobError("finite-M5 content found in ideal-tail template")
    if len(_PARAMETER_LINE.findall(template)) != 1:
        raise CorrelationJobError(
            "expected exactly one unassigned canonical parameters line")
    if re.search(r"(?m)^\s*(?:ac\w*\s+ac|dcOp\s+dc)\b", template):
        raise CorrelationJobError(
            "golden template unexpectedly contains analyses; keep them job-local")


def _validate_values(design: dict, cl_f: float, vdd: float,
                     vicm: float) -> None:
    missing = [key for key in DESIGN_KEYS if key not in design]
    if missing:
        raise CorrelationJobError("design is missing: " + ", ".join(missing))
    positive = {key: float(design[key]) for key in DESIGN_KEYS}
    positive.update(cL=float(cl_f), VDD=float(vdd))
    bad = [key for key, value in positive.items() if not value > 0.0]
    if bad:
        raise CorrelationJobError("values must be positive: " + ", ".join(bad))
    if not 0.0 < float(vicm) < float(vdd):
        raise CorrelationJobError("Vincm must lie strictly between ground and VDD")


def render_netlist(template: str, design: dict, cl_f: float,
                   vdd: float = 1.2, vicm: float = 0.6) -> str:
    """Return one runnable Spectre netlist for an ideal-tail sizing.

    ``design`` uses canonical evaluated geometry keys in SI units:
    ``L1/W1`` for M9=M8, ``L3/W3`` for M1=M0, and ``Itail``.
    """
    _validate_template(template)
    _validate_values(design, cl_f, vdd, vicm)
    values = {
        "VDD": vdd, "Vincm": vicm, "cL": cl_f,
        "L34": design["L3"], "W34": design["W3"],
        "L12": design["L1"], "W12": design["W1"],
        "Itail": design["Itail"],
    }
    parameter_line = "parameters " + " ".join(
        f"{name}={_spectre_number(values[name])}" for name in PARAMETER_ORDER)
    rendered = _PARAMETER_LINE.sub(parameter_line, template)
    analyses = "\n".join((
        "",
        _ANALYSIS_MARKER,
        "dcCorr dc write=\"spectre.dc\" maxiters=150 maxsteps=10000 annotate=status",
        "acCorr ac start=1 stop=10G dec=30 annotate=status",
        "save Vout net02 net04 vdd! Vin\\+ Vin\\-",
        "dcCorrInfo info what=oppoint where=rawfile",
        "// END_ANALOG_AI_CORRELATION_ANALYSES",
        "",
    ))
    return rendered.rstrip() + analyses


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_job(template_path: str | os.PathLike,
              output_root: str | os.PathLike,
              case_id: str, design: dict, cl_f: float,
              request: dict | None = None,
              expected: dict | None = None,
              metadata: dict | None = None,
              vdd: float = 1.2, vicm: float = 0.6,
              overwrite: bool = False) -> Path:
    """Write an atomic, self-describing correlation job directory."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", case_id):
        raise CorrelationJobError("case_id may contain only letters, digits, _ and -")
    template_path = Path(template_path)
    template_bytes = template_path.read_bytes()
    template = template_bytes.decode("utf-8")
    netlist = render_netlist(template, design, cl_f, vdd=vdd, vicm=vicm)

    case_dir = Path(output_root) / "jobs" / case_id
    if case_dir.exists() and any(case_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"job already exists: {case_dir}")
    case_dir.mkdir(parents=True, exist_ok=True)

    design_payload = {
        "case_id": case_id,
        "topology": "5t_ota_ideal_tail",
        "corner": "tt_lib",
        "vdd_V": float(vdd), "vicm_V": float(vicm),
        "cl_F": float(cl_f),
        "geometry": {key: float(design[key]) for key in DESIGN_KEYS},
    }
    job_payload = {
        "schema_version": 1,
        "case_id": case_id,
        "status": "pending",
        "netlist": "input.scs",
        "template": str(template_path),
        "template_sha256": sha256_bytes(template_bytes),
        "netlist_sha256": sha256_bytes(netlist.encode("utf-8")),
        "package_version": __version__,
        "oracle_version": ORACLE_VERSION,
        "simulator": "spectre",
        "corner": "tt_lib",
    }
    if metadata:
        overlap = sorted(set(metadata) & set(job_payload))
        if overlap:
            raise CorrelationJobError(
                "metadata may not replace canonical job fields: "
                + ", ".join(overlap))
        job_payload.update(metadata)

    files = {
        "input.scs": netlist,
        "measure.ocn": render_measurement_script(case_id, vdd=vdd),
        "design.json": json.dumps(design_payload, indent=2) + "\n",
        "job.json": json.dumps(job_payload, indent=2) + "\n",
    }
    if request is not None:
        files["request_private.json"] = json.dumps(request, indent=2) + "\n"
    if expected is not None:
        files["expected_private.json"] = json.dumps(expected, indent=2) + "\n"

    for name, content in files.items():
        tmp = case_dir / (name + ".tmp")
        tmp.write_text(content, encoding="utf-8", newline="\n")
        tmp.replace(case_dir / name)
    return case_dir

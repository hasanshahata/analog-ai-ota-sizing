"""Validate F5 markers/source bindings and atomically write one guest result."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

MAIN_MARKER = "ANALOG_AI_FINITE_METRICS"
CAP_MARKER = "ANALOG_AI_FINITE_CAPS"
BASE_FIELDS = ("dc_gain_dB", "bw_3db_Hz", "gbw_Hz", "phase_at_gbw_deg",
               "phase_margin_deg", "vout_V", "vtail_V", "vmirror_V",
               "vdd_current_A", "power_W")
DEVICES = ("M1", "M2", "M3", "M4", "M5")
DEVICE_FIELDS = ("ID", "gm", "gds", "gmbs", "VDSAT", "VDS")
CAP_FIELDS = ("spectre_cdd_F", "spectre_cgd_F", "drain_admittance_F",
              "gate_transfer_F")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _marker(path: Path, marker: str, count: int) -> list[float]:
    lines = [line for line in path.read_text(errors="replace").splitlines()
             if line.startswith(marker + " ")]
    if len(lines) != 1:
        raise ValueError(f"expected exactly one {marker} line")
    tokens = lines[0].split()[1:]
    if len(tokens) != count:
        raise ValueError(f"{marker} has {len(tokens)} values, expected {count}")
    values = [float(token) for token in tokens]
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"{marker} contains nonfinite values")
    return values


def verify_inputs(case_dir: Path) -> tuple[dict, dict, Path, dict]:
    job = json.loads((case_dir / "job.json").read_text())
    if job.get("schema") != "analog_ai-f5-finite-manual-reference-v1":
        raise ValueError("unexpected finite job schema")
    binding = job["source_binding"]
    bound_files = ("input.scs", "measure.ocn", "capacitance_probe.scs",
                   "measure_caps.ocn", "tolerances.json", "design.json")
    actual = {name: _sha(case_dir / name) for name in bound_files}
    mismatches = [name for name in bound_files if actual[name] != binding.get(name)]
    if mismatches:
        raise ValueError("source binding mismatch: " + ", ".join(mismatches))
    pdk = job["pdk_identity"]
    try:
        pdk_path = Path(pdk["include_path"]).resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"PDK include is unavailable: {pdk['include_path']}") from exc
    pdk_actual = {"include_path": str(pdk_path), "section": pdk["section"],
                  "sha256": _sha(pdk_path), "status": "measured_on_guest"}
    return job, actual, pdk_path, pdk_actual


def build_result(case_dir: Path, ota_log: Path, cap_log: Path) -> dict:
    job, actual, _, pdk_actual = verify_inputs(case_dir)

    main = _marker(ota_log, MAIN_MARKER,
                   len(BASE_FIELDS) + len(DEVICES) * len(DEVICE_FIELDS))
    caps = _marker(cap_log, CAP_MARKER, len(CAP_FIELDS))
    cursor = len(BASE_FIELDS)
    devices = {}
    for device in DEVICES:
        devices[device] = dict(zip(DEVICE_FIELDS,
                                   main[cursor:cursor + len(DEVICE_FIELDS)]))
        cursor += len(DEVICE_FIELDS)
    metrics = dict(zip(BASE_FIELDS, main[:len(BASE_FIELDS)]))
    return {
        "schema": "analog_ai-f5-finite-spectre-result-v1",
        "case_id": job["case_id"], "status": "completed",
        "metrics": {name: metrics[name] for name in BASE_FIELDS[:5]} | {
            "power_W": metrics["power_W"],
            "vdd_current_A": metrics["vdd_current_A"]},
        "nodes": {"vout_V": metrics["vout_V"],
                  "vtail_V": metrics["vtail_V"],
                  "vmirror_V": metrics["vmirror_V"]},
        "devices": devices,
        "capacitance_provenance": dict(zip(CAP_FIELDS, caps)),
        "source_binding": actual,
        "pdk_identity": pdk_actual,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--ota-log", required=True, type=Path)
    parser.add_argument("--cap-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        _, _, _, pdk = verify_inputs(args.case_dir)
        print(pdk["sha256"])
        return
    result = build_result(args.case_dir, args.ota_log, args.cap_log)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temp = args.out.with_suffix(args.out.suffix + ".tmp")
    temp.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    temp.replace(args.out)


if __name__ == "__main__":
    main()

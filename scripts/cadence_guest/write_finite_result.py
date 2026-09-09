"""Validate F5 bindings and atomically write one guest result.

This guest-side helper deliberately uses the Python 2.7/3.5 common syntax
subset because the Cadence Debian VM has an old system Python.
"""

import argparse
import errno
import hashlib
import io
import json
import math
import os
import sys

MAIN_MARKER = "ANALOG_AI_FINITE_METRICS"
CAP_MARKER = "ANALOG_AI_FINITE_CAPS"
BASE_FIELDS = ("dc_gain_dB", "bw_3db_Hz", "gbw_Hz", "phase_at_gbw_deg",
               "phase_margin_deg", "vout_V", "vtail_V", "vmirror_V",
               "vdd_current_A", "power_W")
DEVICES = ("M1", "M2", "M3", "M4", "M5")
DEVICE_FIELDS = ("ID", "gm", "gds", "gmbs", "VDSAT", "VDS")
CAP_FIELDS = ("spectre_cdd_F", "spectre_cgd_F", "drain_admittance_F",
              "gate_transfer_F")
BOUND_FILES = ("input.scs", "measure.ocn", "capacitance_probe.scs",
               "measure_caps.ocn", "tolerances.json", "design.json")


def _join(directory, name):
    return os.path.join(os.path.abspath(directory), name)


def _sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _reject_constant(value):
    raise ValueError("nonfinite JSON token " + value)


def _read_json(path):
    with io.open(path, "r", encoding="utf-8") as handle:
        return json.loads(handle.read(), parse_constant=_reject_constant)


def _isfinite(value):
    return not math.isnan(value) and not math.isinf(value)


def _marker(path, marker, count):
    with io.open(path, "r", encoding="utf-8", errors="replace") as handle:
        lines = [line for line in handle.read().splitlines()
                 if line.startswith(marker + " ")]
    if len(lines) != 1:
        raise ValueError("expected exactly one {0} line".format(marker))
    tokens = lines[0].split()[1:]
    if len(tokens) != count:
        raise ValueError("{0} has {1} values, expected {2}".format(
            marker, len(tokens), count))
    values = [float(token) for token in tokens]
    if not all(_isfinite(value) for value in values):
        raise ValueError("{0} contains nonfinite values".format(marker))
    return values


def verify_inputs(case_dir):
    case_dir = os.path.abspath(case_dir)
    job = _read_json(_join(case_dir, "job.json"))
    if job.get("schema") != "analog_ai-f5-finite-manual-reference-v1":
        raise ValueError("unexpected finite job schema")
    binding = job["source_binding"]
    actual = dict((name, _sha(_join(case_dir, name))) for name in BOUND_FILES)
    mismatches = [name for name in BOUND_FILES
                  if actual[name] != binding.get(name)]
    if mismatches:
        raise ValueError("source binding mismatch: " + ", ".join(mismatches))
    pdk = job["pdk_identity"]
    pdk_path = os.path.realpath(pdk["include_path"])
    if not os.path.isfile(pdk_path):
        raise ValueError("PDK include is unavailable: " + pdk["include_path"])
    pdk_actual = {"include_path": pdk_path, "section": pdk["section"],
                  "sha256": _sha(pdk_path), "status": "measured_on_guest"}
    return job, actual, pdk_path, pdk_actual


def build_result(case_dir, ota_log, cap_log):
    job, actual, unused_pdk_path, pdk_actual = verify_inputs(case_dir)
    del unused_pdk_path
    main = _marker(ota_log, MAIN_MARKER,
                   len(BASE_FIELDS) + len(DEVICES) * len(DEVICE_FIELDS))
    caps = _marker(cap_log, CAP_MARKER, len(CAP_FIELDS))
    cursor = len(BASE_FIELDS)
    devices = {}
    for device in DEVICES:
        devices[device] = dict(zip(
            DEVICE_FIELDS, main[cursor:cursor + len(DEVICE_FIELDS)]))
        cursor += len(DEVICE_FIELDS)
    metrics = dict(zip(BASE_FIELDS, main[:len(BASE_FIELDS)]))
    selected_metrics = dict((name, metrics[name]) for name in BASE_FIELDS[:5])
    selected_metrics["power_W"] = metrics["power_W"]
    selected_metrics["vdd_current_A"] = metrics["vdd_current_A"]
    return {
        "schema": "analog_ai-f5-finite-spectre-result-v1",
        "case_id": job["case_id"], "status": "completed",
        "metrics": selected_metrics,
        "nodes": {"vout_V": metrics["vout_V"],
                  "vtail_V": metrics["vtail_V"],
                  "vmirror_V": metrics["vmirror_V"]},
        "devices": devices,
        "capacitance_provenance": dict(zip(CAP_FIELDS, caps)),
        "source_binding": actual,
        "pdk_identity": pdk_actual,
    }


def _make_parent(path):
    parent = os.path.dirname(os.path.abspath(path))
    if not parent:
        return
    try:
        os.makedirs(parent)
    except OSError as exc:
        if exc.errno != errno.EEXIST or not os.path.isdir(parent):
            raise


def _write_atomic(path, payload):
    path = os.path.abspath(path)
    _make_parent(path)
    temporary = path + ".tmp"
    with io.open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    os.rename(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--ota-log", required=True)
    parser.add_argument("--cap-log", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        unused_job, unused_actual, unused_path, pdk = verify_inputs(args.case_dir)
        del unused_job, unused_actual, unused_path
        sys.stdout.write(pdk["sha256"] + "\n")
        return
    result = build_result(args.case_dir, args.ota_log, args.cap_log)
    _write_atomic(args.out, result)


if __name__ == "__main__":
    main()

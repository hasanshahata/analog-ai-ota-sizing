"""Deterministic synthetic evidence for the bounded Phase-F3 export gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pickle
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analog_ai.circuit.ota5t import OTA5T
from analog_ai.evaluation.evaluator import evaluate_design_finite
from analog_ai.loader import load_engine_from_paths
from analog_ai.utils.netlist import (export_netlist,
                                     verify_finite_netlist_round_trip)

SOURCES = (
    "analog_ai/config.py", "analog_ai/circuit/ota5t.py",
    "analog_ai/circuit/dc_solver.py", "analog_ai/circuit/mna.py",
    "analog_ai/devices/device_model.py", "analog_ai/devices/lut.py",
    "analog_ai/evaluation/constraints.py", "analog_ai/evaluation/evaluator.py",
    "analog_ai/utils/netlist.py", "scripts/probe_f3_export.py",
    "tests/conftest.py",
)
DESIGN = (0.6e-6, 15.0, 0.6e-6, 12.0, 0.6e-6, 10.0, 50e-6)
REQUEST = {"Gain_min": 20.0, "GBW_min": 1e6, "CL_pF": 2.5,
           "Power_max": 400e-6}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_evidence() -> dict:
    spec = importlib.util.spec_from_file_location(
        "f3_synthetic_lut_source", ROOT / "tests" / "conftest.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    with TemporaryDirectory(prefix="analog_ai_f3_") as directory:
        directory = Path(directory)
        paths = directory / "nch.pkl", directory / "pch.pkl"
        for path, data in zip(paths, (module.build_lut_data(300e-6, 0.35),
                                      module.build_lut_data(100e-6, 0.40))):
            with path.open("wb") as stream:
                pickle.dump(data, stream)
        dm, _ = load_engine_from_paths(str(paths[0]), str(paths[1]))
        ota = OTA5T(dm, vdd=1.3, tail_device="finite", op_point="solved")
        record = evaluate_design_finite(ota, DESIGN, REQUEST)
        netlist = export_netlist(record)
        verified = verify_finite_netlist_round_trip(record, netlist)
        corrupted = netlist.replace(
            "Vdd (vdd! 0) vsource dc=1.3",
            "Vdd (vdd! 0) vsource dc=0.1", 1)
        rejected = verify_finite_netlist_round_trip(record, corrupted)
    return {
        "evidence_kind": "phase_f3_synthetic_export_round_trip",
        "source_fingerprint": {name: _sha(ROOT / name) for name in SOURCES},
        "request": REQUEST,
        "finite_record": record,
        "exported_netlist": netlist,
        "parsed_verification": verified,
        "known_failed_diagnostic": {
            "pre_export_verdict": record["verdict"],
            "sat_m5": record["metrics"]["sat_m5"],
        },
        "corruption": {"mutation": "VDD 1.3 V -> 0.1 V",
                       "parsed_verification": rejected},
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    evidence = build_evidence()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    main()

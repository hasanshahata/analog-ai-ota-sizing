"""Engine loading helpers (LUTs + device model + proxy evaluator)."""

from __future__ import annotations

import os

from .circuit.ota5t import OTA5T
from .devices.device_model import DeviceModel
from .devices.lut import LUT

DEFAULT_LUT_DIR = "tech_luts"
NCH_FILENAME = "TSMC_fast_65nm_nch.pkl"
PCH_FILENAME = "TSMC_fast_65nm_pch.pkl"


def load_engine(lut_dir: str = DEFAULT_LUT_DIR, tail_device: str = "ideal",
                op_point: str = "imposed"):
    """Load the LUTs and build (DeviceModel, OTA5T). Loads ~5.5 GB into memory."""
    nch_path = os.path.join(lut_dir, NCH_FILENAME)
    pch_path = os.path.join(lut_dir, PCH_FILENAME)
    for p in (nch_path, pch_path):
        if not os.path.exists(p):
            raise FileNotFoundError(f"LUT not found: {p} (run from the repo root, "
                                    f"or pass lut_dir)")
        if os.path.getsize(p) < 1_000_000:
            raise ValueError(f"{p} is suspiciously small - refusing to use a "
                             "placeholder LUT")
    return load_engine_from_paths(nch_path, pch_path, tail_device=tail_device,
                                  op_point=op_point)


def load_engine_from_paths(nch_path: str, pch_path: str, tail_device: str = "ideal",
                           op_point: str = "imposed"):
    nch = LUT(nch_path)
    pch = LUT(pch_path)
    dm = DeviceModel(nch, pch)
    return dm, OTA5T(dm, vdd=1.2, tail_device=tail_device, op_point=op_point)

"""Frozen nominal-corner guard-band policy derived from Cadence evidence."""

from __future__ import annotations

import math

import numpy as np

GBW_GUARD_BAND = 0.25
POLICY_VERSION = "tt-ideal-tail-gbw-v1"

# ---- v2 tiered policy (PROVISIONAL - pending third disjoint validation) ----
# Measured Spectre/LUT GBW ratios, split by whether the request sits inside
# the app domain (<= 300 MHz): worst uplift needed in-domain 16.1% (n=25
# across both campaigns), out-of-domain 24.6%. The v1 25% flat band covered
# everything but overdesigns in-domain by ~10-20%.
V2_POLICY_VERSION = "tt-ideal-tail-gbw-v2-tiered"
DOMAIN_MAX_GBW_HZ = 300e6
BAND_IN_DOMAIN = 0.18
BAND_OUT_OF_DOMAIN = 0.25


def tiered_guard_band(user_gbw_hz: float) -> float:
    """Band for one request under the v2 tiered policy."""
    if not math.isfinite(user_gbw_hz) or user_gbw_hz <= 0:
        raise ValueError("user_gbw_hz must be positive and finite")
    if user_gbw_hz <= DOMAIN_MAX_GBW_HZ:
        return BAND_IN_DOMAIN
    return BAND_OUT_OF_DOMAIN


def tiered_policy_record(user_gbw_hz: float) -> dict:
    """Serializable provenance for a v2 tiered sizing decision."""
    band = tiered_guard_band(user_gbw_hz)
    return {
        "version": V2_POLICY_VERSION,
        "gbw_guard_band": band,
        "internal_target_formula": "user_GBW_min * (1 + tiered_guard_band)",
        "tier": ("in_domain" if user_gbw_hz <= DOMAIN_MAX_GBW_HZ
                 else "out_of_domain"),
        "domain_max_gbw_hz": DOMAIN_MAX_GBW_HZ,
        "provisional": True,
        "validation": ("pending third disjoint blind Cadence campaign "
                       "(18% tier)"),
        "scope": "5t_ota_ideal_tail_tt_lib_nominal",
    }


def guarded_specs(specs: dict, guard_band: float = GBW_GUARD_BAND) -> dict:
    """Return internal sizing targets while preserving the user contract."""
    if not 0.0 <= guard_band < 1.0:
        raise ValueError("guard_band must be in [0, 1)")
    out = dict(specs)
    out["GBW_min"] = float(specs["GBW_min"]) * (1.0 + guard_band)
    return out


def policy_record(guard_band: float = GBW_GUARD_BAND) -> dict:
    """Serializable provenance for a guarded sizing decision."""
    return {
        "version": POLICY_VERSION if guard_band == GBW_GUARD_BAND else "custom",
        "gbw_guard_band": float(guard_band),
        "internal_target_formula": "user_GBW_min * (1 + guard_band)",
        "scope": "5t_ota_ideal_tail_tt_lib_nominal",
    }


def analyze_gbw_calibration(records: list[dict], step: float = 0.05) -> dict:
    """Summarize Spectre/LUT ratios and recommend an upward rounded margin."""
    completed = [r for r in records if r.get("status") == "completed"]
    if not completed:
        raise ValueError("no completed correlation records")
    ratios = np.asarray([
        float(r["spectre"]["gbw_Hz"]) / float(r["expected"]["gbw_Hz"])
        for r in completed
    ])
    if not np.isfinite(ratios).all() or np.any(ratios <= 0.0):
        raise ValueError("GBW ratios must be positive and finite")
    required = 1.0 / ratios - 1.0
    observed_max = float(required.max())
    rounded = math.ceil((observed_max - 1e-12) / step) * step
    return {
        "n": len(completed),
        "spectre_over_lut_ratio": {
            "minimum": float(ratios.min()),
            "p05": float(np.quantile(ratios, 0.05)),
            "median": float(np.median(ratios)),
            "mean": float(ratios.mean()),
            "maximum": float(ratios.max()),
        },
        "required_lut_uplift": {
            "maximum_observed": observed_max,
            "rounded_to_step": float(rounded),
            "rounding_step": float(step),
        },
        "frozen_policy": {
            "version": POLICY_VERSION,
            "gbw_guard_band": GBW_GUARD_BAND,
            "internal_target_formula": "user_GBW_min * (1 + guard_band)",
        },
    }

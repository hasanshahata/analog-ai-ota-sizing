"""Sizing runtime for the web app (Phase W1).

Owns the one-time heavy initialization (LUT engine + surrogate checkpoint)
and serializes sizing calls: the LUT engine and the optimization path have
not been proven thread-safe, so the runtime is a single sizing worker.

Heavy imports (torch, the LUT loader) live inside ``load()`` so that unit
tests can import this module and inject fakes without 5.5 GB of pickles.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import numpy as np

from ..correlation.calibration import (GBW_GUARD_BAND, POLICY_VERSION,
                                       V2_POLICY_VERSION)
from .schemas import json_safe

log = logging.getLogger("analog_ai.web")

DEFAULT_LUT_DIRNAME = "tech_luts"
DEFAULT_CKPT_SUBPATH = Path("models") / "surrogate" / "poc"


class RuntimeNotReady(RuntimeError):
    """The engine is still loading or failed to load."""


class SizingFailure(RuntimeError):
    """A controlled sizing failure (never a raw traceback to the client)."""


class SizingRuntime:
    """Load-once, lock-protected facade over ``size_ideal_tail_ota``."""

    def __init__(self, project_root: str | Path | None = None,
                 ckpt_dir: str | Path | None = None,
                 tiered_band: bool = True):
        self.root = (Path(project_root).resolve() if project_root
                     else Path(__file__).resolve().parents[2])
        self.ckpt_dir = (Path(ckpt_dir) if ckpt_dir
                         else self.root / DEFAULT_CKPT_SUBPATH)
        self.lut_dir = self.root / DEFAULT_LUT_DIRNAME
        # v2 tiered policy (18% in-domain / 25% beyond) - validated by the
        # third disjoint blind campaign (25/25 user-spec passes, 0 false
        # proxy passes, 2026-09-04; worst observed uplift 17.6%).
        self.tiered_band = tiered_band
        self.state = "loading"           # loading | ready | failed
        self.detail: str | None = None
        self.ota = None
        self.model = None
        self.feat_lo: np.ndarray | None = None
        self.feat_hi: np.ndarray | None = None
        self.champion: str | None = None
        self.current_request: dict | None = None
        self._size_lock = threading.Lock()

    # ---------------------------------------------------------------- load --
    def load(self) -> None:
        """One-time heavy initialization; never leaves partial state."""
        try:
            from ..loader import load_engine
            from ..surrogate.train import load_checkpoint
            from ..sizing import size_ideal_tail_ota  # import check only

            champion_file = self.ckpt_dir / "champion.json"
            if not champion_file.exists():
                raise FileNotFoundError(
                    f"surrogate champion file not found under {ckpt_label(self.ckpt_dir)}")
            import json
            with open(champion_file) as f:
                champion_name = Path(json.load(f)["champion"]).name
            log.info("web runtime: loading LUTs from %s and champion %s",
                     self.lut_dir.name, champion_name)
            _, ota = load_engine(lut_dir=str(self.lut_dir),
                                 tail_device="ideal", op_point="solved")
            ck = load_checkpoint(str(self.ckpt_dir / champion_name))
            meta = ck["meta"]
            self.ota = ota
            self.model = ck["proposal"]
            self.feat_lo = np.asarray(meta["feat_lo"], dtype=float)
            self.feat_hi = np.asarray(meta["feat_hi"], dtype=float)
            self.champion = champion_name
            self.state = "ready"
            self.detail = None
            log.info("web runtime: ready (policy %s, guard band %.2f)",
                     POLICY_VERSION, GBW_GUARD_BAND)
        except Exception as exc:                      # noqa: BLE001
            self.state = "failed"
            self.detail = _public_load_error(exc)
            log.exception("web runtime: load failed")

    # ---------------------------------------------------------------- size --
    def size(self, canonical_specs: dict, seed: int = 0,
             request_id: str | None = None) -> dict:
        """Run one guarded sizing. The input dict is never mutated.

        Raises RuntimeNotReady / SizingFailure; returns a JSON-safe record.
        """
        with self._size_lock:
            if self.state != "ready":
                raise RuntimeNotReady(
                    "sizing engine is not ready (state: %s)" % self.state)
            self.current_request = {
                "request_id": request_id, "started": time.time()}
            log.info("size %s start", request_id)
            from ..sizing import size_ideal_tail_ota
            work = dict(canonical_specs)
            snapshot = dict(canonical_specs)
            try:
                record = size_ideal_tail_ota(
                    self.ota, self.model, work, self.feat_lo, self.feat_hi,
                    tiered_band=self.tiered_band, seed=seed)
            except Exception as exc:                  # noqa: BLE001
                log.exception("sizing failed for specs %s", snapshot)
                raise SizingFailure(_public_size_error(exc)) from None
            finally:
                self.current_request = None
            if work != snapshot:
                raise SizingFailure("internal error: request was mutated")
            return json_safe(record)

    # -------------------------------------------------------------- health --
    def health(self) -> dict:
        """Cheap readiness snapshot; never triggers a new engine load."""
        cur = self.current_request
        return {
            "state": self.state,
            "detail": self.detail if self.state == "failed" else None,
            "policy_version": (V2_POLICY_VERSION
                               if self.tiered_band else POLICY_VERSION),
            "scope": ("ideal-tail 5T OTA, TSMC 65nm tt_lib, VDD 1.2 V, "
                      "Vincm 0.6 V, solved LUT operating point"),
            "busy": cur is not None,
            "current_request_elapsed_s": (
                round(time.time() - cur["started"], 1) if cur else None),
        }

    def load_async(self) -> threading.Thread:
        """Start ``load()`` on a daemon thread (used by app startup)."""
        t = threading.Thread(target=self.load, name="web-runtime-load",
                             daemon=True)
        t.start()
        return t


def ckpt_label(path: Path) -> str:
    """Human-safe location label without absolute server paths."""
    try:
        rel = Path(path).resolve().relative_to(Path(__file__).resolve().parents[2])
        return str(rel)
    except ValueError:
        return path.name


def _public_load_error(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "required LUT or checkpoint files are missing (see server logs)"
    return "runtime initialization failed (see server logs)"


def _public_size_error(exc: Exception) -> str:
    if isinstance(exc, RuntimeNotReady):
        return str(exc)
    if isinstance(exc, SizingFailure):
        return str(exc)
    return ("sizing failed internally; the request was not processed "
            "(see server logs)")

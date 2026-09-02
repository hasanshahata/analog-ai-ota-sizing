"""Feasibility-labeled dataset construction (correction plan Phase 3).

Modules:
- `sampling`: Sobol coverage of the design domain + request derivation
- `build`:   row construction (design/request tables) around the canonical
             evaluator and verifier
- `splits`:  region-based, leakage-safe split assignment
- `io`:      sharded Parquet persistence + manifest
"""

from . import build, io, sampling, splits

__all__ = ["build", "io", "sampling", "splits"]

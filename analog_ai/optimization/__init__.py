"""Optimization-based design generation (multi-start constrained DE baseline)."""

from .de_baseline import make_objective, optimize_specs

__all__ = ["make_objective", "optimize_specs"]

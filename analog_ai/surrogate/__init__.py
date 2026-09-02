"""Supervised amortized inverse design (correction plan Phase 5).

Research PoC on the five-parameter ideal-tail abstraction (see
docs/DESIGN_CONTRACT.md scope decision). The network proposes designs;
`analog_ai.evaluation.constraints` remains the only acceptance authority.
"""

from . import data, evaluate, model, train

__all__ = ["data", "evaluate", "model", "train"]

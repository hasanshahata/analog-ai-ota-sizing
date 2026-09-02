"""Analog AI — canonical OTA sizing package.

Single source of truth for the 65 nm 5T-OTA sizing workflow:
device LUTs, circuit proxy evaluation, hard-constraint verification,
the RL sizing environment, and the Spectre netlist exporter.

The fast analytical evaluator is a *proxy*, never ground truth.
Designs are only "verified" in the sense of `analog_ai.evaluation.constraints`;
transistor-level signoff requires an external simulator (see docs/codex_plan.md, gate G1).
"""

__version__ = "0.1.0"

ORACLE_VERSION = f"analog_ai-{__version__}-proxy"

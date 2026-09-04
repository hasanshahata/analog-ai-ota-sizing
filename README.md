# Analog AI Optimization

RL / optimization system for sizing a 5-transistor OTA in TSMC 65 nm against
target specs (Gain, GBW, CL, Power) using gm/Id lookup tables and a fast
analytical proxy evaluator.

**Status:** nominal ideal-tail research demonstrator with a guarded local web
application. The device physics is
Spectre-characterized LUT data, and the canonical evaluator now solves the DC
operating point from those curves by KCL (`op_point="solved"`) — no imposed
bias, no simulator in the loop. Canonical evaluation (2026-09): the best RL
model (V12) passes 1/5 regression tests — identical to a constant-median
baseline — while the supervised proposal plus hard verification and local
refinement reaches 100% on 1,500 held-out requests with known feasible
witnesses. The current 18% in-domain GBW guard passed a third disjoint Cadence
campaign (25/25 user-spec passes, zero false passes). **Moving to another PC? Start with
`docs/HANDOFF.md`.** Otherwise read `docs/PROJECT_REVIEW.md` (audit) and
`docs/CORRECTION_LOG.md` (what has been fixed so far). The plan being
executed is `docs/codex_plan.md`.

## Layout

| Path | What it is |
|---|---|
| `analog_ai/` | **Canonical package** (single source of truth): LUTs, device model, OTA proxy, hard-constraint verifier, RL environment, netlist exporter |
| `configs/` | Design contract constants (in `analog_ai/config.py`), the five regression cases (`test_cases/`) |
| `scripts/` | Entry points: `evaluate_tests.py`, `optimize_baseline.py` |
| `tests/` | Pytest suite — runs on a synthetic square-law LUT, no 5.5 GB files needed |
| `models/` | Trained PPO agents v1–v12, intermediate `checkpoints/`, `training_telemetry/` |
| `evaluation_results/` | Historical result tables + `canonical/` outputs of the new evaluator |
| `tech_luts/` | TSMC 65 nm NMOS/PMOS characterization LUTs (**2.76 GB each**, not in git) |
| `docs/` | `context.md` (version history diary), `PROJECT_REVIEW.md`, `codex_plan.md` (remediation plan), `DESIGN_CONTRACT.md` |
| `web_app/` | Static browser UI for the sizing web app (`analog_ai/web/` backend) |
| `archive/` | Frozen history: `versions/` (V2–V12 trainer trees), `legacy_root/` (old 7-param package, web app, old scripts), `kaggle/` (notebook builders). Do not import from here. |

## Setup

```bash
uv venv --python 3.11 .venv          # or: python -m venv .venv
uv pip install --python .venv numpy scipy gymnasium pytest
```

Optional (loading/training PPO models, ~2.5 GB): `stable-baselines3==2.9.0 torch`.

## Usage

```bash
# run the test suite (no LUTs required)
.venv/Scripts/python -m pytest

# canonical evaluation of the 5 regression cases with full verdicts
.venv/Scripts/python scripts/evaluate_tests.py --source constant
.venv/Scripts/python scripts/evaluate_tests.py --source optimizer

# non-learning correctness baseline (multi-start DE + hard verification)
.venv/Scripts/python scripts/optimize_baseline.py

# evaluate a trained model (needs stable-baselines3)
.venv/Scripts/python scripts/evaluate_tests.py --source model \
    --model models/universal_ppo_agent_65nm_v12.zip
```

Run scripts and tests from the repository root so `tech_luts/` resolves.

## Web app

A small local web application exposes the guarded, hard-verified nominal-TT
sizing pipeline (ideal-tail 5T OTA): enter four specifications, get a
verified candidate sizing or an explicit `unresolved` result with no
dimensions.

```bash
uv pip install --python .venv/Scripts/python.exe -e ".[web]" torch
.venv/Scripts/python scripts/run_web_app.py     # http://127.0.0.1:8000/
```

Scope and honest limitations: `docs/WEB_APP_USER_GUIDE.md`; implementation
log: `docs/WEB_APP_PROGRESS_LOG.md`.

The deployed UI is self-contained. Tailwind is compiled into the committed
`web_app/static/tailwind.css`; frontend development can rebuild it with
`npm install` followed by `npm run build:web-css`.

## Key properties of the canonical package

- **The LUTs replace Spectre end to end**: the device data is
  Spectre-characterized, and in `op_point="solved"` mode the DC bias point is
  computed from those same curves by Newton iteration on KCL (`dc_solver.py`)
  — no imposed voltages, no assumed branch currents, no simulator.
- **Matched devices stay matched**: M2 reuses M1's geometry, M4 reuses M3's
  (the legacy code produced W1 ≠ W2 "matched" pairs).
- **Domain validation**: out-of-grid LUT queries and unachievable gm/Id targets
  raise instead of silently extrapolating/clamping.
- **Body effect uses the LUT `gmbs`** (the legacy engine substituted 0.2·gm
  everywhere due to a key mismatch).
- **Invalid designs are finite and counted**, never a −1e7 reward.
- **Gymnasium seeding honored**; the RL environment is bit-compatible with the
  V9–V12 models (15-D obs / 5-D action) and supports `one_shot=True`
  (contextual-bandit formulation).
- **A design passes only through the hard-constraint verifier**; the RL cost is
  a shaping signal, never an acceptance test.

## What is still open (correction plan)

1. **Phase F — finite-M5 solved mode** and corresponding Cadence correlation.
2. Complete the remaining 17 Phase E boundary certifications (optional).
3. PVT / Monte Carlo / mismatch and post-layout validation.
4. Seven-parameter dataset regeneration and surrogate retraining after the
   finite-M5 oracle is validated.

See `docs/codex_plan.md` for the full gated plan.

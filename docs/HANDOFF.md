# HANDOFF — project state & how to continue on another PC

Written 2026-09-02. If you are reading this after moving the folder to a new
machine, this file is the entry point. It is updated whenever work pauses.

---

## 1. What this project is

RL/optimization system that sizes a 65 nm TSMC 5T-OTA against Gain/GBW/CL/
Power targets. The device physics is **Spectre-characterized LUT data**
(`tech_luts/*.pkl`, 2.76 GB each) — that data *is* the Spectre replacement.
The canonical evaluator completes the chain with a **KCL-solved DC operating
point** derived from those same LUT curves (no imposed bias, no simulator).
Learned PPO models exist (V1–V12, in `models/`) but the best one (V12) is
*not* goal-conditioned; the project is mid-way through the correction plan
(`docs/codex_plan.md`) that replaces reward tweaking with
oracle → dataset → supervised model → verifier.

## 2. Current state (evidence, all in `evaluation_results/canonical/`)

| Evaluation | Source | Result | Files |
|---|---|---|---|
| V12 model, imposed op point | `model` | 1/5 PASS (test 3 only), fixed design | `model_results.md` |
| V12 model, solved op point | `model_solved` | 1/5 PASS — same conclusion | `model_solved_results.md` |
| Constant median design, imposed | `constant` | 1/5 PASS (identical test to V12 ⇒ policy ≈ constant) | `constant_results.md` |
| Constant median design, solved | `constant_solved` | 1/5 PASS — same conclusion | `constant_solved_results.md` |
| Differential-evolution baseline, imposed | `baseline_de` | **5/5 PASS** | `baseline_de_summary.md` |
| DE baseline, solved op point | `baseline_de_solved` | **5/5 PASS** (completed 2026-09-02 on the new PC) | `baseline_de_solved_summary.md` |

Tests: **60 unit tests + 3 integration tests pass** (integration auto-skips
without the LUTs). One caveat: running the integration tests *while* a
baseline process holds both LUTs in memory can error on a ~14 GB machine
(memory contention) — run them when nothing else has the LUTs loaded.

## 3. Setting up a new PC

Requirements: Python 3.11 (3.12+ works for everything except loading the
Kaggle-era model zips), ~8 GB free disk beyond the repo, ≥ 8 GB RAM for the
LUTs. NOTE (2026-09-03): version control is restored as a **fresh repo**
(branch `main`, tag `oracle-v0.1.0+dataset-pilot`) — the original history
still lives only on the old machine. Also beware: a stray git repo exists at
the user's home directory root — always run git from inside the project.

```bash
# from the repo root
py -3.11 -m venv .venv          # or: uv venv --python 3.11 .venv
.venv/Scripts/pip install numpy scipy gymnasium pytest          # Windows path
# Linux/macOS: .venv/bin/pip install numpy scipy gymnasium pytest
# optional, for loading/training PPO models (~2.5 GB):
#   pip install stable-baselines3==2.9.0 torch --index-url https://download.pytorch.org/whl/cpu

# smoke test (no LUTs needed, ~15 s):
.venv/Scripts/python -m pytest tests/ --ignore=tests/test_integration_real_luts.py

# full test incl. real LUTs (~1-4 min, needs tech_luts/ present):
.venv/Scripts/python -m pytest tests/
```

**Files that must travel with the folder** (excluded from git by size):
`tech_luts/TSMC_fast_65nm_nch.pkl` and `..._pch.pkl` (2.76 GB each). Model
zips and checkpoints ARE in git. If `tech_luts/*.pkl` are missing, everything
still runs on the synthetic-LUT test suite — only real-data runs skip/fail.

## 4. In flight — nothing; Phase 5 PoC complete (2026-09-03)

Done since the move: DE solved-op-point baseline (**5/5 PASS**), **Phase 3**
pilot dataset (`data/pilot/`, splits v2 — zero design-ID leakage), and the
**Phase 5 PoC**: a best-of-5 proposal net + OOD risk head
(`analog_ai/surrogate/`, checkpoints in `models/surrogate/poc/`, champion
seed2). Held-out results (1,500 verified requests): raw 67.9% / best-of-K
**85.3%** / after fallback 85.7%; NN baseline 57.7%; constant 0%; five
regression cases **5/5**; risk head 99.97% accurate; ~5 oracle evals per
request vs ~1,732 for DE. Gates: G4 pass, G6 honored, G3's 95% held-out bar
not yet met (honest gap). Full table:
`evaluation_results/canonical/surrogate_poc_summary.md` and the 2026-09-03
entry in `CORRECTION_LOG.md`.

Reproduce:

```bash
.venv/Scripts/python scripts/train_surrogate.py --data data/pilot     --out models/surrogate/poc --k 5 --seeds 0,1,2
.venv/Scripts/python scripts/evaluate_surrogate.py --stage all --n-eval 1500
```

Next planned work (in order): finite-M5 solved mode (physical gate), then
closing the 85.7% -> 95% gap (wider fallback coverage, parallelized builder,
scaled dataset).

## 5. Command reference

```bash
# canonical 5-test evaluation with full verdicts (choose one source):
.venv/Scripts/python scripts/evaluate_tests.py --source constant  --op-point solved
.venv/Scripts/python scripts/evaluate_tests.py --source model     --op-point solved   # needs sb3
.venv/Scripts/python scripts/evaluate_tests.py --source optimizer --op-point solved

# non-learning correctness baseline (multi-start DE + hard verifier):
.venv/Scripts/python scripts/optimize_baseline.py --op-point solved --seed 0

# every script takes --op-point {solved,imposed}; imposed reproduces the
# legacy V9-V12 semantics and historical numbers.
```

Run everything from the repo root so `tech_luts/` resolves.

## 6. Where things live

| Path | Contents |
|---|---|
| `analog_ai/` | canonical package: `devices/` (LUT+domain checks, matched sizing), `circuit/` (MNA, OTA proxy, **dc_solver.py** KCL solve), `evaluation/` (hard constraint verifier, record evaluator), `envs/` (V9–V12-compatible gym env), `utils/netlist.py`, `config.py` (single design contract) |
| `scripts/` | `evaluate_tests.py`, `optimize_baseline.py`, `build_dataset.py`, `train_surrogate.py`, `evaluate_surrogate.py` (all resumable) |
| `tests/` | unit tests on a synthetic square-law LUT + real-LUT integration tests |
| `configs/test_cases/` | the five frozen regression JSONs |
| `models/` | PPO agents v1–v12, `checkpoints/`, `training_telemetry/`, `surrogate/poc/` (best-of-K checkpoints + champion) |
| `evaluation_results/` | historical v2–v12 tables + `canonical/` (current evidence, incl. `surrogate_poc_summary.md`) |
| `data/pilot/` | Phase 3 dataset: 24.6k design rows, 33.2k verified request rows, splits v2, manifest (consolidated parquet committed; shards are local) |
| `docs/` | `codex_plan.md` (the plan), `CORRECTION_LOG.md` (done so far), `PROJECT_REVIEW.md` (audit), `DESIGN_CONTRACT.md` (frozen contract), `context.md` (historical diary — start at its STATUS banner), `HANDOFF.md` (this file) |
| `archive/` | frozen V2–V12 trainer trees, legacy root package, web app, Kaggle notebooks — **never import from here** |

## 7. Next steps (in `codex_plan.md` order)

1. ~~Finish DE solved baseline tests 2–5 (§4)~~ **Done 2026-09-02 — 5/5 PASS.**
2. ~~Phase 3 — feasibility-labeled dataset~~ **Done 2026-09-03** — builder in
   `analog_ai/dataset/` + `scripts/build_dataset.py`; pilot in `data/pilot/`
   (33,150 verified request rows). See `CORRECTION_LOG.md`.
3. ~~Phase 5 PoC — supervised amortized inverse design~~ **Done 2026-09-03**
   (best-of-K + risk head; 85.3% held-out best-of-K, 5/5 regression cases).
   PPO one-step env stays a demoted ablation.
4. **Phase 5 continuation** — close 85.7% -> 95%: wider DE-fallback coverage,
   parallelized builder + scaled dataset, MDN if heads under-cover.
5. **Phase 6** — held-out evaluation at scale (thousands of targets, seeds),
   goal-sensitivity test, report raw vs post-verification pass rates.
6. Optional: LUT checksums now exist in `configs/lut_manifest.json`; remaining: finite-M5 support in solved mode (currently imposed-only); parallelized dataset builder for scaled runs.

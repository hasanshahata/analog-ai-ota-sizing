# Project Review — Analog AI Optimization

**Date:** 2026-09-01
**Scope:** Full static review of the workspace — all root modules, the V2–V12 trainer trees, the web app, test scripts, stored evaluation results, model artifact metadata, netlists, and the three governing documents (`context.md`, `codex_plan.md`, `review.md`).
**Method:** Every finding below was checked against the checked-in source and artifacts (file reads, diffs, model-zip metadata extraction, checksums, environment probing). Numeric results were audited, not re-simulated — the local machine has no working scientific Python environment (details in §8).

---

## 1. What the project is

A reinforcement-learning system that sizes a 5-transistor OTA in TSMC 65 nm. A PPO agent observes target specs (Gain, GBW, CL, Power), outputs transistor sizing parameters (L1, gm/Id1, L3, gm/Id3, Itail), and is scored by a fast analytical "physics engine" built from gm/Id lookup tables (LUTs) plus a hand-written 3-node small-signal MNA solve. Twelve model generations were trained on Kaggle/Colab; each iteration is a documented attempt to fix a failure mode in the reward function or environment design.

The honest current status: **the best model (V12) passes 1 of the 5 published regression tests** on the three reported requirements (gain, GBW, power), and it does so by outputting essentially **one fixed design for every target** (Itail ≈ 255 µA, L ≈ 0.78 µm, Gain ≈ 31.8 dB, Power ≈ 306 µW on all five tests). The project has not yet demonstrated goal-conditioned sizing, and no design has been validated against a transistor-level simulator.

## 2. Repository map

| Path | Contents | State |
|---|---|---|
| `core/`, `circuits/`, `optimizer/`, `tech_luts/lut_utils.py` | **Root package** — the original 7-parameter system (L1, gmid1, L3, gmid3, L5, gmid5, Itail), 7-action/16-obs delta-action env, finite M5 | Matches **only the V1 model**; incompatible with V2–V12 |
| `V2_Trainer/` … `V12_Trainer/` | Self-contained copies of the evolving 5-parameter system (5-action env, 8→15-obs) + Kaggle notebooks + kernel metadata + zips | V2–V12 env evolution verified intact |
| `web_app/main.py` | FastAPI service using the **root** 7-param package + the **V1** model | Broken paths; unconditional `"status": "success"` |
| `Test_Scripts/test_vN_model.py` (V2–V12) | Evaluation scripts; import from the matching `VN_Trainer` tree | Run only from repo root; Windows-only filename assumptions |
| `Evaluation_Results/*.md` | Stored result tables for V2–V12 | Gain/GBW/Power only — no PM/saturation/width verdicts |
| `Trained_Models/` (V1–V8) + root `universal_ppo_agent_65nm_v9–v12.zip` | Final models | Metadata verified (see §4) |
| `checkpoints/` | V7, V9 intermediate checkpoints (100k–500k) | V10–V12 checkpoints not retained |
| `Archive/` | Notebook build scripts, old notebooks, code-zip packaging | Historical |
| `test_specs/v2_tests/*.json` | The 5 regression cases | Sensible; note historical targets drifted (§6-H7) |
| `tech_luts/*.pkl` | NMOS/PMOS characterization LUTs — **2,763,639,830 bytes each** (2.76 GB) | Present at root; version-local copies are **0-byte placeholders** |
| `diagnostic_sweep.py`, `analog_ai_solver.py`, `generate_results_table.py` | Standalone tools | See §6-C6, §6-H8 |
| `ppo_ota_tensorboard/`, `ota-rl-model-v9.log` | Training telemetry | Log file is **empty**; V7–V12 event files are **byte-identical copies of one run** (md5 `d4e7a0df…`) |
| `context.md`, `codex_plan.md`, `review.md` | History diary, remediation plan, prior external review | Reviewed in §7 |

## 3. How the system works

```
TSMC 65nm LUTs (L, VGS, VDS, VSB grid)
   └─ LUT.lookup_vgs(): reverse gm/Id → VGS
   └─ DeviceModel.size_device(): gm/Id + L + ID → W and small-signal params
        └─ OTA5T.evaluate(): assigns node voltages (Vicm=Vocm=VDD/2 imposed),
           sizes M1/M2 and M3/M4, computes Power/SR/Swing/ICMR/saturation,
           runs MNAEngine.solve_ac() (3×3 complex MNA) over 100 log-spaced freqs
           → Gain, GBW (first 0 dB crossing), PM
             └─ OTA5tGymEnv: targets sampled per episode, cost = sum of squared
                one-sided relative violations, reward from cost
                  └─ PPO (SB3 2.9.0) trained on Kaggle; zip copied back
```

Key implementation facts (verified):

- **RL versions (V2–V12) use an ideal tail device.** In `V12_Trainer/circuits/ota5t.py:58`, M5 is `{'W': 0, 'gds': 0, 'VDSAT': 0, …}`. The 5-parameter action space has no L5/gmid5, so the trained agents never size a physical tail transistor; tail output resistance, headroom, area, and parasitics are absent from everything the models were trained and judged on. (The root 7-param version *does* size a finite M5 — but no RL model uses it.)
- **Matched devices are sized independently.** M1/M2 get separate `size_device` calls at different VDS (VDS1 = Vmirror−Vtail vs VDS2 = Vocm−Vtail), so their widths differ. The stored netlist `test_5t_ota_sized.scs` shows the consequence concretely: `M1 w=289.91u` vs `M2 w=292.53u` on a nominally matched pair (same for M3/M4: 27.28u vs 27.01u).
- **The DC operating point is imposed, never solved.** Branch currents are assumed Itail/2, node voltages derived from open-chain VGS lookups. There is no KCL check that the assumed voltages and currents are mutually consistent — Vmirror/Vtail errors go undetected.
- **Body effect is systematically mis-handled.** `DeviceModel` returns the LUT's `gmbs` under key `'gmbs'`, but `mna_engine.py:36-37` reads `m1.get('gmb', 0.2*m1['gm'])`. The key never matches, so the LUT value is *never used* and a flat 0.2·gm approximation is always substituted — even though a real gmbs lookup exists.
- **Invalid operating points are silently absorbed.** Negative VDS/VSB are clamped to 0.01/0.0 before lookup (`ota5t.py:51,55`); the interpolator is built with `bounds_error=False, fill_value=None` (`lut_utils.py:33-34`) so out-of-grid L/VGS/VDS extrapolates silently; the reverse gm/Id lookup sorts a possibly non-monotonic curve and `np.interp` clamps out-of-range targets to endpoints without flagging infeasibility.
- **Metric extraction is fragile.** GBW is the first sampled magnitude crossing over 100 points from 1 Hz–10 GHz, with phase interpolated in *wrapped* form (no unwrapping, no multiple-crossing handling, "no crossing" reported as GBW = 10 GHz). Dead zeroed terms (`m1['cgs']*0.0` in `mna_engine.py:41`) hint at unfinished capacitance modeling.
- **Because the brute-force sweep and the RL agent call the same `evaluate`,** the sweep's "solutions exist" result demonstrates feasibility *within this proxy only* — it cannot validate the physics itself.

## 4. Version evolution — verified from code

Environment diffs across the trainer trees confirm the documented progression (all 5-action):

| Ver | Obs | Action / Reward | Termination | Verified code state |
|---|---|---|---|---|
| V2 | 8 | delta (`±10 %` of range/step); `old_cost − new_cost` | cost < 10 | Root of the 5-param line |
| V3 | 8 | **byte-identical env to V2** (only notebook title differs) | same | Stochastic re-run, not a fix |
| V4 | 8 | Same scheme; power/width penalties ×1000 | same | **Penalties enlarged, not capped** |
| V6 | 8 | `min(·, 50)` caps + 10-pt "normalized cliffs" | same | First capping |
| V7 | 8 | 0–2000 nominal cost + hard 200-pt cliffs | same | |
| V9 | 15 | **Absolute** parameter output; `max(−1, 1 − cost/500)` | cost < 5 | Architecture rewrite |
| V10 | 15 | Smooth relative-squared cost; `max(−1, 1 − cost/100)` | cost < 5 | Survival-bonus bug present |
| V11 | 15 | `clip(−cost, −10, 0)` | **none** | |
| V12 | 15 | `−cost/100`, unclipped | **none** | Current model |

Model artifact metadata (extracted from the SB3 zips) matches: V1 = 16-obs/7-act (root system), V6 = 8-obs/5-act, V12 = 15-obs/5-act, 1,001,472 timesteps, SB3 2.9.0, net [256, 256], lr 1e-4, batch 512 — consistent with `context.md`.

Stored results confirm the documented outcomes: V10's survival-bonus exploit, V11's escape from the low-current safe zone (GBW 4–17 MHz → 61–731 MHz), and V12's collapse to a single non-conditional design (Itail 255.0–255.1 µA across all five tests).

## 5. Findings

### 5.1 Strengths worth preserving

1. **The gm/Id-LUT methodology is sound** and the LUTs are real and complete at root (2.76 GB each). Lookup → sizing → small-signal evaluation is the right skeleton for fast analog synthesis.
2. **`context.md` is a genuinely good failure-mode diary.** The V10 survival-bonus analysis and the V11 clipping-destroys-the-gradient diagnosis are correct, well-evidenced insights about reward design.
3. **The V9 architectural moves were right**: absolute (one-shot) parameter output and a richer 15-D observation are the correct formulation for a direct sizing proposal.
4. **`codex_plan.md` is an excellent remediation plan** — verifiable gates (G0–G6), oracle-first validation, hard verifier + fallback optimizer, supervised amortized inverse design as the primary path with PPO demoted to an ablation.
5. **Model lineage is preserved** with standard SB3 metadata, and the 5 regression cases are reasonable smoke tests.
6. The **web app is internally consistent** for its era: root 7-param package + V1 16-obs/7-act model + matching API schema.

### 5.2 Critical

- **C1. The circuit evaluator is not ground truth, and nothing validates it.** Imposed DC operating point, ideal M5, unmatched "matched" pairs, the gmbs/gmb bug (LUT body-effect data silently ignored), silent extrapolation/clamping, and fragile metric extraction (§3). No Spectre/ngspice correlation exists anywhere in the repo — the only netlist is one unparameterized sample. Every reported "pass" is a pass *against this proxy*.
- **C2. V12 is not goal-conditioned.** Stored results: one design for all five targets; only CL moves GBW (204M/204M/70M/576M/204M). Test 3 passes because its limits happen to bracket the compromise design. With 200-step episodes and absolute actions, a 2,048-step PPO rollout sees ~10 unique targets — too few to learn conditioning — and per-step actions are redundant with the state (the advantage signal carries little usable attribution).
- **C3. Training targets are not guaranteed feasible.** Gain/GBW/CL/Power are sampled independently over wide uniform ranges (V12 env, `_sample_target_specs`). The feasible region of 65 nm OTAs is a thin sliver of that 4-D box. Training on unlabeled infeasible requests rewards a "best average compromise" policy — which is exactly what V11/V12 converged to. There is also a train/test mismatch: training GBW ∈ 50–300 MHz, but test 1 requests 20 MHz (out-of-distribution).
- **C4. An unguarded reward catastrophe path.** Any exception in `evaluate` yields cost `1e9` → reward `−1e7` in V12 (`rl_environment.py:106-107` feeding `:156`, unclipped). Combined with the silent-extrapolation behaviors above, a single bad numeric state can inject a destructive policy/value update. No finite-value guard exists.
- **C5. Two divergent systems share one repo.** The root package (7-param, finite M5, delta env) is a different, older project that only the V1 model and the web app use. `optimizer/cost_function.py` (root) is a third cost definition used by nothing. The web API doesn't even accept CL as an input (it evaluates at a fixed 1 pF) yet reports `"status": "success"` unconditionally — no verification, no infeasibility handling.
- **C6. No reproducibility scaffolding.** No git, no README, no requirements/lockfile, no tests, empty training log. The V7–V12 TensorBoard event files are **byte-identical** (verified by md5), so they evidence a single run, not per-version training. Version-local LUT copies are 0-byte placeholders — anything that resolves `tech_luts/` relative to a trainer directory instead of repo root will crash with an unpickling error.

### 5.3 High

- **H1. Evaluation is statistically weak and incomplete.** One deterministic rollout per test; no seeds, no repeats, no held-out target set; the saved model is the *last* checkpoint, not the best on validation. The results tables omit PM, saturation margins, and width-limit verdicts entirely (the evaluation scripts never record PM), so "pass/fail" in `context.md` covers only 3 of the constraints the cost function trains on.
- **H2. Result tables are not comparable across versions.** Verified: the V2 table's targets (test 2 = 40 dB, test 1 GBW = 50 MHz, test 3 GBW = 250 MHz) differ from today's JSON specs (35 dB / 20 MHz / 50 MHz). Version-over-version narratives in `context.md` mix changed targets with changed code.
- **H3. Gymnasium seeding is not honored.** `reset()` never calls `super().reset(seed=seed)` and samples through the global `np.random` — runs cannot be reproduced even in principle from a stored seed.
- **H4. The deployment path cannot run as checked in.** `web_app/main.py` expects `universal_ppo_agent_65nm.zip` at repo root (it lives in `Trained_Models/`); `generate_results_table.py` posts to a server with a spec schema (`min_dc_gain_dB`, …) matching no checked-in file; `analog_ai_solver.py` expects `universal_ppo_agent_65nm_v6.zip` at root (absent → falls back to an equally absent V3) and passes a CL argument that only the version-tree `evaluate` accepts.
- **H5. Import resolution depends on how scripts are invoked.** `Test_Scripts/*` use `sys.path.append("VN_Trainer")` while root tools use `sys.path.insert(0, …)`. Run as scripts from repo root they resolve correctly to the version trees; launched from a notebook/interpreter rooted elsewhere they can silently resolve to the root package — whose 7-param `evaluate`/env are incompatible with every V2–V12 model. The prior review's stronger claim (root always shadows V10–V12) is **incorrect for plain script execution** (Python puts the script's own directory, not the CWD, on `sys.path`), but the fragility is real.
- **H6. Windows-only assumptions.** `test_v12_model.py` loads `'universal_ppo_agent_65nm_V12.zip'` while the file is `…_v12.zip` (lowercase) — works only on case-insensitive filesystems.
- **H7. The Spectre exporter produces a non-signoff netlist.** No PDK model/corner include, hardcoded VDD = 1.2 V and CL = 1 pF, bias applied as an ideal voltage source (0.4974 V) rather than the mirrored Itail, ambiguous differential drive (`mag=-0.5, phase=180`), no measurement statements, and exported M1≠M2 widths.

### 5.4 Medium / minor

- **M1.** Area accounting double-counts M2/M4 as exact copies of M1/M3 even though their computed widths differ, and (V12) M5 contributes zero area by construction.
- **M2.** `ICMR_min` is defined inconsistently: root = VGS1 + VDSAT5; V12 = VGS1 (ideal-M5 line).
- **M3.** `LUT.W` silently defaults to 5 µm if the pickle lacks a `W` key — a wrong reference width would quietly rescale every device.
- **M4.** Root dir clutter: empty `V12_output/`, `v5_temp/`, an empty `ota-rl-model-v9.log`, `__pycache__` trees, 5.5 GB LUTs loaded per process with no caching/mmap strategy.
- **M5.** `_evaluate_state` catches bare `Exception` and returns `None` perf; downstream observation becomes zeros — the agent cannot distinguish "invalid design" from "metrics are literally 0".

## 6. Fact-check of `context.md`

| Claim | Verdict |
|---|---|
| "Brute-force sweep of the entire design space" | **Overstated** — `diagnostic_sweep.py` evaluates at most 5×5×5×5×8 = 5,000 grid points per test |
| Sweep "proves the physics engine works correctly" | **Overstated** — it proves self-consistency and in-proxy feasibility; sweep and agent share the same `evaluate` |
| V4 "Capped maximum penalty using min()" | **Incorrect** — V4 multiplies two penalties ×1000 (`V4 …:64,76`); `min()` caps first appear in V6 |
| V2→V3 as separate technical fixes | **Incorrect** — environments byte-identical; V3 is a stochastic re-run |
| V7 "mathematically flawless" 0–2000 scale | **Unproven** — V7 retains hard 200-pt cliffs (`V7 …:70-87`); the Pareto-cancellation root cause is a plausible intuition, not an established proof |
| V11 survival fix "worked perfectly" | **Half-true** — it fixed the incentive, but produced a non-conditional policy with 1/5 primary-spec passes |
| V13 "completely solves" goal conditioning | **Plan only** — no V13 code/model exists in the workspace; one-step episodes increase target diversity but don't address feasibility, multimodality, or physics validity |
| LUT files "~1.25 GB each" | **Incorrect** — 2.76 GB each (5.5 GB total) |
| V9–V12 results, hyperparameters, obs/act dims | **Confirmed** against env code and model-zip metadata |
| V10 diagnosis, V11 clipping diagnosis, V12 fixed-design observation | **Confirmed** by stored result tables |

## 7. Relation to the existing documents

- **`codex_plan.md`** — I agree with it and it already contains the right plan; my findings mainly add evidence for its gates (e.g., G1's absence of any simulator correlation, G2's unlabeled infeasible targets, G6's unconditional `"success"` in the web API). Its judgment — *"Training another PPO version before completing steps 1–3 is unlikely to produce trustworthy progress"* — matches everything I verified.
- **`review.md`** (prior external review) — largely accurate and its physics findings all reproduce here (ideal M5, imposed DC op, gmbs/gmb mismatch, unmatched pairs, fragile PM extraction, placeholder LUTs, identical TB files, historical target drift). Two corrections to it:
  1. Its claim that V10–V12 test scripts "can import the wrong source tree" via `sys.path.append` shadowing is **wrong for plain script execution** — Python puts the *script's* directory (not the CWD) first in `sys.path`, so the version-tree modules win. The real risks are invocation-style dependence (H5), 0-byte local LUTs (C6), and case-sensitive filenames on Linux (H6).
  2. It described the workspace as lacking the version directories; the current workspace **does** contain `V2_Trainer`–`V12_Trainer`, `web_app/`, `utils/`, so several of its "not present in the workspace" statements are now outdated. Conversely, the exact `rl_environment.py` contents that trained V10–V12 *are* present and verified.

## 8. What I could not verify

- **Numerical replay of any result.** The local machine has no usable Python environment: `python` resolves to a Windows Store stub; Python 3.14 has no packages; a leftover `Python312` tree contains only Flask deps (no interpreter, no numpy/scipy/gymnasium/sb3). All training/eval demonstrably ran on Kaggle/Colab. Reported metrics were therefore audited for internal consistency, not regenerated.
- **LUT contents** — loading 5.5 GB of pickles was out of scope; grid extents, units, and polarity of the characterization data are unverified.
- **Whether each model zip's weights match its claimed training run** — plausible from metadata (timesteps, dims, dates), but not cryptographically tied to a specific Kaggle run (the shared TB event file makes V7–V12 training curves indistinguishable).

## 9. Recommendations (prioritized)

1. **Stop training PPO variants.** Twelve iterations demonstrate the loop "reward tweak → new failure mode" is saturated. The constraint is the environment formulation and the unvalidated proxy, not one more reward constant.
2. **Validate the physics first (codex_plan Phase 2).** Fix the matched-pair sizing, solve (or at least KCL-check) the DC operating point, wire up the existing `gmbs` lookup, add a finite M5 to the design vector, and correlate gain/GBW/PM/power against ngspice/Spectre on ~20 designs before trusting any pass/fail.
3. **Generate a real dataset (Phase 3).** Sample/Optimize the domain, label every request feasible/infeasible with a hard-constraint evaluator, and retrain *from data* (supervised, best-of-K or MDN) rather than from a hand-balanced scalar cost. This directly attacks the V11/V12 "average design" collapse.
4. **Add the hard verifier + fallback optimizer (Phase 4)** so any deployed system can only ever return verified designs — then a neural proposer becomes an accelerator, not the guarantee.
5. **Cheap hygiene wins now:** `git init` + commit; pin a `requirements.txt` (SB3 2.9.0, Python 3.11 per the Kaggle metadata); delete the 0-byte LUT placeholders or give them real copies; fix the `V12`/`v12` filename case; record PM/saturation/width verdicts in the evaluation tables; honor Gymnasium seeding; guard against non-finite rewards; archive V10–V12 checkpoints and real per-version TensorBoard logs.
6. **Retire or quarantine the root 7-param system and web app** until they target the same 5/6-parameter design vector as the models; remove `optimizer/cost_function.py` or make it the single shared cost.

## 10. Bottom line

This is a well-documented *learning project* that has successfully catalogued several real RL reward-design failure modes, wrapped around a fast analog proxy whose correctness is unproven and whose known defects (ideal tail, unmatched pairs, ignored body effect, imposed operating point) cap what any amount of training can prove. The single highest-value next step is not V13 — it is making the evaluator trustworthy, then switching to a data-driven, verifier-backed formulation as `codex_plan.md` already prescribes.

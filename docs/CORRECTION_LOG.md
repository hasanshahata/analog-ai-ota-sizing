# Correction Log

Execution record of `docs/codex_plan.md`, starting from the state audited in
`docs/PROJECT_REVIEW.md`. Newest entries at the bottom. Pre-reorganization
snapshot: git commit `912811d`.

## 2026-09-01 — Workspace reorganization (Phase 0/1 hygiene)

- Initialized git; full pre-reorganization state preserved as commit `912811d`.
- Removed: 9 zero-byte placeholder LUTs in version trees, 61 `__pycache__`
  trees, one empty log, two empty directories, and 5 byte-identical duplicate
  TensorBoard event files (V8–V12 copies of the V7 run).
- Reorganized:
  - `archive/versions/` — V2–V12 trainer trees (frozen history, off every
    import path)
  - `archive/legacy_root/` — old 7-parameter package, web app, old scripts,
    sample netlist
  - `archive/kaggle/` — notebook builders and Kaggle workflow
  - `models/` — all final agents v1–v12 + `checkpoints/` + unique
    `training_telemetry/`
  - `configs/test_cases/` — the five regression JSONs (unmodified targets)
  - `docs/` — context.md, codex_plan.md, PROJECT_REVIEW.md, DESIGN_CONTRACT.md
- Added: README.md, requirements.txt (SB3 2.9.0 / Py3.11 pins documented),
  pyproject.toml, .gitignore (5.5 GB LUTs excluded), per-directory READMEs.

## 2026-09-01 — Canonical package `analog_ai/` (Phase 1 + safe Phase 2 fixes)

Single importable package replacing the version-tree `sys.path` pattern:

| Fix | Legacy behavior | Canonical behavior |
|---|---|---|
| Matched pairs | M1/M2, M3/M4 sized independently → different widths (netlists show 289.9µ vs 292.5µ) | M2 reuses M1's geometry, M4 reuses M3's; each re-characterized at its own VDS; enforced in netlists too |
| Body effect | `gmbs` computed from LUT but read as `gmb` → 0.2·gm substituted everywhere | LUT `gmbs` wired into the MNA stamps |
| LUT domain | Silent extrapolation (`fill_value=None`), silent clamping of negative VDS to 10 mV | `DomainError` on out-of-grid queries; gm/Id reverse lookup on the post-peak decreasing branch (real TSMC data has near-peak wiggles); invalid operating points reject the design |
| GBW/PM extraction | First crossing, wrapped-phase interpolation, "no crossing" reported as 10 GHz | Unwrapped phase, explicit `gbw_valid=False` + NaN GBW when no crossing, denser default sweep (30 pts/decade) |
| Invalid designs | cost 1e9 → V12 reward −1e7, unguarded | Finite `COST_INVALID` (2000), counted in `info["invalid"]`, non-finite guard on reward |
| Seeding | `reset(seed)` ignored; global `np.random` | `super().reset(seed=seed)` + `self.np_random`; reproducibility covered by test |
| Verdicts | Markdown tables with 3 metrics, no PM/saturation/width verdicts | Hard-constraint verifier (`evaluation/constraints.py`): per-constraint normalized residuals, programmatic verdict, JSON records with provenance |
| RL formulation | 200-step episodes only | `one_shot=True` mode (contextual-bandit/V13 formulation); obs/action kept bit-compatible with V9–V12 models |
| Spectre export | Hardcoded VDD/CL, ambiguous `mag=-0.5`, unmatched widths, no PDK include | Parameterized CL/VDD/Vicm, matched geometry, `mag=0.5 phase=180`, optional PDK include/corner, save statements |

Known approximation kept deliberately (documented, not hidden): the DC
operating point is still imposed (Vicm = Vocm = VDD/2, branch currents =
Itail/2), but the evaluator now quantifies its self-consistency
(`pair_current_mismatch`, `mirror_current_mismatch` — measured ≈ −26 % on
real designs, i.e. the proxy's weakest assumption, motivating the Phase 2
nonlinear DC solve).

## 2026-09-01 — Test suite (Phase 1 exit gate)

37 tests, all passing locally (Python 3.11.16 venv):
- 35 unit tests on a **synthetic square-law LUT** (no 5.5 GB files needed):
  LUT domain/round-trip, matched-geometry invariance, MNA validated against
  the analytic single-pole solution (Av0 = gm·(ro2∥ro4), GBW = gm/(2πCL),
  exact single-pole PM), body-effect direction, two-pole PM extraction with
  phase unwrapping, constraint boundaries at exact limits, env seeding
  determinism, action-to-bounds mapping, finite invalid rewards, one-shot
  termination, netlist matched geometry.
- 2 integration tests against the **real TSMC LUTs** (auto-skip if absent):
  a hand-picked design fully verifies (Gain 31.4 dB, GBW 103 MHz, PM 75°,
  144 µW → PASS), and a genuinely infeasible bias point (gmid1 = 10 at
  L = 500 nm ⇒ Vtail < 0) is **rejected** instead of silently clamped.

## 2026-09-01 — Non-learning baselines (Phase 4) + model re-evaluation (Phase 6 partial)

Canonical evaluation of the five regression cases, all verdicts programmatic
(`evaluation_results/canonical/`):

| Source | Result | Meaning |
|---|---|---|
| `constant` (median of bounds) | **1/5 PASS** | trivial baseline |
| `model` (V12 via canonical verifier) | **1/5 PASS**, same fixed design on every test (W1 ≈ 81 µ, L1 ≈ 0.78 µ, 306 µW) | confirms PROJECT_REVIEW.md: the policy is goal-insensitive |
| `optimizer` (multi-start DE + verifier) | **5/5 PASS** (objectives 0.0000–0.0005, ≈ 12.5k evals each, ≈ 7 min/test on CPU) | a plain optimizer beats the trained model on every test, with visibly target-following designs (Itail 17–167 µA across tests); see gate G4 |

**Key finding:** under the canonical verifier, V12 and the constant baseline
pass exactly the same single test (test 3) with nearly identical metrics —
the trained policy provides no measurable value over outputting one fixed
design, while unconstrained optimization solves all five. This is the
quantitative case for switching to the Phase 3/5 data-driven formulation
(and for shipping the DE baseline as the production fallback).

## 2026-09-02 — LUT-based self-consistent DC solve (Phase 2.5)

**Motivation:** the project premise is that the LUTs *are* the Spectre
replacement (they are Spectre-characterized device data). The one place the
legacy chain broke that premise was the DC operating point: instead of using
the LUTs to find the circuit's actual bias, it imposed Vtail/Vocm and
Itail/2 branch currents and never checked KCL (measured mismatches of −23 %
to −46 %).

**Implemented** `analog_ai/circuit/dc_solver.py` + `OTA5T(op_point="solved")`:
- Outer fixed-point loop sizes W1/W3 so each device hits its gm/Id target at
  its own solved bias (matched-pair geometry preserved).
- Inner damped Newton solve drives the three KCL residuals (tail, mirror,
  output nodes) to zero using LUT-interpolated device currents, including
  body effect. Convergence failure or an out-of-domain solution marks the
  design invalid.
- The output node now settles where currents actually balance; achieved
  gm/Id, saturation margins, and the AC linearization all use the solved bias.

**Verified** (real TSMC LUTs): KCL residuals ≤ 6e-11 A; ~0.12 s per
evaluation; gm/Id targets hit exactly (e.g. 20.8 → 20.8); unit tests on the
synthetic LUT (7 new, 42 total unit + 3 integration, all passing).

**Impact vs. the imposed point:** metrics move materially — e.g. the DE
test-1 design's GBW is 27 MHz solved vs 21 MHz imposed; the hand design's
112 vs 103 MHz. All previously published numbers (V2–V12 tables and the
imposed-mode canonical results) carry that unquantified bias error; solved
mode removes it. `imposed` mode is retained for reproducing historical
comparisons. Canonical evaluations (`--op-point solved`) are now the default.

**Scope note updated** in `DESIGN_CONTRACT.md`: with the DC chain closed over
LUT data, no simulator remains *inside* the evaluation loop; a one-time
full-circuit AC check would only validate the small-signal modeling choices
(neglected capacitances, GBW/PM extraction), tracked as gate G1 if a
simulator/PDK is ever available.

## 2026-09-02 — DE baseline on the solved op point complete (Phase 4 wrap-up)

Tests 2–5 finished on the new PC (test 1 was run on the old machine before
the move; identical settings — seed 0, maxiter 30, popsize 20, 1 start).
Final table (`baseline_de_solved_summary.md`):

| Test | Verdict | Objective | Evals | Time (s) |
|---|---|---|---|---|
| test1_low_power | PASS | 0.0000 | 3106 | 939.2 |
| test2_high_gain | PASS | 0.0001 | 3226 | 651.6 |
| test3_heavy_load | PASS | 0.0003 | 3226 | 639.9 |
| test4_light_load | PASS | 0.0001 | 3226 | 647.7 |
| test5_balanced | PASS | 0.0002 | 3226 | 622.5 |

**Meaning:** the corrected canonical chain — Spectre-characterized LUTs +
KCL-solved DC operating point + hard-constraint verifier — now has a
non-learning 5/5 PASS reference in solved mode, matching the imposed-mode
result. The correction plan's premise holds end to end without a simulator:
nothing in the solved DC solve blocks feasibility. Learning-phase work
(Phase 3 onward) can now target this baseline.

**Machine note:** project moved to a new PC on 2026-09-02. `.git` did not
survive the move — the project is unversioned here (history only on the old
machine). Venv rebuilt (Python 3.11.9, numpy/scipy/gymnasium/pytest +
sb3 2.9.0/torch 2.14 CPU); all 45 tests re-verified on the new hardware.

## 2026-09-03 — Phase 3: feasibility-labeled dataset builder + pilot run

**Built** (`analog_ai/dataset/` + `scripts/build_dataset.py`, tested on the
synthetic LUT — 52 unit tests total, all passing):
- Sobol coverage of the 5-parameter design domain × CL grid {0.2, 1, 5 pF},
  evaluated through the canonical chain (solved op point, hard verifier);
- request derivation from structurally-passing designs only: feasible
  (achieved metrics relaxed 2–15 %), near-boundary (0–2 %), infeasible_derived
  (one dimension beyond the dataset's observed extreme at that CL);
- DE polish (canonical Phase 4 objective, `analog_ai/optimization/de_baseline.py`
  — the baseline moved out of the script into the package so all consumers
  share one implementation) on stratified feasible requests;
- DE certification of TARGET_RANGES-sampled requests → `infeasible_optimizer`
  hard negatives (best-effort design kept, DE stats recorded);
- region-based splits (10-bin normalized target space, whole regions to one
  split ⇒ no near-duplicate leakage; train/val/test 70/10/20);
- sharded Parquet + `manifest.json` (seed, versions, counts, SHA-256).

**Pilot** (`data/pilot/`, seed 0, solved mode, ~4 h wall on 1 core):
24,588 design rows (24,576 Sobol + 12 DE) and 33,150 request rows —
feasible 11,054 / near-boundary 11,046 / infeasible_derived 11,046 /
infeasible_optimizer 4; splits 23,737/2,219/7,194. Zero label-vs-verdict
inconsistencies (audited).

**Findings along the way:**
- 73 % of random designs are DC-solvable; only **44 % pass the structural
  constraints** (PM/saturation) — the feasible set is thin in the 5-D domain,
  confirming the sampling+polish design.
- Smoke run caught a labeling flaw (requests derived from structurally-failing
  designs can never verify) — fixed before the full run; the certification
  stage then exposed a second one (label taken from the design's structural
  verdict instead of the request verdict) — fixed with a regression test and
  the 4 affected pilot rows repaired in place.
- All 4 certification attempts on TARGET_RANGES corners (42–45 dB gain with
  2–4 pF loads) failed → those corners are optimizer-infeasible; the four
  hard negatives are exactly the rejector-training examples the plan wants.
- Solved-mode evaluation is ~0.37 s/design (3× the imposed-mode number);
  the sweep is single-core and embarrassingly parallel — parallelizing the
  builder is the identified 3× lever for scaled-up runs (GPU is not: the
  arrays are tiny and the code is sequential numpy).

## 2026-09-03 — Phase 5 PoC: supervised amortized inverse design (first working model)

**Pre-training repairs from the external review** (verified before training):
split leakage eliminated (splitter rewritten to assign whole design groups;
pilot re-finalized: 7,740/1,104/2,214 groups, zero overlap vs 4,436 shared
train-test designs before); negative labels renamed to evidence-based
`beyond_sample_envelope` / `unresolved_by_optimizer` (label schema v2);
pyarrow declared; LUT SHA-256s pinned into `configs/lut_manifest.json` +
dataset manifest; fresh git history (`main`, tag `oracle-v0.1.0+dataset-pilot`);
5-parameter ideal-tail scope decision recorded in DESIGN_CONTRACT.md.

**Model** (`analog_ai/surrogate/`): best-of-K proposal net (K=5, sigmoid
outputs mapped exactly onto DESIGN_BOUNDS) trained on positive rows only;
OOD/risk head on all rows; feature ranges fit on train split only, frozen
into checkpoints. 3 seeds trained (~4 min each); champion (seed 2) selected
by LUT-verified pass rate on 200 val requests (90.0% vs 87.5/86.5%).

**Held-out results** (1,500 test requests, verified against the canonical
oracle, solved mode; `surrogate_poc_summary.md`):

| Metric | Value |
|---|---|
| Raw head-0 pass | 67.9% |
| Best-of-5 pass | **85.3%** |
| After DE fallback (5 failures refined, all PASS) | 85.7% |
| Nearest-neighbor baseline | 57.7% |
| Constant-median baseline | 0% |
| DE on same requests (n=10) | 100%, ~1,732 evals / 212 s each |
| Model oracle cost | 5 evals / request (~350x cheaper than DE) |
| Risk head (n=3,712) | neg precision 1.000, recall 0.9995, acc 0.9997 |
| Five regression cases | **5/5** (3 raw, 1 best-of-K, 1 after fallback) |
| Worst normalized violation | 0.78 (95th pct 0.11) |
| Median power regret vs source design | -0.55 uW (model often draws less) |

**Gates:** G4 goal sensitivity PASSES (every request dimension moves the
design; constant baseline decisively beaten, 85.3% vs 0%). G6 honored
(statuses verified / verified_best_of_k / fallback_verified / unresolved,
never bare success). G3 regression criterion met (5/5); the >=95%
held-out-feasible bar is **not yet met** (85.7%) - honest gap.

**Known limitations:** failures concentrate at the target-space edges (the
same corners the optimizer also failed: 14.7% unresolved, worst violation
0.78); fallback coverage was budget-limited to 5 of ~220 failures, so the
85.7% number understates what full fallback would achieve; goal-sensitivity
sweeps verify mostly in mid-range (endpoints sit at extreme/unfeasible
requests). Scaling the dataset, parallelizing the builder, and widening
fallback coverage are the identified levers; finite-M5 and G1 correlation
remain the physical gates before any of that counts as 5T-OTA sizing.

## 2026-09-03 — Phases A-C of the execution plan: integrity, failure taxonomy, warm-start refinement

**Phase A (clean baseline).** 64 unit + 3 real-LUT integration tests pass;
LUT SHA-256s revalidated; dataset invariants recomputed (zero design-ID
overlap, zero label/verdict contradictions, zero duplicate rows, manifest
hashes match); the PoC pipeline reproduced under a new tag
(`surrogate_poc_repro`) **bit-exactly**: raw 67.87% / best-of-K 85.33%,
1500/1500 identical per-request statuses, identical case verdicts,
champion seed2 re-derived deterministically.

**Phase B (failure taxonomy**, `surrogate_failure_report.{json,md}`). All
220 unresolved requests re-verified with full residual vectors: dominant
failed constraint Power_max 157 (71%), GBW 55, Gain 6, widths 2; 132/220
requests have power limits < 50 uW; **218/220 sit within training support**
(nn distance < 0.05); zero all-invalid heads, zero selection failures,
median pairwise head distance 0.54 (heads diverse, not collapsed). Verdict:
the failures are near-misses inside training support, not a coverage or
capacity problem - so local repair, not more data, is the intervention
(codex_status_review_3.md Priority 1/2 confirmed).

**Phase C (neural warm-start local refinement**, `optimization/local_refine.py`).
Bounded Nelder-Mead around the best-ranked heads over a trust-region ladder
(+2/5/10% of normalized range), objective = total violation first (smooth)
with max-violation tie-break; the hard verifier alone accepts. Probing
showed Powell with a max-only objective stalls (46 evals, no progress);
Nelder-Mead + total-first repairs in ~127. New statuses:
`local_refinement_verified` / `global_fallback_verified` recorded separately.

**Benchmark (all 220 failures):**
- recovery: **220/220 local, 0 needed global DE, 0 unresolved**
- cost: median 506 oracle evals (p95 1055) vs ~1,732 for global DE;
  median 26 s per failure
- **end-to-end held-out: raw 67.87% -> best-of-K 85.33% -> 100.00% after
  local refinement** on the same 1,500 requests

**G3 (surrogate performance) is now met within the LUT proxy**: 100% on the
five regression cases and >= 95% (measured 100%) held-out feasible pass
after declared refinement, with usage and cost reported honestly. Exit
gate C of the execution plan met on all three criteria.

**Honest caveats:** every benchmark request derives from a verified design,
so a feasible witness exists by construction - 100% means the pipeline
*recovered all recoverable requests at materially lower oracle cost*, not
that arbitrary requests are feasible. Refinement searches around model
proposals using the oracle; on out-of-proxy requests the risk head (Phase E
work) remains the router. The ideal-tail and proxy-vs-Spectre caveats from
the previous entry are unchanged.

## 2026-09-03 — Phase E: risk-head boundary evidence complete

The full resumable certification run completed all 120 boundary requests and
wrote `risk_evidence_records.json`, `risk_evidence_report.json`, and
`risk_evidence_report.md` under `evaluation_results/canonical/`.

- Synthetic-OOD cohort: 2,211 cases, reported separately from feasibility
  evidence; 99.95% flagged at the 0.5 threshold.
- Certified-boundary cohort: 103 cases with usable evidence classes,
  comprising 78 verified-feasible and 25 unresolved-after-budget cases.
- Awaiting certification: 17 cases, excluded from certified metrics because
  the declared cap of 25 global-DE failures was reached.
- Boundary risk AUC: 0.9987.
- At risk threshold 0.5: flagged fraction 18.45%, precision 1.00, recall
  0.76.
- Flagged requests had 0% pipeline pass rate; unflagged requests had 92.86%
  pipeline pass rate.

Interpretation is deliberately limited: `unresolved_after_budget` means the
pipeline and declared global-DE budget did not find a solution; it is not a
proof of physical infeasibility. Phase E's exit gate is met because synthetic
OOD and optimizer-tested boundary evidence are separated and calibration,
threshold, coverage, and difficulty evidence are reported explicitly.

## 2026-09-04 — Phase F planning: F0.5 pre-implementation review submitted

Codex's finite-M5 execution plan
(`docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md`) requires a mandatory Opus review
gate (F0.5) before any implementation. The completed review is now appended
to that plan file: recommends the nested three-voltage solver with
`Vbias_tail` frozen inside the inner Newton solve; verifies residual signs
against the shipped ideal solver; proposes tolerances (KCL acceptance
<= 1e-9 A, width consistency 1e-6 relative, Id_M5 vs Itail 0.1%, gm/Id5
error <= 1e-3 1/V) plus a sizing-time `W5 > W_NMOS_MAX` rejection; resolves
the cdd/cgd double-counting question from the repo's own data-model
convention (`cdd` already includes the gate-drain overlap, so the tail stamp
uses `cdd` alone); proposes honest solved-point swing
(`(VDD - VDSAT4) - (Vtail + VDSAT2)`) and ICMR_min (`VGS1 + VDSAT5`)
definitions instead of the imposed-mode formulas; and requests five plan
changes, notably keeping the finite+solved evaluator guard until F2 plumbs
m5. Five questions for Hassan/Codex are recorded in the plan. No production
code changed; implementation remains NOT APPROVED pending discussion.

## Still open (updated 2026-09-04)

1. **Finite-M5 solved mode (Phase F)** — the next major physical gate and a
   prerequisite for a complete five-transistor sizing claim. F0.5 review
   submitted 2026-09-04; awaiting Hassan/Codex discussion and F1 approval
   (see the plan's decision record).
2. **Finite-M5 Cadence correlation** — the ideal-tail nominal correlation and
   v2 guard are complete; M5 and later PVT/signoff evidence are not.
3. **Phase E follow-up** — 17 boundary requests await certification under a
   raised global-DE cap; the declared Phase E exit gate is already met.
4. **Phase D (optional)** — K/diversity ablations; existing evidence shows no
   head collapse and therefore low expected gain.
5. **Phase H** — regenerate the seven-parameter dataset and retrain only after
   the finite-M5 oracle and correlation gates pass.

# Opus 5 Execution Plan — Verified 5T-OTA Inverse Design

> **Status note (2026-09-04):** Phases A-C and E are complete; nominal
> ideal-tail Cadence correlation and the tiered v2 deployment guard are
> validated; the web app is implemented. Historical baseline numbers below
> describe the starting point. Current execution continues with Phase F; see
> `docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md` and `docs/HANDOFF.md`.

## Mission

Continue the project from the current supervised proof of concept and turn it into a physically complete, independently validated 5T-OTA sizing system.

The current verified baseline is:

- Five-parameter, ideal-tail LUT proxy.
- Best-of-five surrogate pass rate: **85.3%** on 1,500 held-out feasible requests.
- Primary-head pass rate: **67.9%**.
- Nearest-neighbor pass rate: **57.7%**.
- Differential evolution passes all five regression cases.
- All five regression cases pass through surrogate plus limited fallback.
- Dataset splits have zero shared `design_row_id` values.
- The non-real-LUT test suite has **60 passing tests**.

This is a proof of concept, not yet a complete physical 5T-OTA solution. M5 is ideal in solved mode, full-circuit Spectre correlation is missing, and the 95% held-out pass gate has not been reached.

## Required reading before changing code

Read these files in order:

1. `docs/HANDOFF.md`
2. `docs/codex_status_review_3.md`
3. `docs/DESIGN_CONTRACT.md`
4. `docs/codex_plan.md`
5. `docs/CORRECTION_LOG.md`
6. `evaluation_results/canonical/surrogate_poc_summary.md`
7. `analog_ai/circuit/ota5t.py`
8. `analog_ai/circuit/dc_solver.py`
9. `analog_ai/evaluation/constraints.py`
10. `analog_ai/surrogate/evaluate.py`
11. `scripts/evaluate_surrogate.py`

Do not import production code from `archive/`. It contains historical implementations only.

## Operating rules

1. The hard constraint verifier is the sole authority for pass/fail.
2. Never report a raw network output as successful without verification.
3. Keep raw-model, best-of-K, local-refinement, and global-fallback results separate.
4. Preserve matched geometry: M1=M2 and M3=M4.
5. Reject out-of-LUT-domain evaluations; do not silently clamp or extrapolate.
6. Preserve all existing results and historical models.
7. Do not regenerate the large dataset until finite-M5 and correlation decisions are made.
8. Add tests with every behavioral change.
9. Record seeds, code version, LUT hashes, model settings, and result hashes.
10. Update `docs/HANDOFF.md` and `docs/CORRECTION_LOG.md` after each completed gate.

## Phase A — Establish a clean baseline

### Tasks

1. Confirm Git is available and inspect the working tree.
2. Run the non-real-LUT test suite:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_integration_real_luts.py
   ```

3. When enough RAM is available and no other LUT process is running, run the real-LUT integration tests.
4. Validate SHA-256 values in `configs/lut_manifest.json` against the two LUT files.
5. Recompute the following dataset invariants:
   - zero design-ID overlap across train/validation/test;
   - zero label/verdict contradictions;
   - no duplicate request/design pairs;
   - manifest hashes match the consolidated Parquet files.
6. Reproduce the current surrogate summary without overwriting it; use a new result tag.

### Exit gate A

- Tests pass.
- Dataset integrity checks pass.
- Existing 85.3% best-of-K result is reproducible within deterministic expectations.
- Any discrepancy is documented before further work.

## Phase B — Diagnose the 220 surrogate failures

Do this before changing the model or generating more data.

### Required analysis

For every unresolved held-out request, record:

- dominant failed constraint;
- all normalized residuals;
- whether the circuit evaluation was invalid;
- distance from the nearest training request;
- normalized target-space region;
- best candidate head;
- distance between the best candidate and its source/oracle design;
- number of heads that passed;
- requested Gain, GBW, CL, and power.

Generate tables grouped by:

- gain bins;
- GBW bins;
- load bins;
- power bins;
- dominant failed constraint;
- target-space boundary distance.

Create a machine-readable failure report plus a short Markdown summary under `evaluation_results/canonical/`.

### Questions this phase must answer

1. Are most failures small constraint misses that local refinement can repair?
2. Which specification causes the largest number of failures?
3. Are failures concentrated outside training support?
4. Are any requests likely proxy-infeasible?
5. Are particular heads redundant or collapsed?

### Exit gate B

- Every unresolved request has an assigned failure category.
- The next intervention is selected from evidence, not intuition.

## Phase C — Implement neural warm-start refinement

The current fallback starts global differential evolution over the complete design domain. Add a cheaper local stage centered on the best neural proposal.

### Recommended algorithm

For an unresolved request:

1. Rank heads by maximum normalized constraint violation.
2. Select the best two or three candidates.
3. Transform the bounded design variables to normalized `[0,1]` space.
4. Run a bounded local optimizer around each candidate.
5. Try progressively wider trust regions, for example:
   - ±2% of normalized range;
   - ±5%;
   - ±10%.
6. Stop immediately after hard verification passes.
7. If local refinement fails, invoke global DE.

Candidate algorithms to test:

- Powell with bounds;
- Nelder–Mead in transformed variables with explicit clipping;
- L-BFGS-B if the LUT proxy is numerically smooth enough;
- small-population differential evolution inside the trust region.

Use feasibility first. Minimize maximum positive normalized residual, then total violation, then power/area only after feasibility.

### Implementation targets

- Add reusable refinement code under `analog_ai/optimization/`.
- Keep full-domain DE as a separate fallback.
- Extend `analog_ai/surrogate/evaluate.py` with distinct statuses:
  - `verified`;
  - `verified_best_of_k`;
  - `local_refinement_verified`;
  - `global_fallback_verified`;
  - `unresolved`.
- Record optimizer method, initial head, trust region, evaluations, runtime, and final residuals.

### Required evaluation

Run local refinement on all 220 current failures, or on a stratified subset first if compute is constrained. Report:

- recovery rate;
- median and 95th-percentile oracle evaluations;
- median and 95th-percentile runtime;
- fraction requiring global DE;
- final end-to-end pass rate;
- remaining unresolved categories.

### Exit gate C

- At least 95% post-refinement pass rate on the existing held-out feasible set, or a documented explanation of why the remaining requests are not recoverable.
- Local refinement is materially cheaper than full-domain DE.
- No false-success status is possible.

## Phase D — Audit and improve best-of-K diversity

### Diagnostics

Measure:

- pass rate of each head;
- winning-head frequency;
- number of passing heads per request;
- pairwise normalized distance between heads;
- parameter-wise variance between heads;
- head collapse by target-space region.

Current evidence shows all five heads contribute, but 716/1,500 requests are passed by every head and 220 by none. Determine whether additional diversity targets the unresolved regions or merely spreads already successful predictions.

### Model experiments

Run controlled ablations:

1. K=1 baseline.
2. K=3.
3. K=5 current baseline.
4. K=8 or K=10.
5. K=5 with a small diversity regularizer.

Do not reward arbitrary design separation. Prefer diversity among feasible trade-offs. A candidate diversity term should be weak and monitored for degradation of pass rate.

Select models using LUT-verified validation pass rate, not regression loss.

### Exit gate D

- A statistically supported decision on K and diversity regularization.
- Improvement is measured across at least three seeds.
- Nearest-neighbor and current champion remain included as baselines.

## Phase E — Strengthen feasibility and OOD evidence

The nearly perfect risk-head result is not proof of real feasibility classification. Most negatives are synthetically beyond the observed sample envelope.

### Tasks

1. Generate substantially more independently sampled target requests.
2. Run optimizer certification on a stratified boundary sample.
3. Store outcomes as evidence classes, not mathematical truth:
   - `verified_feasible`;
   - `unresolved_after_budget`;
   - `beyond_sample_envelope`;
   - `invalid_or_out_of_domain`.
4. Separate OOD detection from feasibility prediction.
5. Evaluate calibration, precision, recall, and coverage at multiple rejection thresholds.
6. Test whether rejected requests are genuinely harder for the proposal and fallback pipeline.

### Exit gate E

- Risk metrics are reported separately for easy synthetic OOD cases and optimizer-tested boundary cases.
- No failed optimization run is described as proof of infeasibility.

## Phase F — Add a physical finite M5 to solved mode

This is the major circuit-model transition.

### Target design vector

\[
x=[L_1,gm/I_{D1},L_3,gm/I_{D3},L_5,gm/I_{D5},I_{tail}]
\]

### Required implementation

1. Extend the nonlinear DC solver to include finite M5 behavior.
2. Define how M5 gate bias is produced or supplied.
3. Include M5 current consistency in the DC equations.
4. Include M5 `gds`, `gmbs`, and capacitances in AC MNA.
5. Include M5 width, area, headroom, and saturation constraints.
6. Update netlist export to preserve the exact M5 implementation.
7. Update design bounds, schemas, evaluator output, optimizer, dataset tables, and surrogate output dimension.
8. Bump the oracle and contract versions.

### Required tests

- Seven-parameter arity and bounds.
- M5 LUT-domain rejection.
- M5 current/KCL consistency.
- M5 saturation boundary.
- M5 width limit.
- Tail-node AC stamp validation.
- Netlist round-trip including M5.
- Regression tests proving ideal-tail behavior remains reproducible as a historical mode.

### Exit gate F

- All five fixed cases are feasible under the finite-M5 solved oracle.
- KCL residuals satisfy the declared tolerance.
- Every returned transistor has finite physical geometry and operating data.

## Phase G — Full-circuit Spectre correlation

Do not claim physical correctness from LUT provenance alone. Device LUTs come from Spectre, but the circuit assembly and metric extraction are custom.

### Correlation set

Create at least 50–100 designs spanning:

- low/high current;
- low/high gm/Id;
- minimum/maximum channel lengths;
- light/heavy load;
- high-gain and high-GBW regions;
- saturation boundaries;
- nominal and difficult designs;
- invalid cases.

### Compare

- node voltages;
- device currents;
- `gm`, `gds`, `gmb`;
- gain;
- GBW;
- phase margin;
- power;
- slew rate, if kept as a product metric;
- swing and ICMR, if kept as product metrics.

Store raw simulator outputs and parsed measurements. Never manually copy only successful results.

Suggested initial tolerances:

- gain, GBW, power: ≤5% median relative error;
- node voltages: explicit absolute tolerance in volts;
- phase margin: explicit tolerance in degrees;
- no systematic optimistic bias near constraints.

### Exit gate G

- Declared correlation tolerances pass, or the proxy is recalibrated and versioned.
- All five regression designs pass nominal Spectre verification.

## Phase H — Regenerate the physical dataset and retrain

After finite-M5 and correlation gates pass:

1. Parallelize the dataset builder safely.
2. Generate a larger seven-parameter dataset.
3. Preserve group-exclusive splits.
4. Add boundary-focused sampling based on Phase B failure analysis.
5. Store multiple diverse feasible designs per target where possible.
6. Retrain K-head models over at least 5 seeds.
7. Compare against:
   - constant median;
   - nearest neighbor;
   - warm-start optimizer without neural proposals;
   - global DE;
   - the five-parameter PoC as a historical reference.

### Exit gate H

- At least 95% raw-or-local-refined pass rate on held-out feasible requests.
- 100% pass on the five fixed cases.
- Zero false-success responses.
- Neural warm starts reduce optimizer evaluations materially.

## Phase I — PVT, Monte Carlo, and deployment contract

After nominal Spectre correlation:

1. Add PVT corners.
2. Add supply and temperature ranges.
3. Run mismatch/process Monte Carlo.
4. Define required yield and design margins.
5. Add parasitics when layout is available.
6. Build the API only around verified statuses.

Required API flow:

```text
validate request
→ OOD/risk assessment
→ generate K proposals
→ LUT verification
→ local refinement
→ global fallback if authorized
→ Spectre verification when required
→ return design, margins, provenance, and status
```

The API must never return an unconditional `success` field for an unverified proposal.

## Immediate work package for Opus 5 (updated 2026-09-04)

Phases A-C and E, the ideal-tail Cadence campaigns, and the web remediation are
complete. The next work package is Phase F, governed by
`docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md`.

Opus 5 must first complete the F0.5 pre-implementation review inside that file,
discuss its solver and physical-model findings with Hassan/Codex, and stop.
Production implementation starts only after the Phase F decision record says
`Implementation authorization: APPROVED`. Do not resume the historical A-C
task list below or regenerate a dataset.

## Historical definition of done for the A-C iteration

The next iteration is complete only when it produces:

- code and tests for local refinement;
- a complete failure taxonomy;
- measured recovery rate and computational cost;
- updated raw/best-of-K/local/global pass rates;
- honest accounting of how many failures received each fallback;
- no regression in dataset isolation or hard verification;
- updated `HANDOFF.md` and `CORRECTION_LOG.md`.

## Final success definition

The overall project succeeds when:

- all five transistors are physically sized;
- the solved oracle correlates with full-circuit Spectre;
- every accepted design satisfies every hard constraint;
- held-out feasible pass rate reaches at least 95% after declared refinement;
- fallback usage and runtime are reported honestly;
- infeasible/OOD requests are rejected or marked unresolved;
- nominal regression designs pass Spectre;
- the chosen PVT/Monte Carlo yield target is met;
- every result includes reproducible model, LUT, oracle, and simulator provenance.

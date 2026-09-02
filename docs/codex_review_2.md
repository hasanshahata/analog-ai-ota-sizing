# 5T-OTA AI Sizing Project Review and Implementation Plan

Your idea is feasible, and the project already contains much of the required foundation. However, the current PPO model is not yet performing goal-conditioned OTA sizing. The correct path is:

**validated LUT circuit oracle → constrained optimizer → verified dataset → supervised inverse-design model → optimizer refinement → final verification**

I would pause further PPO training until the circuit oracle and dataset are complete.

## Current project assessment

The repository is in better shape than the historical V1–V12 experiments suggest:

- A canonical Python package now exists under `analog_ai/`.
- The MOS data comes from Spectre-characterized 65 nm LUTs.
- LUT interpolation has explicit domain checking.
- Matched pairs use identical geometry.
- A nonlinear KCL solver computes the operating point.
- There is a hard-constraint verifier, rather than relying on an RL reward to declare success.
- Differential evolution can already find feasible designs.
- The synthetic test suite passes: **42/42 tests**.
- The existing V12 policy passes only **1/5 cases** and produces almost the same design for every specification.

The last point is decisive: the trained PPO model learned a compromise design, not the mapping

\[
[\text{Gain},\text{GBW},C_L,\text{Power},\ldots]
\rightarrow
[\text{transistor dimensions and bias}]
\]

This is visible in `evaluation_results/canonical/model_solved_results.md`: its dimensions and approximately 306 µW power barely change among the five requests.

By contrast, the optimization baseline has already found passing LUT-level solutions for tests 1–3 in `evaluation_results/canonical/baseline_de_solved_records.json`. Tests 4–5 have not yet been completed in that file. The handoff document is slightly stale because it says only test 1 was finished.

## Most important technical gap

The canonical five-parameter design is:

\[
x=[L_1,\ gm/I_{D1},\ L_3,\ gm/I_{D3},\ I_{tail}]
\]

That means M5 is still an ideal current source in solved mode. It has zero width, output conductance, capacitance, and headroom requirements in the stored results.

For a real 5T OTA, this is not sufficient. M5 influences:

- DC gain through its output resistance
- common-mode behavior
- tail-node pole
- phase margin
- input common-mode range
- noise
- area
- saturation and PVT robustness

The production design vector should therefore become:

\[
x=[L_1,\ gm/I_{D1},\ L_3,\ gm/I_{D3},
L_5,\ gm/I_{D5},\ I_{tail}]
\]

The old five-dimensional model can remain as a historical baseline, but it should not define the final problem.

## Recommended system architecture

```text
Requested specifications
        ↓
Schema and feasibility/OOD check
        ↓
AI generates K candidate designs
        ↓
LUT + KCL circuit evaluator
        ↓
Hard constraint verifier
        ↓
Local constrained refinement
        ↓
Pass? ── yes → return verified design/netlist
  │
  no
  ↓
Global optimizer fallback
        ↓
Spectre signoff for final/research validation
```

The AI should be a fast proposal generator. It should not be the component that decides whether its own answer is correct.

## Recommended implementation plan

### Phase 1 — Freeze the real 5T-OTA problem

Before generating data, define exactly what constitutes a solution.

Required request inputs:

- Minimum DC gain
- Minimum GBW
- Load capacitance
- Maximum power
- Minimum phase margin
- Supply voltage
- Input common-mode voltage
- Minimum saturation margin

Strongly recommended additions:

- Slew-rate requirement
- Output swing
- Input common-mode range
- Maximum area
- Process corner and temperature

Required outputs:

- \(W/L\) for M1=M2
- \(W/L\) for M3=M4
- \(W/L\) for M5
- Tail current
- DC operating-point voltages and currents
- Achieved specifications and margins
- Verification status and oracle version

Use SI units internally. Only convert to µm, µA, pF, and MHz for reports.

### Phase 2 — Complete and validate the LUT oracle

Extend solved operating-point support to finite M5. Solve at least:

- Tail voltage
- Mirror voltage
- Output common-mode voltage
- M5 gate-bias voltage, if it is not externally fixed
- KCL at every internal node

Then audit the AC small-signal matrix. Confirm that it includes the required:

- \(g_m\), \(g_{mb}\), and \(g_{ds}\)
- \(C_{gs}\), \(C_{gd}\), \(C_{db}\), and relevant bulk capacitances
- Load capacitance
- Tail-device output conductance and capacitances
- Correct PMOS/NMOS signs
- Differential-to-single-ended gain convention

Do not assume a large saturation margin predicted by the LUT oracle proves correctness. The repeated, very high PM and nearly symmetric operating points in current results should be checked against transistor-level AC simulations.

Create approximately 50–100 frozen correlation designs:

- nominal designs
- short and long channel lengths
- weak, moderate, and strong inversion
- low and high current
- small and large load
- near-saturation-boundary designs
- feasible and invalid designs

For each, compare LUT predictions with Spectre:

- node voltages and branch currents
- transistor \(g_m\), \(g_{ds}\), \(g_{mb}\), capacitances
- gain
- GBW
- phase margin
- power
- slew rate

Suggested initial gate: median error below 5% for gain, GBW, and power, with separately declared limits for phase margin and node voltages.

### Phase 3 — Turn the optimizer into the ground-truth generator

Finish the solved differential-evolution benchmark for tests 4–5, then upgrade the optimizer to the seven-parameter design.

For each target request:

1. Run Sobol or Latin-hypercube sampling.
2. Retain promising valid designs.
3. Apply differential evolution or CMA-ES.
4. Refine feasible designs locally.
5. Save several diverse feasible solutions, not just one.

Use a feasibility-first objective:

\[
V(x,s)=\max_i \max(0,r_i(x,s))
\]

where \(r_i\) is a normalized constraint residual. Only after \(V=0\), minimize secondary objectives such as power, area, or robustness.

A weighted sum alone is dangerous because it permits one excellent metric to compensate for a failed hard requirement.

Store every evaluation in Parquet or HDF5, including:

- target specification
- seven design parameters
- widths calculated from the LUT
- performance metrics
- every constraint residual
- validity and convergence status
- LUT/oracle version
- optimizer seed
- evaluation time

A reasonable first dataset is:

- 20,000–50,000 target requests
- 5–20 candidate designs per request
- extra samples close to feasibility boundaries
- explicit infeasible and out-of-domain requests

### Phase 4 — Design the dataset correctly

Do not independently sample every target over a rectangular box and assume it is feasible. For example, maximum gain, maximum GBW, minimum power, and maximum load may be mutually impossible.

Build feasible targets from verified designs:

1. Sample or optimize a physical design.
2. Evaluate its achieved metrics.
3. Generate requests dominated by those achieved metrics.
4. Label the originating design as a feasible solution.
5. Tighten some requirements to create near-boundary examples.

Split the data by target-space regions, not random rows. Otherwise almost identical target/design points can appear in both training and testing.

Recommended splits:

- interpolation training set
- interpolation validation set
- boundary validation set
- held-out feasible test set
- infeasible/OOD test set
- the five fixed regression cases

### Phase 5 — Train a supervised inverse-design model

Use supervised learning as the primary model, not PPO.

Inputs:

\[
s=[A_{v,\min},\log GBW_{\min},\log C_L,
\log P_{\max},PM_{\min},V_{DD},V_{ICM},\ldots]
\]

Outputs:

\[
x=[L_1,gm/I_{D1},L_3,gm/I_{D3},L_5,gm/I_{D5},\log I_{tail}]
\]

Use output transforms such as sigmoid-to-bounds so the network can never produce parameters outside the valid domain.

Because several transistor sizings may satisfy the same request, use one of:

- K independent output heads with best-of-K training
- a mixture-density network
- a conditional normalizing flow

I recommend beginning with **5–10 candidate heads**. It is substantially simpler to train and debug than a normalizing flow.

The loss should combine:

- supervised distance to oracle designs
- diversity among candidate heads
- optional differentiable proxy constraint penalty
- preference for robust margin, low power, or small area

Checkpoint selection must use verified held-out pass rate, not regression loss alone.

### Phase 6 — Add inference-time refinement

A raw neural prediction will rarely land exactly on a tight constraint boundary.

For every request:

1. Generate K neural candidates.
2. Evaluate all candidates with the LUT oracle.
3. Rank them by maximum normalized violation.
4. Refine the best 2–3 candidates with a local optimizer.
5. Run hard verification.
6. If none pass, invoke differential evolution.
7. Return only a verified result.

This hybrid approach gives you both:

- neural-network speed
- optimizer reliability

The important performance measures will be:

- raw AI pass rate
- pass rate after local refinement
- fallback rate
- total LUT evaluations
- runtime
- power/area regret relative to the optimizer
- false-success count, which must be zero

### Phase 7 — Spectre and robustness validation

The LUT system can replace repeated transistor evaluation during search, but a LUT-based analytical circuit evaluator should still be validated at complete-circuit level.

For final candidate designs:

- export an exact Spectre netlist
- simulate nominal DC, AC, stability, and transient response
- compare measurements with LUT predictions
- test process corners
- vary VDD and temperature
- run mismatch/Monte Carlo
- later include extracted parasitics

The final label should distinguish:

- `proxy_verified`
- `spectre_verified`
- `fallback_verified`
- `infeasible`
- `unresolved`

## Practical milestone sequence

I would execute the project in this order:

1. Finish optimizer tests 4–5 using the solved oracle.
2. Add finite-M5 support to the solved DC and AC evaluator.
3. Create 50–100 Spectre correlation cases.
4. Fix/calibrate the oracle until the correlation gate passes.
5. Implement the versioned dataset generator.
6. Generate a small 2,000-target pilot dataset.
7. Train a K-head supervised model.
8. Measure raw prediction, refinement, and fallback performance.
9. Scale the dataset only after the pilot demonstrates goal sensitivity.
10. Run held-out, PVT, Monte Carlo, and Spectre evaluation.
11. Wrap the verified pipeline in an API or UI.

## Definition of success

The project should be considered successful when:

- All five fixed cases pass using finite M5.
- LUT predictions correlate acceptably with Spectre.
- Raw AI proposals clearly outperform a constant and nearest-neighbor baseline.
- AI plus local refinement passes at least 95% of held-out feasible requests.
- Global fallback resolves most remaining feasible requests.
- Infeasible/OOD requests are reported honestly.
- No unverified design is returned as successful.
- The system produces a complete, simulator-ready \(W/L\) and bias solution.

The existing detailed roadmap in `docs/codex_plan.md` is fundamentally sound. The highest-value next coding task is finite-M5 solved-oracle support; the highest-value experimental task is Spectre correlation. Generating a large ML dataset before those two steps would risk training the model to reproduce errors in the present proxy.

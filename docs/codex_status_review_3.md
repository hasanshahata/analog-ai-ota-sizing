# Current Project Status Evaluation

## Current status

The project has now reached a genuine **supervised inverse-design proof of concept**.

The strongest current result is:

- **85.3%** verified pass rate from the best of five neural proposals.
- **67.9%** pass rate from the primary proposal alone.
- **57.7%** for nearest-neighbor retrieval.
- **0%** for the constant-median baseline.
- **5/5** fixed regression cases pass when limited fallback is allowed.
- **60/60** non-real-LUT tests pass.
- Dataset split leakage has been corrected.
- Git is restored and the working tree appears clean.

This is meaningful progress: unlike PPO V12, the supervised model responds to requested specifications and clearly beats simple baselines.

## Project maturity by component

| Component | Status | Assessment |
|---|---|---|
| LUT device model | Implemented | Good research foundation |
| Solved DC operating point | Implemented | KCL-consistent for ideal-tail model |
| Hard verifier | Implemented | Correct acceptance architecture |
| Differential-evolution oracle | Implemented | 5/5 regression cases |
| Dataset pipeline | Implemented | Pilot complete and reproducible |
| Dataset splits | Repaired | Zero design-ID overlap |
| Supervised proposal model | Implemented | First successful PoC |
| Risk/OOD model | Implemented | Promising but labels are synthetic |
| Local proposal refinement | Not implemented | Current fallback restarts global DE |
| Finite M5 solved model | Not implemented | Major physical limitation |
| Spectre circuit correlation | Not completed | Major validity gate |
| PVT/Monte Carlo | Not started | Required for signoff |
| Production API | Not started | Appropriate at this stage |

## Verified improvements since the previous audit

### Dataset leakage is fixed

The rebuilt dataset contains:

- 33,150 request rows
- 23,202 training rows
- 3,312 validation rows
- 6,636 test rows

Measured design-ID overlap:

- Train ↔ validation: **0**
- Train ↔ test: **0**
- Validation ↔ test: **0**

That removes the most serious flaw found in the previous review.

### Labels now use more honest names

The negative classes are now:

- `beyond_sample_envelope`
- `unresolved_by_optimizer`

This is more scientifically accurate than calling them proven infeasible.

### Reproducibility improved

The project now has:

- LUT SHA-256 hashes in `configs/lut_manifest.json`
- Dataset output hashes
- Training seeds
- Model checkpoints
- Frozen normalization ranges
- Champion-selection records
- Declared `pyarrow` dependency
- Restored Git history/tagging

### The first supervised model works

The best-of-K network generates five bounded candidates. Every proposal remains inside the legal five-parameter design domain.

Detailed held-out results:

| Outcome | Requests |
|---|---:|
| Head 0 passes | 1,018 |
| Another head passes | 262 |
| No head passes | 220 |
| Total | 1,500 |

Per-head pass rates range from 64.5% to 73.3%, confirming that useful behavior is distributed across the heads.

For 716 requests, all five heads pass. For 220, none pass.

These results support the claim that the network learned a useful target-to-design relationship.

## Important limitations in the reported results

### 1. The “after fallback” result is incomplete

Only **5 of the 220 failed requests** were sent through DE fallback. All five passed, increasing the aggregate result from 85.3% to 85.7%.

Therefore, 85.7% is not the full hybrid-system pass rate. It means:

> The model passes 85.3%, and five selected failures were successfully recovered.

A full fallback evaluation could potentially approach 100%, but that has not been measured. The summary should call this “after five fallback trials,” not simply “after DE fallback.”

### 2. There is no local refinement yet

The current `refine()` function invokes differential evolution across the entire design bounds. It does not use the neural prediction as a warm start.

This misses one of the primary advantages of inverse design. The intended flow should be:

\[
\text{neural proposal}
\rightarrow
\text{bounded local refinement}
\rightarrow
\text{global DE only if needed}
\]

A local method may turn many of the 220 near-misses into verified designs using tens of oracle calls instead of roughly 1,700.

### 3. The 95% gate has not been met

Current best-of-K pass rate:

\[
85.3\%
\]

Target:

\[
\geq95\%
\]

This is a 9.7 percentage-point gap, corresponding to approximately 145 additional successful designs per 1,500 requests.

The worst normalized violation is 0.78, while the 95th percentile is approximately 0.11. This suggests many failures are close enough for local repair, but a small number are substantially outside the learned feasible region.

### 4. Risk-classifier performance is overly optimistic

The risk model reports almost perfect accuracy. That should not yet be interpreted as real feasibility detection.

Most negative examples were constructed beyond the sampled envelope, so they are likely easy to distinguish from derived positive examples. Only four requests carry optimizer-based negative evidence.

The classifier currently distinguishes the dataset-generation rules very well. It has not demonstrated reliable classification of genuinely infeasible analog specifications.

A better risk evaluation requires:

- Many more optimizer-tested requests
- Hard feasible/infeasible cases near the boundary
- Independent target generation
- Calibration curves
- Precision/recall at operational thresholds
- Separate OOD and feasibility metrics

### 5. It remains an ideal-tail model

The complete learned output is still:

\[
[L_1,\ gm/I_{D1},\ L_3,\ gm/I_{D3},\ I_{tail}]
\]

M5 is not physically sized in solved mode. Consequently, the current result should be described as:

> Goal-conditioned sizing of a 5T-OTA proxy with an ideal tail-current source.

It is not yet complete physical sizing of all five transistors.

### 6. Spectre correlation remains open

The project’s device data originates from Spectre, but the assembled circuit equations and extracted metrics have not been validated against full-circuit simulations.

The following remain unverified at circuit level:

- DC operating-point voltages
- Complete small-signal gain
- GBW
- Phase margin
- Parasitic poles
- Slew rate
- Swing
- ICMR

Until correlation is completed, `verified` means “verified by the LUT proxy,” not “Spectre-verified.”

## Recommended next steps

### Priority 1: Implement neural warm-start refinement

For each failed candidate:

1. Select the head with the smallest maximum constraint violation.
2. Create tight bounds around its predicted design.
3. Run a low-budget local or population optimizer.
4. Expand the bounds only if refinement fails.
5. Use full-domain DE only as the final fallback.

Measure:

- Recovery rate
- Oracle calls
- Runtime
- Remaining violation
- Percentage requiring global fallback

This is likely the fastest route from 85.3% toward the 95% target.

### Priority 2: Diagnose the 220 failures

Partition them by dominant violated constraint:

- Gain
- GBW
- Power
- Phase margin
- Saturation margin
- Width
- Invalid DC solution

Also plot failure rate against:

- Gain request
- GBW request
- Load
- Power limit
- Distance from training support

This will reveal whether the primary problem is data coverage, model capacity, or infeasible requests.

### Priority 3: Improve best-of-K diversity

The best-of-K setup is useful, but there is no explicit diversity term. Consider adding:

\[
L=L_{\text{best-of-K}}+\lambda L_{\text{diversity}}
\]

Use a modest diversity term so heads represent different trade-offs rather than arbitrary parameter differences.

Measure head utilization and pairwise design distance. An MDN is unnecessary until the simpler K-head architecture has been fully exploited.

### Priority 4: Expand optimizer-certified evaluation

Run DE on:

- All 220 surrogate failures, if compute permits
- Or at least a stratified sample of 50–100 failures
- Boundary cases from each constraint
- Requests classified as high-risk
- Requests outside the current sampled envelope

This separates:

- Model failures on feasible requests
- Proxy-infeasible requests
- Optimizer failures
- Out-of-distribution requests

### Priority 5: Decide the M5 transition

Before building a much larger dataset, implement finite-M5 support in the solved operating-point model.

The final design vector should become:

\[
[L_1,gm/I_{D1},L_3,gm/I_{D3},L_5,gm/I_{D5},I_{tail}]
\]

Then regenerate the dataset and retrain the model. Otherwise, substantial computation will be invested in learning a design abstraction that must later be replaced.

### Priority 6: Perform Spectre correlation

Create a frozen set of representative designs and compare proxy versus Spectre for:

- Node voltages and currents
- Gain
- GBW
- Phase margin
- Power
- Device operating parameters

Only after this gate passes should the project use stronger language such as “automatic OTA sizing” without the “proxy” qualification.

## Bottom line

The project has crossed an important threshold: it now has a working goal-conditioned learned proposal model. The 85.3% verified best-of-K result is credible within the present dataset and LUT proxy, and it decisively improves over PPO, constant output, and nearest-neighbor retrieval.

The current system is best described as:

> A successful five-parameter, ideal-tail, LUT-oracle inverse-design proof of concept with 85.3% raw verified coverage and a reliable global optimization fallback.

The shortest path forward is:

1. Analyze the 220 failures.
2. Implement neural warm-start local refinement.
3. Evaluate fallback on a representative larger sample.
4. Add finite M5.
5. Correlate the complete circuit with Spectre.
6. Regenerate a physically complete dataset and retrain.

The project is no longer blocked on whether AI can learn the mapping—it can. The remaining challenge is turning that proof of concept into a physically complete and independently validated sizing system.

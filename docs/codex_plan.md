# Codex Remediation and Validation Plan

## Objective

Build a reproducible conditional OTA sizing system that returns a verified design for feasible requests, rejects or explains infeasible requests, and correlates with transistor-level simulation. The plan deliberately separates proposal quality from correctness: the learned model makes fast proposals; independent verification and constrained optimization provide the acceptance guarantee.

## Success gates

Do not call a model “working” until these gates pass:

- **G0 — Reproducibility:** clean install, deterministic smoke test, pinned dependencies, one canonical package/config, LUT checksums, and no `sys.path` hacks.
- **G1 — Physics correlation:** DC/AC metrics and device operating points correlate against Spectre (or another selected signoff simulator) on a frozen design set within agreed tolerances.
- **G2 — Oracle feasibility:** every training/evaluation target has a stored oracle result and explicit feasible/infeasible label.
- **G3 — Surrogate performance:** 100% pass on the five regression cases and at least 95% pass on a large held-out feasible target set after verification/fallback; report worst-case normalized violation and oracle regret.
- **G4 — Goal sensitivity:** controlled target changes cause physically sensible changes in output; a constant-action baseline is decisively beaten.
- **G5 — Signoff:** all returned regression designs pass all nominal constraints in transistor-level simulation, then meet the agreed PVT/Monte Carlo yield target.
- **G6 — Safe deployment:** the API returns `verified`, `fallback_verified`, or `infeasible/unresolved`; it never returns unconditional `success` from a raw network prediction.

Numerical tolerances and yield targets must be agreed before training. Suggested starting points are ≤5% median error for gain/GBW/power versus Spectre on an in-domain correlation set, ≥95% held-out feasible target pass after fallback, and zero false-success responses.

## Phase 0 — Freeze the contract and evidence

1. Create one versioned specification schema containing:
   - Gain_min_dB, GBW_min_Hz, CL_F, Power_max_W;
   - fixed or requested PM_min_deg and saturation-margin minimum;
   - geometry/LUT-domain limits;
   - optional SR, swing, ICMR, area, PVT, and yield requirements.
2. Decide whether SR/swing/ICMR are product requirements. They exist in root/web code but not V2–V12 targets; ambiguity must be removed.
3. Freeze the five current JSON cases without silently changing historical targets. Add a separate version field and immutable test-set manifest.
4. Archive each existing model with hashes for model, source commit/snapshot, LUTs, environment config, dependency versions, seed, training log, and evaluation output.
5. Amend `context.md` so hypotheses are labeled as hypotheses and the brute-force results are described as proxy-grid evidence.

**Exit:** a machine-readable contract and immutable artifact manifest exist.

## Phase 1 — Make one reproducible codebase

1. Create a single installable package, for example `analog_ai/`, with `devices`, `circuit`, `oracle`, `models`, `evaluation`, and `export` modules.
2. Replace V2–V12 copied source trees with read-only experiment configs/manifests. Preserve history, but stop importing from version directories.
3. Pin Python, NumPy, SciPy, Gymnasium, Stable-Baselines3/PyTorch, and test tools in a lockfile. Record the V12 SB3 2.9.0/Python 3.12 environment for compatibility.
4. Add LUT metadata and SHA-256 validation. Fail fast for missing, placeholder, wrong-polarity, or wrong-grid files.
5. Centralize bounds, normalization, target sampling, cost/constraints, and model paths. Remove the unused divergent cost function.
6. Add structured experiment configs with seed, train/validation splits, optimizer settings, simulator revision, and output directory.
7. Fix all tests and applications to import the installed package. Update the solver and web application to the same current design-vector definition.
8. Add CI/static tests that do not require loading the full LUT, plus an opt-in integration test for LUT/simulator runs.

**Exit:** one command builds/tests the project and one command reproduces an evaluation from a declared artifact.

## Phase 2 — Repair and validate the circuit oracle before training

1. Inspect LUT axes and units. Enforce bounds on L, VGS, VDS, VSB, gm/Id, current density, and width; return a typed invalid-design result instead of extrapolating silently.
2. Fix the `gmbs`/`gmb` interface and add device-level interpolation tests at grid points and between grid points.
3. Preserve matched geometry:
   - size M1 once and use the same W/L for M2;
   - size M3 once and use the same W/L for M4;
   - compute the resulting currents at their actual biases rather than re-sizing each branch to force equality.
4. Restore a finite M5 with L5/gmId5 (or a justified fixed design), output resistance, capacitances, headroom, area, and saturation checks.
5. Implement a nonlinear DC operating-point solve for Vtail, Vmirror, Vout/current balance. Reject non-convergence and invalid operating regions.
6. Re-derive the AC small-signal matrix from the topology and add KCL/unit tests. Include all required gm, gmb, gds, and capacitance stamps with consistent sign convention.
7. Make metric extraction robust: denser/adaptive sweep, phase unwrapping, multiple unity-crossing handling, explicit no-crossing status, and interpolation tests on known transfer functions.
8. Repair the Spectre exporter:
   - include the selected PDK model/corner;
   - export identical matched geometries;
   - use the requested CL, VDD, Vicm, and bias current;
   - define a valid differential AC source;
   - generate DC, AC, stability, transient/SR, and operating-point measurements.
9. Generate a frozen correlation suite spanning boundaries and nominal designs. Compare LUT oracle versus Spectre for node voltages, branch currents, gm/gds/caps, gain, GBW, PM, power, SR, swing, and saturation.
10. Calibrate or replace approximations until G1 tolerances pass. Keep separate names for `fast_proxy` and `spice_oracle`; never call the fast proxy ground truth.

**Exit:** the fast oracle is demonstrably correlated in a declared domain, and every proposal can be independently simulated.

## Phase 3 — Build real ground-truth design data

1. Replace the claim of exhaustive search with reproducible sampling/optimization:
   - Sobol or Latin-hypercube coverage of the design domain;
   - multi-start constrained differential evolution/CMA-ES/Bayesian optimization;
   - local refinement near feasible/Pareto boundaries.
2. Store every design, metrics, constraint residual, validity flag, oracle version, and simulator cross-check in a versioned dataset (Parquet/HDF5, not only Markdown).
3. Derive target requests from verified feasible designs. This guarantees that the feasible training distribution has labels. Separately generate deliberately infeasible and near-boundary requests.
4. Because inverse design is one-to-many, store multiple diverse feasible designs per target or a Pareto set (power, area, margin, robustness).
5. Split by target regions, not random rows, to prevent near-duplicate leakage. Maintain:
   - train set;
   - interpolation validation set;
   - boundary validation set;
   - held-out feasible test set;
   - held-out infeasible/OOD set;
   - five fixed regression cases.
6. Validate the five claimed sweep counts by rerunning a versioned sweep and saving raw output. Report exactly which constraints and grid values define each count.

**Exit:** a traceable oracle dataset covers the operating domain and distinguishes feasible from infeasible requests.

## Phase 4 — Establish non-learning baselines

1. Implement a hard constraint evaluator that returns each normalized residual and a Boolean pass/fail.
2. Implement multi-start constrained optimization as the correctness baseline and production fallback. It must optimize lexicographically: feasibility first, then power/area/robustness.
3. Measure success rate, evaluations, runtime, and oracle regret on all frozen sets.
4. Add simple baselines:
   - nearest feasible design in normalized target space;
   - constant median design;
   - per-request warm-start local optimizer.
5. Use these to detect whether a neural model genuinely uses goals. If it cannot beat nearest-neighbor plus refinement, do not deploy it.

**Exit:** the project has a reliable, slower solver and meaningful baselines before ML training begins.

## Phase 5 — Train the conditional proposal model

### Recommended primary path: supervised amortized inverse design

1. Input only normalized request/context variables and an explicit feasibility/domain indicator. Use log scaling for GBW, CL, power, current, and widths where appropriate.
2. Predict bounded design variables with transforms that exactly respect geometry/gmId/current limits.
3. Handle multiple valid designs using one of:
   - K diverse candidate heads with best-of-K loss;
   - a mixture-density network;
   - a conditional normalizing flow.
4. Train on oracle designs, rank candidates by hard constraint residual plus secondary objective, then refine the best candidates with the constrained optimizer.
5. Train a separate feasibility classifier/calibrated uncertainty model. OOD or low-confidence requests go directly to fallback optimization.
6. Select checkpoints on held-out constraint pass rate after verification, not training reward.

This approach directly learns the target→design mapping, uses every oracle label efficiently, and avoids PPO value/advantage noise.

### Optional RL ablation: corrected V13

If PPO must be retained for research comparison:

1. Use one-step episodes and target-only observation. Call `super().reset(seed=seed)` and use Gymnasium’s RNG.
2. Sample only from a declared mixture of feasible, boundary, and labeled-infeasible requests.
3. Use multiple parallel environments and fixed validation callbacks.
4. Return finite, bounded rewards for invalid evaluations and log invalid-rate separately.
5. Prefer a feasibility-first reward such as negative maximum normalized constraint violation, with a small secondary power/area term only after feasibility. Alternatively use explicit Lagrange multipliers per constraint.
6. Compare PPO against direct supervised learning using the same oracle-evaluation budget. Do not assume one-step PPO is best simply because it fits the contextual-bandit interpretation.
7. Run at least 5–10 seeds and report median/worst performance and confidence intervals.

**Exit:** a selected proposal model beats all baselines on frozen validation data and shows measurable goal sensitivity.

## Phase 6 — Evaluation that can support a guarantee

1. Replace Markdown-only scripts with a shared evaluator that records:
   - requested specs;
   - complete design including M5;
   - every achieved metric;
   - every normalized constraint residual;
   - LUT-domain/DC-convergence status;
   - raw proposal pass, post-refinement pass, fallback pass;
   - runtime and oracle evaluations;
   - simulator result and corner.
2. Compute programmatic verdicts for all constraints. A design passes only if every required residual is ≤0.
3. Run target-conditioning tests: vary one target at a time and verify expected response trends and non-constant action variance.
4. Report raw-model pass rate separately from verifier/fallback pass rate. Never hide fallback usage.
5. Report feasible-set coverage, infeasible rejection precision/recall, worst normalized violation, power/area regret versus oracle, and calibration/OOD metrics.
6. Evaluate all seeds on at least thousands of held-out targets, including boundary and adversarial combinations.
7. Run Spectre nominal validation for every fixed regression case and a representative held-out sample.
8. Add PVT corners, supply/temperature/load variation, extracted parasitics when available, and Monte Carlo mismatch/process analysis. Optimize required design margins to meet the chosen yield target.
9. Generate a signed evaluation manifest with code/LUT/model/simulator hashes.

**Exit:** G3–G5 pass with reproducible evidence.

## Phase 7 — Production integration

1. API flow:

   `validate request → feasibility/OOD check → generate K proposals → fast hard verification → local refinement → SPICE verification when required → fallback global optimization → return status`

2. Return full constraint margins and provenance with every design.
3. Refuse unsupported PDK/corner/range requests explicitly.
4. Cache verified results keyed by request, oracle version, LUT hash, and simulator corner.
5. Export the exact verified geometry/bias/load to the netlist; re-read simulator measurements before labeling success.
6. Monitor proposal pass rate, fallback rate, OOD rate, and simulator disagreement. Retrain only through a versioned dataset/model release.

**Exit:** only independently verified designs are exposed as successful.

## Minimal test suite to add immediately

- LUT axis/unit/checksum and out-of-domain rejection tests.
- gm/Id reverse-lookup monotonicity/ambiguity tests.
- M1=M2 and M3=M4 geometry invariants.
- DC KCL residual and convergence tests.
- `gmbs` propagation test.
- Known one-/two-pole transfer-function tests for gain/GBW/PM extraction.
- Environment observation/action shape and dtype tests.
- Seed reproducibility and target distribution tests.
- Invalid-evaluation finite reward test.
- Constraint-verdict tests at exact boundaries.
- Model/environment metadata compatibility test before inference.
- Import-resolution test proving the canonical package is loaded.
- Regression tests for all five JSON cases with complete metrics.
- Netlist round-trip test comparing exported geometry and requested CL/bias.

## Recommended implementation order

1. Contract and repository consolidation.
2. Physics fixes and Spectre correlation.
3. Hard verifier and constrained optimizer baseline.
4. Versioned feasible/infeasible dataset.
5. Supervised multi-candidate proposal model.
6. Optional one-step PPO ablation.
7. Full held-out/PVT/Monte Carlo evaluation.
8. Verified API and netlist integration.

Training another PPO version before completing steps 1–3 is unlikely to produce trustworthy progress. Even if its proxy score improves, the current evaluator and harness cannot establish that the resulting OTA is physically correct.

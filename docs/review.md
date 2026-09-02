# Analog AI Optimization — Technical Review

## Executive conclusion

The project has a useful gm/Id LUT-based exploration prototype and the model history shows genuine learning about reward-design failure modes. However, no trained version currently demonstrates a reliable, goal-conditioned OTA sizing system. V12 passes only one of the five published tests on the three reported requirements (gain, GBW, and power), produces essentially one design for every request, and has not been validated against a transistor-level simulator.

The main blocker is not simply another PPO reward bug. There are four coupled problems:

1. **The circuit evaluator is not yet ground truth.** It forces a DC operating point, independently sizes devices that must be matched, uses an ideal tail source, and contains small-signal/modeling inconsistencies. The brute-force sweep proves feasibility only inside this same proxy.
2. **The learning formulation is poorly matched to the task.** Absolute one-shot sizing is a contextual inverse-design problem, not a 200-step control problem. Independently sampled targets are not guaranteed to be jointly feasible.
3. **Evaluation is not reproducible or complete.** V10–V12 can import the wrong source tree, reported tables omit PM/saturation/width verdicts, no seeds or held-out validation are used, and historical tests changed after V4.
4. **The repository has no single executable source of truth.** Root code, version folders, notebooks, web application, models, and tests describe incompatible 7-parameter and 5-parameter systems.

Therefore, the statements in `context.md` should be treated as a development diary, not verified ground truth. The safe path is to validate and repair the circuit oracle first, generate traceable feasible design data, train a conditional proposal model, and always verify/fallback-optimize its output. RL can remain an experiment, but should not be the primary guarantee mechanism.

## What the project contains

The repository implements a 65 nm 5-transistor OTA sizing workflow:

- LUT interpolation for NMOS and PMOS device quantities (`tech_luts/lut_utils.py`).
- A gm/Id-to-width sizing layer (`core/device_model.py` and version copies).
- A hand-written 3-node AC MNA approximation (`core/mna_engine.py`).
- An OTA performance wrapper (`circuits/ota5t.py` and a different 5-variable version under V2–V12).
- Gymnasium environments and Stable-Baselines3 PPO training notebooks.
- Twelve archived model generations, five JSON specification cases, evaluation scripts/tables, a diagnostic grid sweep, a Spectre netlist exporter, and a FastAPI web application.

V2–V12 share identical circuit, MNA, device, LUT, and standalone cost-function code. Only `optimizer/rl_environment.py` and notebook training settings materially evolve. This is important: changes in the later published results primarily reflect reward/environment changes and stochastic training, not improved circuit physics.

## Evidence and audit limitations

This review used the checked-in source, model ZIP metadata, evaluation tables, test specifications, notebook builders, and diagnostic sweep. Full numerical replay was not possible because the workspace's Python executable could not be launched during the audit; several version-local LUT placeholders also report zero accessible bytes. That does not affect the static defects below, but it means the published metric values were audited rather than independently regenerated.

There is no Git repository metadata available at the workspace root, no dependency lock/requirements file, and no automated unit-test suite. The six TensorBoard event files checked under V7–V12 are byte-identical, so they do not provide version-specific training evidence.

## Findings by severity

### Critical: the analytical evaluator is not circuit ground truth

`diagnostic_sweep.py` searches a grid of 5 L1 values × 5 gm/Id1 values × 5 L3 values × 5 gm/Id3 values × 8 currents: at most 5,000 candidates per test before filtering. It is not a sweep of the “entire design space,” which is continuous. Its reported feasibility is useful for this grid and this proxy only.

More importantly, the sweep and the RL environment call the exact same `OTA5T.evaluate` implementation. Agreement cannot establish that the physics engine is correct. There is no checked-in Spectre/ngspice comparison, no DC operating-point correlation, no AC waveform comparison, no PVT corners, and no Monte Carlo validation.

Specific circuit-model defects are:

- **Matched devices are not kept matched.** `V12_Trainer/circuits/ota5t.py` calls `size_device` separately for M1 and M2 at different VDS values, allowing different W values. It does the same for M3 and M4. A physical differential pair and 1:1 current mirror require shared geometry. The subsequent MNA response therefore represents a topology that the intended matched netlist does not necessarily implement.
- **The DC operating point is imposed rather than solved.** `Vicm` and `Vocm` are fixed at VDD/2. Branch currents are assumed to be Itail/2. There is no nonlinear KCL solve that demonstrates those node voltages and currents are mutually consistent for the shared transistor sizes.
- **V2–V12 use an ideal tail source.** M5 has zero width, length, gm, gds, and capacitance. Its finite output resistance, headroom, area, noise, and parasitic poles are absent. Saturation and width constraints consequently exclude the actual fifth transistor. The root/web implementation uses a different, seven-variable finite-M5 model, so deployment and training are different systems.
- **Body transconductance is silently ignored.** `device_model.py` returns `gmbs`, while `mna_engine.py` requests `gmb` and therefore always substitutes `0.2*gm`.
- **Small-signal capacitance stamping is an undocumented approximation.** Several device capacitances and terminal couplings are omitted or placed without a derivation/test. There is no KCL/unit test against a SPICE linearized operating point.
- **Phase margin extraction is fragile.** It takes the first sampled magnitude crossing from only 100 logarithmic points over ten decades and interpolates wrapped phase directly. It does not unwrap phase, detect multiple crossings, or distinguish “no crossing below 10 GHz” from a real 10 GHz GBW.
- **Out-of-grid interpolation can extrapolate silently.** `RegularGridInterpolator(..., bounds_error=False, fill_value=None)` extrapolates for L/VGS/VDS/VSB outside the characterization grid. `VDS` is clamped to 10 mV in places, but all lookup coordinates are not explicitly checked against LUT support.
- **Reverse gm/Id lookup assumes a usable monotonic curve.** Sorting a potentially noisy/non-monotonic gm/Id curve and using `np.interp` can select a nonphysical branch and clips out-of-range targets without reporting infeasibility.

These defects invalidate any claim that a passing proxy design is guaranteed to pass transistor-level simulation.

### Critical: the evaluation harness can load the wrong version

Tests V2–V9 use `sys.path.insert(0, version_dir)`, but V10–V12 use `sys.path.append(...)`. When launched from the repository root, the root packages (`circuits`, `optimizer`, `core`, and `tech_luts`) precede the appended version directory. The root environment expects seven actions and sixteen observations, whereas the V12 model artifact records five actions and fifteen observations. The root `OTA5T.evaluate` also does not accept the `CL=` argument used by V12 tests.

Thus the published V10–V12 evaluation scripts are not cleanly reproducible from the documented workspace layout. Imports must use a single installed package or explicit versioned modules, never `sys.path` manipulation.

### Critical: V12 is not goal-conditioned in practice

The V12 table shows nearly invariant output:

- L1 ≈ 0.78 µm for every test.
- L3 ≈ 0.78 µm for every test.
- Itail ≈ 255 µA for every test.
- Power ≈ 306 µW for every test.
- Gain ≈ 31.8 dB for every test.

Only CL changes the simulated GBW. Test 3 passes because its limits happen to contain this compromise. Tests 1, 2, 4, and 5 fail power and/or gain. This is direct evidence of conditional-policy collapse.

The `context.md` diagnosis of target starvation is plausible: a single environment with 200-step episodes supplies only about ten new goals per 2,048-step rollout. However, the claim that temporal-difference advantage is necessarily “pure noise” is too strong. The process is still a definable MDP; it is simply redundant and badly aligned because every action directly replaces the entire design. V13’s proposed one-step environment fixes redundancy, but does not by itself guarantee conditional learning, target feasibility, simulator fidelity, or multimodal inverse design.

### High: target sampling creates unknown and possibly infeasible specifications

Gain, GBW, CL, and power are sampled independently from broad uniform ranges. Five feasible hand-picked tests do not prove that every Cartesian combination in those ranges is feasible. For example, simultaneous high gain, high GBW, heavy load, and minimum power is likely much harder than any marginal range suggests.

Training on infeasible goals causes the optimal policy to learn compromises. Because no feasibility flag or distance-to-feasible-frontier is modeled, a constant “average good” design can minimize expected loss. The target distribution should come from verified feasible designs (or explicitly label infeasible requests), and evaluation must separate feasible interpolation, boundary, and infeasible cases.

There is also a distribution mismatch: training GBW is sampled from 50–300 MHz, while test 1 requests 20 MHz. Historical V2–V4 evaluation tables use different targets from the current JSON files (for example, 40 dB rather than 35 dB in test 2). Version-to-version comparisons are therefore not consistently apples-to-apples.

### High: reward/cost definitions do not enforce a clear contract

The active environment cost and `optimizer/cost_function.py` are different implementations; the latter is unused by the versioned RL environments. This invites silent drift.

V10–V12 use squared one-sided relative violations plus small power/area terms. Problems include:

- A single scalar weighted sum cannot guarantee each hard constraint; it permits compensation and depends on arbitrary scaling.
- Failure paths return cost `1e9`. V12 converts that to reward `-1e7` without clipping or finite-value checks, risking destructive policy/value updates.
- Area is both a hard width limit and a soft geometry objective, but M5 area is zero and M2/M4 area is approximated as 2×M1 and 2×M3 even though their computed widths can differ.
- The reward is flat with respect to spec overshoot except for power/area. That is acceptable for constrained optimization, but produces many valid outputs for one goal; a deterministic neural policy trained only from scalar reward has no stable label selecting among modes.
- There is no explicit feasibility-first lexicographic rule or primal-dual constraint handling.

For a guarantee, every proposed design must be passed through a hard Boolean verifier. Reward magnitude alone is not a verifier.

### High: evaluation reports are incomplete and statistically weak

The Markdown result tables report only gain, GBW, CL, power, W1/L1, W3/L3, and Itail. They do not report or verdict:

- phase margin;
- saturation margin for each device;
- NMOS/PMOS width limits;
- finite-M5 headroom and size;
- numerical/LUT-domain validity;
- swing, ICMR, or slew rate if those are intended requirements;
- simulator correlation.

Tests use one deterministic policy run and do not specify seeds, repeated initial states, confidence intervals, a held-out target set, or an oracle comparison. Training saves the last model rather than selecting a best model on a fixed validation suite. `reset(seed=...)` does not call `super().reset(seed=seed)` and samples through global `np.random`, so Gymnasium seeding is not honored.

The five fixed tests are useful smoke tests but cannot measure generalization across a four-dimensional target domain. “Pass” must be calculated programmatically for every constraint, not inferred from a partial table.

### High: the repository’s runtime paths are mutually incompatible

- Root `optimizer/rl_environment.py` is a 7-action, 16-observation, delta-action environment, unlike V9–V12.
- `web_app/main.py` uses that root environment and expects `universal_ppo_agent_65nm.zip` at the root, but that file is stored under `Trained_Models` and is an older model.
- `analog_ai_solver.py` explicitly uses V6 and falls back to V3, not the current model.
- Version directories duplicate almost all code and contain placeholder/incomplete LUT artifacts.
- The Spectre exporter hardcodes CL=1 pF and VDD=1.2 V, has no PDK model include, and uses a bias voltage derived from the proxy rather than reproducing/verifying target Itail. Its differential source definition uses a negative magnitude together with 180° phase, which is ambiguous/wrong for many simulators.

There is no dependable path from a V12 action to a signoff-ready, verified netlist.

## Version-by-version assessment

| Version | What the checked-in code changed | Observed result | Review of failure cause |
|---|---|---|---|
| V1 | No complete versioned trainer/evaluation artifact is present. Root/archive code reflects an earlier 7-variable formulation. | No auditable result. | Claims about V1 cannot be verified from a corresponding source/model/evaluation set. |
| V2 | 5 actions, 8 observations; delta actions; reward is old cost minus new cost; unbounded, severely mismatched penalties; ideal M5. | Highly inconsistent outputs; only some individual specs met. | Blind observation of actual design/constraints, local navigation, huge reward scale, and incomplete physics all contribute. |
| V3 | Environment code is byte-for-byte identical to V2; training configuration is also effectively the same. | Different stochastic outcome, not a systematic improvement. | There is no code-level V3 fix to attribute. Differences are consistent with unseeded PPO variance/artifact handling. |
| V4 | Adds a 150 µm global width constraint and increases power/width quadratic weights to 1,000. | Large power/width failures remain. | Contrary to `context.md`, V4 does not cap exploding penalties; it makes two unbounded terms much larger. |
| V5 | Relaxes power weight, separates 150 µm NMOS/500 µm PMOS limits, trains 1M steps. | Some GBW wins, severe power/width/gain failures. | Reweighting moves the compromise but leaves unbounded discontinuous scales and blind/delta architecture unchanged. |
| V6 | Caps most violation components, changes width limits to 250/750 µm, uses normalized cliffs. | Policy collapses to 10 µA; GBW fails all tests. | The safer low-current basin is real. Also, `old_cost-new_cost` rewards only pathwise improvement and the observation still hides design and constraint state. |
| V7 | Replaces huge global multiplier with a nominal 0–2000 cost and hard 200-point cliffs; lower learning rate. | Closer on some cases but no full reliable solution. | The “exact cancellation” explanation in `context.md` is not generally proven because nonlinear gm/Id physics, area, PM, saturation, and clipping also affect cost. It is a useful local intuition, not a mathematical root-cause proof. |
| V8 | Multiplies gain/GBW soft penalties and power/width cliffs by 10. | Mostly worse/low-current behavior. | V8 strengthens discontinuities; it does not change architecture or physics. The diagnostic sweep only disproves infeasibility inside the proxy grid. |
| V9 | 15D observation, absolute actions, absolute reward; larger network/lower LR. Keeps V8 cliffs and early success termination. | All cases choose 10 µA; GBW fails. | Avoiding cliffs plus positive per-step reward encourages a safe basin. The architecture improves observability, but repeated absolute actions remain redundant. |
| V10 | Smooth relative squared cost and reward `max(-1, 1-cost/100)`; early termination remains. | Much closer GBW on tests 3–5, but only partial compliance. | The positive-reward/episode-length incentive is a valid defect. Reward saturation at -1 also discards information for high costs. |
| V11 | Negative reward clipped to [-10,0], no early termination. | High-current, nearly fixed design; only test 3 meets reported gain/GBW/power. | Clipping makes broad cost regions indistinguishable; sparse goal diversity and infeasible independent targets also push toward an average design. |
| V12 | Removes reward clip with `-cost/100`; trains 1M steps. | Still one fixed design; test 3 only passes reported primary limits. | Scaling alone cannot fix the 200-step contextual mismatch, infeasible goal distribution, multimodal mapping, or lack of validation/model selection. Extreme exception rewards are now unsafe. |
| Proposed V13 | One-step episode and target-only observation; no implementation/model is present. | Not evaluated. | Correct direction for an absolute-action policy, but PPO is unnecessary for a static inverse problem and one-shot episodes alone provide no guarantee. |

## Problems in `context.md` that should be corrected

The document is valuable as history, but the following statements should not be used as factual acceptance evidence:

- “Entire design space” — the checked-in sweep is a 5,000-point coarse grid per test.
- “This proves the physics engine works correctly” — it proves only self-consistency/feasibility in the same proxy.
- V4 “capped maximum penalty” — caps appear in V6, while V4 increases unbounded weights.
- V2 and V3 as separate technical fixes — their checked-in environment and training configuration are identical.
- V7 “mathematically flawless” and exact Pareto cancellation — neither is established by analysis or controlled ablation.
- V11 survival fix “worked perfectly” — it fixed one incentive but produced a non-conditional policy and only one reported full primary-spec pass.
- V13 “completely solves” goal conditioning — it increases target diversity but does not solve feasibility, inverse-design multimodality, optimizer choice, or physics validity.
- LUT size “~1.25 GB each” — the root files are reported as approximately 2.76 GB each (about 5.5 GB total), consistent with the web-app message but not the context text.

## What is worth preserving

- gm/Id LUT use is a sensible way to reduce the analog design search space.
- Dynamic CL and goal inputs are necessary for a conditional solver.
- The five hand-authored tests provide useful regression cases.
- The diagnostic sweep demonstrates that at least some target regions are feasible under the current proxy.
- The V9 move to absolute actions correctly recognizes that long delta navigation is unnecessary if the desired product is an immediate sizing proposal.
- The V10 normalization is much safer than V2–V8’s raw unit-dependent penalties.
- Model ZIPs contain standard SB3 metadata and distinct weights; V12 records 1,001,472 timesteps, a 15D observation space, a 5D action space, and a [256,256] policy.

## Required definition of “works well”

A defensible claim should mean all of the following:

1. The request is declared feasible by a validated oracle or correctly rejected as infeasible.
2. The returned design passes every hard constraint in the analytical verifier.
3. It passes an independent transistor-level simulator using the exported matched geometry and actual bias/load.
4. It passes a predefined PVT/Monte Carlo robustness policy, not only TT nominal.
5. On a frozen held-out feasible target set, pass rate and oracle regret meet explicit thresholds.
6. The production API never labels an unverified proposal as successful; it invokes a constrained optimizer fallback or returns a clear failure.

No neural model can by itself guarantee those conditions. A verifier plus fallback optimizer can guarantee that only passing designs are returned within the validated domain; simulator signoff is required for circuit-level confidence.

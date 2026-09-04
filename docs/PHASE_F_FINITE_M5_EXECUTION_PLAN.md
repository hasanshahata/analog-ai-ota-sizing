# Phase F Plan - Finite-M5 Solved 5T OTA

**Created:** 2026-09-04

**Revised for Opus 5 handoff:** 2026-09-04

**Status:** plan ready for discussion; implementation is not authorized yet

**Current production mode:** solved ideal-tail OTA remains frozen and supported

## Purpose

Phase F replaces the ideal tail-current source research abstraction with a
physical NMOS M5 in the LUT-based solved oracle. The finite-tail design vector
is:

```text
x7 = [L1, gmid1, L3, gmid3, L5, gmid5, Itail]
```

For an accepted design, the oracle must return:

```text
M1/M2: W1, L1
M3/M4: W3, L3
M5:    W5, L5
tail bias: Vbias_tail
nominal requested current: Itail
solved node voltages, device operating points, constraints, and provenance
```

The gate-bias generator is outside the sized OTA boundary. Its power, area,
noise, and mismatch are not included. This exclusion must remain visible in
every finite-mode result and exported netlist.

## What Phase F does not do

- It does not replace or modify the existing five-parameter checkpoints.
- It does not expose finite mode through the web app before Cadence validation.
- It does not inherit the ideal-tail GBW guard or claim that it applies to M5.
- It does not regenerate the dataset or train a seven-output model.
- It does not add PVT, Monte Carlo, noise, mismatch, or layout parasitics.
- It does not silently extrapolate or clamp outside a LUT domain.

Dataset regeneration and learning belong to Phase H, after the finite oracle
and its Cadence correlation are accepted.

## Verified starting point

- The nominal ideal-tail pipeline is validated and remains the production web
  default.
- Current gates are 139/139 non-real-LUT tests and 3/3 real-LUT integration
  tests passing.
- `analog_ai/config.py` already defines the seven parameter names and bounds.
- imposed operating-point mode can already produce finite-M5 geometry.
- `analog_ai/circuit/mna.py` already has a tail-node M5 `gds`/`cdd` stamp.
- constraints already include an existing finite M5 in the NMOS width maximum.
- `analog_ai/circuit/ota5t.py` deliberately rejects
  `tail_device="finite", op_point="solved"` with `NotImplementedError`.
- `evaluate_design()` still serializes only five design parameters.
- finite netlist export currently emits a zero-volt M5 gate source rather than
  a solved `Vbias_tail`; this must not be treated as complete.

## Required reading for Opus 5

Read these files in order before proposing changes:

1. `docs/HANDOFF.md`
2. `docs/DESIGN_CONTRACT.md`
3. this document
4. `docs/CORRECTION_LOG.md`
5. `analog_ai/config.py`
6. `analog_ai/devices/lut.py`
7. `analog_ai/devices/device_model.py`
8. `analog_ai/circuit/dc_solver.py`
9. `analog_ai/circuit/ota5t.py`
10. `analog_ai/circuit/mna.py`
11. `analog_ai/evaluation/constraints.py`
12. `analog_ai/evaluation/evaluator.py`
13. `analog_ai/utils/netlist.py`
14. `analog_ai/optimization/de_baseline.py`
15. `analog_ai/optimization/local_refine.py`
16. `tests/test_dc_solver.py`, `tests/test_ota.py`, and `tests/test_mna.py`

Do not import production behavior from `archive/`; it is historical evidence.

## Mandatory discussion gate F0.5

Opus 5 must not edit production code immediately. Its first action is to append
a review to **Opus 5 pre-implementation review** at the bottom of this file.
That review must:

1. restate the proposed solver equations and confirm their signs;
2. compare the recommended nested solve with a four-unknown solve;
3. identify numerical failure modes and how they will fail closed;
4. state exactly how M5 capacitances are interpreted and stamped;
5. review the proposed swing and ICMR definitions instead of copying the
   imposed-mode formulas without proof;
6. list every file it expects to change in F1;
7. list any disagreement or requested plan change;
8. stop and wait for discussion/approval.

No implementation begins until the decision record says
`Implementation authorization: APPROVED`. Approval of this planning commit is
not implementation authorization.

## Proposed finite-tail DC formulation

### Fixed design inputs

```text
L1, gmid1, L3, gmid3, L5, gmid5, Itail, VDD, VICM
```

### Solved circuit voltages

```text
z = [Vtail, Vmirror, Vout]
```

For each candidate `Vtail`, derive the tail gate voltage from the reverse LUT:

```text
Vbias_tail = lookup_vgs(nch, L5, gmid5, VDS=Vtail, VSB=0)
```

With W1, W3, and W5 frozen inside a Newton iteration, use actual LUT drain
currents in all equations:

```text
Rtail   = Id_M1 + Id_M2 - Id_M5
Rmirror = Id_M1 - Id_M3
Rout    = Id_M4 - Id_M2
```

The existing damped Newton/backtracking strategy may be reused, but residual
evaluation must not hide out-of-domain points with permanent clamping.

### Outer geometry-consistency loop

At the current solved voltages:

- size W1 for `Itail/2` at the M1 target gm/Id and bias;
- size W3 for `Itail/2` at the diode-connected M3 target gm/Id and bias;
- size W5 for `Itail` at `gmid5`, `VDS=Vtail`, `VSB=0`;
- repeat the inner KCL solve until all widths and residuals converge.

The final verification must re-evaluate M5 using the returned **fixed** W5 and
**fixed** `Vbias_tail`. It must demonstrate:

```text
Id_M1 + Id_M2 = Id_M5
Id_M1 = Id_M3
Id_M4 = Id_M2
Id_M5 approximately equals Itail
gmid_M5 approximately equals gmid5
```

This distinction matters: the DC design procedure may calculate the bias, but
the AC model treats that final bias node as AC ground. It does not track the
tail voltage dynamically.

### Alternative Opus must evaluate

A four-unknown formulation can solve
`[Vtail, Vmirror, Vout, Vbias_tail]` with the three KCL residuals plus
`gmid_M5 - gmid5 = 0`. Opus must compare conditioning, residual normalization,
domain handling, and testability. The nested three-voltage formulation is the
current recommendation because it reuses the strict reverse-LUT operation and
avoids mixing ampere and dimensionless residuals in one unscaled Jacobian.

## Physical validity and failure contract

An evaluation is invalid unless all of these hold:

- the design vector has exactly seven finite values inside canonical bounds;
- `Itail > 0` and `CL > 0`;
- `0 < Vtail, Vmirror, Vout, Vbias_tail < VDD`;
- every final LUT coordinate is strictly inside its characterized domain;
- W1, W3, and W5 are positive, finite, and inside hard width limits;
- final KCL residual magnitude is below the declared tolerance;
- final width relative change is below the declared tolerance;
- M5 current error and achieved-gm/Id error are explicitly bounded;
- all five devices meet any requested saturation requirement;
- GBW is a real first 0 dB crossing within the configured sweep.

Temporary trial-point clipping for Newton line search is permitted only if it
is reported as a diagnostic and the final solution passes strict domain checks.
Convergence failure, singular Jacobian, infeasible reverse lookup, and domain
failure must produce deterministic invalid records rather than NaNs or false
success.

Before implementation, Opus must propose numeric values and justification for:

- KCL tolerance;
- outer width-consistency tolerance;
- `Id_M5` versus `Itail` tolerance;
- achieved M5 gm/Id tolerance;
- maximum inner and outer iterations.

## Work packages

### F1 - solved DC kernel

Primary files:

- `analog_ai/circuit/dc_solver.py`
- `analog_ai/circuit/ota5t.py`
- `tests/test_dc_solver.py`
- new focused finite-solver tests if separation improves clarity

Tasks:

1. Add an explicit finite-tail solver path without changing the ideal solver's
   call or results.
2. Enforce seven-parameter arity in solved finite mode.
3. Solve and return W5, `Vbias_tail`, achieved gm/Id5, device M5 data, KCL
   residuals, convergence counts, and domain diagnostics.
4. Remove only the finite+solved `NotImplementedError` guard after tests exist.
5. Preserve the public ideal-tail behavior exactly.

F1 tests must cover:

- nominal convergence and deterministic repeatability;
- the three KCL residuals and M5 current consistency;
- returned W5/L5 and `Vbias_tail`;
- achieved gm/Id5 reporting;
- wrong arity and non-finite/negative inputs;
- M5 reverse-lookup/domain rejection;
- impossible headroom and saturation-boundary behavior;
- convergence failure and singular/ill-conditioned behavior;
- unchanged ideal-tail regression outputs.

**F1 gate:** focused synthetic-LUT tests pass, followed by the complete
non-real-LUT suite. Stop, document, commit, and request review before F2.

### F2 - finite-M5 metrics, AC model, and hard constraints

Primary files:

- `analog_ai/circuit/ota5t.py`
- `analog_ai/circuit/mna.py`
- `analog_ai/evaluation/constraints.py`
- `tests/test_mna.py`
- constraint/evaluator tests

Tasks:

1. Feed the solved M5 operating point into MNA.
2. Treat the final M5 gate and source as AC ground; stamp its drain loading at
   the tail node using the documented meanings of `gds`, `cgd`, and `cdd`.
3. Confirm whether `cdd` already includes gate-drain contribution before
   adding `cgd`; do not double count capacitance.
4. Include M5 in area, width, saturation, and explicit per-device evidence.
5. Derive and document finite-tail swing and ICMR definitions. If the current
   proxy cannot justify them, mark them unavailable rather than returning a
   confident but incorrect value.
6. Compare ideal and finite results on controlled synthetic examples.

**F2 gate:** unit tests prove the tail stamp, constraints, area, and failure
boundaries; the full non-real-LUT suite remains green.

### F3 - seven-parameter contract and round trip

Primary areas:

- config and oracle/contract versioning;
- loader and evaluator serialization;
- optimizer bounds and local refinement;
- dataset schemas/sampling, without regenerating the dataset;
- netlist export;
- CLI fixtures and documentation.

Tasks:

1. Introduce explicit mode-aware parameter names instead of globally replacing
   the five-parameter constants.
2. Serialize all seven parameters and `Vbias_tail` in evaluation records.
3. Export M5 with its returned W/L and a DC source set to the returned
   `Vbias_tail`.
4. Reject a five-parameter checkpoint in finite mode; never pad two outputs.
5. Preserve old records and models under their original oracle version.
6. Round-trip finite data through request -> optimizer -> evaluator -> result
   -> netlist.

**F3 gate:** round-trip and compatibility tests pass; the existing web app is
still ideal-tail only.

### F4 - real-LUT feasibility baseline before learning

Create a dedicated, non-canonical result directory such as:

```text
evaluation_results/finite_m5/f4_baseline_<timestamp>/
```

Tasks:

1. Verify LUT hashes before loading the real tables.
2. Run the five frozen regression requests with finite solved mode and global
   optimization.
3. Record seed, bounds, evaluations, runtime, invalid categories, full design,
   metrics, constraints, and provenance.
4. Never overwrite ideal-tail canonical evidence.
5. Change bounds only for a documented physical reason and version that change.

**F4 gate:** all five requests have verified finite-M5 solutions, or each
failure has a documented physical/contract explanation. No surrogate training
starts here.

### F5 - independent Cadence correlation

Tasks:

1. Create a separate finite-M5 Cadence template and runner path. Keep all
   ideal-tail templates immutable.
2. Instantiate returned W1/L1, W3/L3, W5/L5, and `Vbias_tail`.
3. First correlate a manual reference and operating-point quantities:
   `Vtail`, `Vmirror`, `Vout`, device currents, gm, gds, gmbs, and VDSAT.
4. Then correlate gain, GBW, PM, power, and saturation margins.
5. Run a disjoint stratified campaign spanning currents, gm/Id, lengths,
   loads, gain/GBW demands, and boundaries.
6. Archive every job, raw Spectre result, OCEAN log, stdout log, parser output,
   and campaign manifest.
7. Derive a finite-specific policy only from its own evidence.

**F5 gate:** declared tolerances and a zero-false-pass deployment gate pass.
Only then may a separate finite mode be considered for the web app or Phase H.

## Test and resource protocol

Run the smallest relevant synthetic tests after each edit. At every work-package
gate run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_integration_real_luts.py -q
```

Run real-LUT tests only when enough memory is available and no web process is
holding another LUT copy:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_integration_real_luts.py -q
```

Do not load the approximately 5.5 GB LUT pair concurrently in multiple
processes. Cadence execution remains a deliberate Debian-VM step using the
shared-folder runner.

## Documentation, Git, and evidence rules

After every gate:

1. append actions, commands, failures, and measured results to this file;
2. update `docs/HANDOFF.md` and `docs/CORRECTION_LOG.md`;
3. store machine-readable evidence under a new versioned result directory;
4. run `git diff --check` and inspect the exact diff;
5. commit one bounded work package with a descriptive message;
6. push only after its gate passes and report the commit ID.

Never delete or rewrite ideal-tail evidence. Never call a failed optimization
proof of infeasibility. Never mark a plan item complete without its evidence.

## Stop conditions

Stop implementation and return to discussion if:

- the proposed solver requires LUT extrapolation;
- the M5 capacitance meaning cannot be established;
- a physical metric definition is ambiguous;
- ideal-tail numerical results change unexpectedly;
- a real-LUT run repeatedly exhausts memory;
- a needed PDK/Cadence assumption differs from the frozen testbench;
- passing a gate would require relaxing a hard constraint without approval.

## Definition of Phase F complete

- solved finite mode accepts the explicit seven-parameter design;
- every accepted design returns physical M1-M5 geometry and `Vbias_tail`;
- actual M5 current participates in tail KCL;
- M5 affects AC loading, area, headroom, saturation, and constraints;
- all final points are strictly in the LUT domain;
- ideal-tail historical behavior remains reproducible;
- the five regression cases have auditable finite-mode baseline outcomes;
- a separate finite-M5 Cadence campaign is archived and passes its declared
  deployment gate;
- no five-parameter model is represented as a finite-M5 model.

---

## Opus 5 pre-implementation review

**Review status:** submitted 2026-09-04 - awaiting Hassan/Codex discussion
(completed review below).

**Implementation authorization:** NOT APPROVED

Opus 5 must append its review below this line and then stop. Use this template:

```text
Reviewer/date:
Files read:
Recommended solver:
Equation/sign check:
Nested-vs-four-unknown comparison:
Proposed numerical tolerances:
M5 AC/capacitance interpretation:
Swing/ICMR decision:
F1 files to change:
Risks and fail-closed behavior:
Requested plan changes:
Questions for Hassan/Codex:
```

### Completed review - 2026-09-04

**Reviewer/date:** Opus 5 (Claude), 2026-09-04

**Files read** (plan's required order, plus the fixture source):
`docs/HANDOFF.md`, `docs/DESIGN_CONTRACT.md`, this plan,
`docs/CORRECTION_LOG.md` (incl. the 2026-09-04 still-open list),
`analog_ai/config.py`, `analog_ai/devices/lut.py`,
`analog_ai/devices/device_model.py`, `analog_ai/circuit/dc_solver.py`,
`analog_ai/circuit/ota5t.py`, `analog_ai/circuit/mna.py`,
`analog_ai/evaluation/constraints.py`, `analog_ai/evaluation/evaluator.py`,
`analog_ai/utils/netlist.py`, `analog_ai/optimization/de_baseline.py`,
`analog_ai/optimization/local_refine.py`, `tests/test_dc_solver.py`,
`tests/test_ota.py`, `tests/test_mna.py`, plus `tests/conftest.py` (needed
below: it defines the synthetic LUT's capacitance convention, which settles
one of the plan's open questions).

**Recommended solver:** the nested three-voltage solve - with ONE change to
the proposed formulation: `Vbias_tail = lookup_vgs(nch, L5, gmid5, VDS=Vtail,
VSB=0)` must be computed once per OUTER iteration and held FROZEN during the
inner Newton solve, not recomputed inside every residual evaluation.

- The physical circuit has a fixed gate bias. The inner solve should see a
  fixed device, exactly as W1/W3 are frozen; the gm/Id5 target is re-imposed
  at each outer fixed-point update, so at convergence `Vbias_tail` is
  self-consistent with the solved Vtail (same philosophy as the existing
  W1/W3 sizing loop, `dc_solver.py:109-150`).
- With a frozen `Vbias_tail` the residuals are smooth LUT interpolants of
  (Vtail, Vmirror, Vout), so the numeric Jacobian has exactly the character
  the existing damped-Newton/backtracking was tuned for; no
  `d(Vbias_tail)/d(Vtail)` coupling is injected mid-Newton.
- The strict reverse lookup (`lut.py:119-163`, raises on unachievable gm/Id
  or non-monotonic curves) then only ever fires on converged outer iterates
  - a deterministic invalid record - never mid-line-search at a trial Vtail
  that briefly leaves the achievable-gm/Id region.

Initial guess: same recipe as ideal mode (VGS1 at Vicm/2 -> Vtail0), then
`W5_0 = Itail / ids_char(L5, vgs5(Vtail0), Vtail0) * w_ref_n`.

**Equation/sign check** (magnitudes |Ids|; PMOS in |V| = VSG/VSD; currents
leaving a node positive):

- `Rtail = Id_M1 + Id_M2 - Id_M5 = 0` with
  `Id_M5 = (W5/w_ref_n) * ids(nch, L5, VGS5=Vbias_tail, VDS5=Vtail, VSB5=0)`.
  Sign confirmed: M5 conducts tail-node -> ground, M1/M2 sources feed the
  node. This is exactly ideal-mode R1 (`dc_solver.py:93`:
  `i1 + i2 - Itail`) with `Itail -> Id_M5`. `VDS5 = Vtail` and `VSB5 = 0`
  are correct (drain at the tail node, source grounded), so no body effect
  enters M5.
- `Rmirror = Id_M1 - Id_M3 = 0` (ideal-mode residual [1], unchanged).
- `Rout = Id_M4 - Id_M2 = 0` (ideal-mode residual [2], unchanged).
- W1 sizing: unchanged (reverse lookup at own solved bias, VSB = Vtail).
- W3 sizing: unchanged (diode self-consistency loop).
- W5 sizing (new): `W5 = Itail / ids_char(nch, L5, vgs5, Vtail, 0) *
  w_ref_n` with `vgs5 = lookup_vgs(L5, gmid5, VDS=Vtail, VSB=0)`.

Fixed-point consistency (why the final checks hold by construction): at the
accepted point, `vgs5` was produced by the reverse lookup AT that Vtail
(achieved gm/Id5 = target to interpolation error) and W5 makes
`Id_M5 = Itail` at that same point, so the tail KCL reduces to the
ideal-mode equation and `Id_M1 + Id_M2 = Id_M5 = Itail` simultaneously.
Re-evaluating with the returned FIXED W5 and FIXED `Vbias_tail` is then the
identical function evaluation, so "Id_M5 approximately equals Itail" and
"gmid_M5 approximately equals gmid5" hold by construction; the declared
tolerances only have to absorb interpolation roundoff. No sign errors found.

**Nested-vs-four-unknown comparison:** AGREE with nested.

- Residual units: nested = all amperes, same as the shipped solver;
  four-unknown mixes amperes with a dimensionless gm/Id residual and needs
  ad-hoc Jacobian row scaling.
- Jacobian cost: nested = 3 finite-difference columns of plain forward
  lookups; four-unknown adds a 4th column that perturbs `Vbias_tail`
  through a full VGS-curve interpolation per residual call.
- Branch safety: the strict reverse lookup restricts the solution to the
  post-peak decreasing branch of gm/Id(VGS) (`lut.py:145-162`). A FREE
  `Vbias_tail` unknown has no such guard and can converge to the
  subthreshold side of the peak on a locally flat curve.
- Domain handling: nested fails closed (DomainError at converged outer
  points); the gm/Id residual in the four-unknown form is defined even
  where the gate voltage is not characterizable - easier to hide a bad
  bias.
- Reuse/testability: nested reuses the exact Newton/backtracking
  scaffolding, so the ideal-mode suite is a meaningful control.
- Accuracy: identical at convergence (gm/Id5 pinned exactly either way).

Keep the four-unknown form only as a documented fallback if the nested
outer loop fails to converge on synthetic tests (not expected; the
W5-Vtail coupling is the same class the W1 loop already handles).

**Proposed numerical tolerances:**

- Inner KCL: Newton target `tol = 1e-12` A; acceptance `max|R| <= 1e-9` A -
  identical to ideal mode (`dc_solver.py:41` and `:155`). Ideal mode
  achieves <= 6e-11 A on real LUTs at 10-500 uA branch currents (<= 1e-5
  relative); nothing about the finite tail changes that scale.
- Outer width consistency: max relative change over (W1, W3, W5) < 1e-6,
  `max_outer = 8` (raise to 12 only if the three-width fixed point
  measurably needs it); log iteration counts and final width deltas in the
  record for diagnosis.
- `Id_M5` vs `Itail`: acceptance bound 0.1% relative at the accepted point
  - exact by construction at convergence; the bound doubles as a tripwire
  against a silently clamped or mis-scaled M5 evaluation.
- Achieved gm/Id5 vs target: acceptance bound |achieved - target| <= 1e-3
  1/V - exact by construction of the reverse lookup at the converged Vtail;
  catches accidental evaluation at a stale bias.
- Iterations: `max_newton = 60`, backtracking steps 30 - unchanged.
- NEW hard rejection: W5 sizing producing `W5 > W_NMOS_MAX` (250 um)
  rejects the design as invalid at sizing time (an unsizable tail means the
  DC point is not implementable). The existing `max(id_char, 1e-18)` guard
  would otherwise hide this as an absurd width. (W1/W3 keep their
  trial-level `max(vtail, 0)` / `1e-3` sizing guards; the final strict
  domain check still governs - no permanent clamping anywhere in the
  accepted path.)

**M5 AC/capacitance interpretation:** the gate-bias generator is outside the
sized boundary and M5's source is at ground, so both M5 gate and source are
AC ground. M5 therefore contributes NO transconductance term to the
admittance matrix - only drain loading at the tail node. The existing stamp
`Y[0,0] += m5["gds"] + s*m5["cdd"]` (`mna.py:49-51`) is already structurally
correct for a finite M5; F2's MNA work is PLUMBING (feed the solved M5
operating point instead of the zeroed `ideal_tail` dict), not new stamps.

On the plan's double-counting question, this repo's own data model answers
it in-convention: `tests/conftest.py` `_caps` defines
`cgd = cox*W_REF*10nm` (overlap) and `cdd = cgd + 0.2*cox*W*L`, i.e. `cdd`
ALREADY INCLUDES the gate-drain overlap. The stamp must therefore use `cdd`
alone and must NOT add `cgd` - which the current stamp already satisfies.
Caveat: that pins the convention of this codebase's LUTs; before F2 freezes,
the real TSMC characterization deck / save list should be checked once to
confirm the pickle's `cdd` carries the same meaning. If it does not, only
the finite stamp changes (ideal mode has `cdd_M5 = 0` and is unaffected).
M5's `cgs`/`cgg` never enter the 3x3 solve.

**Swing/ICMR decision:** do NOT copy the imposed-mode finite formulas; the
solved point knows Vtail exactly, so use it:

- `Swing = (VDD - VDSAT4) - (Vtail + VDSAT2)`, all at the solved point. The
  imposed formula `VDD - VDSAT4 - VDSAT2 - VDSAT5` substitutes VDSAT5 for
  Vtail only because imposed mode does not know Vtail. M5's own saturation
  (`Vtail - VDSAT5`) is already enforced separately as `sat_m5` /
  `Sat_margin_min`; folding it into Swing a second time double-counts the
  same physical limit.
- `ICMR_min = VGS1(solved) + VDSAT5(solved)`: the textbook lower ICMR bound
  (tail needs `Vtail >= VDSAT5` while `Vicm = Vtail + VGS1`). It reduces to
  the current solved-mode value `ICMR_min = VGS1` (`ota5t.py:260`) as
  `VDSAT5 -> 0`, so ideal-mode regression values are preserved exactly.
- The upper ICMR limit is not derivable from this proxy without new
  assumptions; leave it unreported rather than confident-wrong (matches the
  plan's F2 task 5).
- Both definitions land in F2 with synthetic-LUT unit tests; if either is
  challenged in discussion, mark the metric unavailable instead of guessing.

**F1 files to change:**

- `analog_ai/circuit/dc_solver.py` - add the finite-tail solver as a
  separate function; `solve_operating_point` itself untouched, so the ideal
  call graph is provably unchanged.
- `tests/test_dc_solver_finite.py` (new) - the plan's F1 test list: nominal
  convergence + determinism, three KCL residuals + M5 current consistency,
  returned W5/L5/`Vbias_tail`, achieved gm/Id5, wrong arity and
  non-finite/negative rejection, M5 reverse-lookup/domain rejection,
  impossible headroom and saturation-boundary behavior, convergence failure
  and singular-Jacobian behavior, unchanged ideal-mode regression outputs.
- `analog_ai/circuit/ota5t.py` - NO functional change in F1 under the split
  requested below (docstring note only).
- Nothing else: `mna.py` / `constraints.py` / `evaluator.py` / `netlist.py`
  belong to F2/F3 exactly as planned.

**Risks and fail-closed behavior:**

1. Reverse-lookup DomainError cannot occur mid-Newton under the frozen-
   `Vbias_tail` scheme; at outer converged points it raises ->
   deterministic invalid record. No clamping in the accepted path.
2. Near-threshold M5: `ids_char -> 0` makes naive W5 explode; the
   `max(id_char, 1e-18)` guard exists and the new `W_NMOS_MAX` sizing-time
   rejection turns that case into a clean invalid instead of an absurd
   design.
3. Headroom exhaustion (`Vbias_tail + VDSAT5` leaves no room for VGS1 at
   the given Vicm): tail KCL unsolvable -> `DCConvergenceError` ->
   `InvalidDesignError`, the same fail-closed path as today.
4. Singular/ill-conditioned Jacobian (M5 deep in subthreshold flattening
   `dId_M5/dVtail`): existing `LinAlgError` raise -> invalid; the residual
   non-convergence path also catches slow gradient death.
5. Outer-loop oscillation between W5 and Vtail: bounded by `max_outer` with
   a deterministic message and the last width deltas recorded.
6. Trial-point voltage clipping during backtracking stays exactly as in
   ideal mode (`np.clip` to `[1e-3, VDD-1e-3]`, recorded in
   `domain_clamps`), and the final solution passes the strict unclamped
   domain check extended with the M5 coordinates (VDS5 = Vtail within the
   VDS grid, VGS5 = `Vbias_tail` within the VGS grid, L5 within the L
   grid).
7. Ideal-mode regression lock: existing `test_dc_solver.py`, `test_ota.py`,
   `test_mna.py` must pass with unchanged results; the finite path lives
   behind a separate function and, during F1, behind the still-in-place
   evaluator guard.
8. No persisted evidence before F3: F1/F2 produce test-level evidence only;
   canonical records under new provenance start at F3/F4, so no finite
   result can be mistaken for an ideal-tail record (ORACLE_VERSION bump
   stays in F3 as planned).

**Requested plan changes:**

1. Freeze `Vbias_tail` within each inner Newton solve; recompute it once
   per outer iteration (rationale under "Recommended solver").
2. Move "remove the finite+solved NotImplementedError guard" (F1 task 4) to
   the START of F2. Removing it in F1 would make
   `OTA5T(tail_device="finite", op_point="solved").evaluate()` callable
   while m5 is not yet plumbed - ideal-tail AC metrics could present
   themselves as finite-mode results, exactly the failure class this plan
   exists to prevent. F2 task 0 becomes: remove guard, plumb the solved m5
   into the MNA call, prove the stamp with tests.
3. Add the sizing-time `W5 > W_NMOS_MAX` rejection (see tolerances).
4. Adopt the solved-Vtail swing/ICMR definitions above instead of the
   imposed-mode formulas - the plan itself demands proof "instead of
   copying the imposed-mode formulas without proof", and the proof points
   the other way.
5. Make explicit in F1 that no canonical/persisted records are written
   before F3's versioning lands (implied by the package order already).

**Questions for Hassan/Codex:**

1. `cdd` convention of the real TSMC pickle: may the characterization deck
   / OCEAN save list be checked (one-time, before the F2 freeze) to confirm
   `cdd` includes the gate-drain overlap, as the repo's synthetic-LUT
   convention does? If it cannot be checked, I propose stamping cdd-only
   (current behavior) and letting the F5 manual-reference correlation
   arbitrate, reserving the stop condition "M5 capacitance meaning cannot
   be established" for a demonstrated disagreement.
2. Are the two proposed metric definitions accepted for F2 (solved-Vtail
   swing; `ICMR_min = VGS1 + VDSAT5`)?
3. Is the guard-removal move to F2 (requested change 2) acceptable?
4. F4 runs the five frozen regression requests verbatim in finite mode;
   outcomes may legitimately differ from the ideal-tail baseline
   (documented per plan). Confirm no attempt should be made to make them
   match by tuning.
5. Trial-point voltage clipping with recorded clamps + strict final check
   (as in ideal mode) - confirmed as the accepted policy for the finite
   solver?

## Decision record

| Date | Decision | Owner | Evidence/reason |
|---|---|---|---|
| 2026-09-04 | External M5 gate bias is returned; its generator remains out of scope | Project | Keeps the seven-variable sizing problem explicit and implementable |
| 2026-09-04 | Existing ideal-tail pipeline and web default stay frozen | Project | Preserves validated nominal evidence and deployed behavior |
| 2026-09-04 | F0.5 pre-implementation review submitted by Opus 5 - recommends the nested solver with a frozen inner Vbias_tail; five plan-change requests pending discussion | Opus 5 | Completed review appended under "Opus 5 pre-implementation review" |
| Pending | Select nested or four-unknown finite solver | Hassan/Codex after Opus review | Awaiting F0.5 discussion |
| Pending | Approve F1 implementation | Hassan/Codex | Awaiting F0.5 discussion |

## Execution log

### 2026-09-04 - plan revision

- Re-audited the finite-mode guard, solved DC kernel, MNA tail stamp,
  evaluator serialization, constraints, and netlist exporter.
- Added the mandatory Opus discussion gate and withheld implementation
  authorization.
- Proposed a nested three-node KCL solve with M5 reverse-gm/Id bias calculation
  and an outer W5 consistency loop.
- Added work-package boundaries, tests, evidence locations, stop conditions,
  Git discipline, and separate Cadence validation requirements.
- No production code or runtime behavior changed.

### 2026-09-04 - F0.5 pre-implementation review submitted

- Read the full required-reading list (HANDOFF, DESIGN_CONTRACT, this plan,
  CORRECTION_LOG, config, lut, device_model, dc_solver, ota5t, mna,
  constraints, evaluator, netlist, de_baseline, local_refine, and the
  three solver test files) plus tests/conftest.py.
- Appended the completed review under "Opus 5 pre-implementation review".
  Headline conclusions:
  - Nested three-voltage solver recommended, with Vbias_tail computed once
    per outer iteration and frozen during the inner Newton (the strict
    reverse lookup then only fires on converged points, and the inner
    Jacobian keeps the character the ideal solver was tuned for).
  - Residual signs verified against the shipped ideal solver
    (`Rtail = Id_M1 + Id_M2 - Id_M5`, `Rmirror = Id_M1 - Id_M3`,
    `Rout = Id_M4 - Id_M2`); at the outer fixed point the final M5 checks
    hold by construction.
  - Tolerances proposed: KCL acceptance <= 1e-9 A, width consistency 1e-6
    relative over (W1, W3, W5), Id_M5 vs Itail 0.1%, gm/Id5 error
    <= 1e-3 1/V, plus a new sizing-time W5 > W_NMOS_MAX rejection.
  - cdd/cgd question resolved in-convention: conftest defines
    `cdd = cgd + junction`, so the tail stamp uses cdd alone and must not
    add cgd (the existing stamp already complies); real-pickle check
    requested before the F2 freeze.
  - Honest solved-point metric definitions proposed instead of the imposed
    formulas: Swing = (VDD - VDSAT4) - (Vtail + VDSAT2);
    ICMR_min = VGS1 + VDSAT5 (reduces to the ideal-mode value).
  - Five requested plan changes, notably: keep the finite+solved evaluator
    guard until F2 plumbs m5 (prevents ideal-tail metrics masquerading as
    finite results), and move the guard removal to F2 task 0.
- Five questions for Hassan/Codex recorded (cdd provenance check, metric
  definitions, guard move, F4 no-tuning confirmation, trial-clip policy).
- No production code or runtime behavior changed. Implementation remains
  NOT APPROVED pending Hassan/Codex discussion.

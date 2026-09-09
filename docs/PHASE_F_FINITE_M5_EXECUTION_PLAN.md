# Phase F Plan - Finite-M5 Solved 5T OTA

**Created:** 2026-09-04

**Revised for Opus 5 handoff:** 2026-09-09 (Astra review)

**Status:** Astra re-reviewed corrective commit `ece10e5` on 2026-09-09:
F1-R1 through F1-R4 accepted. The remaining R5 follow-up (numerical-setting
validation R5a + source-content binding R5b) is now implemented and a new
immutable probe archive generated; awaiting final F1 acceptance. F2 remains
closed. See the corrective re-review and the R5 follow-up entry at the end
of this file.

**Technical direction:** Astra is the brain (architecture, physical assumptions,
acceptance criteria, and gate review); Opus is the muscles (implementation,
tests, experiments, and evidence). Hassan owns scope and deployment decisions.

**Review precedence:** the 2026-09-09 Astra directions below supersede conflicting
2026-09-04 proposals. The original Opus review is retained as review history,
not as an unqualified implementation specification. See also
[`astra_review.md`](../astra_review.md).

**Current authorization:** Hassan authorized F1 implementation on 2026-09-09
(bounded package per Astra A6). F2 and later packages remain unauthorized
until Astra accepts the F1 evidence.

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
- Astra reran the gates on 2026-09-09: 139/139 non-real-LUT tests and 3/3
  real-LUT integration tests passed. Both LUT hashes matched the manifest.
- `analog_ai/config.py` defines seven parameter names, but `DESIGN_BOUNDS_7`
  currently has only six bounds: Itail is missing. Correct this before F1
  finite input validation. Do not change the five-parameter bounds.
- imposed operating-point mode can already produce finite-M5 geometry.
- `analog_ai/circuit/mna.py` already has a tail-node M5 `gds`/`cdd` stamp.
- constraints already include an existing finite M5 in the NMOS width maximum.
- `analog_ai/circuit/ota5t.py` deliberately rejects
  `tail_device="finite", op_point="solved"` with `NotImplementedError`.
- That constructor guard is incomplete: a finite/imposed object can currently
  call `evaluate(x5, op_point="solved")` and receive ideal-tail results. Add
  dispatch/override checks before relying on the unsupported-mode boundary.
- `evaluate_design()` still serializes only five design parameters.
- finite netlist export currently emits a zero-volt M5 gate source rather than
  a solved `Vbias_tail`; this must not be treated as complete.
- The shared verifier currently ignores request-specific PM/saturation minima,
  and the shared MNA has terminal-stamp concerns identified in Astra R1/R7.
  Passing the current tests does not resolve these issues.

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
17. `astra_review.md` and the Astra directions in this document; also read
    `tests/conftest.py` as a synthetic fixture, not as foundry-data provenance.

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
8. submit the concrete proposal for Astra's design review before implementation.

No implementation begins until the decision record says
`Implementation authorization: APPROVED`. Approval of this planning commit is
not implementation authorization.

Opus's initial review has already been submitted. Astra has now reviewed it;
the next implementation handoff should use the amended decisions below, without
repeating the historical five questions. A future instruction to implement a
bounded package should be recorded as its authorization; routine reversible
work within that authorized package does not require repeated permission.

## Proposed finite-tail DC formulation

### Fixed design inputs

```text
L1, gmid1, L3, gmid3, L5, gmid5, Itail, VDD, VICM
```

### Solved circuit voltages

```text
z = [Vtail, Vmirror, Vout]
```

At the start of each outer iteration, use the current `Vtail` to derive a
candidate tail gate voltage. The existing reverse lookup is an initial estimate;
the accepted finite bias must meet the declared **forward gm/ID ratio** gate:

```text
Vbias_tail = lookup_vgs(nch, L5, gmid5, VDS=Vtail, VSB=0)
```

Hold W1, W3, W5, and `Vbias_tail` fixed throughout the inner Newton solve,
including Jacobian probes and line search. Use actual LUT drain currents:

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
- update `Vbias_tail` between inner solves only;
- repeat until widths, gate bias, actual M5 gm/ID, current error, and KCL
  residuals all meet their respective tolerances.

The final verification must re-evaluate M5 using the returned **fixed** W5 and
**fixed** `Vbias_tail`. It must demonstrate:

```text
Id_M1 + Id_M2 = Id_M5
Id_M1 = Id_M3
Id_M4 = Id_M2
Id_M5 approximately equals Itail
gmid_M5 approximately equals gmid5
```

Here `gmid_M5 = returned_M5.gm / returned_M5.ID`. Record the independently
interpolated `gmid` table value under a different name. Interpolation of a ratio
is not generally the ratio of interpolated quantities (Astra R6).

This distinction matters: the DC design procedure may calculate the bias, but
the AC model treats that final bias node as AC ground. It does not track the
tail voltage dynamically.

### Alternative Opus must evaluate

A four-unknown formulation can solve
`[Vtail, Vmirror, Vout, Vbias_tail]` with the three KCL residuals plus
`gmid_M5 - gmid5 = 0`. Opus must compare conditioning, residual normalization,
domain handling, and testability. The nested three-voltage formulation is the
current recommendation because it reuses the strict reverse-LUT operation and
avoids mixing ampere and inverse-volt residuals in one unscaled Jacobian.
Both formulations still need scaling and branch/domain safeguards; do not
describe gm/Id as dimensionless or claim either iteration path guarantees
physical correctness without final fixed-device verification.

## Physical validity and failure contract

An evaluation is invalid unless all of these hold:

- the design vector has exactly seven finite values inside canonical bounds;
- `Itail > 0` and `CL > 0`;
- `0 < Vtail, Vmirror, Vout, Vbias_tail < VDD`;
- every final LUT coordinate is within its closed characterized domain,
  including legal endpoints such as M5 VSB=0, without extrapolation;
- W1, W3, and W5 are positive, finite, and inside hard width limits;
- final KCL residual magnitude is below the declared tolerance;
- final width relative change is below the declared tolerance;
- M5 current error and achieved-gm/Id error are explicitly bounded;
- all five devices meet any requested saturation requirement;
- GBW is a real first 0 dB crossing within the configured sweep.

Separate solver validity from design acceptance: a converged in-domain DC point
may fail width/saturation/performance constraints. Return explicit failure
categories. A kernel may return such a point for diagnostics, but it must never
be accepted as a feasible design. Require finite mandatory fields and complete
M1-M5 evidence; missing optional requested metrics must also prevent acceptance.

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

- `analog_ai/config.py` (finite bounds only)
- `analog_ai/circuit/dc_solver.py`
- `analog_ai/circuit/ota5t.py` (close dispatch bypass; no public finite metrics yet)
- `tests/test_dc_solver.py`
- new focused finite-solver tests if separation improves clarity

Tasks:

1. Add an explicit finite-tail solver path without changing the ideal solver's
   call or results.
2. Enforce seven-parameter arity in solved finite mode.
3. Solve and return W5, `Vbias_tail`, achieved gm/Id5, device M5 data, KCL
   residuals, convergence counts, and domain diagnostics.
4. Keep finite+solved public evaluation unavailable, including per-call
   overrides; close the existing bypass. Expose the finite DC kernel only to
   focused tests and development probes until F2's complete integration gate.
5. Preserve the public ideal-tail behavior exactly.
6. Validate the actual forward gm/ID ratio, final bias convergence, and strict
   finite-domain semantics; do not silently change the historical ideal LUT
   contract while implementing these checks.

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
non-real-LUT suite. Submit the bounded diff and evidence to Astra before F2.

### F2 - finite-M5 metrics, AC model, and hard constraints

Primary files:

- `analog_ai/circuit/ota5t.py`
- `analog_ai/circuit/mna.py`
- `analog_ai/evaluation/constraints.py`
- minimal finite schema/provenance support in `analog_ai/evaluation/evaluator.py`
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
7. Audit the complete shared MNA terminal stamps, not just M5. Independent tests
   must cover body-current conservation, capacitor connectivity, and input
   capacitive excitation. Keep any corrected finite AC implementation distinct
   from the historical ideal oracle (see Astra direction A4).
8. Enforce effective requested PM/saturation limits and finite complete evidence.
9. Prepare seven-value serialization and a distinct finite oracle/schema identity
   before removing public guards. Remove those guards only when the integrated
   metrics, constraints, and record path pass together. Do not expose a partially
   wired F2 evaluator or persist finite results under the old oracle identity.

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

1. Complete mode-aware contracts across consumers, building on F1 bounds and
   F2's minimal schema; never globally replace five-parameter constants.
2. Serialize all seven parameters and `Vbias_tail` in evaluation records.
3. Export M5 with its returned W/L and a DC source set to the returned
   `Vbias_tail`.
4. Reject a five-parameter checkpoint in finite mode; never pad two outputs.
5. Preserve old records and models under their original oracle version.
6. Round-trip finite data through request -> optimizer -> evaluator -> result
   -> netlist.
7. Preserve every supported optional request field, solved current, bias,
   per-device saturation evidence, and provenance throughout that round trip.
8. Fail explicitly if a finite record is passed to an ideal-only dataset,
   model, RL environment, web entry point, or correlation renderer.

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
failure has an auditable status: proven contract rejection, domain/numerical
failure, or unresolved within the declared search budget. Exhausted optimization
does not require an invented physical explanation. Record best residuals and
budget for unresolved cases. No surrogate training starts here.

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
8. Define measured request checks for all requested constraints, including
   per-device saturation, and explicit unavailable statuses. The present
   ideal-tail collector checks only gain/GBW/power/default PM and cannot be
   reused as the complete finite gate.
9. Freeze device/metric tolerances before the manual-reference run; separate
   policy-development data from a locked disjoint validation campaign. Bind
   raw results to netlist, measurement-script, LUT, and PDK identities.

**F5 gate:** report correlation-tolerance passes and full measured-request
passes separately. All declared release gates must pass with no missing cases,
and the locked validation campaign must have zero observed false passes. This
is a finite-sample result, not a universal guarantee. Only then may a separate
finite mode be considered for the web app or Phase H.

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
5. prepare one bounded work package with a descriptive commit message;
6. commit/push when covered by the implementation session's authorization,
   after its gate passes; report the revision and exact evidence. This review
   task itself does not require a commit or push.

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
- all final points are in the closed LUT domain without extrapolation;
- ideal-tail historical behavior remains reproducible;
- the five regression cases have auditable finite-mode baseline outcomes;
- a separate finite-M5 Cadence campaign is archived and passes its declared
  deployment gate;
- no five-parameter model is represented as a finite-M5 model.

---

## Opus 5 pre-implementation review

**Review status:** submitted 2026-09-04 - awaiting Hassan/Codex discussion
(completed review below).

**Historical-status note (2026-09-09):** Astra's review and dispositions now
appear below. Pending statements and questions inside the original submission
are retained as history and are superseded by those dispositions.

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

## Astra review and implementation directions - 2026-09-09

**Reviewer:** Astra. **Baseline:** `f9798cda312b701b6ee3870ea238c849b74db86d`.
**Disposition:** retain the Sol work-package structure; revise the numerical,
contract, AC, and evidence details before implementation. Opus implements the
bounded packages; Astra reviews the reasoning, diff, tests, and measured results.
The full project findings and reproduction results are in
[`astra_review.md`](../astra_review.md).

### A1. Solver choice and a useful independent cross-check

Use the nested three-voltage solve with **all three widths and Vbias_tail
frozen throughout each inner solve**. The stated residual equations have the
correct zeros; their row signs need only remain internally consistent. The
three residuals are not all written with the same “currents leaving positive”
convention, despite the wording in Opus's review.

The outer loop updates geometry and gate bias. Convergence requires more than
small width changes: record `delta_Vbias_tail`, final KCL, M5 current error, and
actual gm/ID error. After the final update, independently evaluate all five
devices at the returned voltages and **fixed returned widths/gate bias**, with
trial clamping disabled. Do not report residuals from the preceding geometry.

Freezing the bias removes reverse lookup from inner residual evaluations, but
does not guarantee failure only at converged points: initialization and outer
updates can fail, and forward lookups or trial currents can still be invalid.
LUT interpolants are piecewise smooth; reject nonfinite Jacobians/steps and
report stalled or ill-conditioned solves explicitly, rather than relying only
on `LinAlgError` to detect conditioning problems.

There is a useful cross-check under the specified sizing contract: if the final
M5 is sized and biased to conduct exactly Itail, the three DC KCL equations
reduce to the ideal-tail equations at that same point. An ideal solved point
with a separately sized M5 can therefore provide an initial guess and a nominal
reference, **provided M5 passes domain, width, bias, and saturation checks**.
Do not require finite and ideal nominal DC voltages to differ as proof that M5
is active. Prove participation by perturbing fixed M5 width/bias and observing
the tail-current residual. This reference checks the M5 extension; it is not
independent validation of the shared ideal solver or of the physical circuit.

The four-unknown alternative remains a fallback, not a second production solver
to build speculatively. Its gm/Id residual has units 1/V and must be scaled. A
free gate voltage can be branch-bounded; the nested method is preferred for
reuse and explicit branch control, not because other formulations are inherently
incapable of respecting the domain.

### A2. Numerical contract and true achieved gm/ID

Adopt these as proposed F1 defaults; Opus must measure convergence/failure
coverage and record the actual settings in every diagnostic record:

| Quantity | Proposed setting and interpretation |
|---|---|
| Inner Newton target | max absolute KCL residual <=1e-12 A |
| Final KCL acceptance | <=1e-9 A; also report residual/Itail, which is <=1e-4 at the current 10 uA lower bound |
| Outer width changes | maximum relative change over W1/W3/W5 <=1e-6 |
| Outer gate-bias change | absolute change <=1e-8 V; final physical residual checks remain mandatory |
| M5 current target | abs(ID5-Itail)/Itail <=1e-3 |
| M5 achieved ratio | abs(gm5/ID5-gmid5) <=1e-3 1/V, using the actual returned gm and current |
| Iteration budgets | initial max_outer=8, max_newton=60, backtracking=30; any increase requires recorded before/after evidence |

The gm/ID gate is **not justified by interpolation roundoff**. Astra reproduced
table gm/Id=15.0 while returned gm/ID=13.8501628 at a synthetic M5 bias. Use the
existing reverse lookup as a branch-aware initial estimate, then, if needed,
solve the forward `abs(gm)/abs(ids)` target on a valid decreasing branch. Reject
unbracketed/ambiguous roots explicitly; do not extend the branch or clamp to an
endpoint to obtain an answer. Include table gm/Id and its discrepancy in the
diagnostics. If Opus proposes a different achieved-ratio convention or tolerance,
bring measured evidence to Astra before changing this contract.

M5 reference current must be positive and finite. Do not use a tiny current
floor to turn an unsizable device into apparently valid geometry. Final widths
must satisfy hard limits. An excessive **initial or intermediate** W5 is not
proof that the final design is impossible; try a bounded, documented seed/update
strategy or return a numerical failure. Do not prematurely reject a potentially
valid design solely because one seed implied W5>250 um.

Trial-point clipping is permitted only with explicit diagnostics and strict
final checks. Count voltage line-search clipping as well as LUT-coordinate
clipping; the current `domain_clamps` list does not fully report both. Never
copy the common `1e-9` absolute length/voltage tolerance into the finite-domain
contract. Boundary endpoints, particularly VSB=0, remain valid.

### A3. Contract prerequisites and public exposure

Correct the finite bounds before kernel validation:

```python
DESIGN_BOUNDS_7 = DESIGN_BOUNDS[:4] + (
    (60e-9, 1.5e-6), (5.0, 25.0),
) + DESIGN_BOUNDS[4:]
```

Test name/bound count, order, units, exactly seven finite values, and positive
finite CL/Itail. Check explicit constructor and per-call mode overrides. The
existing finite/imposed -> solved override bypass must be closed in F1.

Accept Opus's request to retain the guard in F1, with a stronger boundary:
**public finite evaluation opens only after F2 metrics, hard checks, and minimal
record/provenance support pass together**. The earlier “remove guard at start
of F2” wording is unsafe for intermediate states. Move the minimum serialization
work forward from F3; F3 then completes optimizer/export/dataset compatibility.

Minimum finite records include: schema/oracle identity, parameter names/order,
all seven values, topology/tail mode/op-point mode, VDD/VICM/CL, W1/W3/W5,
Vtail/Vmirror/Vout/Vbias_tail, requested Itail and solved ID5, per-device OP and
saturation data, KCL/current/ratio errors, iteration counts, clipping diagnostics,
all effective request constraints, and the external-bias-generator exclusion.
Persisted experiment manifests additionally pin code, LUT hashes, settings,
seed, environment, and output hashes. Use strict JSON with explicit null/reason
for unavailable optional fields, and reject missing mandatory finite evidence.

Keep the historical ideal oracle identifier and readers reproducible; assign
distinct identities to changed physics/contract semantics. A single global
version bump with no mode/schema distinction is insufficient. Do not reinterpret
old records or checkpoints under finite bounds. Add negative round-trip tests
that attempt to send finite data into every supported ideal-only consumer.

Request PM/saturation minima must reach both optimization and verification. The
effective floor is at least the frozen default, tightened by a supported request.
Missing or nonfinite requested metrics cannot pass. Keep legacy contract fixes
versioned and separate from silent changes to historical ideal evidence.

### A4. AC interpretation: M5 is local; F2 validation is broader

Accept the local M5 conclusion conditionally: with gate, source, and body at AC
ground, its gm and gmb controlled sources have zero incremental drive. Drain
loading is `gds5 + s*Cdd5` **if Cdd5 denotes the complete drain self-capacitance
for those grounded terminals**. Do not add cgd blindly.

The synthetic fixture establishes only its own convention. It does not settle
whether the real pickle stores signed charge derivatives, magnitudes, total
capacitance, or a subset. Establish the real convention from the characterization
deck/save expressions and model documentation, or a focused device-level
Spectre experiment that isolates the required admittance. Record exactly which
keys, signs, and overlap/junction contributions are included. The presence of a
`cdd` key, a synthetic formula, or an aggregate OTA pass does not establish this.

Do **not** accept “F2 is plumbing only.” Astra R7 identifies missing drain-row
body terms, questionable input-capacitor connections/excitation, and overlap
double counting under the synthetic convention in the shared MNA. For finite
AC, derive device terminal equations independently and test the complete matrix
and RHS, including asymmetric devices and driven-gate capacitance. A test that
only observes a response change when a capacitor changes is insufficient.

Reference for controlled-current and lumped-capacitor terminal connectivity:
[MIT 6.012 Lecture 11, pages 5 and 14](https://ocw.mit.edu/courses/6-012-microelectronic-devices-and-circuits-fall-2005/ce96d1ec5951846e0d1240383b10d8af_lec11.pdf).
The application of those equations to the repository is Astra's derivation;
this source does not establish the foundry LUT's capacitance semantics.

If corrected finite stamps differ from historical ideal stamps, preserve a
versioned legacy ideal path and a documented corrected finite path. A global
correction would invalidate the frozen ideal guard until separately evaluated.
For the ideal-limit test, zero the M5 admittance in the **same corrected AC
model**; do not demand equality to a legacy matrix containing other differences.

Capacitance provenance remains a stop condition for freezing F2's physical
claims. Opus may prepare convention-explicit synthetic code/tests while that
evidence is pending; an unresolved convention is not permission to mark the
real-device AC gate complete.

### A5. Headroom, swing, ICMR, current, and power

Accept these only as **nominal frozen-operating-point headroom estimates**:

```text
Vout_low_est  = Vtail + VDSAT2
Vout_high_est = VDD - VDSAT4
Swing_est    = Vout_high_est - Vout_low_est
ICMR_low_est = VGS1 + VDSAT5
```

If they represent a required positive saturation floor, include that floor in
the corresponding bounds and record it. Report whether the nominal Vout lies
between the output bounds. Do not clamp a negative interval into a plausible
positive swing.

These estimates do not prove large-signal output swing or a common-mode sweep:
Vtail, VGS1, body effect, currents, and VDSAT can change as the circuit moves.
Retain explicit estimate/status semantics; defer optional acceptance on an
unvalidated range metric or reject that requested metric as unavailable. A true
range claim requires a fixed-geometry, fixed-Vbias_tail sweep with an explicit
testbench and per-point validity checks. Resizing M5 at each sweep point would
test different circuits. Upper ICMR remains unavailable without a justified
definition.

Correct Opus's headroom wording: **Vbias_tail is a gate voltage and is not a
series drain-source drop**. The tail saturation condition is
`Vtail - VDSAT5 >= effective Sat_margin_min`; the input-pair common-mode
relationship is `VICM = Vtail + VGS1`.

Use solved supply current for finite core power:
`Pcore = VDD * (ID3 + ID4)`, cross-checked against `VDD * ID5` by KCL. Record
requested `VDD*Itail` separately if useful. `ID5/CL` is a slew-rate proxy, not
a transient measurement. Exclude external bias-generator power/area/noise/mismatch
visibly; do not silently include those quantities in any “total” claim.

### A6. Required evidence by work package

| Package | Opus delivery required for Astra review |
|---|---|
| F1 | Correct finite bounds; kernel tests; all public finite/solved calls still rejected; nominal and boundary KCL; fixed-device perturbation; true gm/ID check; singular/stalled/domain cases; bias/width convergence diagnostics; unchanged ideal regression outputs |
| F2 | Independent terminal-derived matrix/RHS tests; grounded M5 test; capacitance convention evidence; M5 area/saturation/width; tightened-request and malformed-evidence tests; explicit metric estimate policy; versioned finite record support before guard removal |
| F3 | Seven-dimensional optimizer and normalization; schema round trip including Vbias_tail and optional specs; correct finite netlist; precision/geometry round trip; explicit rejection by ideal-only consumers and five-output models |
| F4 | Five frozen requests under finite mode, fixed budgets/seeds, complete record/manifests, runtime and full oracle-call counts, classified failures, no overwritten ideal results |
| F5 | Device-level manual reference and OP extraction first; frozen tolerances; finite template/runner; raw logs and hashes; separate correlation and full measured-request verdicts; disjoint locked policy validation |

For F4, successful finite designs need not match ideal metrics. Do not tune the
five request targets or discard hard cases to manufacture agreement. Numerical
failure and budget exhaustion remain legitimate unresolved outcomes. Distinguish
F4's completion of an auditable baseline from a claim of universal feasibility.

For F5, archive input and measurement-script hashes with results, validate the
complete schema and finite fields, and reject stale/wrong-job results. Make
missing device measurements fail the relevant gate. Fixing a policy after seeing
the locked validation set requires a new disjoint validation set. Report both
the number of proxy-selected candidates and all attempted/completed cases.

The 2026-09-09 review rechecked the historical tiered campaign: 25/25 measured
user-spec passes, **22/25 correlation-tolerance passes**, 25 raw JSON files and
50 logs. That is useful ideal-tail evidence, not a finite-M5 certificate, and
the historical measured verdict omits per-device saturation.

### A7. Disposition of Opus's five questions

| Original question | Astra disposition |
|---|---|
| May the characterization/save convention be checked? | Yes; this read-only check is necessary technical work within implementation. Preserve the stop condition if the meaning remains unresolved; use an isolated device experiment if source material is unavailable. |
| Accept proposed swing and ICMR? | Accept as labeled nominal estimates with the limitations in A5, not as verified large-signal ranges. |
| Move guard removal out of F1? | Yes; remove only after integrated F2 metrics, constraints, and minimal finite records pass. Close the existing override bypass in F1. |
| F4 uses the frozen five requests without tuning? | Yes. Report changed outcomes and unresolved budgets honestly. |
| Permit recorded trial clipping plus strict final checks? | Yes, including explicit voltage-clipping diagnostics, legal grid endpoints, and no final extrapolation. |

Opus should not repeat these questions during an authorized package unless new
evidence contradicts the stated assumptions. Escalate actual design changes,
unresolved physical definitions, or a proposed relaxation of acceptance criteria
to Astra with a concrete example, measured failure, and proposed resolution.

### A8. Brain/muscles handoff protocol

1. Astra sets the package contract, physical assumptions, regression boundary,
   and independent acceptance evidence.
2. Opus implements that package, runs relevant checks, and records failures as
   well as successful results. Opus owns routine implementation details.
3. Opus submits a bounded diff with files changed, commands and measured
   outcomes, example valid/invalid records, provenance, and unresolved issues.
4. Astra reviews that concrete evidence and records technical acceptance or
   specific corrections before the next package expands scope.
5. Hassan remains the scope/deployment decision maker. Record implementation
   authorization when instructed to implement; this review does not pretend
   such implementation or deployment already occurred.

No sub-agent implementation was launched for this review. “Opus is the muscles”
defines the implementation ownership for the next handoff, not a claim that
Opus has already executed the amended plan.

## Decision record

| Date | Decision | Owner | Evidence/reason |
|---|---|---|---|
| 2026-09-04 | External M5 gate bias is returned; its generator remains out of scope | Project | Keeps the seven-variable sizing problem explicit and implementable |
| 2026-09-04 | Existing ideal-tail pipeline and web default stay frozen | Project | Preserves validated nominal evidence and deployed behavior |
| 2026-09-04 | F0.5 pre-implementation review submitted by Opus 5 - recommends the nested solver with a frozen inner Vbias_tail; five plan-change requests pending discussion | Opus 5 | Completed review appended under "Opus 5 pre-implementation review" |
| 2026-09-09 | Nested three-voltage solver with widths and gate bias frozen in the inner loop selected as the implementation direction | Astra | A1/A2; final fixed-device and true gm/ID checks required |
| 2026-09-09 | Correct six-entry finite bounds and close per-call mode bypass before relying on F1's contract | Astra | Reproduced in workspace; Astra R2/R3 |
| 2026-09-09 | Public finite evaluation stays closed until integrated F2 metrics/constraints/minimal schema are ready | Astra | Prevents ideal metrics or five-field records being presented as finite results |
| 2026-09-09 | F2 includes an independent full terminal-stamp audit; real capacitance convention remains evidence-gated | Astra | A4 and Astra R7; fixture convention is not foundry provenance |
| 2026-09-09 | Swing/ICMR are labeled nominal estimates unless fixed-device sweeps justify stronger claims | Astra | A5 |
| 2026-09-09 | Astra owns design/gate review; Opus owns implementation/tests/evidence | Hassan direction, recorded by Astra | User's brain/muscles assignment |
| 2026-09-09 | Implementation authorization: APPROVED for the bounded F1 package | Hassan | User instruction 2026-09-09: "Implementation authorization: APPROVED" |
| 2026-09-09 | F1 delivered: finite DC kernel + 27 focused tests; gates 166/166 non-real-LUT and 3/3 real-LUT; real-LUT probe archived; submitted for Astra review | Opus | Execution log 2026-09-09; evidence under `evaluation_results/finite_m5/f1_probe_*/` |
| 2026-09-09 | Astra F1 gate review: CHANGES REQUIRED (F1-R1..R5); F2 stays closed | Astra | Gate-review entry; reproductions in `astra_review.md` findings |
| 2026-09-09 | F1 corrective package delivered addressing F1-R1..R5; awaiting Astra re-review | Opus | Corrective execution-log entry; evidence `f1_probe_20260909_031000` |
| 2026-09-09 | Corrective re-review of ece10e5: R1-R4 accepted; R5 still requires setting validation and exact source identity; F2 remains closed | Astra | Reproduced successful tol=inf record that cannot serialize as strict JSON; archived source is old commit plus dirty flag without source hashes/patch |
| 2026-09-09 | Probe saturation margins are diagnostics only: F2's saturation verifier must reject the probe cases; no floor adjustment | Astra direction, recorded by Opus | Astra F1 gate review, saturation interpretation |
| 2026-09-09 | Astra corrective re-review: F1-R1..R4 accepted; R5a (controls validation) + R5b (source binding) open | Astra | Corrective re-review entry; 185 passed + 3 passed independently verified |
| 2026-09-09 | R5 follow-up delivered: controls validated before solving, probe evidence bound to source fingerprints/diff hash, new immutable archive; submitted for final F1 acceptance | Opus | R5 follow-up entry; evidence `f1_probe_20260909_045513` |
| 2026-09-09 | F1 technical review: CHANGES REQUIRED; F2 remains closed | Astra | Independently reproduced domain/extrapolation, ambiguous-root, and nonfinite-output failures; corrections below |
| 2026-09-09 | Accept max_outer=60 as a bounded default; reject the common 1e-9 edge tolerance and inconsistent final evaluation | Astra | Synthetic nominal requires 10 iterations; archived wide real case needs 31; domain deviation contradicts A2 and permits out-of-grid geometry |

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

### 2026-09-09 - Astra project and Phase F review

- Reviewed the active circuit/LUT stack, hard verifier, record schemas,
  optimization, learning/data flow, correlation tooling, web runtime/UI,
  tests, and current/historical planning evidence.
- Created `astra_review.md` with prioritized findings and reproduced probes.
- Reran 139 non-real-LUT tests (including browser tests) and three real-LUT
  integration tests successfully. Verified both real-LUT hashes before the
  integration run; no second process loaded the real LUT pair.
- Verified the pilot Parquet hashes, 24,588/33,150 design/request counts,
  zero design-ID overlap across splits, zero duplicate request/design pairs,
  zero missing design references, and zero positive-label/verdict contradictions.
- Reproduced six-entry finite bounds, the finite/solved override bypass,
  ignored tightened PM/saturation requests, seven-value record truncation,
  near-boundary LUT extrapolation/reverse-lookup endpoint clamping, a true
  gm/ID mismatch, incomplete malformed-evidence rejection, and risk-mask
  tensor misalignment.
- Checked the tiered campaign's stored counts and raw JSON/report parity:
  25 completed, 22 correlation passes, zero recorded false proxy passes;
  25 raw JSON files and 50 logs. No new Cadence execution or large benchmark
  rerun was performed.
- Updated the operative package instructions and recorded dispositions of
  Opus's questions. Added the Astra/Opus ownership and review protocol.
- No production implementation, deployment, commit, or push was performed.

### 2026-09-09 - F1 implementation (solved finite DC kernel)

Authorized by Hassan ("Implementation authorization: APPROVED", bounded F1
package per Astra A6). All F1 work-package tasks completed; delivered for
Astra gate review before any F2 work.

**Changes**

- `analog_ai/config.py` - `DESIGN_BOUNDS_7` corrected from six to seven
  entries (Itail restored; first four and Itail share the frozen
  five-parameter bounds). Five-parameter bounds untouched.
- `analog_ai/circuit/dc_solver.py` (new code only; the ideal
  `solve_operating_point` is untouched and locked by a byte-stable snapshot
  test):
  - `validate_finite_design` - deterministic seven-value arity/finiteness/
    bounds validation, never clips.
  - `_forward_gmid_vgs` - the A2 forward gm/ID gate: the strict reverse
    lookup is a branch-aware initial estimate only; the accepted tail bias
    solves the FORWARD ratio of separately interpolated gm and ids by
    bracketed Brent iteration on the post-peak decreasing branch of the
    table curve. Unbracketed and ambiguous roots raise deterministically
    (no branch extension, no endpoint clamping, no current floor).
  - `_ids_closed` - closed-domain current evaluation: membership per the
    repo's own definition (`LUT.in_domain`, grid endpoints legal, 1e-9
    float-representation slack); a coordinate within that slack of an edge
    is evaluated AT the edge, never extrapolated beyond the characterized
    box; anything genuinely outside raises.
  - `solve_operating_point_finite` - nested three-voltage solve with W1,
    W3, W5 AND `Vbias_tail` frozen through the inner damped Newton
    (Jacobian probes and line search included); outer loop re-sizes the
    three widths and re-derives the gate bias; final verification
    re-evaluates all five devices at the FIXED returned widths/bias with
    clamping disabled; forward gm/ID5 and ID5-vs-Itail acceptance gates;
    KCL acceptance 1e-9 A with residual/Itail reported; convergence counts,
    width/bias deltas, LUT-axis clamp counts, and line-search voltage-clip
    counts in every record; optional `trace` captures per-outer-iteration
    trajectories; hard width limits bind on the FINAL geometry only.
- `analog_ai/circuit/ota5t.py` - closed the per-call override bypass:
  `evaluate(..., op_point="solved")` on a finite-tail object now raises
  NotImplementedError (previously it silently returned ideal-tail results).
  Public finite evaluation remains closed.

**Deviations from the A2 initial settings, with recorded evidence**

- `max_outer` default 8 -> 60. The outer loop converges geometrically at a
  design-dependent rate: synthetic nominal needs 10 iterations (rate ~0.2;
  at 8 it stalls at width change 3.7e-6); a real TSMC wide design
  (L1=L5=0.6 um, gmid1=gmid5=12, gmid3=10, Itail=100 uA) needs 31
  (rate ~0.64, Vtail ~ 30 mV; at 20 it stalls at width 3.3e-5, bias
  8.7e-7 V). Correction (2026-09-09, per Astra F1-R5): the trajectories
  were observed interactively at delivery but NOT archived; they are
  archived from the corrective package onward
  (`f1_probe_20260909_031000`, traces for the 12/31/12-iteration
  convergences and the 20-iteration failure). Not an
  oscillation; outer iterations past the first cost 1-3 Newton steps, so
  the raise is nearly free in wall time (worst measured full solve 0.88 s).
- Strict final domain semantics use the repo's closed-domain definition
  (`LUT.in_domain`) with edge-snap evaluation. Flagged for Astra review:
  a converged voltage can sit 1 ULP outside a grid edge by floating-point
  arithmetic alone (e.g. 1.2 - 0.7500000000000001 = 0.44999...96 vs a 0.45
  grid min); rejecting that would violate "boundary endpoints remain
  valid", so the point is evaluated at the edge and never extrapolated.
- Bug caught during implementation: the Jacobian condition guard was
  initially written inverted (1e-12 instead of 1e12) and rejected healthy
  solves; the first synthetic probe caught it before any test was written.

**Tests** (`tests/test_dc_solver_finite.py`, 27 focused tests, all passing)

Bounds contract (7 names/7 bounds, shared entries); deterministic input
validation (arity, NaN/inf, negative Itail, bound violations); nominal
convergence + bit-identical determinism; KCL acceptance + M5 current
consistency (windows consistent with the declared tolerances); returned
W5/L5/Vbias_tail + matched pairs; forward gm/ID5 gate + table ratio
recorded separately; closed-domain membership incl. M5 coordinates and
VSB=0 endpoint; convergence/clip diagnostics; A1 fixed-device perturbation
(+2% W5 moves the tail residual by ~2% of Itail); ideal-solved-point
reference (voltages agree within 2 mV); ideal-kernel byte-stable snapshot;
boundary currents 10 uA / 300 uA; 500 uA rejected by the W5 hard-limit
check; headroom exhaustion fails closed; max_outer exhaustion fails
deterministically; unachievable gmid5 rejected by the forward gate; L5
outside the characterized L box rejected (between-lengths interpolation
confirmed legal); nonfinite device data raises the explicit guard;
position-independent exact-sizing case converges in one outer iteration
with identically zero residual; public finite+solved rejection incl. the
closed bypass; ideal+solved arity and behavior preserved.

**Gates**

- Non-real-LUT suite: 166/166 pass (139 baseline + 27 new), exit 0:
  `.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_integration_real_luts.py -q`
- Real-LUT integration: 3/3 pass, exit 0 (no other process held the LUTs).

**Real-LUT probe** (`scripts/probe_finite_kernel.py`; development
evidence, not a canonical evaluation - no finite record carries canonical
identity before F3):

| Design | Result | Key measured values |
|---|---|---|
| nominal_50uA (L1=L5=0.5um, gmid1=15, gmid5=10) | converged 0.43 s | Vtail 79.1 mV, W5 12.9 um, Vbias_tail 0.5676 V, KCL 3.19e-12 A, table-vs-forward gmid5 10.0080 vs 10.0000 |
| wide_100uA (gmid1=gmid5=12, gmid3=10) | converged 0.88 s | Vtail 30.5 mV, W5 118.7 um, KCL 1.68e-11 A, 12.0019 vs 12.0000 |
| boundary_10uA | converged 0.38 s | KCL 6.39e-13 A; identical voltages to nominal (Itail scales widths only - homogeneity sanity check) |

The real-data table-vs-forward offset confirms the A2 forward-gate
requirement on TSMC data. Evidence:
`evaluation_results/finite_m5/f1_probe_20260909_020725/` (before: wide
design failing at max_outer=20) and `f1_probe_20260909_020926/` (after:
all three converge at max_outer=60).

**Known items for Astra**

1. The slow-convergence regime (rate up to ~0.64/iteration) is affordable
   now (< 1 s per solve) but fixed-point acceleration may be worth
   evaluating before F4 uses the kernel inside an optimizer loop.
2. The `_ids_closed` edge-snap interpretation of the closed-domain rule
   (above) needs explicit Astra sign-off.
3. `sat_m5` is reported as a diagnostic; saturation acceptance remains a
   hard-constraint matter for F2.
4. `astra_review.md` is still untracked in the working tree (Astra's
   artifact; left for its author to commit).

### 2026-09-09 - Astra F1 gate review of commit 6b42cf6

**Decision: CHANGES REQUIRED. F2 must not start yet.** This is a technical
review of the delivered package, not a request to restart the implementation.
Retain the sound parts and deliver a bounded F1 corrective commit.

**Independently verified**

- Reviewed actual commit `6b42cf60d5daaa19eb347fe1551f3c3e082b4e4c`, the focused
  tests, probe script, and both archived real-LUT probe JSON files.
- Reran the full non-real-LUT suite: **166 passed**, exit 0. Reran real-LUT
  integration: **3 passed**, exit 0. The two dependency deprecation warnings
  remain non-failing. No new real finite probe or Cadence campaign was run.
- Compared parsed definitions against `f9798cd`: all pre-existing functions
  and classes in `dc_solver.py` are unchanged. The new seven-entry bounds,
  frozen inner geometry/bias, and explicit finite+solved override rejection
  implement the intended direction.
- Reproduced synthetic nominal failure at max_outer=8 (width change
  3.72155e-6, bias change 1.99485e-7 V), followed by convergence in 10 outer
  iterations with the default 60. The last width changes contract by about
  0.198 per iteration. The archived real wide case fails at 20 and converges
  at 31. **The 60-iteration bound is accepted**; acceleration is not an F1
  requirement. Do not generalize the measured subsecond runtime to all inputs.

#### F1-R1 - P1: domain handling violates the finite contract

**Locations:** `dc_solver.py::_ids_closed`, `_forward_gmid_vgs`, the final
`_point` calls, and `_DOMAIN_EDGE_TOL` (reviewed line 265).

The constant is **1e-9 in every axis**, including meters. It is not a one-ULP
representation allowance. A 0.5 nm out-of-grid length is many orders of
magnitude larger than floating-point spacing at that length. A2 explicitly
prohibits copying the historical common length/voltage tolerance.

Reproduced with the repository synthetic LUT and the nominal seven-vector,
changing only L5 to **179.5 nm** while the LUT minimum is **180 nm**:

- The kernel returns successfully and reports the out-of-grid L5.
- The reported tail residual is `3.6211808856e-10 A`.
- Tail KCL recomputed from returned device IDs is `-3.1416074576e-12 A`.
- Clip diagnostics are empty.

The discrepancy has a direct source explanation: final residuals use snapped
`_ids_closed` coordinates, whereas forward-bias lookups and returned `_point`
data use raw coordinates accepted by the permissive legacy LUT checker. Those
lookups can extrapolate. Thus the final verified point and returned evidence
are not the same evaluation, and the claim that nothing ever extrapolates is
incorrect.

**Required correction:** introduce finite-specific coordinate validation with
at most a small, justified floating-point representation allowance per axis;
reject genuinely out-of-grid geometry. Handle a legal endpoint consistently
across bias lookup, final currents, and all returned device parameters. Keep
the requested design distinct from any canonicalized evaluation coordinates
and record any permitted snap. Recompute acceptance KCL from the same device
points that are returned. Preserve legacy ideal LUT behavior.

**Required tests:** legal endpoints including VSB=0; `nextafter` cases on both
sides of relevant voltage/length endpoints; 0.5 nm below the length minimum
must reject; no forward or final lookup outside the validated domain;
returned-current KCL agrees with reported KCL to floating-point accuracy.

#### F1-R2 - P1: ambiguous forward gm/ID roots are accepted

**Location:** `dc_solver.py::_forward_gmid_vgs`, reviewed lines 364-389.

Multiple brackets are sorted by distance from the reverse-lookup estimate and
the first is selected. Multiple exact hits return the first hit immediately.
This contradicts A2 and the delivery claim that ambiguous roots are rejected.

Reproduced using the existing `_FakeLUT` interface with constant positive
current and a consistent gm/current/table curve on its VGS grid:

```text
ratio = [12, 10.005, 9.995, 10.005, 9, 8, 7, 6,
         5, 4, 3.8, 3.6, 3.4, 3.2, 3, 2.8]
target = 10
```

This curve passes the allowed small-wiggle check but has three target
crossings. The helper returns **VGS=0.525 V**. A curve containing a target
plateau `[12, 10, 10, 9, ...]` also returns a gate voltage instead of rejecting
the nonunique solution. The current exact-sizing test relies on an entirely
flat target curve, so it currently endorses that ambiguity.

**Required correction:** establish one unique, valid decreasing-branch root
before solving/returning. Count exact hits, intervals, and plateaus together,
deduplicating a single grid-node root shared by adjacent intervals. Reject
multiple roots and flat target intervals rather than choosing one by proximity.
Replace the flat-ratio exact-sizing fixture with a unique-root fixture.

**Required tests:** multiple crossings with a valid reverse estimate; repeated
exact roots; target plateau; unique endpoint root; unique interior root;
unbracketed root. These tests must not simply mirror the current selection rule.

#### F1-R3 - P1: successful records can contain nonfinite operating-point data

**Location:** final verification and per-device `_point` construction in
`solve_operating_point_finite`, reviewed lines 629-694.

The finite checks largely cover residuals during iteration and M5 current.
They do not validate the complete returned device data. Reproduced by wrapping
the synthetic PMOS LUT's `lookup('gm', ...)` to return NaN while leaving its
current and gm/Id table unchanged: the kernel returns successfully with
**M3.gm=NaN and M4.gm=NaN**. Its existing nonfinite-current test does not cover
this failure. Comparisons of the form `error > tolerance` also do not reject
NaN without an explicit finiteness check.

**Required correction:** construct and validate all returned device points
before acceptance. Require finite mandatory currents, gm/gds/VDSAT, geometry,
voltages, errors, and residuals; require appropriate positive current/geometry.
Optional absent data may have an explicit unavailable policy, but present NaN
data must not masquerade as a successful OP. Check finiteness before threshold
comparisons. Apply this only to the finite path.

**Required tests:** isolated nonfinite gm, gds, and VDSAT; nonfinite M5 error;
final-only nonfinite data; actual singular and ill-conditioned Jacobian guards.
The last two Jacobian cases were required in F1 but have no explicit focused
tests in the delivered file. A headroom/convergence failure is not equivalent
coverage.

#### F1-R4 - P2: invalid per-call mode values still silently fall back

**Location:** `analog_ai/circuit/ota5t.py::evaluate`, reviewed line 89.

The finite+solved bypass is fixed, but `op_point='solvde'` still returns imposed
results, and `op_point=''` is treated as an omitted override. Reproduced on an
ideal/solved object. A3 requires validation of explicit overrides, not only
the supported finite+solved combination.

**Required correction:** distinguish `None` from an explicit override and
validate the effective value against the supported modes before dispatch.
Test invalid strings and empty strings while preserving all valid ideal calls
and the finite+solved prohibition.

#### F1-R5 - P2: effective numerical settings and trajectories are not archived

**Locations:** kernel convergence metadata; `scripts/probe_finite_kernel.py`;
both `f1_probe_*` JSON files.

The kernel reports the constant tolerance dictionary even when `tol` is
overridden. Reproduced: a call with `tol=5e-13` records `1e-12`. Maximum inner
and outer budgets are not included in the returned configuration. The probe
copies expected LUT manifest values without verifying hashes itself, omits
source revision/hash and full device records, and never passes or archives
`trace`. Neither committed JSON contains the trajectories claimed in the
delivery. The pre-change wide error and post-change count support the budget
increase, but the detailed reproducibility claim needs correction.

**Required correction:** validate and record effective tol/iteration budgets;
give the probe explicit budget arguments; hash the loaded LUT files before
loading or reference a verifiable check; record source identity, full kernel
OP, and traces for both successful and failed comparison runs. Development
records can have a distinct noncanonical schema without borrowing a production
finite-oracle identity. Reproduce the before/after runs without source edits,
and use strict JSON. Correct the historical log wording if a claimed artifact
was only observed interactively and not saved.

#### Interpretation of the real-device evidence

All three successful archived cases have **negative M5 saturation margins**:

| Case | Archived sat_m5 |
|---|---:|
| nominal_50uA | -48.043 mV |
| wide_100uA | -58.598 mV |
| boundary_10uA | -48.043 mV |

These are converged DC points, not feasible finite-OTA designs. Returning them
for F1 diagnostics is consistent with separating convergence from saturation
acceptance. This is **not an additional F1 blocker**. Make it prominent in the
handoff: F2's saturation verifier must reject these cases, and F4 still owes
evidence of physically feasible finite designs. Do not adjust the saturation
floor to make these probes pass.

#### Next Opus delivery

Deliver one bounded F1 corrective package addressing F1-R1 through F1-R5,
with the specified regression cases and updated development evidence. Keep
public finite evaluation closed and leave F2 metrics/MNA work for the next
package. Rerun focused tests, the complete non-real-LUT suite, and real-LUT
integration after the corrections. Astra will review the actual diff and
artifacts; passing the old 169 tests alone does not close the findings.

This review changed only this plan. It did not implement fixes, run F2, commit,
or push; the pre-existing untracked `astra_review.md` was left unchanged.

### 2026-09-09 - F1 corrective package delivered (addresses F1-R1..R5)

One bounded corrective commit addressing Astra's F1 gate review; public
finite evaluation stays closed; F2 not started.

**F1-R1 (domain handling).** `_canonical_coord` replaces the rejected 1e-9
tolerance scheme: coordinates strictly inside the grid pass through; an
outside value is accepted only within TWO ULPs of the violated edge (a
single subtraction of grid-edge-scale operands can miss an edge by that
much - the float-representation allowance Astra asked for), snapped to the
edge, and recorded in `clip_diagnostics.coordinate_snaps` (axis, requested,
canonical). Anything further - including Astra's 0.5 nm-below-180 nm
reproduction - raises DomainError. One canonical coordinate set now feeds
the acceptance KCL AND every returned device point: all twelve device
coordinates are canonicalized, M1-M5 points are built from them, each point
is validated, and the acceptance residuals are recomputed FROM the returned
IDs - the verified point and the returned evidence are one evaluation by
construction. `_forward_gmid_vgs` canonicalizes L/VDS/VSB before every
lookup, so bias derivation can no longer extrapolate. Legacy ideal LUT
behavior untouched.

**F1-R2 (ambiguous roots).** The reverse-estimate proximity selection is
removed entirely. Exact grid-node hits and strict sign-change intervals are
counted together (a node root shared by adjacent intervals counts once
because strict products exclude zero endpoints); zero roots raise as
unbracketed; more than one root - including a two-node target plateau -
raises as ambiguous. Astra's three-crossing curve and the `[12, 10, 10, 9,
...]` plateau now reject; unique endpoint and unique interior roots are
solved exactly.

**F1-R3 (nonfinite returned data, Jacobian guards).** New
`_validate_point_finite` validates every returned M1-M5 point (finite
W/L/VGS/VDS/VSB/ID/gm/gds/VDSAT plus optional keys when present; positive
W/L/ID) before acceptance, and every M5 acceptance comparison is preceded
by an explicit finiteness check (NaN can no longer pass a `> tol`
comparison). The missing explicit Jacobian tests were added: a true
singular case (VGS-only currents make R3 the exact negative of R2; a
VDS-dependent table gain prevents the zero-residual shortcut) reports
"singular KCL Jacobian"; a near-dependent variant reports
ill-conditioned-or-singular.

**F1-R4 (mode validation).** `OTA5T.evaluate` distinguishes None
(constructor mode) from an explicit override and validates the effective
value against {imposed, solved} before dispatch: `'solvde'` and `''` now
raise ValueError instead of silently falling back to imposed. All valid
calls preserved.

**F1-R5 (recordation).** The kernel records effective settings:
`convergence.tolerances` reflects the ACTUAL `tol`, and
`convergence.effective_settings` carries {tol, max_newton, max_outer}.
`scripts/probe_finite_kernel.py` rewritten: explicit budget arguments
(`--max-outer/--max-newton/--tol`); streaming sha256 self-verification of
both LUT files against `configs/lut_manifest.json` (abort on mismatch);
source identity (git commit, dirty state, python); full kernel OP records;
archived per-iteration traces for successful AND failed runs; a
before/after comparison run (wide design at max_outer=20 and at the
default) inside ONE invocation with no source edits; strict JSON
(`allow_nan=False`). Verified evidence:
`evaluation_results/finite_m5/f1_probe_20260909_031000/` - hashes verified;
nominal 12 outer iterations / 0.41 s, wide 31 / 0.82 s, boundary 12 /
0.37 s, zero coordinate snaps; the comparison run fails at budget 20 with
20 archived trace rows. The interactive convergence-rate claims of the
original entry (10 synthetic / 31 real wide) are unchanged and now
reproducible from the archived traces.

**Tests.** Focused file grew 27 -> 46 tests: nextafter both-side
canonicalization, absolute-excursion rejection (including Astra's 0.5 nm
case at kernel level), snap recording with canonical returned evidence,
bitwise KCL-from-returned-points identity, the six R2 root-uniqueness
cases, nonfinite gm/gds/VDSAT returned-data rejection including final-only
M5 poisoning, singular + ill-conditioned Jacobian guards, invalid/empty
op_point rejection, and effective-settings recordation. The flat-ratio
exact-sizing fixture - which had endorsed the old ambiguity selection - was
replaced by a unique-root fixture.

**Gates.** Focused 46/46; complete non-real-LUT suite exit 0 (139 baseline
+ 46); real-LUT integration 3/3 exit 0.

**Saturation interpretation recorded (Astra, non-blocking).** All archived
successful probe cases carry NEGATIVE M5 saturation margins (nominal
-48.0 mV, wide -58.6 mV, boundary -48.0 mV): they are converged DC points,
NOT feasible finite-OTA designs. F2's saturation verifier must reject these
cases, F4 still owes evidence of physically feasible finite designs, and
the saturation floor must not be adjusted to make probes pass. Flagged
prominently in HANDOFF.

### 2026-09-09 - Astra corrective re-review of ece10e5

**Reviewed revision:** `ece10e5816e296a04d7096436d2df5d38501a919`.
**Decision:** accept F1-R1 through F1-R4; keep F1-R5 open for the limited
corrections below. **F2 remains closed.** No further numerical redesign is
requested, and the previously accepted max_outer=60 setting remains accepted.

**Verification performed:** reran the complete non-real-LUT suite (**185
passed**, including the 46 focused cases) and real-LUT integration (**3
passed**), both exit 0. Compared all pre-existing `dc_solver.py` function/class
definitions with `f9798cd`; they remain unchanged. Inspected the corrective
diff, focused tests, probe implementation, and strict-JSON archived evidence.
The two existing dependency deprecation warnings remain non-failing.

**Findings closed:**

| Finding | Acceptance evidence |
|---|---|
| R1 domain/final-point consistency | The 1e-9 allowance is removed. Independent probes confirmed one/two-ULP snaps and three-ULP rejection at both voltage and length edges. The 179.5 nm rejection test passes. Returned device points feed acceptance KCL directly. |
| R2 ambiguous roots | Multiple intervals and multiple exact hits/plateaus reject; unique roots work. Independently checked repeated separated node roots and a unique interior node root in addition to the delivered tests. |
| R3 nonfinite OP evidence | All M1-M5 mandatory OP fields and present optional numeric fields are validated before acceptance. Poisoned gm/gds/VDSAT and final M5 data reject. Explicit rank-deficient/near-dependent Jacobian tests now exist. |
| R4 mode dispatch | Invalid and empty overrides reject; None and valid overrides preserve intended behavior; finite+solved public calls stay closed. |

The corrected real-LUT archive contains consecutive trace lengths **12, 31,
12, and 20**, including the failed low-budget run. For each successful archived
record, recomputing the three KCL equations from its returned device IDs gives
exactly its stored residual dictionary. Effective finite settings and verified
LUT hashes are now present. The three negative M5 saturation margins are
correctly described as convergence diagnostics, not feasible designs.

#### Remaining R5a - P2: validate numerical controls before solving

**Location:** `analog_ai/circuit/dc_solver.py:488` at the reviewed revision.

Effective values are now recorded, but `tol` is never validated. On the
existing unique-root, constant-current synthetic construction, a call with
`tol=float('inf')` **returns successfully with zero KCL residual**, stores
infinity in both tolerance/settings metadata, and subsequently fails
`json.dumps(record, allow_nan=False)` with:

```text
Out of range float values are not JSON compliant
```

This does not demonstrate a false physical KCL pass: the independent final
KCL check still exists. It does demonstrate that invalid controls bypass the
inner stopping rule and produce an unusable supposedly successful record.
On the same construction, zero, negative, and NaN tolerances produce a
misleading singular-Jacobian error instead of invalid-input rejection.
Validation was explicitly requested in the original R5 disposition.

**Required small fix:** validate the effective tolerance as a positive finite
real scalar; reject booleans and nonnumeric values. Validate maximum iteration
budgets as positive integer scalars without silently truncating fractions.
Do this before lookup/iteration and return deterministic ValueError messages.
Keep the final KCL acceptance threshold unchanged. Add focused invalid-setting
tests, including the successful-infinity reproduction and strict JSON for a
normal result.

#### Remaining R5b - P2: bind evidence to the actual source contents

**Location:** `scripts/probe_finite_kernel.py::source_identity` and
`f1_probe_20260909_031000/f1_real_lut_probe.json`.

The archive reports:

```json
{"git_commit": "6b42cf60d5daaa19eb347fe1551f3c3e082b4e4c",
 "git_dirty": true, "python": "3.11.9"}
```

This honestly flags local changes, but identifies the pre-corrective parent
plus an unspecified dirty state. No source digest or patch identifies the
actual changed code that generated the traces. Merely committing that output
later does not record those missing source contents.

**Required small fix:** record a content-hash manifest for the executed kernel,
LUT/device implementation, configuration, loader, and probe (or all active
package/probe Python sources), alongside the Git revision. Alternatively,
record a clean source revision with a check that relevant tracked source files
match it. Keep unrelated untracked review/output files separate from code
identity; there is no requirement to commit `astra_review.md` to run a probe.
For dirty source, save the actual source hashes or a complete reproducible
source snapshot/patch. Generate a new immutable probe directory after this fix;
preserve the earlier archive as history.

While correcting the probe, preserve supplied `tol` and `max_newton` in the
comparison run and override **only** `max_outer`. The current comparison call
passes only `{"max_outer": 20}`, silently dropping any other CLI controls.
The existing default-settings archive is not affected, but a customized
before/after run would change more than one variable. Add a lightweight probe
test for effective comparison settings and source fingerprint coverage.

**Next delivery:** one small R5 follow-up with invalid-control checks, source
fingerprinting, controlled budget comparison, and a new trace archive. R1-R4
are closed unless that diff introduces a regression; do not reopen their
design or begin F2 in this follow-up. Rerun the applicable regression gates
and submit the exact revision/evidence for final F1 acceptance.

Only this plan was edited during the re-review. No implementation changes,
new real finite probe, Cadence run, commit, push, or F2 work were performed.
The pre-existing untracked `astra_review.md` remains unchanged.

### 2026-09-09 - R5 follow-up delivered (controls validation + source binding)

Small bounded package addressing exactly the two open R5 items; solver
structure and the accepted max_outer=60 setting untouched; F2 not started.

**R5a - numerical controls validated before solving.** New
`_validate_numeric_settings` runs before ANY lookup or iteration: the
effective tolerance must be a positive finite real number (booleans and
nonnumeric values rejected) and the budgets positive integers - fractional
values (7.5) are rejected, never truncated, and sub-1 budgets reject, all
with deterministic ValueError messages. Astra's reproduction is closed:
`tol=float('inf')` now rejects instead of returning a record that stored
infinity and then failed strict JSON. The final KCL acceptance threshold is
unchanged (still the declared 1e-9 A, independent of `tol`). Tests: 11
invalid-setting cases (the inf reproduction, zero/negative/NaN/bool/string
tolerances, fractional/boolean/sub-1 budgets) plus a strict-JSON compliance
test on a normal result (`json.dumps(record, allow_nan=False)`).

**R5b - evidence bound to actual source contents.** The probe now records
a content-hash manifest of all nine executed sources (kernel, LUT/device
implementation, config, loader, and the probe script itself) alongside the
Git revision. The dirty flag reflects TRACKED changes only
(`--untracked-files=no`), so untracked review/output files no longer taint
code identity; when tracked changes exist, a `git diff HEAD` sha256 pins
the exact working-tree code that generated the run. The comparison run
preserves any supplied tol/max_newton and overrides ONLY max_outer
(`comparison_budgets` helper). A lightweight probe test module
(`tests/test_probe_finite_kernel.py`, 4 tests, no LUT loading) covers the
comparison-budget rule, fingerprint coverage/validity with an independent
hash spot-check, and source-identity shape.

**Gates and evidence.** Focused 62/62 (58 finite incl. 11+1 new, 4 probe);
complete non-real-LUT suite exit 0; real-LUT integration 3/3 exit 0. New
immutable archive: `evaluation_results/finite_m5/f1_probe_20260909_045513/`
- LUT hashes verified, 9-source fingerprint, tracked-changes diff hash,
  strict JSON; measured outcomes unchanged (nominal 12 outer / 0.34 s,
  wide 31 / 0.84 s, boundary 12 / 0.37 s, comparison run fails at
  max_outer=20 with 20 archived trace rows). Earlier archives preserved as
  history. Submitted revision for final F1 acceptance: the commit carrying
  this entry (see decision record).

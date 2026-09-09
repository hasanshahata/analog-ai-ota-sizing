# Phase F Plan - Finite-M5 Solved 5T OTA

**Created:** 2026-09-04

**Revised for Opus 5 handoff:** 2026-09-09 (Astra review)

**Status:** **F1 ACCEPTED** at `db6db4a`; **F2 development integration
ACCEPTED** at `e0accfe`. **F3 CHANGES REQUIRED** after Astra's review of
`2684166`: public finite/solved dispatch and schema routing are accepted,
but export context, round-trip verification, search constraints, finite
optimizer normalization, and compatibility guards need correction
(F3-R1..R5). F4 is not released. The finite library path remains provisional;
real capacitance provenance and physical AC acceptance remain open for F5.
See the final F3 gate-review entry for the bounded Opus handoff.

**Technical direction:** Astra is the brain (architecture, physical assumptions,
acceptance criteria, and gate review); Opus is the muscles (implementation,
tests, experiments, and evidence). Hassan owns scope and deployment decisions.

**Review precedence:** the 2026-09-09 Astra directions below supersede conflicting
2026-09-04 proposals. The original Opus review is retained as review history,
not as an unqualified implementation specification. See also
[`astra_review.md`](../astra_review.md).

**Current authorization:** Hassan assigned Astra the technical gate reviews.
F1 and F2 development integration are accepted; Astra releases the bounded F3
contract/round-trip handoff below to Opus. This does not authorize web exposure,
deployment, dataset regeneration, retraining, changes to the frozen ideal-tail
oracle, or execution of the later F4/F5 campaigns.

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
| 2026-09-09 | F1 ACCEPTED at `db6db4a`; bounded F2 released to Opus under A8 | Astra | Final F1 acceptance entry |
| 2026-09-09 | Corrected finite AC model added alongside the frozen legacy stamps (audit found the five R7 discrepancies); cdd convention recorded as UNRESOLVED with the cdd-only stamp under a documented assumption | Opus | F2 execution-log entry; `tests/test_mna_audit.py`; `f2_integration_20260909_054929` |
| 2026-09-09 | F2 implemented (audit + capacitance evidence + metrics/constraints/schema); public finite evaluation still closed; awaiting Astra F2 review | Opus | F2 execution-log entry |
| 2026-09-09 | Astra F2 gate review of `acfb995`: CHANGES REQUIRED (F2-R1..R5) | Astra | F2 gate-review entry; independent reproductions |
| 2026-09-09 | F2 correction package delivered: junction-decomposed stamps, request validation, strict-JSON failure paths, supply context, F2 fingerprints + new archive; awaiting re-review | Opus | F2 correction entry; evidence `f2_integration_20260909_112307` |
| 2026-09-09 | Astra corrective re-review of `a700ae7`: F2-R1/R4/R5 accepted; two P2 record-boundary items open (conversion overflow, nonfinite supply echo) | Astra | Corrective re-review entry; independent reproductions |
| 2026-09-09 | F2 record-boundary follow-up delivered: overflow-safe numeric conversion naming the field, supply-context validation before device work with JSON-safe echoes, regenerated source-bound archive; submitted for final F2 acceptance | Opus | Boundary follow-up entry; evidence `f2_integration_20260909_114535` |
| 2026-09-09 | Astra final F2 acceptance at `e0accfe`; bounded F3 compatibility package released | Astra | Final F2 acceptance entry |
| 2026-09-09 | F3 implemented: public finite/solved dispatch activated together with mode-aware record routing, seven-parameter optimizer bounds, finite netlist export with solved bias, explicit ideal-only-consumer rejections; awaiting Astra F3 review | Opus | F3 execution-log entry |
| 2026-09-09 | Astra re-review of `a700ae7`: F2-R1/R4/R5 accepted; original R2/R3 failures fixed, two P2 record-boundary cases remain; guards stay closed | Astra | Final re-review entry; 261 non-real-LUT and 3 real-LUT tests passed independently; all 12 source hashes match |
| 2026-09-09 | F2 development integration ACCEPTED at `e0accfe`; all F2 findings closed; bounded F3 compatibility handoff released | Astra | Final F2 acceptance entry; 270 non-real-LUT and 3 real-LUT tests passed independently, 12 matching source hashes, boundary reproductions closed; physical AC gate remains open |
| 2026-09-09 | Astra F2 review at `acfb995`: CHANGES REQUIRED (F2-R1..R5); keep public guards and F3 closed; F1 remains accepted | Astra | Independent capacitor-only, malformed-request, strict-JSON, supply-identity, and source-coverage reproductions in the final gate-review entry |
| 2026-09-09 | F1 technical review: CHANGES REQUIRED; F2 remains closed | Astra | Independently reproduced domain/extrapolation, ambiguous-root, and nonfinite-output failures; corrections below |
| 2026-09-09 | Accept max_outer=60 as a bounded default; reject the common 1e-9 edge tolerance and inconsistent final evaluation | Astra | Synthetic nominal requires 10 iterations; archived wide real case needs 31; domain deviation contradicts A2 and permits out-of-grid geometry |
| 2026-09-09 | FINAL F1 ACCEPTANCE: APPROVED at db6db4a; R1-R5 closed | Astra | Independently passed 201 non-real-LUT + 3 real-LUT tests; all 9 archived source fingerprints match delivered files; pre-lookup control rejection and archived KCL/trace checks pass |
| 2026-09-09 | Bounded F2 implementation handoff released to Opus; public finite evaluation stays closed until its integrated gate passes | Astra, under A8 | F1 prerequisite satisfied; F2 scope and acceptance requirements remain as amended in A3-A6 |

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

### 2026-09-09 - Astra final F1 acceptance at db6db4a

**Decision: F1 ACCEPTED. All F1 review findings R1-R5 are closed.**
Reviewed revision: `db6db4a5d1607f066289d44a6b1aa9ae50c438fa`.
Opus may proceed with the bounded F2 work package under A8. This is acceptance
of the finite DC kernel and its development evidence, not acceptance of a
complete physical finite OTA or of F2 metrics/AC behavior.

#### Independently verified acceptance evidence

- Full non-real-LUT suite: **201 passed**, exit 0, comprising the 139-test
  baseline and 62 finite-kernel/probe cases. Real-LUT integration: **3 passed**,
  exit 0. Existing dependency deprecation warnings are non-failing.
- Invalid numerical controls reject before any device access. An independent
  sentinel device object that fails on every attribute access confirmed
  rejection of infinite/NaN/zero/boolean tolerance, fractional outer budget,
  and infinite Newton budget. The original `tol=inf` reproduction is closed.
- Valid effective settings are recorded; ordinary returned records serialize
  as strict JSON. Final KCL acceptance remains 1e-9 A, independent of the
  configurable inner target. Solver structure and max_outer=60 are unchanged.
- All **nine** SHA-256 values in the source fingerprint of
  `f1_probe_20260909_045513/f1_real_lut_probe.json` match the delivered files
  independently hashed during this review. The archive's parent revision and
  dirty state therefore no longer leave the executed source unspecified.
  Acceptance rests on these verified content hashes; the diff hash is
  supplementary identification, not a substitute for recoverable source.
- The archive parses as strict JSON and records successful LUT hash checks.
  It contains consecutive trace lengths **12/31/12** for nominal/wide/boundary
  cases and **20** for the intentionally exhausted comparison run.
- For each successful archived case, KCL recomputed from its returned M1-M5
  IDs exactly equals its stored residual dictionary. The maximum archived
  residual is approximately **1.683e-11 A**.
- Independent comparison-helper check: supplied `tol=5e-13` and
  `max_newton=7` are preserved, only max_outer changes to 20, and the caller's
  settings dictionary remains unchanged.
- Parsed definitions of every pre-existing function/class in `dc_solver.py`
  still match `f9798cd`. No implementation source changed during this review.

Commands used for the regression gates:

```powershell
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_integration_real_luts.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_integration_real_luts.py -q
```

No fresh finite real-LUT probe or Cadence campaign was run during this final
review; the submitted archive was checked against the delivered source and
its internal device/trace evidence. The real-LUT integration suite was rerun.

#### Bounded F2 handoff to Opus

1. Begin with the independent complete MNA terminal-equation/stamp audit and
   the real-LUT capacitance convention evidence required by A4. Do not reduce
   F2 to inserting M5 into the old matrix. Preserve the historical ideal path
   if corrected finite AC semantics differ.
2. Implement finite metrics and M1-M5 hard checks, including effective requested
   PM/saturation minima, complete finite evidence, and the A5 policy for
   headroom estimates versus validated range metrics. The archived probe
   margins remain -48.0/-58.6/-48.0 mV: F2's saturation verifier must reject
   these diagnostic points without relaxing the floor.
3. Integrate the minimal seven-parameter finite schema and distinct provenance
   before exposing public finite evaluation. Keep the constructor and per-call
   guards until metrics, constraints, AC, and record handling pass together.
4. Deliver the bounded F2 diff, independent tests, declared capacitance/metric
   assumptions, example valid and invalid records, and regression evidence for
   Astra review. If real capacitance semantics remain unresolved, record that
   limitation and do not claim the physical AC gate has passed.

F1 acceptance does not release later packages or web deployment. F4 still owes
physically feasible finite designs; F5 still owes independent finite-M5 Cadence
correlation. Earlier review decisions and archives remain as history and are
superseded by this acceptance for the current F1 revision.

Plan, HANDOFF, and CORRECTION_LOG updated for this gate. No production fixes,
F2 implementation, commit, or push were performed by Astra during the review;
the pre-existing untracked `astra_review.md` remains unchanged.

### 2026-09-09 - F2 implemented (bounded package per the F1 acceptance handoff)

Order followed the handoff exactly: (1) independent MNA terminal-stamp
audit, (2) real-LUT capacitance-convention evidence, (3) integrated finite
metrics, constraints, and minimal schema. Public finite evaluation REMAINS
CLOSED: `OTA5T.evaluate` still rejects every finite+solved call (guard
tests included), and the negative-saturation probe points are rejected as
feasible designs.

**1. Independent MNA audit (Astra R7).** The complete terminal equations
were derived from scratch and audited against the legacy 3x3 stamps; all
five reported discrepancies reproduce. A corrected assembly
(`MNAEngine.assemble_ac_corrected` / `solve_ac_corrected`) is added for the
finite path; the legacy `solve_ac` is byte-frozen for the historical ideal
oracle. Audited and corrected: (i) M1/M2 body transconductance now acts at
BOTH terminals (legacy had it only in the tail diagonal); (ii) the spurious
tail->drain cgs couplings are replaced by right-hand-side gate excitation;
(iii) the spurious tail->drain cgd couplings (driven gates) are removed and
their excitation moved to the RHS; (iv) M4's gate-drain capacitance is
stamped as a true two-terminal capacitor (legacy had a single +sC
off-diagonal); (v) M3's same-node gate-drain overlap is never stamped
(double-counted under the fixture convention). `tests/test_mna_audit.py`
(10 tests) verifies the corrected assembly ENTRY-FOR-ENTRY against an
independent element-stamp reference assembler on asymmetric devices with
all capacitances and body effect present, body-current conservation at both
terminals, RHS-only driven-gate excitation, the M4 two-terminal stamp, the
M3 no-op, M5 drain-loading-only (gm5/gmbs5 provably ignored), the ideal
limit inside the corrected model, the textbook DC limit with legacy
equality at zero capacitance, full nodal-current closure of the solved
response (< 1e-18), and pins the exact legacy-vs-corrected entry
differences. Honest note: during the audit the independent reference caught
a sign error in the first draft of the corrected RHS (cgs excitation sign) -
fixed before delivery; this is the failure class the audit exists to catch.

**2. Real-LUT capacitance convention (Astra A4) - evidence recorded,
limitation explicit.** In-repository provenance is exhausted: the pickles
originate from a Google Drive download (`archive/kaggle`) with no
characterization deck or save expressions, so the DEFINITION of `cdd`
cannot be established in-repo. A new data-level observation on the real
pickle (nch, VSB=0, 12 samples): cdd/cgd spans 1.21-2.39 (median 1.97) -
consistent with a total drain capacitance (overlap + junction), which
CONSTRAINS but does not establish the convention. The corrected finite
model therefore stamps drain loading as `gds + s*cdd` alone under the
explicitly recorded assumption that Cdd is the complete drain
self-capacitance for grounded gate/source/body; the limitation is carried
in the mna.py module contract, in every finite record
(`capacitance_assumption` field), and in the archived probe. The physical
AC gate is NOT claimed passed; the F5 device-level Spectre experiment
remains the arbiter.

**3. Integrated finite metrics, hard constraints, minimal schema.**
- `OTA5T._evaluate_solved_finite` (private, dev/test access only): DC from
  the accepted F1 kernel; AC from the corrected model with the solved M5 as
  pure drain loading; Power = VDD*(ID3+ID4) with a KCL cross-check against
  VDD*ID5 (measured 6.9e-8 relative on the nominal case, bounded by the
  accepted KCL residuals) and the requested VDD*Itail recorded separately;
  SR recorded as the ID5/CL PROXY with an explicit note; saturation
  evidence for all five devices under the FROZEN 50 mV floor; area
  including M5; A5 headroom ESTIMATES labeled as estimates (Swing_est,
  Vout bounds, ICMR_low_est, in-bounds indicator) with the acceptance keys
  Swing/ICMR_min NaN so any requested range constraint FAILS CLOSED, and
  the upper ICMR limit unreported.
- Effective constraint limits (Astra R1, scoped to the finite path):
  requests may TIGHTEN the PM/saturation floors, never relax them -
  attempted relaxations are clamped up to the frozen default and recorded;
  nonfinite/negative requested minima fail closed. The shared ideal-path
  R1 correction remains a separate versioned task and was NOT silently
  changed here.
- Minimal finite schema (Astra A3): `FINITE_SCHEMA_VERSION`
  ("analog_ai-0.2.0-finite-solved-dev", development identity, distinct from
  the ideal oracle), seven mode-aware parameter names (R4 regression
  covered), VDD/VICM/request echo, complete M1-M5 OP + saturation +
  forward-vs-table gm/Id evidence, KCL/current/ratio errors, convergence
  and clipping diagnostics, effective limits, bias-generator exclusion,
  and the capacitance assumption; strict-JSON nulls for unavailable
  optional metrics; fail-closed invalid records with no truncation.
- `tests/test_finite_evaluator.py` (19 tests): schema identity, seven-name
  serialization, strict JSON, complete evidence, the negative-saturation
  rejection with the frozen floor, the complementary all-saturated PASS
  case, PM/saturation tightening and relaxation clamping, range-request
  fail-closed behavior, power cross-check, corrected-AC provenance
  (reported gain equals an independent corrected-model recomputation and
  DIFFERS from the legacy model), estimate labeling, area/M5 inclusion,
  arity/nonfinite/domain/invalid-spec invalid records, and the still-closed
  public surface.

**Gates and evidence.** Focused: 10 audit + 19 evaluator + 62 F1 tests all
green; complete non-real-LUT suite: 230 collected, exit 0; real-LUT
integration: 3/3, exit 0. Real-LUT F2 integration probe
(`scripts/probe_finite_evaluator.py`, archived under
`evaluation_results/finite_m5/f2_integration_20260909_054929/`): LUT
hashes verified, 9-source fingerprint, strict JSON; both designs integrate
end-to-end (~0.4 s) with gain 31.2 dB, GBW 57.2/11.7 MHz, PM 86.7/90.6 deg
and EXACTLY ONE failed constraint row - Sat_margin_min (sat_m5 -48.0 mV) -
i.e. the archived diagnostic points are rejected as feasible designs, as
required.

**Not done (out of F2 scope, for Astra's attention):** guard removal (F2
task 9 awaits this review), F3 optimizer/export/dataset compatibility, and
the ideal-path versioned R1 correction.

### 2026-09-09 - F2 correction package delivered (addresses F2-R1..R5)

One bounded correction commit addressing Astra's F2 gate review; F1
acceptance untouched; public finite guards stay closed.

**F2-R1 (capacitance double counting).** Under the declared lumped
convention `Cdd = Cgd + Cdb`, the corrected assembly now derives the
junction `Cdb = Cdd - Cgd` per device and stamps the gate-drain ELEMENT
per its true connectivity plus the JUNCTION at the drain - never the total
plus the element. Consequences: M1/M2 drain diagonals carry `Cgd + Cdb =
Cdd` (invariant, but the RHS uses the overlap element only); M3 contributes
only its junction (its overlap is a same-node no-op); M4's output diagonal
carries `Cgd4 + Cdb4 = Cdd4` with the two-terminal overlap element stamped
in full; M5 keeps the total (its overlap and junction both terminate at AC
ground). Astra's three limiting cases are now enforced by tests: a lone
1 pF Cgd=Cdd with zero junction contributes exactly 1 pF (M1: mirror
diagonal + RHS 0.5 pA; M3: nothing; M4: `[[1,-1],[-1,1]]` pF), with the
complementary junction-only cases. Inconsistent inputs (`Cdd < Cgd`)
raise ValueError instead of clipping a negative junction.
`tests/test_mna_audit.py` was rebuilt on a PRIMITIVE reference assembler
(Cgs/Cgd/Cdb, with the engine's total Cdd constructed FROM the
primitives), so the decomposition is verified against primitive truth -
the previous tests varied `cgd` while treating total `cdd` as an unrelated
ground capacitor and encoded the defect; they are replaced. Nodal-current
closure (< 1e-18), full asymmetric matrix/RHS equality, the pinned
legacy-vs-corrected differences (updated for the junction fix), and the
ideal limit are all re-verified.

**F2-R2 (malformed request limits).** New `validate_finite_specs` runs
BEFORE any device work: every supported finite request field is
type-checked (booleans/strings/None rejected), finite, and range-checked
(GBW/CL/Power/SR strictly positive - a nonpositive power limit is
nonphysical and would invert its residual; PM_min in (0, 180]; Gain_min >=
0; Sat_margin_min/Swing_min/ICMR_max >= 0); unsupported fields reject.
Zero-meaningful thresholds keep positive normalization scales (a zero
Sat_margin_min request is clamped to the frozen default, which the
constraint module uses as its scale). All residual scales are therefore
positive on every reachable path. Tests: 17 malformed-field cases
asserting record-level fail-closed behavior (empty constraint rows - a
passing power row against a negative limit is now unreachable), the
unsupported-field case, normalization of a valid request, and the
zero-saturation-threshold scale guarantee.

**F2-R3 (strict JSON on failure paths).** The COMPLETE finite record is
now JSON-safe: constraint rows serialize nonfinite achieved/residual as
explicit nulls with the verdict and reason preserved (failures are never
turned into passes; L_domain's tuple limit/achieved become lists), the
request echo is normalized on success and sanitized on rejection
(nonfinite numerics -> null; strings/booleans preserved as the reason),
and the invalid-design fallback sanitizes NaN values while the
invalid_reason carries the field name. Strict
`json.dumps(record, allow_nan=False)` is now asserted on the range-failure
record, the NaN-design invalid record, the infinite-request invalid
record, and a no-crossing AC record (CL = 1 mF: gbw_valid False, GBW
null, warning retained) - not only on the success-shaped schema.

**F2-R4 (supply context).** The record serializes the EFFECTIVE
`ota.VDD`/`ota.Vicm` (not config defaults) plus a
`supply_context_canonical` flag, and carries the `ac_model` identifier.
Test: a vdd=1.3 evaluation records vdd 1.3 / vicm 0.65 with power
consistent with the actual supply (65 uW at Itail = 50 uA).

**F2-R5 (fingerprint coverage).** The F1 helper keeps its accepted default
contract; a new `source_fingerprint_f2()` extends it with the evaluator
and constraints modules and the actual F2 probe entry point (12 files
total). The F2 probe records the extended set, and the regenerated archive
contains strict-JSON range-failure and malformed-request examples
alongside the ordinary diagnostic records.

**Gates and evidence.** Focused: 13 audit + 36 evaluator + 6 probe tests
green; complete non-real-LUT suite exit 0; real-LUT integration 3/3 exit
0. New immutable archive:
`evaluation_results/finite_m5/f2_integration_20260909_112307/` (LUT
hashes verified, 12-source fingerprint, strict JSON; nominal/boundary
designs verdict=False with exactly Sat_margin_min failing at sat_m5
-48.0 mV; both required record examples included). The earlier archive
(`f2_integration_20260909_054929`) is retained as history. The 50 mV
floor, the accepted F1 kernel, the legacy ideal oracle, and the public
finite guards are unchanged; capacitance provenance remains open for F5.

### 2026-09-09 - Astra F2 gate review at acfb995: changes required

**Decision: F2 is not accepted. Keep the public finite guards in place.**
Reviewed revision: `acfb995f95810b4d2f1174eed9ece914a23facfd`.
F1 acceptance at `db6db4a` remains valid. Opus may implement the bounded
corrections below and resubmit F2; F3, web exposure, and physical AC acceptance
are not released. These are F2 findings, distinct from the closed F1 R1-R5.

#### What is accepted in this delivery

- The added drain-row body terms, driven-gate RHS signs, removal of spurious
  input-capacitor node couplings, and M4's negative mutual capacitor terms
  follow the stated terminal connectivity. M5 remains pure drain loading.
  The source text of legacy `solve_ac` is unchanged from `db6db4a`.
- Five-device saturation, M5 area, supply-current power, and the separately
  labeled slew proxy and headroom estimates are appropriate. The nominal
  synthetic record and both archived real records fail the 50 mV saturation
  floor. Neither diagnostic point is a feasible design.
- Tightened PM/saturation limits and clamped attempted relaxations work for
  ordinary finite numeric requests. Seven named parameters and a distinct
  development schema avoid the historical truncation/oracle-identity defects.
- Recording the unresolved real capacitance convention is appropriate. The
  12 magnitude samples are observations, not a characterization definition.
  A4's physical-AC stop condition remains in force. Development under an
  explicit, internally consistent assumption is permitted; deferral to an F5
  experiment does not itself close that gate.

#### F2-R1 - P1: the corrected matrix still double counts total drain capacitance

**Locations:** `analog_ai/circuit/mna.py:133-142`,
`tests/test_mna_audit.py:89-122`, and `tests/conftest.py:44`.

The fixture defines `cdd = cgd + junction`, and the finite record describes
`cdd` as complete drain self-capacitance with the other terminals grounded.
Nevertheless, the corrected assembler and its reference both stamp the full
`cdd` to ground and a separate `cgd` element for M1/M2/M4. M3 retains the
overlap already embedded in `cdd3` even after the explicit `cgd3` term is
removed. The reference's different programming structure does not make its
capacitance interpretation independent. Its current-closure test repeats the
same interpretation, so algebraic closure cannot detect this error.

Independent limiting-case reproduction: set every device coefficient and CL
to zero, then set only the named device's `cdd = cgd = 1e-12` F. This means
one 1 pF gate-drain capacitor and zero junction capacitance under the declared
lumped convention. At `f = 1/(2*pi)` Hz, `s = j`:

| Device varied | Returned capacitive matrix contribution | Required contribution |
|---|---|---|
| M1 | Mirror diagonal 2 pF; RHS +0.5 pA | Mirror diagonal 1 pF; RHS +0.5 pA |
| M3, gate tied to drain | Mirror diagonal 1 pF | Zero: both capacitor terminals are the same node |
| M4 | Mirror/output block `[[1,-1],[-1,2]]` pF | `[[1,-1],[-1,1]]` pF |

For this explicit lumped convention, derive a junction component
`Cdb = Cdd - Cgd` and stamp it plus the actual gate-drain element. Equivalently,
the corrected capacitive diagonals for mirror/output should be:

```text
Cmirror = Cdd1 + (Cdd3 - Cgd3) + Cgs3 + Cgs4 + Cgd4
Cout    = Cdd2 + Cdd4 + CL
```

The tail diagonal, driven-gate RHS, and M4 mutual terms retain their intended
forms. These equations are conditional on the declared lumped convention;
they do not establish that real signed charge derivatives can be decomposed
this way. Make normalization/convention handling explicit across M1-M5 and
reject inconsistent inputs rather than clipping a negative derived component
or silently interpreting the same key differently by device.

**Required verification:** build independent reference devices from primitive
`Cgs`, `Cgd`, and `Cdb`, then construct the engine's total `Cdd` input from
those primitives. Cover all three limiting cases above, asymmetric full
matrix/RHS equality, and independent current closure. Preserve the legacy
path. Replace the current tests that vary `cgd` while treating total `cdd` as
an unrelated ground capacitor; those tests currently encode the defect.

#### F2-R2 - P1: malformed request limits can pass or escape the record boundary

**Locations:** `analog_ai/evaluation/evaluator.py:155-181,235-243,301-302`
and the reused `analog_ai/evaluation/constraints.py` arithmetic.

Only CL and the two default floors receive finite-path validation. Independent
calls using the synthetic nominal design reproduced:

- `Power_max=-1e-6`: the power row **passes** at approximately 60 uW because
  its scale is negative; residual is approximately -61. The overall nominal
  verdict still fails saturation, which masks this impossible power acceptance.
- `Power_max=0.0`: uncaught `ZeroDivisionError`.
- `PM_min=None`: uncaught `TypeError`.
- `Gain_min="20"`: uncaught `TypeError` in constraint subtraction.

**Required correction:** validate/normalize all supported finite request
fields before device work. Reject nonfinite and invalid types with a clear
invalid record; enforce each field's documented range. All residual scales
must be positive. Where a zero threshold is meaningful, use an independent
positive scale; otherwise reject it explicitly. Handle expected malformed
input errors at the record boundary without broadly hiding programming bugs.
Keep this finite-scoped so historical ideal semantics remain unchanged.

**Required verification:** negative/zero power and GBW/SR scale cases,
null/string/boolean/nonfinite fields, pre-lookup rejection, and a valid
request. Assert both the row behavior and record-level fail-closed behavior;
an unrelated failed saturation row is not evidence of correct power checking.

#### F2-R3 - P2: strict JSON fails on required failure paths

**Locations:** `analog_ai/evaluation/evaluator.py:222,297,305-311`.

Normal metrics use `_finite_num`, but constraint dictionaries, the raw request,
and the invalid-design fallback do not. Independently, each of these returns
a record that fails `json.dumps(record, allow_nan=False)`:

1. Valid nominal design with `Swing_min=0.3, ICMR_max=0.9`: the unavailable
   constraint rows contain NaN achieved values and infinite residuals.
2. `gmid5=NaN`: the invalid-design fallback retains NaN in its seven-value list.
3. `PM_min=Infinity`: the invalid record echoes Infinity in `request`.

The existing tests exercise these paths but apply the strict-JSON assertion
only to the ordinary nominal record. Thus the reported strict-JSON guarantee
does not cover the records most needed for audit and batch evaluation.

**Required correction:** make the complete finite record JSON-safe, including
request echoes, invalid designs, nested diagnostics, and constraint rows.
Represent unavailable/nonfinite numeric fields as null with explicit failure
and reason information; do not turn unavailable constraints into passes or
substitute zero metrics. Preserve the reason a request was invalid. Add strict
serialization/parse checks to each unavailable/invalid-record case and to a
no-crossing AC result, rather than testing only the success-shaped schema.

#### F2-R4 - P2: records report default supply and common mode instead of the evaluated ones

**Location:** `analog_ai/evaluation/evaluator.py:220-221`.

The solver uses `ota.VDD` and `ota.Vicm`, but the record writes `config.VDD`
and `config.VICM`. Independent evaluation with `OTA5T(..., vdd=1.3)` returns
metrics and requested power of 65 uW at Itail=50 uA, while declaring `vdd=1.2`
and `vicm=0.6`; the actual common mode is 0.65 V. This record cannot faithfully
reproduce its own operating point or power definition.

**Required correction:** serialize effective OTA supply/common mode (or reject
noncanonical settings explicitly if the finite contract fixes them). Carry
the actual `ac_model` identifier into the finite record as well; it currently
exists only in the private performance dictionary. Test the nondefault-supply
case and consistency between record context, power, and returned node biases.

#### F2-R5 - P2: the F2 archive does not fingerprint its new evaluator or entry point

**Locations:** `scripts/probe_finite_evaluator.py:100` and the fixed module
list in `scripts/probe_finite_kernel.py:86-97`.

All nine hashes present in the submitted archive independently match the
delivered files. However, the F1 helper's unchanged fingerprint list omits
`analog_ai.evaluation.evaluator`, `analog_ai.evaluation.constraints`, and
`scripts/probe_finite_evaluator.py`. These are precisely the additional
sources that produce the F2 verdicts, schema, and probe configuration.

The archive records parent revision `db6db4a` plus tracked changes. A diff
hash is supplementary identification, not recoverable source or proof that
the omitted files match this delivery. In particular, a new untracked probe
is not represented by `git diff HEAD`. The accepted F1 coverage cannot simply
be inherited by a different executed entry point.

**Required correction:** extend the fingerprint helper with an explicit F2
source/entry-point set, retaining the F1 contract. Add coverage assertions for
the new evaluator, constraint implementation, and actual probe script, with
independent content-hash checks. After the corrections, produce a new immutable
F2 archive whose hashes match the submitted source; retain the old archive as
historical evidence. Include a strict-JSON range-failure and malformed-request
example alongside the ordinary diagnostic records.

#### Independent verification and next delivery

- Complete non-real-LUT suite: **230 passed**, exit 0.
- Real-LUT integration suite: **3 passed**, exit 0.
- Submitted F2 archive parses as strict JSON, records both LUT hash matches,
  and contains two diagnostic records with exactly one failed row each:
  `Sat_margin_min`, with sat_m5 approximately -48.043 mV. Stored gain is
  31.1797 dB; stored GBW is 57.1759/11.6634 MHz. These remain outputs of the
  submitted provisional AC model, not physically validated AC measurements.
- Nine included source hashes match; missing F2 coverage is identified above.
- Legacy `solve_ac` source text is unchanged from the accepted F1 revision.
- The capacitor, JSON, malformed-request, and nondefault-supply reproductions
  above ran independently against the delivered code using the repo's
  synthetic LUT builder. No implementation files were edited to reproduce them.

Regression commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_integration_real_luts.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_integration_real_luts.py -q
```

Opus should deliver one bounded F2 correction package covering F2-R1..R5,
the targeted regression cases, and new source-bound evidence. Keep the 50 mV
floor, accepted F1 kernel, legacy ideal oracle, and public finite guards.
Do not expand into F3 or claim the capacitance provenance gate passed.
Astra will review that concrete revision before guard removal is considered.

This review updated the plan and `astra_review.md` only. No production fixes,
fresh real finite probe, Cadence campaign, commit, or push were performed.

### 2026-09-09 - Astra F2 corrective re-review at a700ae7

**Decision: accept the substantive corrections; final F2 acceptance still
requires two small record-boundary fixes.** Reviewed revision:
`a700ae76dd1ced0ca569b2c517e7bc0d95a24456`. Keep the public finite guards
closed. F1 remains accepted, and F3 is not released.

#### Findings closed and evidence verified

| Finding | Re-review result |
|---|---|
| F2-R1, capacitance double counting | **Accepted.** Independently reran all three capacitor-only reproductions: M1 gives exactly 1 pF and +0.5 pA RHS; M3 gives zero; M4 gives `[[1,-1],[-1,1]]` pF. The rebuilt reference uses primitive Cgs/Cgd/Cdb, and the full asymmetric assembly and terminal-current closure tests pass. Acceptance is conditional on the declared lumped convention, not proof of real LUT semantics. |
| F2-R2, malformed requests | The original negative/zero power, null PM, text gain, and nonfinite field reproductions are **closed**. A sentinel evaluator confirmed rejection without reaching device work. Numeric conversion overflow remains below. The original P1 negative-scale fail-open defect is fixed. |
| F2-R3, strict JSON | The original unavailable-range, NaN-design, and infinite-request reproductions are **closed**, including strict serialization. The no-crossing test passes. Invalid supply metadata remains below. |
| F2-R4, effective context | **Accepted.** Independent evaluation at 1.3 V records 1.3 V supply and 0.65 V common mode, marks the context noncanonical, and preserves the actual supply-based power. The record now carries `ac_model`. |
| F2-R5, source binding | **Accepted.** All 12 hashes in `source_fingerprint_f2` independently match the delivered files, including the evaluator, constraints, and actual F2 probe. F1's default fingerprint coverage remains intact. |

Independent gates: **261 non-real-LUT tests passed**, exit 0, and **3
real-LUT integration tests passed**, exit 0. The accepted F1 DC kernel is
unchanged from `db6db4a` (file comparison after line-ending normalization).
Legacy `solve_ac` and ideal `_evaluate_solved` source text are unchanged.

The new archive
`evaluation_results/finite_m5/f2_integration_20260909_112307/f2_integration_probe.json`
parses as strict JSON and records both LUT hash matches. Both ordinary
diagnostic records still fail exactly `Sat_margin_min`, with sat_m5 about
-48.043 mV. Updated provisional GBWs are 57.4899 and 11.6752 MHz. The range
example also fails Swing/ICMR with null unavailable fields; the malformed
power example has no metrics or constraint rows and an explicit invalid reason.
These are valid development records, not feasible designs or independent
physical AC evidence. A4's real-capacitance stop condition remains open.

#### Remaining F2-R2 boundary - P2: integer-to-float overflow escapes validation

**Locations:** `analog_ai/evaluation/evaluator.py:217,239-240,390-401`.

The supported-field type check admits Python integers, but `float(value)`
can raise before the finiteness check. Independent reproduction, using the
same nominal design and either the synthetic OTA or a no-device-work sentinel:

```python
evaluate_design_finite(ota, nominal_x7, {"Gain_min": 10**400})
# OverflowError: int too large to convert to float
```

This is a valid JSON integer, although it is not representable by the numeric
backend. It must yield an invalid record instead of escaping a batch
evaluation. The failure-echo helper `_json_safe_scalar` performs the same
conversion, so merely catching `OverflowError` around the main evaluation
will move the failure into the error path.

**Required small correction:** handle numeric conversion overflow explicitly
and name the offending field. Make the invalid request/design echo safe for
the same input: retain a JSON-safe raw integer if appropriate, or use null
with the reason preserved. Do not alter the F1 kernel to do this. Apply the
same record-boundary handling to oversized design integers so failure
serialization cannot re-raise. Avoid a blanket exception catch that hides
implementation errors.

**Acceptance tests:** oversized positive/negative request integers and an
oversized design entry return `verdict=False`, null metrics, an explicit
reason, and records accepted by `json.dumps(..., allow_nan=False)`. A sentinel
should prove malformed requests are rejected before device work. Keep ordinary
finite numeric requests and the already-passing malformed cases unchanged.

#### Remaining F2-R3 boundary - P2: nonfinite supply is echoed into invalid records

**Location:** `analog_ai/evaluation/evaluator.py:306-309`, before its `try`.

The effective-context fix correctly reports valid supplies, but copies their
raw float values without validation or sanitization. Both of these constructed
objects reach the finite record path today:

```python
ota = OTA5T(dm, vdd=float("nan"), tail_device="finite", op_point="imposed")
# The same reproduction works with vdd=float("inf").
r = evaluate_design_finite(ota, nominal_x7, ordinary_specs)
# verdict=False after a LUT-domain rejection, but vdd/vicm remain NaN or inf.
json.dumps(r, allow_nan=False)
# ValueError: Out of range float values are not JSON compliant
```

Thus an invalid evaluation context still violates the complete-record JSON
contract. The rejection also happens after device access and reports a LUT
domain error rather than the actual invalid supply setting.

**Required small correction:** validate effective supply/common mode at the
finite record boundary before device access, and construct a JSON-safe
invalid record for malformed context. Require a finite positive supply and
finite common mode within the applicable circuit domain. Preserve the
offending setting's identity in the reason and use null for nonfinite echoed
values. Ensure conversion failures occur inside the protected boundary.
Keep the valid 1.3/0.65 V behavior; do not silently replace bad settings with
canonical defaults or change historical ideal behavior.

**Acceptance tests:** NaN/Infinity supply, nonfinite common mode, and invalid
supply types return strict-JSON invalid records without device work. Retain
the valid canonical and noncanonical supply checks.

#### Bounded next delivery to Opus

Implement only these numeric-boundary corrections and targeted tests. The
capacitance redesign, primitive audit, source coverage, and valid supply
reporting are accepted and need no rework. Keep the 50 mV floor, F1 kernel,
legacy oracle, and public guards unchanged. Submit the exact revision with
applicable regression results and source-bound examples of the two new
failure paths; preserve the existing archives. If rerunning the real F2
probe, write a new immutable directory whose fingerprints match that revision.
No new feasibility search or Cadence campaign is required for this follow-up.

Commands independently completed during this re-review:

```powershell
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_integration_real_luts.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_integration_real_luts.py -q
```

Only this plan and `astra_review.md` were edited. No implementation changes,
fresh finite real-LUT probe, Cadence run, commit, or push were performed.

### 2026-09-09 - F2 record-boundary follow-up delivered (overflow + supply context)

Exactly the two remaining P2 items from Astra's corrective re-review; no AC
redesign, no kernel change, no guard change.

**R2 boundary - integer-to-float overflow.** `validate_finite_specs` now
performs the numeric conversion inside an explicit overflow guard: an
integer that is unrepresentable as a float (e.g. the valid-JSON
`Gain_min=10**400`) raises a deterministic ValueError naming the field
("...is out of representable numeric range") instead of an escaping
OverflowError. `validate_finite_design` applies the same guard per design
parameter (name included). `_json_safe_scalar` passes arbitrary-precision
integers through (valid JSON) and no longer converts them, so failure
echoes cannot re-raise; `_finite_num` gained the same conversion guard so
failure serialization is safe everywhere. No blanket exception catch was
added - implementation errors stay visible.

**R3 boundary - invalid supply context.** New `_effective_supply` validates
the effective supply/common mode at the record boundary BEFORE any device
work: conversion failures (non-numeric settings) and nonfinite or
out-of-range values (VDD must be finite and positive; VICM finite in
(0, VDD)) produce a deterministic reason naming the offending setting; the
record echoes nonfinite values as null and serializes strict-JSON. The
record path fails closed on the reason before specs/design validation or
device access. Valid canonical (1.2/0.6) and noncanonical (1.3/0.65)
behavior is unchanged and still tested.

**Tests.** Eight new boundary tests: oversized positive/negative request
integers and an oversized design entry (verdict=False, null metrics, named
reasons, strict-JSON-safe records, design echo null with the field named),
a sentinel-device object proving oversized requests reject BEFORE device
work, NaN/infinity supply, nonfinite common mode, a malformed supply TYPE
(duck-typed object), and an out-of-range common mode.

**Gates and evidence.** Focused finite suite green (including the eight
new cases); complete non-real-LUT suite exit 0; real-LUT integration 3/3
exit 0. Regenerated immutable archive
`evaluation_results/finite_m5/f2_integration_20260909_114535/`: 12 source
fingerprints independently verified against the delivered files (including
the evaluator, constraints, and the F2 probe), strict JSON, and all four
failure-path examples - range-failure, malformed power, oversized request
integer (reason carries the offending field), and nonfinite supply (vdd
echoed as null, reason names VDD). Earlier archives retained as history.

### 2026-09-09 - Astra final F2 acceptance at e0accfe

**Decision: F2 development integration ACCEPTED. All F2 review findings
F2-R1 through F2-R5, including both remaining P2 boundary cases, are closed.**
Reviewed revision: `e0accfe99721f8b5706ad879601ea78d02a919ae`.
F1 remains accepted. Opus may proceed with the bounded F3 compatibility
package under A8, with the public-activation conditions below.

This is acceptance of the implemented DC/AC integration, finite constraints,
minimal development records, and their software evidence under the declared
lumped capacitance assumption. It is not acceptance of a physically validated
finite OTA, real-LUT capacitance definitions, or the later feasibility and
Cadence campaigns. A4's physical-AC stop condition remains in force.

#### Independently verified evidence

- Complete non-real-LUT suite: **270 passed**, exit 0. Real-LUT integration
  suite: **3 passed**, exit 0. The finite evaluator now collects 54 cases,
  up from 45; this follow-up adds nine parameterized cases. Existing warning
  output is non-failing.
- Positive and negative `Gain_min=10**400` requests now produce invalid
  records with a field-specific representability reason. Their integer echoes
  serialize strictly without another conversion. A sentinel device object
  confirmed no device access.
- Oversized integers independently injected into L1, gmid1, L5, gmid5, and
  Itail produce invalid records, null offending design values, and strict JSON.
  The previous escaping `OverflowError` is closed.
- NaN/Infinity VDD, NaN/Infinity VICM, malformed supply/common-mode strings,
  nonpositive supply, and common mode at or outside the supply endpoints all
  reject before device access. Every independently returned record serializes
  with `json.dumps(record, allow_nan=False)` and names the invalid setting.
- Independent valid synthetic evaluations at 1.2/0.6 V and 1.3/0.65 V retain
  their actual context and supply-based power. The public finite/solved
  override still raises as expected in the reviewed revision.
- All **12** SHA-256 entries in `source_fingerprint_f2` of
  `f2_integration_20260909_114535/f2_integration_probe.json` match independently
  hashed delivered source files. The archive parses as strict JSON and records
  successful verification of both LUT hashes.
- The archive contains both ordinary diagnostic designs plus all four required
  failure examples: unavailable ranges, malformed power, oversized request
  integer, and nonfinite supply. Ordinary designs still fail exactly
  `Sat_margin_min`, with sat_m5 approximately -48.043 mV. Their provisional
  GBWs remain 57.4899/11.6752 MHz. These are converged diagnostics, not feasible
  designs. For all three records with device data, KCL recomputed from the
  returned IDs exactly matches the stored residuals using the kernel's signs.
- Function source text for `solve_operating_point_finite`, ideal
  `solve_operating_point`, ideal `_evaluate_solved`, and legacy `solve_ac`
  remains unchanged from `db6db4a`. To be precise, `dc_solver.py` itself did
  change: the narrow overflow guard in `validate_finite_design` is accepted
  as the requested input-boundary correction. No Newton, sizing, convergence,
  tolerance, saturation-floor, or legacy AC algorithm was changed.

Regression commands completed independently:

```powershell
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_integration_real_luts.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_integration_real_luts.py -q
```

No fresh real finite probe or Cadence campaign was run during this review;
the submitted archive was verified against source and its internal evidence,
and the real-LUT integration suite was rerun.

#### Bounded F3 handoff to Opus

Implement the existing F3 contract/round-trip package. The remaining public
activation work from F2 task 9 belongs in this same compatibility delivery;
it is authorized after this acceptance, subject to the following contract:

1. **Activate dispatch and records together.** Route finite/solved constructor
   and per-call evaluation to the accepted finite implementation. Before
   removing guards, make the generic record entry point route finite/solved
   calls to the finite schema, or reject them explicitly if an entry point
   remains ideal-only. Today `evaluate_design` still uses five names and the
   historical oracle identity; merely removing the OTA guard would expose
   that mismatch. Test public evaluation through the supported loader and
   record entry points, including invalid requests and seven-parameter names.
   Preserve default ideal behavior and explicit invalid-mode rejection.
2. **Complete the seven-parameter contract.** Make optimizer bounds and
   normalization mode-aware; preserve L5, gmid5, Itail, solved Vbias_tail,
   effective supply, CL, optional requests, constraints, and finite provenance
   across the request-to-result round trip. Keep finite schema/oracle identity
   distinct from the frozen ideal oracle and visibly provisional while its
   physical gate is open. Do not regenerate datasets or train models.
3. **Export the actual finite circuit.** Carry returned M5 W/L and gate bias
   into the netlist, with the intended source/body connections and effective
   supply/load context. Verify precision and geometry survive the round trip;
   do not silently round a design and reuse the pre-rounding verdict.
4. **Make compatibility explicit.** Five-output checkpoints and ideal-only
   dataset, RL, web, or correlation consumers must reject unsupported finite
   records/designs instead of truncating or padding. Preserve old evidence,
   models, and ideal outputs under their original identities.
5. **Deliver one bounded diff for Astra review.** Include public dispatch,
   complete finite record and netlist round trips, compatibility failures,
   strict-JSON valid/invalid examples, provenance, and applicable full
   regression evidence. A converged-but-saturation-failing design is a valid
   round-trip fixture if its failed verdict remains explicit. A fresh global
   feasibility search is not needed for this compatibility gate.

The public guards have not been removed by this review. Their removal must
be implemented with the supported record path and its tests, not as an
isolated deletion. F3 acceptance remains subject to Astra's review of the
concrete delivery. F4 feasibility, F5 physical correlation, web deployment,
and seven-output learning remain separate unreleased work.

Plan, HANDOFF, CORRECTION_LOG, and `astra_review.md` updated for this gate.
No implementation edits, commit, or push were performed by Astra. Earlier
review decisions and archives are retained as history and are superseded
by this acceptance for the reviewed F2 revision.

### 2026-09-09 - F3 compatibility package implemented

One bounded package per the F2 acceptance handoff: public activation and
record routing delivered TOGETHER, seven-parameter contract, finite
netlist round trip, and explicit compatibility rejections.

**1. Dispatch and records activated together.**
- `OTA5T`: the finite+solved constructor combination is now supported and
  `evaluate` routes finite+solved to the accepted finite implementation
  (`_evaluate_solved_finite`, unchanged since F2 acceptance). Invalid mode
  strings still raise ValueError; ideal+solved still requires five
  parameters; the finite/imposed historical path is unchanged.
- `evaluate_design` is mode-aware: finite+solved objects route to the
  finite schema (`evaluate_design_finite`, distinct dev oracle identity,
  seven mode-aware parameter names); all other combinations keep the
  historical five-parameter record under the frozen ideal oracle identity.
  A design vector whose length does not match the routed mode raises
  explicitly - never truncated or padded (the imposed-finite historical
  path included).
- Public evaluation tested through the SUPPORTED loader entry point
  (`load_engine_from_paths(tail_device="finite", op_point="solved")`) and
  through the generic record entry point, with invalid-mode and
  invalid-request cases; default loader behavior stays ideal.

**2. Seven-parameter contract completed.**
- `config.design_bounds(tail_device)` returns the mode-correct bounds;
  `de_baseline.optimize_specs` and `optimization/local_refine` derive their
  search domains from the OBJECT's tail mode (a finite object optimizes
  seven parameters and returns a finite record; ideal objects keep the
  frozen five-parameter bounds). Normalization/learning remain five-output
  by design (finite surrogate work is Phase H).

**3. Finite netlist export.**
- The finite branch now exports the ACTUAL circuit: returned M5 W/L and
  the SOLVED `Vbias_tail` as the gate-source dc value (the historical
  zero-volt gate source is removed), the effective VICM in the header, a
  rounding warning, and an explicit refuse-to-export for evaluations
  without a solved bias (imposed-finite). Print precision: W/L at 0.1 nm,
  gate bias at 1 uV. Round-trip test: parsed exported geometry/bias match
  the returned values at print precision and the re-evaluated record
  re-derives the saturation verdict explicitly (the convergence-diagnostic
  fixture stays honestly failing).

**4. Compatibility made explicit.**
- `dataset/build.evaluate_design_row` raises for non-five design vectors
  and for finite+solved objects (the dataset path cannot truncate finite
  designs; datasets regenerate only in Phase H).
- `sizing.size_ideal_tail_ota` rejects finite-tail objects explicitly.
- `correlation.campaign.expected_from_sizing` rejects non-ideal-tail
  topologies (finite correlation belongs to the F5 finite path);
  historical ideal records keep working.
- The RL environment stays five-dimensional by construction; the web
  runtime stays hard-wired to the ideal tail and the guarded
  `size_ideal_tail_ota` entry.
- Old evidence, models, and ideal outputs keep their original identities;
  the finite schema stays visibly provisional (dev identity, saturation
  diagnostics) while the physical gate is open.

**Gates.** New `tests/test_f3_compatibility.py` (15 tests): public
dispatch via loader and direct construction, record routing both ways,
mismatched-length rejection, mode-aware bounds (config + DE smoke + local
refine), netlist geometry/bias precision round trip and refuse-to-export,
dataset/sizing/correlation rejections, and strict-JSON valid/invalid
public record examples. Updated the two former guard tests to assert the
new public dispatch while retaining invalid-mode rejection coverage.
Complete non-real-LUT suite: 285 collected, exit 0. Real-LUT integration:
3/3, exit 0.

**Not done (separate unreleased work):** F4 feasibility baseline, F5
finite correlation (and the capacitance provenance experiment), web
deployment of finite mode, and seven-output learning (Phase H).

### 2026-09-09 - Astra F3 gate review at 2684166: changes required

**Decision: F3 is not accepted; deliver the bounded corrections below before
F4.** Reviewed revision: `268416635bdbc7e10e8d03d1dc1c2dfca087567a`.
F1 and F2 acceptance stand. The correctly routed provisional finite library
entry points may remain enabled; this review does not request a rollback of
the accepted dispatch work or release finite web deployment.

#### Accepted portions and independent verification

- Finite/solved construction, supported-loader dispatch, and the generic
  record route now reach the finite implementation and its seven-field dev
  schema. Ideal defaults and invalid mode checks remain intact. Historical
  record arity checks prevent seven-value truncation at that entry point.
- The mode-aware bounds correctly include all seven parameters. M5's solved
  gate bias replaces the zero-volt export, and imposed-finite export without
  that solved bias rejects. These are useful partial corrections, subject to
  the context and verification findings below.
- Dataset row construction and ideal sizing have explicit rejection checks
  for the tested finite cases. These do not cover every ideal-only consumer.
- **285 non-real-LUT tests passed**, exit 0; **3 real-LUT integration tests
  passed**, exit 0. Independent synthetic reproductions below expose gaps
  outside the assertions in those passing tests.
- Parsed executable bodies of `_evaluate_solved_finite`, ideal
  `_evaluate_solved`, `_evaluate_imposed`, legacy `solve_ac`, and
  `assemble_ac_corrected` are unchanged from `e0accfe`. The finite evaluator
  docstring changed to describe public activation; the accepted calculations
  did not change.

#### F3-R1 - P1: export loses the evaluated supply/common-mode context

**Locations:** `analog_ai/utils/netlist.py:25-37,81-85`.

Independent reproduction using the synthetic nominal finite design:

```python
ota = OTA5T(dm, vdd=1.3, tail_device="finite", op_point="solved")
perf = ota.evaluate(nominal_x7, CL=2.5e-12)
text = export_netlist(perf, cl=2.5e-12)
```

The evaluated context is VDD=1.3 V and VICM=0.65 V. The exported header and
actual sources instead say VDD=1.2 V and VICM=0.6 V. The exporter uses its
default arguments, while the performance dictionary does not carry the supply
or common mode needed to reconstruct the context. The header reports the
export arguments, not necessarily the evaluated values. A caller can likewise
pass a different CL without any consistency check.

**Required correction:** give finite export an authoritative evaluated
context, preferably the complete finite record or an explicit context-bearing
export input. Derive VDD/VICM/CL from it. Reject inconsistent explicit overrides,
or represent them as a new, unevaluated circuit with no inherited verdict.
Keep historical ideal behavior scoped separately. Test noncanonical supply,
nondefault common mode/load, and conflicting overrides through the supported
record-to-export path, not only manually matched default arguments.

#### F3-R2 - P1: the round-trip test does not verify the exported circuit

**Location:** `tests/test_f3_compatibility.py:148-168`; also the unconditional
`proxy-verified design` header in `analog_ai/utils/netlist.py:36`.

The test parses W5/L5/Vbias_tail, checks their print error, and then calls
`evaluate_design_finite(ota, list(NOMINAL), ...)`. None of the parsed values
is used in that evaluation. It does not read back M1-M4 geometry, supply,
common mode, load, or connectivity. Re-running the original gm/ID sizing
targets is not an evaluation of fixed exported devices and bias.

Independent mutation check: wrapping the exporter in memory to change only
`Vdd (vdd! 0) vsource dc=1.2` to `dc=0.1` still lets
`test_netlist_round_trip_rederives_verdict` pass. No production file was
changed for this reproduction. The delivered evidence therefore does not
support the execution log's claim of a re-derived exported-circuit verdict.
The generic export header also calls the known negative-saturation diagnostic
a `proxy-verified design`, despite its failing feasibility verdict.

**Required correction:** parse and verify the complete emitted circuit,
including all device geometry/connections and sources/load. If claiming a
post-export verdict, evaluate the parsed fixed geometry and fixed gate bias;
do not re-size them from the original seven targets. Alternatively, explicitly
withhold the exported-circuit verdict and test that it remains unverified:
serialization agreement and a pre-export verdict are separate facts. This
alternative does not waive the complete geometry/context round-trip checks
or claim physical AC validation. Use print precision that meets the declared
round-trip contract and make rounding/verification status machine-readable.

Add mutation tests for supply, M1/M3 geometry, M5 gate bias, and CL that fail
the semantic round-trip check or invalidate the exported verdict. Preserve
the original request, finite schema/model identity, physical assumptions,
and pre-export pass/fail status in the export evidence. Correct the delivery
log's unsupported verdict claim rather than retaining it as current evidence.
No Spectre campaign is required to demonstrate serialization integrity.

#### F3-R3 - P2: search objectives do not enforce the finite request contract

**Locations:** `analog_ai/optimization/de_baseline.py:28-43` and
`analog_ai/optimization/local_refine.py:31-45,65-66`.

Both objectives call historical `evaluate_constraints(perf, specs)` without
the finite effective limits or finite request validation. Changing only the
number of optimizer bounds does not integrate the accepted finite constraint
contract. Independent evaluations at the same synthetic nominal point:

| Objective | Ordinary request | PM_min=179 degrees and Sat_margin_min=0.3 V |
|---|---:|---:|
| DE | 2.1912072155324798 | 2.1912072155324798 |
| Local | 2.1932484227582925 | 2.1932484227582925 |

The final finite record correctly reports the tightened limits and rejects
them, but the search objective does not change at all. This finding does not
claim a false final PASS; it means the search optimizes a different request
from the verifier. Both objectives also raise `ZeroDivisionError` for
`Power_max=0.0`, after device work, despite the finite record boundary already
having the required request validation.

**Required correction:** normalize/validate the finite request before search
and use its effective limits consistently in DE, local objectives, and final
verification. Keep scalar shaping separate from acceptance, but derive its
residuals from the same finite contract. Invalid requests must reject before
lookup/search; missing requested metrics must remain failed and must not
create NaN/Infinity optimizer bookkeeping or an unhandled no-best-design path.
Scope the change to finite mode so historical ideal behavior remains frozen.

Tests must prove tightened PM/saturation requests change the relevant search
residuals, malformed/zero-scale requests reject before device work, and an
unavailable Swing/ICMR request ends with an explicit failed/unresolved outcome.
The final record must retain the full request and effective limits.

#### F3-R4 - P2: finite local search still runs in physical coordinates

**Location:** `analog_ai/optimization/local_refine.py:73-82`.

The code computes `u0`, but converts its trust-region bounds back to physical
units and passes physical `x0` to Nelder-Mead with `xatol=1e-6`. An independent
interception of the minimizer call confirmed the input vector:

```text
[6e-7, 15, 6e-7, 12, 6e-7, 10, 5e-5]
xatol = 1e-6
```

That one tolerance means 1 micrometer in length coordinates, 1 microampere
in current, and 1e-6 1/V in gm/ID. Adding two bounds does not satisfy A6/F3's
seven-dimensional optimizer/normalization requirement. Deferring learned
five-output normalization to Phase H is correct, but does not defer finite
optimizer coordinate normalization.

**Required correction:** run finite local optimization in normalized design
coordinates with dimensionless trust regions and stopping tolerances. Convert
to physical units at evaluation and back to physical output at the record
boundary. Keep the existing ideal search path unchanged. Test all seven
normalization/denormalization coordinates and endpoints, including Itail at
index 6, actual normalized minimizer inputs, and physical returned designs.
Do not implement finite surrogate training or change historical model scaling.

#### F3-R5 - P2: ideal-only consumers still accept or truncate finite inputs

**Locations:** `analog_ai/envs/sizing_env.py:46-69` and
`analog_ai/surrogate/data.py:134-136`.

Independent reproductions:

- `OTA5tSizingEnv(finite_solved_ota)` constructs successfully with a five-value
  action space. Reset and a zero action produce an ordinary invalid episode
  (`invalid=True`, cost 2000) because the finite evaluator requires seven
  values. The incompatible engine is not rejected. With explicitly supplied
  seven-row bounds, this environment can also construct a seven-dimensional
  action space; it is not unconditionally five-dimensional by construction.
- `design_matrix([finite_record["design"]])` silently returns shape `(1,5)`,
  selecting L1/gmid1/L3/gmid3/Itail and discarding L5/gmid5. The dataset writer
  guard does not protect this direct learned-data consumer.

**Required correction:** reject finite-tail engines at the current ideal-only
RL boundary and reject finite schemas/design fields before five-target
conversion. Apply the same explicit compatibility policy at supported
five-output model/inference entry points; do not rely on downstream arity
errors being converted into ordinary invalid candidates. Preserve supported
historical ideal records and test finite objects, finite seven-field rows,
and checkpoint/engine mode mismatches without launching training. Existing
dataset/sizing guards may remain; they need no redesign.

#### Bounded corrective handoff

Opus should deliver one F3 correction package covering F3-R1..R5 and the
targeted tests above. Keep accepted public finite dispatch/schema routing,
F1/F2 numerical behavior, the 50 mV floor, and historical ideal outputs.
The finite model stays explicitly provisional; do not begin F4 feasibility,
F5 correlation, finite web deployment, dataset regeneration, or retraining.

Include source-bound example evidence of request -> finite record -> export
-> parsed circuit, with effective context, all geometry/bias, metadata and
verification status. Include a known failed diagnostic and an intentionally
corrupted export that the round-trip check rejects. Update the delivery
claims to match the checks actually performed. Submit the exact correction
revision and applicable regression gates for Astra re-review.

Regression commands independently completed during this review:

```powershell
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_integration_real_luts.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_integration_real_luts.py -q
```

Only review/status documents changed. No production fixes, fresh finite
real-LUT probe, optimizer campaign, Cadence run, commit, or push were performed.
The ordinary regression suite includes the delivered bounded DE smoke test;
the independent objective/coordinate probes above were synthetic checks.

## 2026-09-09 - Astra final F3 acceptance at `79c615a`

**F3 is accepted. F1/F2 remain accepted, and F4 feasibility work is now
released as the next bounded package. F5 and later work remain closed.**

Sol 5.6 completed the correction package after Opus reached its execution
limit. Independent Astra review confirmed:

- **F3-R1 closed:** finite export takes VDD, VICM, and CL from the authoritative
  finite record, rejects conflicting overrides, and preserves non-round numeric
  contexts through serialization.
- **F3-R2 closed:** the checker parses and compares all M1-M5 geometry and
  connectivity, tail bias, supplies, differential excitation, load, subcircuit
  instance, schema/oracle/request/capacitance metadata, and duplicate devices.
  It certifies serialization only; `exported_circuit_verdict` remains null until
  external circuit simulation. The exact 0.1 V corruption reproduction rejects.
- **F3-R3 closed:** finite DE and local objectives validate requests before
  device work and use the same effective PM/saturation limits as the finite
  verifier. Missing requested metrics receive finite penalties and remain failed.
- **F3-R4 closed:** finite local refinement runs in seven normalized coordinates,
  including endpoint clipping and Itail at index 6, and returns physical values.
  The ideal local path remains unchanged.
- **F3-R5 closed:** finite engines/records are rejected at the current ideal-only
  RL, learned-data, inference, and checkpoint boundaries; seven-field records can
  no longer be silently reduced to five columns.

Source-bound evidence is archived in
`evaluation_results/finite_m5/f3_correction_export_evidence.json`: all 11 SHA-256
fingerprints independently match `79c615a`; the 1.3/0.65 V, 2.5 pF diagnostic
serializes and verifies; its negative M5 saturation margin and false pre-export
verdict are retained; a VDD mutation to 0.1 V is rejected. This is synthetic
serialization evidence, not physical AC correlation.

Independent gates: 301/301 non-real-LUT tests, 3/3 real-LUT integration tests,
strict evidence regeneration equality, and clean `git diff --check` apart from
the repository's expected LF-to-CRLF notices. The accepted F1 finite solver,
F2 corrected AC assembly, and legacy ideal executable bodies are unchanged.

F4 must now find and archive genuinely feasible finite-tail designs under the
frozen 50 mV saturation floor. Do not reinterpret the existing negative-margin
diagnostics as feasible designs. Capacitance provenance and physical AC
correlation remain F5 gates; finite web deployment and Phase H learning remain
unreleased.

## 2026-09-09 - Sol F4 feasibility-baseline delivery for Astra review

Sol 5.6 completed the bounded F4 real-LUT feasibility package. This is a
delivery record, not gate acceptance: Astra must independently review it before
F5 can be released. No production oracle behavior, frozen request, seven-value
bound, ideal-tail canonical evidence, web path, dataset, or model was changed.

The new runner `scripts/run_f4_baseline.py` verifies both real LUT files against
`configs/lut_manifest.json` before loading them, validates each request before
search, uses the accepted finite objective and final hard verifier, records
invalid exception categories and exact call counts, and writes strict JSON to a
new non-canonical directory. The frozen campaign used seed 0, 42 initial
population members, 12 maximum generations, polishing enabled, and the existing
`DESIGN_BOUNDS_7` plus 50 mV default saturation floor. The historical ideal
solutions were used only as four seed rows for their five shared coordinates;
L5/gmid5 were explicitly varied and the finite verifier alone decided status.

Machine-readable evidence is archived at
`evaluation_results/finite_m5/f4_baseline_20260909_170218/f4_baseline.json`
(SHA-256
`050ff0dabbd13187c95e5a5fff4cbedbc57d9b2b68dee137b7537fcdc9ad5676`).
Its source and five request fingerprints match the delivered workspace. Both
2,763,639,830-byte LUTs were independently checked against the manifest:
NCH `20c15dd9215789d94a438ffd14229f8ab09459474bb965371077a5435ed87e01`
and PCH `ea80ded3113fb3b701b5bbca9fc4f854c1b1742bb716e668dc95fe92ac169a6c`.

All five frozen requests have `verified_feasible` final records with no failed
constraints:

| Request | Full oracle calls | Invalid calls | Runtime (s) | Gain (dB) | GBW (Hz) | PM (deg) | Power (W) | Min sat. margin (V) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| test1_low_power | 555 | 310 | 236.159 | 32.050244 | 20,160,662.268 | 88.947234 | 1.260021e-05 | 0.162139 |
| test2_high_gain | 1,003 | 253 | 252.890 | 35.100066 | 52,755,273.792 | 82.113643 | 3.618571e-05 | 0.152501 |
| test3_heavy_load | 715 | 308 | 248.000 | 26.768564 | 50,119,724.603 | 90.859109 | 1.283411e-04 | 0.124459 |
| test4_light_load | 1,179 | 259 | 259.258 | 28.296307 | 250,000,111.671 | 83.740861 | 3.411768e-05 | 0.129217 |
| test5_balanced | 715 | 277 | 208.166 | 31.251382 | 102,642,533.422 | 82.508426 | 6.779855e-05 | 0.125137 |

Totals are 4,162 optimizer evaluations, five separate final-verification
evaluations, 4,167 full oracle calls, 1,407 classified `InvalidDesignError`
calls during search, and 1,204.473 seconds of per-case runtime. Optimizer
termination by the declared generation cap is retained in the evidence and is
not presented as optimizer convergence; the separately evaluated best designs
nevertheless pass every finite hard constraint.

Delivery gates:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_f4_baseline.py -q
# 4 passed

.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_integration_real_luts.py -q
# 305 collected tests, exit 0; three existing warnings
```

`tests/test_f4_baseline.py` checks strict/source-bound evidence, all five hard
verdicts and 50 mV saturation floor, seven-coordinate initialization, and exact
call accounting. The expensive real-LUT optimization was not repeated after
the completed campaign. F5 Cadence correlation and capacitance provenance,
finite web deployment, dataset regeneration, and Phase H training remain
closed pending Astra's F4 gate decision.

## 2026-09-09 - Astra final F4 acceptance at `43e934b`

**F4 is accepted.** The five frozen requests are all `verified_feasible` under
the unchanged `DESIGN_BOUNDS_7` and frozen 50 mV saturation floor. Astra
independently verified the source/request/LUT bindings, strict JSON, all hard
constraint rows, seven-value bounds, and the 4,167-call accounting, then replayed
all five archived winners through the real LUT evaluator with matching verdicts,
constraints, and principal metrics.

Independent gates passed: 4/4 focused F4 tests, 305/305 non-real-LUT tests, and
3/3 real-LUT integration tests. The accepted F1-F3 executable paths are
unchanged. The non-canonical artifact remains a real-LUT proxy feasibility
baseline; it is not physical AC validation.

F5 is released as the next bounded package under its existing independent
Cadence-correlation contract. Begin with the device-level manual reference,
operating-point extraction, capacitance provenance experiment, and tolerances
frozen before measured validation. Do not expose finite mode through the web,
regenerate datasets, or start Phase H training until F5 passes its own gate.

## 2026-09-09 - Astra F5 manual-reference preparation review at `f7222c0`

**The local F5 preparation package is accepted for one manual smoke test; the
F5 correlation gate is not yet accepted.** The package creates a separate
finite-M5 template and guest path, preserves the ideal correlation sources,
and instantiates the F4 `test5_balanced` winner's M1/M2, M3/M4, and M5 geometry
plus solved `Vbias_tail`.

The tolerance contract in `configs/finite_m5_cadence_tolerances_v1.json` is
frozen before measurement. The manual deck extracts Vtail, Vmirror, Vout,
gain, GBW, PM, power, and ID/gm/gds/gmbs/VDSAT/VDS for M1-M5. A separate
single-device M5 experiment measures grounded-drain and gate-transfer
admittance and Spectre OP cdd/cgd so the LUT cdd convention can be decided
without changing the accepted F2 assumption after seeing a campaign.

Astra required and verified full Cadence-exported diffusion/resistance geometry
expressions on all five OTA devices and M5CAP, a fail-closed resolved-PDK hash
before simulation, re-verification before atomic result emission, binding of
all public job inputs including `design.json`, explicit unavailable failures
for requested SR/Swing/ICMR, and a capacitance decision that also requires
Spectre OP/admittance consistency.

Local gates passed: 9/9 focused tests, 314/314 non-real-LUT tests, 3/3 real-LUT
integration tests, Python compilation, Git Bash syntax validation, all generated
source bindings, and immutable ideal correlation hashes. The one-point OP/cap
enrichment replays the archived F4 winner and performs no optimization.

No external files were staged and no Spectre result exists yet. The next action
is one manual guest run only. Its purpose is to validate the MMSIM14 OCEAN OP
names, capture PDK identity, resolve the capacitance convention, and compare the
manual reference under the frozen tolerances. Do not create or run the locked
validation campaign until Astra reviews that returned raw evidence.

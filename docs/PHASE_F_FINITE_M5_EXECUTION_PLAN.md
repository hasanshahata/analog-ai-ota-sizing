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

**Review status:** awaiting Opus 5

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

## Decision record

| Date | Decision | Owner | Evidence/reason |
|---|---|---|---|
| 2026-09-04 | External M5 gate bias is returned; its generator remains out of scope | Project | Keeps the seven-variable sizing problem explicit and implementable |
| 2026-09-04 | Existing ideal-tail pipeline and web default stay frozen | Project | Preserves validated nominal evidence and deployed behavior |
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

# Astra project review

**Date:** 2026-09-09  
**Reviewed revision:** `f9798cda312b701b6ee3870ea238c849b74db86d`  
**Reviewer:** Astra  
**Scope:** active implementation, tests, stored evidence, and the Sol 5.6 / Opus 5 Phase F proposal. This review changes documentation only.

**Latest gate review (2026-09-09):** F1 remains accepted at `db6db4a`.
**F2 development integration is accepted at `e0accfe`; all F2 findings are
closed.** F3 at `2684166` requires corrections (F3-R1..R5); F4 is not
released. Public finite dispatch/schema routing is accepted, but export,
search-contract integration, normalization, and compatibility remain
incomplete. Real capacitance provenance and physical AC acceptance remain
open. The original project-wide findings below describe the baseline revision
and are retained as history; current details are in the final addendum and
Phase F gate entry.

## Assessment

The project is a useful nominal ideal-tail analog-sizing research application, with a working browser interface, a learned proposal model, optimization fallback, and real Spectre correlation evidence. Its strongest architectural decision is separating proposal generation from hard verification. The dataset also has good, independently checked integrity.

It is **not yet a physically complete solved finite-M5 sizing system**. More significantly, several enforcement and modeling gaps remain underneath the passing tests. Phase F should proceed as a controlled extension with explicit contracts and independent circuit checks; simply adding M5 to the existing solver is insufficient.

The Phase F plan has the right overall sequence and scope. Opus's frozen-bias nested solve is a reasonable implementation choice, but its claims about exact gm/Id agreement, established capacitance meaning, and F2 being only plumbing need correction. My detailed implementation directions are incorporated in [the Phase F plan](docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md#astra-review-and-implementation-directions---2026-09-09).

**Working relationship:** Astra owns architecture, physical assumptions, acceptance criteria, and review of evidence. Opus owns implementation, focused tests, numerical experiments, and documented delivery of each work package. Hassan owns project scope and deployment decisions. This review does not execute Phase F or claim that its gates have passed.

## Verification performed

| Check | Result measured during this review |
|---|---|
| Initial Git working tree | Clean |
| Non-real-LUT test suite, including browser tests | 139 passed; exit code 0 |
| Real-LUT integration suite | 3 passed; exit code 0 |
| NMOS and PMOS LUT SHA-256 | Both match `configs/lut_manifest.json`; each file is 2,763,639,830 bytes |
| Consolidated dataset hashes | Both match `data/pilot/manifest.json` |
| Dataset row counts | 24,588 designs; 33,150 requests |
| Shared design IDs between train/validation/test | Zero for all three pairings |
| Duplicate request/design pairs | Zero, using design ID plus all four request fields |
| Missing referenced design IDs | Zero |
| Positive-label/verdict contradictions | Zero for `feasible` and `near_boundary` |
| Latest tiered-guard campaign | 25 completed; 22 correlation passes; zero recorded false proxy passes |
| Latest campaign raw archive | 25 JSON results and 50 logs; every raw JSON equals its report's Spectre payload |

Commands used for the regression suites:

```powershell
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_integration_real_luts.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_integration_real_luts.py -q
```

The environment had approximately 17.9 GiB available before the real-LUT run. Only one review process loaded the real LUT pair. The non-LUT suite reported two dependency deprecation warnings involving Starlette/httpx and AnyIO; neither caused a failure.

Additional short Python probes used the repository's synthetic LUT generator and temporary files to reproduce findings below. No production source or persistent dataset was modified. No model was retrained, no optimization campaign was regenerated, and no new Cadence simulation was run. Historical large-benchmark results were inspected as stored evidence, not freshly reproduced. The foundry characterization deck and the full contents of historical trainer archives were not audited. No applicable workspace `AGENTS.md` was found.

## Architecture and evidence

| Area | Assessment |
|---|---|
| `devices/` and `circuit/` | Clear split between characterized devices, DC solve, and AC assembly. Domain and interpolation semantics need tightening. |
| `evaluation/` | Correct concept: every constraint decides acceptance independently of scalar cost. Actual validation misses tightened request limits and malformed evidence. |
| `optimization/` | Global DE and local repair are usable baselines. Bounds, units, exceptions, and call accounting need attention before seven-dimensional use. |
| `dataset/` | Design-group splitting and evidence-based negative labels are good choices. Current persisted data passes the integrity checks above. Schemas remain five-dimensional. |
| `surrogate/` | Best-of-K proposals plus verification is appropriate for a many-solution inverse problem. Model metadata and exclusion masking need hardening. |
| `correlation/` | Golden ideal-tail template, private expected values, raw logs, and resumable jobs provide useful independent evidence. The measured verdict is narrower than the oracle contract. |
| `web/` and static UI | Local assets, input validation, controlled failures, and serialized sizing are working. Export validation and presentation can imply more verification than exists. |
| Repository operations | Useful scripts and extensive historical evidence; Python dependency reproducibility and normative documentation lag the implementation. |

Stored [PoC evidence](evaluation_results/canonical/surrogate_poc_summary.md) reports 67.9% primary-head and 85.3% best-of-K success on 1,500 held-out requests with feasible witnesses. [The correction log](docs/CORRECTION_LOG.md) and `evaluation_results/canonical/surrogate_poc_refined_records.json` document recovery of the 220 remaining cases by local refinement. This is evidence of effective repair on that benchmark, not universal feasibility or a fresh untouched test set after repair tuning. A new frozen evaluation cohort is needed for future generalization claims.

The [latest Cadence summary](evaluation_results/cadence_correlation/band18_validation_25/campaign_summary.md) distinguishes **25/25 user-spec passes** from **22/25 correlation-tolerance passes**. Preserve that distinction. The measured deployment verdict currently covers gain, GBW, power, and default PM only. It does not independently validate every saturation and geometry constraint. Zero observed failures in a stratified sample is an empirical gate, not a population guarantee.

## Findings requiring action

Severity: **P1** affects correctness or the next Phase F gate; **P2** affects reliability, reproducibility, or the strength of claims. Each finding states whether it was reproduced or inferred from source inspection.

### R1 — P1: tightened PM and saturation requests are ignored

**Source:** `analog_ai/evaluation/constraints.py`, `evaluate_constraints`, especially the PM and saturation branches; `analog_ai/sizing.py`, request filtering.

The verifier reads PM and saturation thresholds from default `limits`, ignoring `specs['PM_min']` and `specs['Sat_margin_min']`. A reproduced performance dictionary with PM=60 degrees and minimum saturation margin=0.06 V **passes** a request for PM>=80 degrees and margin>=0.10 V. The emitted limits remain 45 degrees and 0.05 V. The deployment sizing helper also retains only the four base request keys, dropping optional constraints.

Use a single effective-request contract. Requested minima may tighten the frozen floors; explicit experimental relaxation must have separate provenance. Preserve supported optional constraints through optimization and serialization, or reject unsupported fields. Test tightened, absent, invalid, and attempted-relaxation cases. This requires a versioned contract correction, not rewriting historical verdicts.

### R2 — P1: the finite/solved prohibition can be bypassed

**Source:** `analog_ai/circuit/ota5t.py:80`, `evaluate`, and `_evaluate_solved`.

The constructor checks the mode combination, but the per-call `op_point` override does not. Reproduced:

```python
ota = OTA5T(dm, tail_device="finite", op_point="imposed")
perf = ota.evaluate([0.6e-6, 15, 0.6e-6, 12, 50e-6],
                    CL=1e-12, op_point="solved")
assert perf["devices"]["M5"]["type"] == "ideal_tail"
```

A finite-configured object returns ideal-tail results from a five-value vector. Unknown override strings also fall through to imposed mode. Enforce the mode matrix and vector arity at evaluation entry, including overrides. Keep all unsupported finite/solved entry points closed until the complete finite evaluator is ready.

### R3 — P1: seven parameter names have only six bounds

**Source:** `analog_ai/config.py:29`; both optimizer modules.

`DESIGN_BOUNDS_7` appends L5 and gm/Id5 to the first four bounds but omits Itail. Measured lengths are **7 names, 6 bounds**. The plan's verified-starting-point claim is therefore wrong. Global DE, local refinement, surrogate normalization, and dataset construction still use five-dimensional constants.

Define the finite bounds as the first four bounds, the two M5 bounds, then the original Itail bound. Add name/order/arity checks and pass a mode-specific immutable contract to consumers. Fix finite bounds before F1 input validation, rather than waiting until F3. Keep existing model output dimensions unchanged.

### R4 — P1: evaluation records can silently corrupt the design and omit solver evidence

**Source:** `analog_ai/evaluation/evaluator.py`, record construction and `dc_diagnostics`.

The serializer zips every vector against five names. For a seven-value vector, it records **L5 as Itail** and drops gm/Id5 and the actual current. This was reproduced even on the invalid-record path. Solved `Vout`, KCL residuals, achieved gm/Id, body bias, and domain diagnostics are not preserved in the normal evaluation record. Provenance contains one shared oracle string and a timestamp, without distinguishing imposed/solved or ideal/finite semantics.

Require exact mode-aware serialization, explicit schema/oracle IDs, topology, operating-point mode, supply/common mode/load, complete DC diagnostics, and all finite geometry/bias. Persist this before any public finite path can emit results. A new finite schema must reject five-dimensional checkpoints and retain historical record interpretation.

### R5 — P1: the claimed strict LUT contract is not strictly enforced

**Source:** `analog_ai/devices/lut.py:79` and `lookup_vgs`.

The same absolute `1e-9` domain tolerance is applied to lengths in meters and voltages in volts. Because the interpolator extrapolates, a length **0.5 nm below the synthetic LUT's minimum** is accepted and evaluated. A query 1.1 nm below is rejected. This tolerance is substantial on a 60 nm length axis.

The inverse lookup also accepts targets outside the actual branch endpoints within a one-percent-span tolerance and feeds them to `np.interp`, which returns an endpoint. A target 0.001 1/V below the measured minimum was accepted and returned VGS=1.2 V. Small permitted branch increases also mean the reversed interpolation coordinates are not guaranteed ordered.

Separate branch-quality tolerances from achievable-range validation. Use unit-aware boundary handling and explicitly reject final extrapolation. Grid endpoints must remain legal: VSB=0 is essential for M5, so “strictly inside” must mean **within the closed characterized domain without extrapolation**, not excluding endpoints. Do not globally change the frozen oracle unnoticed; introduce versioned semantics and comparison evidence.

### R6 — P1 for Phase F: reverse gm/Id agreement does not prove returned gm/current agreement

**Source:** `analog_ai/devices/lut.py`, `_point` in `analog_ai/circuit/dc_solver.py`; Opus's tolerance proposal.

The code interpolates `gm`, `ids`, and tabulated `gmid` independently. On the synthetic NMOS table, at L=0.6 um, VDS=0.15 V, VSB=0 and requested gm/Id=15 1/V:

| Quantity | Reproduced value |
|---|---:|
| Reverse-lookup VGS | 0.4827813487 V |
| Forward interpolated `gmid` | 15.0 1/V |
| Forward `gm` | 3.749327969e-5 S |
| Forward `ids` | 2.707064186e-6 A |
| Ratio of returned gm to returned current | 13.85016280 1/V |

This discrepancy is interpolation error, not floating-point roundoff. Define the finite achieved quantity explicitly as returned `gm / ID`; report table gm/Id separately. If the gate is 0.001 1/V, use a branch-restricted scalar solve of the actual ratio or demonstrate that the chosen interpolation meets it. Never satisfy the gate by reporting only the inverse table's own answer.

### R7 — P1: shared AC assembly needs a terminal-by-terminal audit

**Source:** `analog_ai/circuit/mna.py:49`; `tests/test_mna.py`; `tests/conftest.py::_caps`.

Source inspection identifies specific discrepancies with the stated lumped MOS model:

- NMOS body transconductance enters the tail diagonal, but is absent from the drain-row tail coefficients at `Y[1,0]` and `Y[2,0]`. The same controlled drain-source current must contribute at both terminals.
- Input-device `cgd` is placed between tail and drain in the source-row off-diagonals even though the gate is externally driven. Capacitive input excitation is missing from the right-hand side.
- The fixture defines `cdd = cgd + junction`, while drain diagonals add both `cdd` and `cgd`. That double-counts overlap under the fixture's convention.
- M4 gate-drain coupling is not stamped as the corresponding two-terminal capacitor under that convention.

These are circuit-law/source findings; their complete effect on real-LUT accuracy was not numerically characterized here. The controlled-current and lumped-capacitor reference is [MIT 6.012, Lecture 11, pages 5 and 14](https://ocw.mit.edu/courses/6-012-microelectronic-devices-and-circuits-fall-2005/ce96d1ec5951846e0d1240383b10d8af_lec11.pdf). This reference establishes terminal connectivity, not the proprietary pickle's capacitance definitions.

For M5 alone, with gate/source/body at AC ground, a drain self-admittance `gds5 + s*Cdd5` is plausible **if Cdd5 has that documented meaning**. It does not validate the other four device stamps. Existing tests mainly prove approximate limiting responses and that changing a capacitor changes the result; they do not prove complete terminal stamping. F2 needs independent matrix/terminal-current tests, including asymmetric cases. Preserve the old ideal oracle as a versioned historical implementation; do not silently recalibrate its guard after a shared-MNA correction.

### R8 — P1: generic export does not reproduce the evaluated circuit

**Source:** `analog_ai/utils/netlist.py:56`.

Finite export drives M5's gate with 0 V. Ideal export clamps the tail node with an ideal voltage source, whereas the solved oracle models an ideal current source with infinite small-signal output resistance. A voltage source AC-grounds the tail. These are different circuits.

The browser uses the separate golden-template renderer, whose ideal current source is correct; do not conflate that working path with the generic exporter. Consolidate supported export contracts, emit the returned finite bias with adequate precision, and test topology as well as text. Pinning a tail voltage is only an explicitly named diagnostic testbench. Exported geometry must be re-verifiable after any rounding or legal-grid snapping.

### R9 — P1 for F5: measured Cadence passes cover an incomplete contract

**Source:** `analog_ai/correlation/campaign.py:130`; `analog_ai/correlation/ocean.py`.

The measured verifier enforces four metrics and always uses default PM. It ignores requested tighter PM and all per-device saturation evidence. The OCEAN generator explicitly defers device OP extraction. A reproduced measured PM=60 degrees passes a request for 80 degrees.

F5 must add and validate device OP extraction before labeling a finite design independently verified. Check all requested constraints using measured evidence, validate finite numeric fields, and report missing measurements as unavailable/failing. Store netlist/measurement-script/PDK identity with results; the current collector primarily joins on case ID, and the runner skips existing results without establishing that their input hashes match. Use new immutable job IDs and input-hash checks for reruns.

### R10 — P2: malformed evidence is not consistently fail-closed

**Source:** `analog_ai/evaluation/constraints.py` and `evaluator.py`.

Reproduced: PM=+infinity, minimum saturation margin=+infinity, and an empty device dictionary pass the structural verifier with empty specs. Width maxima default to zero for missing devices. NaN is checked, but infinities and mandatory device completeness are not. This probe demonstrates verifier weakness; it does not establish that today's normal web solver emits that malformed record.

Also reproduced: `evaluate_design(..., design=None, ...)` raises `TypeError`, and a nonnumeric design raises `ValueError` during serialization before the advertised invalid-record exception handler. `record_to_json` permits JSON NaN/Infinity; the web layer has a separate sanitizer.

Validate request/design types, finite required metrics, positive finite geometry, mandatory devices, and positive normalization scales before calculating residuals. Allow ideal-device sentinels only in explicitly nonphysical fields. Use consistent invalid records and strict JSON with null plus a reason for unavailable optional metrics. Retain enough error categories to distinguish numerical rejection from programming errors.

### R11 — P2: export validation is weaker than its API documentation

**Source:** `analog_ai/web/app.py::NetlistRequest`; `analog_ai/correlation/spectre_job.py:63`.

The web route describes verified, domain-validated geometry, but accepts arbitrary positive finite values without linking them to a sizing result. The golden renderer checks positivity, not canonical width/length/current limits; direct use even accepts positive infinity. A probe rendered 1 nm lengths, 1 m widths, and `Itail=inf`. Pydantic prevents infinity at the HTTP boundary, but not the out-of-domain finite geometry.

Either describe this endpoint as an unverified geometry renderer or require a stored verified-result identity and enforce full bounds. The normal UI supplies a successful result, but the endpoint itself does not establish verification. This is a correctness/trust-label issue, not evidence of command injection.

### R12 — P2: risk-row exclusion produces mismatched training tensors

**Source:** `analog_ai/surrogate/data.py:105`, `build_split`.

The exclusion mask is applied to risk labels and returned rows, but not to feature/design arrays. A valid `polish_failed` probe returns shapes X=(1,4), D=(1,5), y=(0,), rows=0. The training script passes X and y to `TensorDataset`, so datasets containing excluded valid rows can break risk training. The current pilot has no `polish_failed` label, explaining why current evidence is unaffected.

Filter aligned rows before constructing all arrays, or return separate explicitly aligned proposal and risk datasets. Add a mixed-label test before Phase H.

### R13 — P2: optimization accounting and scaling need clearer contracts

**Source:** `optimization/local_refine.py`, `optimization/de_baseline.py`, `surrogate/evaluate.py`, `sizing.py`.

Local search computes normalized bounds but runs Nelder-Mead in physical coordinates with a shared `xatol=1e-6` across meter-valued lengths, ampere-valued current, and gm/Id. Thus the stopping criterion is not dimensionally balanced. Broad `except Exception` converts implementation defects into invalid-candidate penalties. Reported optimizer `nfev` omits verifier evaluations and the final deployment reevaluation. These issues do not negate measured successful verdicts, but weaken reproducibility and performance comparisons.

Run finite local optimization in normalized coordinates, use typed expected-failure exceptions, and count oracle evaluations at one boundary. Preserve historical counts as historically defined. Treat exhausted search as unresolved, never proof of infeasibility.

### R14 — P2: provenance, setup, and UI wording lag the supported scope

**Sources:** `loader.py`, `surrogate/train.py`, `web/runtime.py`, `README.md`, `pyproject.toml`, `web_app/static/app.js`.

- Normal engine loading does not verify the manifest. Optional LUT verification occurs after unpickling. Match trusted hashes before deserialization and validate model/schema/oracle compatibility at startup. The review verified the local assets; the runtime does not currently enforce that linkage.
- Python requirements are mostly lower bounds, with no committed Python lock. The basic README setup omits dependencies used by current dataset and web/surrogate tests. Document core/dev/web/ML environments and capture a reproducible tested environment.
- `champion.json` contains Windows separators; using `Path(...).name` on POSIX does not extract the intended filename. Store a portable relative filename or normalize both separators.
- Loader and OTA constructors default to imposed mode although documentation presents solved mode as canonical. Preserve legacy compatibility while making canonical entry points explicit.
- The UI snaps displayed W/L and current without reevaluating the snapped circuit, repeats a global minimum saturation margin in each device row, labels an ideal current source as saturation-checked, and hardcodes a 0.94 Spectre-UGF estimate. Label displayed approximations and global margins clearly; make any predictive calibration versioned and visibly estimated.
- The README/design contract overstate that LUTs replace Spectre end to end or leave no DC correlation work. Characterization provenance, interpolation, scaling, topology, and testbench agreement still need independent checking. Historical status documents should be labeled snapshots, with one current handoff as the entry point.

## Phase F review decision

The Sol planning structure is suitable after correction: separate finite solver, frozen ideal behavior, no inherited guard, no seven-output learning until correlation, and independent F4/F5 evidence. The bounds error, existing dispatch bypass, incomplete verifier, and shared-MNA concerns must become explicit work items.

Opus's proposal is accepted in direction with these qualifications:

1. Freeze W1/W3/W5 and the M5 gate voltage during each inner KCL solve. Check gate-bias convergence as well as width convergence. Freezing is a numerical design choice; an algebraically eliminated bias formulation is not inherently physically wrong merely because Newton trial points differ.
2. Recompute every final device at returned fixed geometry/bias. Do not assume convergence checks hold merely because a sizing equation was used earlier.
3. Measure physical `gm/ID` independently of tabulated gm/Id. Opus's 0.001 1/V threshold is a proposed gate requiring a compatible inverse method and evidence.
4. Reject excessive final W5, but do not automatically call an oversized initial guess infeasible. Seed or damp updates, record failures, and keep invalid versus constraint-failing states distinct.
5. The external gate bias does not stack in the drain-source headroom path. The relevant tail condition is Vtail>=VDSAT5 plus any required saturation margin.
6. Treat swing/ICMR formulas as frozen-operating-point headroom estimates. They do not prove a large-signal swing or common-mode range; fixed-geometry sweeps would be required for those claims. Missing requested metrics must fail closed.
7. Delay public finite evaluation until metrics, constraints, serialization, and provenance are all ready. Move minimal schema work forward; postponing it until F3 while exposing F2 results is inconsistent.
8. Add an independent AC derivation and a device-level Cadence contract. Do not weaken the capacitance stop condition on the strength of a synthetic fixture.

## Recommended implementation order

| Order | Owner and deliverable | Review condition |
|---|---|---|
| 1 | Astra: freeze the amended finite contract and numerical definitions | Resolve the explicit gm/Id and capacitance evidence requirements |
| 2 | Opus: F1 finite DC kernel and focused failure tests | Seven bounds, fixed-bias KCL, true achieved ratio, final domain checks, closed public dispatch |
| 3 | Opus: F2 AC/constraints plus minimal finite record schema | Independent stamp tests; no finite records labeled as the old oracle |
| 4 | Opus: F3 optimizer/export/schema compatibility | Seven-value round trip; finite bias preserved; old models explicitly incompatible |
| 5 | Opus: F4 bounded real-LUT baseline | Immutable evidence; unresolved outcomes described honestly |
| 6 | Opus with the Cadence environment: F5 manual OP then disjoint campaigns | Separate correlation and full measured-constraint gates; frozen holdout policy |
| Each gate | Astra: inspect code, independent tests, failures, and evidence | Review the concrete package before expanding scope |

Shared correctness fixes that affect existing ideal-tail results need a separate versioned migration and correlation decision. Preserving a historical oracle is compatible with acknowledging its limitations; it is not a reason to inherit incorrect semantics into the finite oracle.

## F2 gate-review addendum - 2026-09-09

**Reviewed revision:** `acfb995f95810b4d2f1174eed9ece914a23facfd`.
**Decision:** changes required; F1 remains accepted. Astra independently ran
the complete non-real-LUT suite (230 passed) and real-LUT integration suite
(3 passed). The legacy `solve_ac` source is unchanged, and the two submitted
real finite diagnostic records correctly fail the frozen saturation floor.

Five reproduced findings block F2 acceptance:

| Finding | Priority | Evidence and required correction |
|---|---|---|
| F2-R1: inconsistent capacitance interpretation | P1 | Both corrected assembly and reference stamp total `cdd` plus separate `cgd`. A lone 1 pF gate-drain capacitor becomes 2 pF at an M1 drain and leaves a spurious 1 pF on diode-connected M3. Derive the reference from primitive capacitors and normalize the total-drain convention consistently. |
| F2-R2: incomplete finite request validation | P1 | `Power_max=-1e-6` passes its row at about 60 uW; zero power, null PM, and text gain cause uncaught exceptions. Validate every supported request field and keep residual scales positive. |
| F2-R3: incomplete strict-JSON handling | P2 | Requested unavailable ranges, a NaN design, and an infinite PM request all return records rejected by strict JSON. Normalize every record field while retaining explicit failed verdicts/reasons. |
| F2-R4: incorrect evaluated context | P2 | An actual 1.3 V / 0.65 V evaluation records default 1.2 V / 0.6 V. Serialize effective supply/common mode and the AC-model identifier. |
| F2-R5: incomplete F2 source binding | P2 | All nine included hashes match, but the new evaluator, constraint module, and actual F2 probe entry point are absent. Extend coverage and regenerate immutable evidence after correction. |

The detailed reproductions, conditional capacitance equations, test
requirements, and bounded Opus handoff are recorded in
[the Phase F plan](docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md#2026-09-09---astra-f2-gate-review-at-acfb995-changes-required).
The real capacitance definition remains unresolved; magnitude ratios and
passing self-consistency tests do not establish physical AC correctness.
Keep the public guards until Astra reviews the corrected integrated package.

Only review documents changed. No implementation fixes, fresh finite real-LUT
probe, Cadence run, commit, or push were performed during this F2 review.

## F2 corrective re-review - a700ae7, 2026-09-09

The substantive corrections are accepted: the primitive capacitor reference
and corrected matrix now agree with the independent limiting cases, effective
supply context is accurate, and all 12 source fingerprints match. The original
malformed-request and strict-JSON reproductions also pass. Independently:
**261 non-real-LUT tests and 3 real-LUT integration tests passed**. The F1
kernel and historical ideal implementations remain unchanged.

**Final F2 acceptance is pending two P2 boundary fixes:**

- `Gain_min=10**400` raises an uncaught `OverflowError` during float
  conversion. The invalid-request echo repeats that conversion, so both
  validation and failure serialization need protection. Apply the same
  record-boundary handling to oversized design entries.
- An OTA constructed with NaN/Infinity supply returns an invalid record
  containing nonfinite `vdd`/`vicm`; strict JSON still raises. Validate the
  effective context before lookup and sanitize its invalid-record echo.

The accepted AC correction does not need redesign. Keep public finite guards
closed, F1 accepted, the 50 mV floor unchanged, and F3 unreleased until the
small follow-up is reviewed. Real capacitance provenance remains an open
physical-AC gate. Detailed reproductions and the bounded Opus handoff are in
[the final plan entry](docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md#2026-09-09---astra-f2-corrective-re-review-at-a700ae7).

Only the plan and this review changed; no implementation edits, fresh finite
probe, Cadence run, commit, or push were performed.

## Final F2 acceptance - e0accfe, 2026-09-09

**F2 development integration accepted; all F2-R1..R5 findings and boundary
follow-ups are closed.** Reviewed revision:
`e0accfe99721f8b5706ad879601ea78d02a919ae`.

Independently verified **270 non-real-LUT tests and 3 real-LUT integration
tests passed**. Oversized request/design integers and invalid supply/common
mode now reject before device work and yield strict-JSON records. Valid
1.2/0.6 V and 1.3/0.65 V context and power remain correct. All 12 source
fingerprints in `f2_integration_20260909_114535` match the delivered files;
the archive includes both diagnostics and all four failure examples.

The solver function bodies and legacy ideal AC remain unchanged. The finite
design validator's narrow conversion-overflow guard is accepted. Negative
M5 margins still fail the frozen 50 mV floor; these records do not establish
feasibility or physical AC accuracy. The real capacitance definition remains
an open A4/F5 evidence requirement.

Opus may start the bounded F3 compatibility package. Public activation must
include mode-aware record routing: the current generic `evaluate_design`
still uses five names and the historical oracle identity. Preserve ideal
defaults and complete the seven-parameter/netlist round trip and explicit
rejection by unsupported consumers before submitting F3 for review. Full
instructions are in the [final F2 acceptance and F3 handoff](docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md#2026-09-09---astra-final-f2-acceptance-at-e0accfe).

Only review/status documents changed. No implementation edits, fresh finite
real-LUT probe, Cadence campaign, commit, or push were performed by Astra.

## F3 gate review - 2684166, 2026-09-09

**Decision: changes required.** Reviewed revision:
`268416635bdbc7e10e8d03d1dc1c2dfca087567a`. F1/F2 acceptance stands, and
the public finite dispatch/schema routing is accepted. Independently:
**285 non-real-LUT tests and 3 real-LUT integration tests passed**.
Executable finite/ideal evaluation and AC bodies remain unchanged from F2.

| Finding | Priority | Independently verified gap |
|---|---|---|
| F3-R1: export context | P1 | Evaluation at 1.3/0.65 V exports 1.2/0.6 V by default. Finite export must consume and check the actual evaluation context. |
| F3-R2: unsupported round-trip verdict | P1 | The test ignores parsed W/L/bias when re-evaluating the original target vector. It still passes with the exported supply mutated to 0.1 V. The export header also labels a failed diagnostic as proxy-verified. |
| F3-R3: search request mismatch | P2 | Both objectives give identical costs after tightening PM/saturation; `Power_max=0` raises after evaluation. Use finite validation/effective limits consistently through search and final verification. |
| F3-R4: optimizer normalization missing | P2 | Finite Nelder-Mead still receives mixed physical units with a shared `xatol=1e-6`. Seven bounds do not provide dimensionless optimizer coordinates. |
| F3-R5: incomplete compatibility | P2 | RL accepts a finite engine and produces invalid episodes; `design_matrix` silently converts a seven-field finite design to five targets. Reject incompatible inputs at these boundaries. |

Detailed reproductions and the bounded correction contract are in the
[F3 gate-review entry](docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md#2026-09-09---astra-f3-gate-review-at-2684166-changes-required).
The round trip must check the actual emitted circuit. A post-export verdict
must be derived from fixed exported devices/bias or explicitly withheld;
re-sizing the original targets is not that verification. Finite surrogate
training remains Phase H; finite optimizer normalization belongs to F3.

Only review/status documents changed. No production fixes, new finite
real-LUT probe, feasibility campaign, Cadence run, commit, or push were made.

## Final F3 gate review — accepted at `79c615a` (2026-09-09)

Sol 5.6 completed the bounded correction package after Opus reached its limit.
I independently verified that F3-R1 through F3-R5 are closed: exported supply,
common-mode, and load values come from the finite record; the round-trip checker
uses the parsed complete circuit and rejects the 0.1 V corruption; finite search
uses validated effective limits; finite local refinement uses all seven normalized
coordinates; and ideal-only RL/surrogate boundaries reject finite inputs.

The source-bound diagnostic retains its failed pre-export verdict and negative
M5 saturation margin. Its machine-readable `exported_circuit_verdict` is null,
which is the correct status until external circuit simulation. All 11 evidence
hashes match the accepted source and regeneration is identical.

Independent gates passed: 301 non-real-LUT tests and 3/3 real-LUT integration
tests. The accepted F1/F2 numerical kernels and legacy ideal executable bodies
remain unchanged. F3 is accepted and F4 feasibility may begin. F5 correlation,
finite web deployment, and Phase H learning remain closed.

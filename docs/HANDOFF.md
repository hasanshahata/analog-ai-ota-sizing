# HANDOFF — project state & how to continue on another PC

Written 2026-09-02. If you are reading this after moving the folder to a new
machine, this file is the entry point. It is updated whenever work pauses.

---

## 1. What this project is

RL/optimization system that sizes a 65 nm TSMC 5T-OTA against Gain/GBW/CL/
Power targets. The device physics is **Spectre-characterized LUT data**
(`tech_luts/*.pkl`, 2.76 GB each) — that data *is* the Spectre replacement.
The canonical evaluator completes the chain with a **KCL-solved DC operating
point** derived from those same LUT curves (no imposed bias, no simulator).
Learned PPO models exist (V1–V12, in `models/`) but the best one (V12) is
*not* goal-conditioned; the project is mid-way through the correction plan
(`docs/codex_plan.md`) that replaces reward tweaking with
oracle → dataset → supervised model → verifier.

## 2. Current state (evidence, all in `evaluation_results/canonical/`)

| Evaluation | Source | Result | Files |
|---|---|---|---|
| V12 model, imposed op point | `model` | 1/5 PASS (test 3 only), fixed design | `model_results.md` |
| V12 model, solved op point | `model_solved` | 1/5 PASS — same conclusion | `model_solved_results.md` |
| Constant median design, imposed | `constant` | 1/5 PASS (identical test to V12 ⇒ policy ≈ constant) | `constant_results.md` |
| Constant median design, solved | `constant_solved` | 1/5 PASS — same conclusion | `constant_solved_results.md` |
| Differential-evolution baseline, imposed | `baseline_de` | **5/5 PASS** | `baseline_de_summary.md` |
| DE baseline, solved op point | `baseline_de_solved` | **5/5 PASS** (completed 2026-09-02 on the new PC) | `baseline_de_solved_summary.md` |

Tests: **60 unit tests + 3 integration tests pass** (integration auto-skips
without the LUTs). One caveat: running the integration tests *while* a
baseline process holds both LUTs in memory can error on a ~14 GB machine
(memory contention) — run them when nothing else has the LUTs loaded.

## 3. Setting up a new PC

Requirements: Python 3.11 (3.12+ works for everything except loading the
Kaggle-era model zips), ~8 GB free disk beyond the repo, ≥ 8 GB RAM for the
LUTs. NOTE (2026-09-03): version control is restored as a **fresh repo**
(branch `main`, tag `oracle-v0.1.0+dataset-pilot`) — the original history
still lives only on the old machine. Also beware: a stray git repo exists at
the user's home directory root — always run git from inside the project.

```bash
# from the repo root
py -3.11 -m venv .venv          # or: uv venv --python 3.11 .venv
.venv/Scripts/pip install numpy scipy gymnasium pytest          # Windows path
# Linux/macOS: .venv/bin/pip install numpy scipy gymnasium pytest
# optional, for loading/training PPO models (~2.5 GB):
#   pip install stable-baselines3==2.9.0 torch --index-url https://download.pytorch.org/whl/cpu

# smoke test (no LUTs needed, ~15 s):
.venv/Scripts/python -m pytest tests/ --ignore=tests/test_integration_real_luts.py

# full test incl. real LUTs (~1-4 min, needs tech_luts/ present):
.venv/Scripts/python -m pytest tests/
```

**Files that must travel with the folder** (excluded from git by size):
`tech_luts/TSMC_fast_65nm_nch.pkl` and `..._pch.pkl` (2.76 GB each). Model
zips and checkpoints ARE in git. If `tech_luts/*.pkl` are missing, everything
still runs on the synthetic-LUT test suite — only real-data runs skip/fail.

## 4. In flight — nothing; execution-plan Phases A-C complete (2026-09-03)

**State of the system** (all evidence in `evaluation_results/canonical/`):
LUT oracle + solved DC + hard verifier; DE baseline 5/5; pilot dataset with
zero-leakage splits; best-of-5 surrogate + OOD risk head. The full
deployment ladder now reads: propose 5 heads -> verify -> bounded local
refinement around the best heads -> global DE (never needed so far).

**End-to-end held-out results (1,500 verified requests, champion seed2):**

| Ladder stage | Pass rate |
|---|---|
| Raw head-0 | 67.9% |
| Best-of-K | 85.3% |
| + local refinement | **100.0%** (220/220 failures recovered, 0 global DE) |

Cost: local refinement median 506 oracle evals (p95 1055), 26 s — vs ~1,732
evals for global DE. Phase A reproduction was bit-exact (1500/1500
identical statuses). Failure taxonomy: Power_max dominates (157/220),
218/220 within training support. **G3 met within the LUT proxy** (100% on
regression cases; 100% >= 95% held-out after declared refinement).
Caveats: benchmark requests derive from verified designs (feasible witness
exists by construction); ideal-tail scope and proxy-vs-Spectre caveats
unchanged. Key files: `surrogate_poc_summary.md`,
`surrogate_failure_report.md`, `surrogate_poc_refined_records.json`,
`surrogate_poc_repro_summary.md`, 2026-09-03 `CORRECTION_LOG.md` entries.

Reproduce the ladder:

```bash
.venv/Scripts/python scripts/evaluate_surrogate.py --stage all --n-eval 1500
.venv/Scripts/python scripts/analyze_failures.py
.venv/Scripts/python scripts/refine_failures.py
```

Next planned work (execution plan): Phase E risk-head evidence (certified
boundary set + calibration), optional Phase D diversity ablations (heads
show no collapse — low expected gain), then Phase F finite-M5 solved mode,
Phase G Spectre correlation, and only then Phase H dataset retraining.
The dataset stays frozen until the M5/correlation decisions are made.

**Update 2026-09-03 (later): Phase E done; Cadence correlation started.**
Phase E (risk-head evidence) is complete: 120 independently sampled boundary
requests, 103 certified (78 verified-feasible / 25 unresolved-after-budget,
17 awaiting a raised global-DE cap). Boundary-cohort risk AUC 0.9987;
precision 1.00, recall 0.76 at threshold 0.5; flagged requests have 0%
pipeline pass vs 92.9% unflagged — the risk head transfers beyond synthetic
negatives. Report: `risk_evidence_report.md`. Separately, a Cadence Spectre
correlation workstream now exists (`analog_ai/correlation/`,
`docs/CADENCE_CORRELATION_LOG.md`): golden netlist audited, blind job
pipeline validated end-to-end on a Debian VM (Spectre 14.1/IC617), and the
manual reference case passes all frozen tolerances (gain +0.21 dB, GBW
-3.7%, PM -2.53 deg, power -0.00005%). Step 4 (25-case stratified campaign)
is built and tested but not yet staged/run — nothing is blocking it now
that the LUT engine is free.

**Update 2026-09-03 (evening): web app complete (Phases W0-W5).**
A local web application around `analog_ai/sizing.py` now exists:
`analog_ai/web/` (FastAPI backend: frozen schemas, single-worker runtime,
versioned `/api/v1/health` + `/api/v1/size`), `web_app/static/`
(static UI; now served with locally compiled CSS), and
`scripts/run_web_app.py` (launch). Four inputs
(gain dB, GBW MHz, CL pF, power uW, TARGET_RANGES-bounded, never clipped);
results are hard-verified candidates or an explicit unresolved with no
geometry; every response carries the scope warning and the
`tt-ideal-tail-gbw-v1` guard provenance. Tests: 32 web tests + full
non-LUT suite green. Real-LUT parity smoke vs a direct API call: PASS
(`evaluation_results/web_app/parity_smoke_001.json`). Docs:
`docs/WEB_APP_USER_GUIDE.md`, `docs/WEB_APP_PROGRESS_LOG.md`.

**Update 2026-09-04: web app redesigned (stitch_UI v3) + GBW policy v2
validated.** The UI is now the stitch studio design (Tailwind CDN, KPI
cards, Circuit Parameters table, Spectre netlist export via
`/api/v1/netlist`); 38 pytest + 10 Playwright tests; Playwright specs in
`tests/e2e/`. The sizing guard is now **`tt-ideal-tail-gbw-v2-tiered`**
(18% internal GBW uplift for requests <= 300 MHz, 25% beyond), validated
by a third disjoint blind Cadence campaign: 25/25 user-spec passes,
0 false proxy passes, worst uplift 17.6%; median Spectre margin over user
spec +16.3% (vs +22.5% under v1 flat 25%). Each result also shows its
sizing path, oracle evals, wall time, and expected Spectre UGF. Full
story: `docs/CADENCE_CORRELATION_LOG.md`; evidence:
`evaluation_results/cadence_correlation/band18_validation_25/`. Test plan:
`docs/WEB_APP_TEST_PLAN.md`.

## 5. Command reference

```bash
# canonical 5-test evaluation with full verdicts (choose one source):
.venv/Scripts/python scripts/evaluate_tests.py --source constant  --op-point solved
.venv/Scripts/python scripts/evaluate_tests.py --source model     --op-point solved   # needs sb3
.venv/Scripts/python scripts/evaluate_tests.py --source optimizer --op-point solved

# non-learning correctness baseline (multi-start DE + hard verifier):
.venv/Scripts/python scripts/optimize_baseline.py --op-point solved --seed 0

# every script takes --op-point {solved,imposed}; imposed reproduces the
# legacy V9-V12 semantics and historical numbers.
```

# local web app (guarded nominal-TT sizing; ~5.5 GB LUTs load at startup):
.venv/Scripts/python scripts/run_web_app.py          # http://127.0.0.1:8000/

Run everything from the repo root so `tech_luts/` resolves.

## 6. Where things live

| Path | Contents |
|---|---|
| `analog_ai/` | canonical package: `devices/` (LUT+domain checks, matched sizing), `circuit/` (MNA, OTA proxy, **dc_solver.py** KCL solve), `evaluation/` (hard constraint verifier, record evaluator), `envs/` (V9–V12-compatible gym env), `utils/netlist.py`, `config.py` (single design contract) |
| `scripts/` | `evaluate_tests.py`, `optimize_baseline.py`, `build_dataset.py`, `train_surrogate.py`, `evaluate_surrogate.py` (all resumable) |
| `tests/` | unit tests on a synthetic square-law LUT + real-LUT integration tests |
| `configs/test_cases/` | the five frozen regression JSONs |
| `models/` | PPO agents v1–v12, `checkpoints/`, `training_telemetry/`, `surrogate/poc/` (best-of-K checkpoints + champion) |
| `evaluation_results/` | historical v2–v12 tables + `canonical/` (current evidence, incl. `surrogate_poc_summary.md`) |
| `data/pilot/` | Phase 3 dataset: 24.6k design rows, 33.2k verified request rows, splits v2, manifest (consolidated parquet committed; shards are local) |
| `docs/` | `codex_plan.md` (the plan), `CORRECTION_LOG.md` (done so far), `PROJECT_REVIEW.md` (audit), `DESIGN_CONTRACT.md` (frozen contract), `context.md` (historical diary — start at its STATUS banner), `HANDOFF.md` (this file) |
| `web_app/static/` | Browser UI (HTML/CSS/JS, no build system) for the sizing web app |
| `analog_ai/web/` | FastAPI backend: `schemas.py` (frozen W0 contract), `runtime.py` (single-worker sizing service), `app.py` (HTTP API) |
| `archive/` | frozen V2–V12 trainer trees, legacy root package, web app, Kaggle notebooks — **never import from here** |

## 7. Next steps (in `codex_plan.md` order)

1. ~~Finish DE solved baseline tests 2–5 (§4)~~ **Done 2026-09-02 — 5/5 PASS.**
2. ~~Phase 3 — feasibility-labeled dataset~~ **Done 2026-09-03** — builder in
   `analog_ai/dataset/` + `scripts/build_dataset.py`; pilot in `data/pilot/`
   (33,150 verified request rows). See `CORRECTION_LOG.md`.
3. ~~Phase 5 PoC — supervised amortized inverse design~~ **Done 2026-09-03**
   (best-of-K + risk head; 85.3% held-out best-of-K, 5/5 regression cases).
   PPO one-step env stays a demoted ablation.
4. ~~Phase 5 continuation~~ **Superseded 2026-09-03** — warm-start local
   refinement closed the gap entirely: 100% end-to-end held-out, G3 met
   (within the LUT proxy). Global DE fallback never needed.
5. **Phase E** (risk evidence) and **Phase 6** (evaluation at scale, PVT/
   Monte Carlo per execution plan Phase I) — see §4 for the order.
6. Optional: LUT checksums now exist in `configs/lut_manifest.json`; remaining: finite-M5 support in solved mode (currently imposed-only); parallelized dataset builder for scaled runs.

## 2026-09-04 — offline web hardening and Phase F start

The web UI no longer requires Tailwind CDN or Google Fonts at runtime. Its
Tailwind utilities are prebuilt into `web_app/static/tailwind.css`; rebuild
after frontend class changes with `npm install` and `npm run build:web-css`.
The regression gate is green: 139/139 non-real-LUT tests and 3/3 real-LUT
integration tests. The third 18% guard campaign now has all 75 raw result/log
artifacts archived under its `raw/` tree and matched against the structured
report. The previous server on port 8017 was stopped to release LUT memory for
the integration test. A fresh server was then started on the documented
`http://127.0.0.1:8000/`; its final health was `ready`, v2-tiered, and idle.

The next major engineering phase is finite-M5 solved mode. F0 architecture and
bias-contract decisions are recorded in
`docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md`. The revised plan now requires Opus 5
to complete an F0.5 technical review in that same file and stop for discussion;
F1 production implementation is not authorized until the decision record is
explicitly approved. The current web app remains ideal-tail only.

**Update 2026-09-04 (later): F0.5 review submitted.** The completed Opus 5
review is appended to `docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md` under
"Opus 5 pre-implementation review". Headlines: nested three-voltage solver
recommended with `Vbias_tail` frozen inside the inner Newton (recomputed once
per outer iteration); residual signs verified against the shipped ideal
solver; tolerances proposed (KCL <= 1e-9 A, width 1e-6 relative, Id_M5 0.1%,
gm/Id5 <= 1e-3 1/V, plus a sizing-time `W5 > W_NMOS_MAX` rejection); the
cdd/cgd double-counting question resolved in-convention (`cdd` already
includes the gate-drain overlap per `tests/conftest.py` — stamp uses `cdd`
alone); honest solved-point swing/ICMR definitions proposed instead of the
imposed-mode formulas; five plan-change requests and five open questions for
Hassan/Codex (notably: keep the finite+solved evaluator guard until F2
plumbs m5). No production code changed; implementation remains NOT APPROVED
pending discussion.

## 2026-09-09 — Astra gate review; Phase F1 implemented and delivered

Astra's full project review (`astra_review.md`, summarized in the Phase F
plan) amended the finite-M5 plan (nested solver confirmed; forward gm/ID
gate required; six-entry `DESIGN_BOUNDS_7` and a finite/solved dispatch
bypass flagged and to be fixed; brain/muscles ownership protocol). Hassan
then authorized the bounded F1 package, and F1 is now implemented:

- `DESIGN_BOUNDS_7` corrected to seven entries; the finite/solved override
  bypass is closed (finite + solved raises everywhere in `OTA5T`).
- New finite DC kernel `solve_operating_point_finite`
  (`analog_ai/circuit/dc_solver.py`): nested three-voltage solve, widths and
  `Vbias_tail` frozen through the inner Newton, forward gm/ID5 gate (bracketed
  Brent on the decreasing branch; reverse lookup as estimate only), strict
  fixed-device final verification, convergence/clip diagnostics, hard width
  limits on final geometry. The ideal kernel is untouched (byte-stable
  snapshot test).
- Public finite evaluation stays closed until the F2 integration gate.
- Gates: **166/166** non-real-LUT (139 baseline + 27 new focused finite
  tests) and **3/3** real-LUT integration. Real-LUT probe (nominal/wide/
  boundary designs) archived under `evaluation_results/finite_m5/f1_probe_*/`:
  all converge in < 1 s with KCL ≤ 1.7e-11 A; the Astra forward-vs-table
  gm/Id discrepancy is confirmed on TSMC data.
- Two recorded deviations with before/after evidence (Astra A2 allows):
  `max_outer` default 8 → 60 (measured geometric rates: synthetic nominal
  needs 10 iterations, a real wide design 31 — not oscillation), and
  closed-domain final checks use the repo's `LUT.in_domain` semantics with
  edge-snap evaluation (a 1-ULP edge excursion is evaluated at the edge,
  never extrapolated). Both are flagged in the plan's execution log for
  Astra sign-off.

Full delivery record: `docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md` execution
log, 2026-09-09 F1 entry. F2 (finite metrics, MNA plumbing, constraints,
minimal finite records) is not started and awaits Astra's F1 acceptance.

**Update 2026-09-09 (later): F1 corrective package delivered.** Astra's gate
review of `6b42cf6` returned CHANGES REQUIRED (F1-R1..R5, with
reproductions). The bounded corrective package addresses all five: true
ULP-scale coordinate canonicalization with recorded edge snaps (0.5 nm
below the LUT length minimum now rejects; the old 1e-9 tolerance is gone);
acceptance KCL recomputed FROM the returned device points at one canonical
coordinate set (verified point == returned evidence); strict unique-root
enforcement in the forward gm/Id solve (multi-crossing curves and target
plateaus reject; no proximity selection); finite/physical validation of
every returned M1-M5 point with finiteness checks before threshold
comparisons; explicit `op_point` value validation (`'solvde'`/`''` raise);
effective solver settings recorded in every kernel record; and the probe
now self-verifies LUT hashes, records source identity, and archives full
OP records plus per-iteration traces for successful AND failed runs in
strict JSON. Gates: 46/46 focused, full non-real-LUT suite exit 0 (139
baseline + 46), 3/3 real-LUT integration. Corrective evidence:
`evaluation_results/finite_m5/f1_probe_20260909_031000/`.

**Prominent (Astra, saturation):** the three successful probe cases all
have NEGATIVE M5 saturation margins (-48.0 / -58.6 / -48.0 mV) — they are
converged DC diagnostics, not feasible finite-OTA designs. F2's saturation
verifier must reject them, F4 still owes evidence of physically feasible
finite designs, and the saturation floor must not be adjusted to make
probes pass.

**Update 2026-09-09 (latest): F1 R5 follow-up delivered.** Astra accepted
F1-R1..R4 and kept two narrow R5 items open; both are now closed in code:
(a) numerical controls are validated before any lookup or iteration
(positive finite tolerance; positive integer budgets, fractions rejected —
`tol=float('inf')` now rejects); (b) probe evidence is bound to exact
source contents via a 9-file sha256 fingerprint, a tracked-changes-only
dirty flag with a `git diff HEAD` hash, and a comparison run that isolates
`max_outer`. New immutable archive
`evaluation_results/finite_m5/f1_probe_20260909_045513/`; gates 62/62
focused, full non-real-LUT suite exit 0, 3/3 real-LUT integration.
Awaiting Astra's final F1 acceptance; F2 remains closed.

**Update 2026-09-09 (current): Astra accepted F1 at `db6db4a`.** All F1-R1
through F1-R5 findings are closed. Astra independently reran **201 non-real-LUT
tests and 3 real-LUT integration tests**, verified all nine archived source
fingerprints against delivered files, checked pre-lookup invalid-control
rejection, and validated archived KCL/trace consistency. See the final F1
acceptance entry in `docs/PHASE_F_FINITE_M5_EXECUTION_PLAN.md`.

**Next owner/action:** Opus may begin the bounded F2 package; Astra reviews
its independent MNA derivation, capacitance evidence, metrics/constraints,
and minimal finite record schema. Public finite evaluation stays closed until
that integrated gate passes. The archived negative M5 saturation margins remain
diagnostics and must fail F2 acceptance; the ideal-tail runtime stays frozen.
F2 implementation, later packages, and deployment were not performed by this
review.

**Update 2026-09-09 (F2 delivered): bounded F2 implemented, awaiting Astra
review.** Delivered in the handoff's order, with PUBLIC FINITE EVALUATION
STILL CLOSED (`OTA5T.evaluate` still rejects finite+solved; tested):

1. **Independent MNA audit (R7):** all five reported legacy-stamp
   discrepancies reproduce. A corrected terminal-equation model
   (`MNAEngine.assemble_ac_corrected`/`solve_ac_corrected`) is added for the
   finite path; the legacy `solve_ac` is byte-frozen for the historical
   ideal oracle. `tests/test_mna_audit.py` (10 tests) verifies the corrected
   assembly entry-for-entry against an independent element-stamp reference
   assembler, body-current conservation at both terminals, RHS-only
   driven-gate excitation, M4's cgd as a true two-terminal capacitor, M3's
   same-node overlap never stamped, M5 as pure drain loading, the ideal
   limit inside the corrected model, full nodal-current closure (< 1e-18),
   and the exact pinned legacy-vs-corrected differences. The audit caught a
   sign error in the first corrected-RHS draft before delivery.
2. **Capacitance convention (A4): recorded limitation.** No characterization
   material exists in-repo (LUTs are Google Drive downloads). New data-level
   observation: real cdd/cgd spans 1.21-2.39 (n=12) - consistent with a
   total drain capacitance, but the DEFINITION is unresolved; stamping uses
   cdd alone under a documented assumption and the physical AC gate stays
   open pending F5's device-level Spectre experiment.
3. **Integrated metrics/constraints/schema:** private
   `_evaluate_solved_finite` (corrected-AC metrics with the solved M5;
   Power = VDD*(ID3+ID4) KCL-cross-checked; SR labeled ID5/CL proxy;
   five-device saturation under the FROZEN 50 mV floor; A5-labeled headroom
   estimates with acceptance keys NaN so requested range constraints fail
   closed); effective constraint limits scoped to the finite path (requests
   tighten, never relax; invalid requests fail closed); minimal dev finite
   schema `analog_ai-0.2.0-finite-solved-dev` with seven mode-aware
   parameter names and strict-JSON nulls. The ideal-path versioned R1
   correction remains a separate open task.

Gates: 10 audit + 19 evaluator + 62 F1 focused tests green; 230-collected
non-real-LUT suite exit 0; 3/3 real-LUT integration. Real-LUT F2 probe
(`evaluation_results/finite_m5/f2_integration_20260909_054929/`): both
designs verdict=False with exactly Sat_margin_min failing (sat_m5 -48.0 mV)
- the negative-saturation diagnostic points are rejected as feasible
designs, as required.

**Update 2026-09-09 (F2 corrections delivered): Astra's F2 review returned
CHANGES REQUIRED (F2-R1..R5); the bounded correction package addresses all
five.** F1 stays accepted; public finite guards stay closed.

1. **F2-R1 (capacitance double counting):** under the declared
   `Cdd = Cgd + Cdb` convention the corrected assembly now derives the
   junction per device and stamps the gate-drain ELEMENT per its true
   connectivity plus ONLY the junction at the drain - Astra's lone-1pF
   limiting cases (M1: 1 pF not 2 pF; M3: nothing; M4 `[[1,-1],[-1,1]]`)
   are enforced by tests, with junction-only complements and `Cdd < Cgd`
   rejection. `tests/test_mna_audit.py` rebuilt on a PRIMITIVE reference
   assembler (the engine's total Cdd is constructed FROM Cgs/Cgd/Cdb
   primitives), replacing tests that had encoded the defect.
2. **F2-R2 (malformed requests):** `validate_finite_specs` type-, finite-,
   and range-checks every supported finite request field before any device
   work (strictly-positive quantities reject zero so no normalization
   scale can be zero or inverted); 17 malformed-field tests assert
   record-level fail-closed behavior.
3. **F2-R3 (strict JSON):** the complete record is JSON-safe - constraint
   rows with nonfinite values as explicit nulls (verdicts preserved),
   normalized/sanitized request echoes, sanitized invalid-design values -
   asserted on range-failure, NaN-design, infinite-request, and
   no-crossing-AC records.
4. **F2-R4 (supply context):** records carry the effective
   `ota.VDD`/`ota.Vicm`, a `supply_context_canonical` flag, and the
   `ac_model` identifier; tested at vdd=1.3.
5. **F2-R5 (fingerprints):** `source_fingerprint_f2()` extends the
   accepted F1 set with the evaluator/constraints modules and the actual
   F2 entry point (12 files), with independent-hash coverage tests.

New immutable archive:
`evaluation_results/finite_m5/f2_integration_20260909_112307/` (LUT
hashes verified, strict JSON, required range-failure and malformed-request
examples; both diagnostic designs still verdict=False with exactly
Sat_margin_min failing). Earlier archive retained as history. The 50 mV
floor, F1 kernel, legacy ideal oracle, and public finite guards are
unchanged; capacitance provenance remains open for F5.

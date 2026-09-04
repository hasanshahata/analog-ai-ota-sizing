# Current Project Status Review

**Audit date:** 2026-09-04

**Audited revision:** `c5b614d` (`main`)

**Scope:** sizing pipeline, Phase E, Cadence correlation, web application,
tests, documentation, and remaining roadmap

## Executive conclusion

The project has reached a strong **nominal ideal-tail research-demonstrator**
state. The complete browser-to-sizing path exists and the current deployment
policy has independent Cadence evidence. It is ready to generate guarded
sizing candidates for the frozen application domain, but it is not a general
or signoff-ready 5T-OTA sizing system.

The most important current facts are:

- the solved-LUT sizing ladder reaches 100% on the 1,500-request held-out
  feasible benchmark after local refinement;
- Phase E risk evidence is complete under its declared certification cap;
- three 25-case nominal Cadence campaigns were performed: the unguarded
  campaign exposed optimistic GBW prediction, v1 eliminated false passes with
  a flat 25% guard, and the third disjoint campaign validated the current 18%
  in-domain tier;
- the v2 campaign achieved 25/25 Spectre user-spec passes and zero false proxy
  passes;
- the FastAPI web backend, browser UI, result display, and Spectre-netlist
  export are implemented;
- a real web server is currently listening on `127.0.0.1:8017`, reports
  `ready`, uses `tt-ideal-tail-gbw-v2-tiered`, and was idle at audit time;
- the Git worktree was clean before this review document was added;
- the current automated run is **134 passed, 4 failed**. All four failures are
  browser visibility failures caused by relying on Tailwind CDN for the
  `.hidden` utility when the CDN is unavailable. The sizing backend is not the
  source of these failures.

## Capability matrix

| Capability | Current state | Evidence / qualification |
|---|---|---|
| Solved DC operating point from gm/Id LUTs | Complete | KCL-solved ideal-tail oracle |
| Hard constraint verification | Complete | Sole authority for accepted designs |
| Best-of-five neural proposal | Complete | 85.33% held-out pass before refinement |
| Local neural warm-start refinement | Complete | Recovered 220/220 held-out misses |
| Global fallback | Implemented | Fail-closed; expensive and not always successful |
| Phase E risk evidence | Exit gate met | Boundary AUC 0.9987; unresolved is not called infeasible |
| Nominal ideal-tail Cadence correlation | Complete for the deployment experiment | 75 campaign cases across three campaigns, plus manual reference |
| Current v2 GBW guard | Validated in-domain | 18% for app requests <=300 MHz; third disjoint 25/25 campaign |
| Web/API black box | Implemented | Four inputs, verified sizing or unresolved, netlist export |
| Browser robustness without internet | Failing | Tailwind CDN outage breaks visibility and styling assumptions |
| Finite physical M5 in solved mode | Not implemented | Major Phase F gate |
| PVT / Monte Carlo / mismatch | Not implemented | Phase I |
| Post-layout/parasitic signoff | Not implemented | Outside current evidence |
| Other PDKs, supplies, common modes, corners | Not supported | Frozen nominal scope only |

## Current black-box scope

The web application accepts:

| Input | Allowed application range |
|---|---:|
| Minimum DC gain | 20 to 45 dB |
| Minimum GBW | 50 to 300 MHz |
| Load capacitance | 0.1 to 5 pF |
| Maximum power | 50 to 400 uW |

For a verified request it returns matched M1/M2 W/L, matched M3/M4 W/L,
ideal tail current, nominal LUT metrics, constraint margins, pipeline cost,
calibration provenance, and a Spectre netlist export. An unresolved request
returns no geometry.

The supported operating context is fixed to TSMC 65 nm `tt_lib`, VDD=1.2 V,
Vincm=0.6 V, and an ideal tail-current source. There is no M5 device sizing in
this mode.

## Sizing and learning evidence

The surrogate should be understood as a fast proposal generator followed by
verification and repair, not as an independently trustworthy raw predictor:

| Ladder point | Held-out feasible pass rate |
|---|---:|
| Primary network head | 67.87% |
| Best of five heads | 85.33% |
| After bounded local refinement | 100.00% |

All 220 best-of-K misses were recovered locally. Median repair cost was 506
oracle evaluations and approximately 26 seconds; the 95th percentile was
1,055 evaluations. The benchmark is composed of requests with known feasible
witnesses, so 100% here does not imply that every arbitrary combination in the
input rectangle is feasible.

Phase E processed 120 boundary requests. The certified subset contains 78
verified-feasible and 25 unresolved-after-budget cases; 17 were left awaiting
certification after the configured global-failure cap was reached. At risk
threshold 0.5, boundary precision is 1.00 and recall 0.76. This is useful
routing evidence, not mathematical feasibility proof. The web runtime does
not currently use the risk head as a separate pre-routing stage; it relies on
range validation and the fail-closed sizing ladder.

## Cadence correlation status

### Campaign 1: unguarded

- 25/25 simulations completed;
- only 5/25 met all original specifications in Spectre;
- 20 false proxy passes, all caused by GBW;
- mean Spectre-minus-LUT GBW error: -6.05%;
- worst error: -16.74%.

This campaign correctly disproved reliance on the unguarded LUT boundary.

### Campaign 2: v1 flat 25% guard

- disjoint 25-case validation;
- 25/25 met user specifications in Spectre;
- zero false proxy passes;
- median Spectre GBW margin above the user target: +22.51%;
- only 15/25 met all original correlation tolerances;
- guarded sizing accepted 25 of 34 attempted requests (73.5%).

The policy was safe on the sample but caused material in-domain overdesign.

### Campaign 3: v2 in-domain 18% guard

- third disjoint 25-case validation;
- 25/25 met user specifications in Spectre;
- zero false proxy passes;
- 22/25 met all correlation tolerances;
- median Spectre margin over the user target: +16.3%;
- worst required uplift observed: 17.6%;
- all 25 selected campaign requests were accepted by the sizing ladder.

The current official policy is `tt-ideal-tail-gbw-v2-tiered`: 18% at or below
300 MHz, 25% above that boundary. Because the web input contract stops at
300 MHz, normal web requests use the validated 18% tier.

The margin between the 18% guard and the observed 17.6% worst case is only
0.4 percentage points. This is encouraging evidence, not a statistical
guarantee. New worse-tail evidence must trigger a policy re-evaluation.

## Web application status

Implemented components:

- `analog_ai/web/schemas.py`: strict four-input schema, conversion, safe
  success/unresolved response construction;
- `analog_ai/web/runtime.py`: one-time LUT/checkpoint loading and serialized
  sizing worker;
- `analog_ai/web/app.py`: health, sizing, static UI, and verified netlist API;
- `web_app/static/`: interactive browser form and result presentation;
- `scripts/run_web_app.py`: local launch entry point;
- web unit, API, static, Playwright, and real-engine parity checks;
- user guide, test plan, progress log, screenshots, and parity evidence.

At audit time, `http://127.0.0.1:8017/api/v1/health` returned:

```text
state: ready
policy: tt-ideal-tail-gbw-v2-tiered
busy: false
```

The real-engine parity evidence shows identical output between a served web
request and a direct `size_ideal_tail_ota` call for the frozen seed. Scripted
latency checks recorded approximately 7 to 35 seconds for local-refinement
examples. A hard unresolved example required about 9.4 minutes and 3,944
oracle evaluations, so worst-case interactive latency remains important.

## Test audit

Command executed:

```powershell
.venv/Scripts/python.exe -m pytest tests --ignore=tests/test_integration_real_luts.py
```

Result on 2026-09-04:

```text
134 passed, 4 failed, 2 warnings
```

The focused non-browser web tests passed 38/38. The four failures were:

- idle results panel should be hidden;
- results should stay hidden after invalid input;
- results should stay hidden for an unresolved request;
- reset should hide previous results.

Root cause: `index.html` obtains Tailwind from `cdn.tailwindcss.com`, and the
local stylesheet does not define `.hidden`. When the CDN is unavailable, the
class has no effect. This also contradicts older documentation describing the
UI as dependency-free. The durable fix is to build/vendor the required CSS
locally; adding a local `.hidden { display: none !important; }` rule is only
the minimum immediate containment.

The real-LUT integration suite was not rerun during this audit because the
active web server already holds the approximately 5.5 GB LUT engine in memory;
the project documentation warns that a second concurrent load can exhaust a
roughly 14 GB machine.

## Documentation and provenance findings

The primary history is detailed, but several files are stale or internally
inconsistent:

1. `WEB_APP_IMPLEMENTATION_PLAN.md` still says implementation has not started
   and specifies v1, although W0-W5 are implemented and v2 is official.
2. `CORRECTION_LOG.md` still says the initial 25-case campaign has not run and
   Gate G is at that earlier point.
3. `DESIGN_CONTRACT.md` retains headings saying provisional even though its
   later paragraph promotes v2 to official.
4. The `size_ideal_tail_ota` docstring still describes v2 as provisional.
5. The runtime's ready log reports the v1 policy constants even when the
   runtime is using tiered v2; its health response is correct.
6. The v2 campaign repository folder contains the structured campaign records
   and summary, but no per-case `raw/` directory with Spectre stdout and OCEAN
   logs. The two earlier validation folders each archive 75 raw files. The v2
   raw artifacts should be copied from the shared Cadence folder if they still
   exist.

These do not invalidate the structured v2 measurements, but they weaken
handoff clarity and raw-evidence completeness.

## Readiness decision

### Ready for

- local demonstrations and research use;
- generating nominal-TT, ideal-tail sizing candidates inside the four-input
  application domain;
- exporting a candidate Spectre netlist for independent verification;
- explicit fail-closed behavior when no protected design is found.

### Not ready for

- claiming it sizes any 5T OTA;
- sizing a physical tail transistor M5;
- tapeout/signoff decisions without Cadence verification;
- PVT, temperature, supply variation, mismatch, Monte Carlo, noise, layout
  parasitics, or yield claims;
- another topology, PDK, corner, supply, or common-mode voltage;
- unattended public/network deployment.

## Recommended next actions

1. **Fix the web release blocker:** remove the runtime dependency on Tailwind
   CDN by committing locally built/vendor CSS, then rerun all 138 non-real-LUT
   tests and the browser suite offline.
2. **Synchronize documentation and comments:** mark W0-W5 complete, make v2
   official consistently, update Gate G status, and correct the runtime ready
   log.
3. **Complete v2 evidence archiving:** bring the 25 Spectre result files, 25
   OCEAN logs, and 25 Spectre logs into the repository evidence tree and audit
   hashes/counts.
4. **Run real-LUT integration after stopping the current server** to avoid
   memory contention, then record the current final test count.
5. **Begin Phase F finite-M5 solved mode** if the goal remains a physically
   complete 5T OTA. Do not regenerate/retrain the seven-parameter dataset until
   this oracle transition and its Cadence correlation are complete.
6. Optionally finish the 17 remaining Phase E certification cases and decide
   whether the risk head should become an explicit web routing/early-rejection
   stage.

## Overall assessment

The central idea is working in its declared scope: a learned proposal plus a
gm/Id LUT oracle, hard verification, local repair, and a Cadence-derived GBW
guard can generate useful ideal-tail nominal candidates. The project is beyond
a proof-of-concept script and now has an operable web product shell. The next
quality step is to repair offline UI reliability and reconcile evidence/docs;
the next major analog-design step is finite M5.

## Remediation update (later 2026-09-04)

The recommendations from this audit were executed:

- runtime CDN dependencies were replaced by committed local compiled CSS;
- the four browser failures were fixed and guarded by a new offline-assets
  test;
- current gates are 139/139 non-real-LUT and 3/3 real-LUT tests passing;
- all 75 third-campaign raw files were recovered and matched to the report;
- stale v2/phase documentation and runtime log metadata were corrected;
- Phase F was started at F0 with a concrete finite-M5 execution and external
  gate-bias contract plan.

The server on port 8017 was stopped to run the real-LUT tests. A fresh service
was then started on the documented port 8000 and reached `ready` with the v2
tiered policy. The remaining major limitation is still the unimplemented
finite-M5 solved oracle, followed by its independent Cadence correlation.

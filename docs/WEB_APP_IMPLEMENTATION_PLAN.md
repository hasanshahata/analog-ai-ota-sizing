# Ideal-Tail 5T-OTA Web App Implementation Plan

**Created:** 2026-09-03  
**Status:** implemented (W0-W5 complete); offline asset hardening completed 2026-09-04
**Target:** a simple local web application around the verified nominal-TT sizing pipeline

## 1. Goal

Build a small web application where a user enters the required OTA specifications and receives either:

1. a hard-verified candidate sizing for the ideal-tail 5T-OTA; or
2. an explicit `unresolved` result with no fabricated transistor dimensions.

The application must call the existing deployment API in
`analog_ai/sizing.py`; it must not reimplement the sizing algorithm or use the
obsolete web application under `archive/legacy_root/web_app`.

## 2. Supported circuit and honest scope

The first release supports only:

- topology: matched NMOS input pair plus matched PMOS current-mirror load;
- ideal tail-current source (no finite M5 geometry);
- TSMC 65 nm LUTs at the typical `tt_lib` corner;
- `VDD = 1.2 V`;
- `Vincm = 0.6 V`;
- solved LUT operating point;
- the validated tiered GBW deployment guard,
  `tt-ideal-tail-gbw-v2-tiered` (18% inside the <=300 MHz app domain).

The UI must label results as **nominal LUT-based sizing candidates**, not
post-layout or PVT signoff. Cadence remains the final authority. The guard was
validated on one disjoint 25-case nominal campaign with 25/25 physical spec
passes, but this is not a universal guarantee.

## 3. Black-box contract

### User inputs

| UI field | Internal key | UI unit | Internal unit | Initial allowed range |
|---|---|---:|---:|---:|
| Minimum DC gain | `Gain_min` | dB | dB | 20 to 45 dB |
| Minimum GBW | `GBW_min` | MHz | Hz | 50 to 300 MHz |
| Load capacitance | `CL_pF` | pF | pF | 0.1 to 5 pF |
| Maximum power | `Power_max` | uW | W | 50 to 400 uW |

The initial ranges match the model's request domain. Values outside them must
be rejected clearly rather than silently clipped. Phase margin and saturation
margin remain hard verifier constraints with the frozen defaults; they are not
editable in the first simple UI.

### Successful outputs

- M1/M2: common width and length;
- M3/M4: common width and length;
- ideal tail current `Itail`;
- sizing-path status (`verified`, best-of-K, or refinement path as reported);
- predicted nominal LUT metrics: gain, GBW, phase margin, power, output DC
  voltage, tail voltage, and mirror voltage;
- user-spec pass verdict and per-constraint margins;
- internal guarded target and calibration-policy version;
- oracle evaluation count and a visible scope/signoff warning.

Lengths and widths should be displayed in nm/um and current in uA, while the
API response retains full-precision SI values for reproducibility.

### Unresolved output

If the protected pipeline cannot find a verified design within its budget,
the response must contain:

- `status = "unresolved"`;
- no W/L values and no tail-current recommendation;
- a short explanation that unresolved does not prove physical infeasibility;
- guidance to relax specifications or use a larger offline search budget.

## 4. Proposed architecture

Use a small Python backend plus a static single-page frontend:

```text
Browser form
    -> POST /api/v1/size
    -> request validation and unit conversion
    -> size_ideal_tail_ota(...)
    -> response formatting
    -> sizing/result cards in browser
```

Recommended stack:

- FastAPI and Pydantic for the HTTP API and input validation;
- Uvicorn for the local server;
- plain HTML, CSS, and JavaScript for the first UI;
- the existing PyTorch surrogate checkpoint and solved LUT evaluator.

This avoids adding a frontend build system. The archived FastAPI prototype may
be consulted only for layout ideas; its PPO backend, seven-variable design,
extra spec fields, and imposed operating point are obsolete.

## 5. Proposed files

```text
analog_ai/web/
    __init__.py
    app.py                 # FastAPI construction, startup, routes
    runtime.py             # one-time LUT/checkpoint loading and sizing service
    schemas.py             # validated request/response models and unit mapping
web_app/
    static/index.html
    static/style.css
    static/app.js
scripts/run_web_app.py     # simple supported launch command
tests/
    test_web_schemas.py
    test_web_api.py
    test_web_runtime.py
docs/
    WEB_APP_USER_GUIDE.md
    WEB_APP_PROGRESS_LOG.md
```

Add a `web` optional dependency group to `pyproject.toml` for FastAPI and
Uvicorn. Keep heavy LUT/model initialization out of module import so unit tests
can inject a lightweight fake runtime.

## 6. Implementation phases

### Phase W0 - freeze the UI/API contract

1. Define the four input fields, units, range limits, response fields, and
   error format in Pydantic schemas.
2. Add a versioned route, `POST /api/v1/size`.
3. Define health states for `GET /api/v1/health`: `loading`, `ready`, and
   `failed`.
4. Freeze the rule that only `user_verdict = true` plus a non-null physical
   design can be displayed as a successful sizing.

**Exit gate:** schema tests cover valid input, missing fields, non-finite
numbers, bad units/ranges, unresolved output, and successful output.

### Phase W1 - build the sizing runtime

1. Resolve repository paths relative to a configured project root, not the
   current terminal directory.
2. At application startup, load the approximately 5.5 GB typical-corner LUTs
   once with `load_engine(tail_device="ideal", op_point="solved")`.
3. Read `models/surrogate/poc/champion.json`, load the selected checkpoint, and
   recover `feat_lo` and `feat_hi` from checkpoint metadata.
4. Convert UI units to the canonical black-box request.
5. Call `size_ideal_tail_ota` with the frozen guard policy and fail-closed
   behavior.
6. Serialize only JSON-safe values and expose an application-generated request
   ID for debugging.
7. Protect the runtime from concurrent mutation. Start with a single sizing
   worker/lock because the LUT engine and optimization path have not yet been
   proven thread-safe.

**Exit gate:** runtime tests prove the exact converted request reaches the
sizing API, the original request is preserved, unresolved results contain no
geometry, and exceptions become controlled errors.

### Phase W2 - implement the HTTP API

1. Implement startup readiness and useful errors for missing LUT/checkpoint
   files.
2. Implement `/api/v1/health` without triggering a new engine load.
3. Implement `/api/v1/size` with validation, timeout/error handling, and the
   response schema.
4. Do not expose server paths, stack traces, private campaign requests, or
   checkpoint internals to the browser.
5. Add structured server logs containing request ID, status, elapsed time,
   sizing path, and oracle-evaluation count, but not hidden validation data.

**Exit gate:** API tests exercise 200 success, 422 validation error, 503 not
ready, controlled internal failure, and unresolved response.

### Phase W3 - build the simple browser interface

1. Add a four-field form with units beside every field and sensible example
   defaults.
2. Disable duplicate submissions while a request is running and show progress;
   global fallback can take noticeably longer than a direct proposal.
3. Render matched devices clearly as M1=M2 and M3=M4.
4. Show sizing, nominal metrics, constraint margins, internal GBW target, and
   calibration version in separate compact sections.
5. Render unresolved and server-error states without stale results.
6. Place the scope warning next to every result, not only in an About page.
7. Make the layout usable on desktop and mobile and accessible by keyboard.

**Exit gate:** manual browser checks cover success, unresolved, invalid input,
server unavailable, repeated submission, and narrow-screen layout.

### Phase W4 - verification against the existing pipeline

1. Run the existing non-LUT regression suite to detect integration regressions.
2. Run the new web unit/API tests using fakes so CI does not require 5.5 GB
   LUT files.
3. Run one real-LUT smoke request locally and compare the web JSON with a
   direct call to `size_ideal_tail_ota` using the same seed and search budget.
4. Confirm identical physical sizing, metrics, policy version, and verdict.
5. Check that an intentionally unsupported/out-of-range request is rejected
   and that a known unresolved request never produces geometry.

**Exit gate:** all automated tests pass and the real-LUT web/direct parity
record is saved under `evaluation_results/web_app/`.

### Phase W5 - documentation and handoff

1. Write installation and launch commands in `WEB_APP_USER_GUIDE.md`.
2. Document the first startup memory/time cost and expected per-request latency.
3. Document the four inputs, all outputs, units, supported operating scope,
   and meaning of `unresolved`.
4. Update `README.md` and `docs/HANDOFF.md` with the supported launch path.
5. Record every implementation action, test result, failure, correction, and
   decision chronologically in `docs/WEB_APP_PROGRESS_LOG.md`.

**Exit gate:** a new user can start the server and obtain a result by following
only the user guide.

## 7. Result formatting rules

The backend should return the canonical SI record plus a presentation layer.
Suggested display precision:

- W: three decimal places in um;
- L: one decimal place in nm;
- `Itail`: three decimal places in uA;
- gain and phase margin: two decimal places;
- GBW: three decimal places in MHz;
- power: three decimal places in uW.

Rounding is display-only. Constraint verdicts must always use the unrounded
canonical values produced by the verifier.

## 8. Safety and reliability requirements

- Never call the archived PPO web backend.
- Never label an unverified or unresolved design as success.
- Never silently clamp an input to the training range.
- Never imply support for finite M5, PVT, Monte Carlo, another PDK, another
  supply/common-mode point, or post-layout parasitics.
- Avoid loading the LUTs once per HTTP request.
- Limit request concurrency initially to prevent memory pressure.
- Preserve full calibration and verifier provenance in every successful JSON
  response.
- Bind to localhost by default; authentication/rate limiting is required before
  exposing the service on a network.

## 9. Definition of done

The first web-app release is complete when:

- the four supported specs can be entered in a browser;
- the app invokes the guarded solved-mode sizing API, not legacy code;
- successful results show M1/M2 W/L, M3/M4 W/L, and ideal tail current;
- unresolved requests show no dimensions;
- nominal metrics and every hard-constraint verdict are visible;
- loading, invalid-input, unresolved, and runtime-failure states are handled;
- fake-runtime tests and one real-LUT parity test pass;
- the limitations and 25-case Cadence evidence are visible and documented;
- all implementation progress is recorded in the project docs.

## 10. Executed order

W0 through W5 were executed in order. The UI was subsequently redesigned and
the v2 policy was validated by a third disjoint Cadence campaign. On
2026-09-04 the Tailwind CDN and Google Fonts runtime dependencies were removed;
the required Tailwind utilities are now compiled at build time and committed as
`web_app/static/tailwind.css` for deterministic offline operation.

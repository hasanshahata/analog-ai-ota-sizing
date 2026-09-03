# Web App Progress Log

Chronological record of the web-app implementation
(`docs/WEB_APP_IMPLEMENTATION_PLAN.md`). One entry per action, test result,
failure, correction, and decision.

## 2026-09-03 — Environment + Phase W0 (contract freeze)

- Installed `fastapi 0.141.1`, `uvicorn 0.52.4`, `httpx 0.28.1`
  (pydantic 2.13.5) into `.venv` via uv (the venv has no pip).
- Added `web = ["fastapi>=0.110", "uvicorn>=0.29", "httpx>=0.27"]` optional
  dependency group to `pyproject.toml`.
- Created `analog_ai/web/` with `schemas.py`: the frozen W0 contract —
  UI-unit `SizeRequest` (gain dB, GBW MHz, CL pF, power µW; bounds derived
  from `config.TARGET_RANGES`; non-finite and out-of-range rejected, never
  clipped; booleans rejected; unknown fields rejected via
  `extra="forbid"`), unit conversion to canonical SI (GBW Hz, power W),
  `ConstraintOut` with signed margin, `json_safe` (NaN/inf → null so strict
  JSON is always producible), display `presentation` layer, and response
  factories that enforce the frozen display rule: only `user_verdict=True`
  plus non-null geometry can build a success response; unresolved responses
  carry no geometry keys at all and the word "infeasible" never appears.
- Decision: field names carry units (`GBW_min_MHz`, `Power_max_uW`) so the
  black-box contract is self-documenting; the internal guarded request is
  derived only inside `size_ideal_tail_ota`, never in the web layer.
- Tests: `tests/test_web_schemas.py` (14) — valid input, boundaries,
  missing fields, non-finite, out-of-range, boolean smuggling, unresolved
  no-geometry, success freezing rule, NaN sanitisation, domain-constraint
  JSON safety, presentation rounding, error shape.
  **Result: 14/14 PASS.** Two initial failures were test bugs (0.5 µm is
  500 nm; float-exact comparison replaced with approx). **W0 exit gate met.**

## 2026-09-03 — Phase W1 (sizing runtime)

- Created `analog_ai/web/runtime.py`: `SizingRuntime` resolves the repo
  root from `__file__` (never the CWD), loads the engine once with
  `load_engine(tail_device="ideal", op_point="solved")`, reads
  `models/surrogate/poc/champion.json` (basename-safe) and recovers
  `feat_lo`/`feat_hi` from checkpoint metadata. Heavy imports live inside
  `load()` so tests import the module without LUTs/torch.
- Single sizing worker: `threading.Lock` serialises `size()`; concurrent
  calls are queued. Input dicts are never mutated (snapshot check raises a
  controlled `SizingFailure` if violated).
- Failure semantics: load failures set state `failed` with a sanitised
  public detail (no server paths; full traceback only in server logs);
  sizing exceptions become `SizingFailure` with a sanitised message;
  calls before ready raise `RuntimeNotReady`. `health()` reads state only
  and never triggers a load.
- Tests: `tests/test_web_runtime.py` (9) — root resolution, verbatim
  request forwarding, request preservation, guard policy unchanged,
  unresolved-no-geometry, controlled errors, not-ready refusal, serialized
  concurrency (alternating enter/exit), failed-load recording.
  **Result: 9/9 PASS** (one monkeypatch-ordering test bug fixed).
  **W1 exit gate met.**

## 2026-09-03 — Phase W2 (HTTP API)

- Created `analog_ai/web/app.py`: `create_app(runtime=None)` — an injected
  runtime is never auto-loaded; a self-constructed runtime loads on a
  background daemon thread at startup. Routes: `GET /api/v1/health`,
  `POST /api/v1/size` (versioned). `RequestValidationError` is mapped onto
  the frozen `{"error": {"code", "message"}}` format (422). Not-ready →
  503 `not_ready`; sizing failure → 500 `sizing_failed` with sanitised
  message; no stack traces or paths reach the browser.
- Decision: **no hard timeout that kills a sizing call** — the worker is
  not interruptible and abandoning it mid-search would violate fail-closed
  behaviour; the sync endpoint runs in a threadpool so `/health` stays
  responsive during long requests. Structured server logs carry request
  ID, status, pipeline path, oracle evals, elapsed — never spec values or
  hidden validation data.
- The static UI is mounted at `/` when `web_app/static/` exists.
- Tests: `tests/test_web_api.py` (9) — 200 success, 200 unresolved
  (no geometry), 422 (missing/out-of-range/unknown field), raw-JSON `NaN`
  rejected 422, 503 not-ready, 500 controlled (no leak), health reflects
  state without loading, failed-state detail sanitised, static index
  served. **Result: 9/9 PASS.** Full web suite 32/32.
  **W2 exit gate met.**

## 2026-09-03 — Phase W3 (browser UI)

- Created `web_app/static/{index.html,style.css,app.js}` (dependency-free,
  `node --check` clean): four-field form with units and allowed-range
  hints, example defaults (35 dB / 100 MHz / 1 pF / 200 µW), duplicate
  submissions disabled with an elapsed-time progress indicator, results
  rendered as separate compact sections (device sizing with explicit
  M1 = M2 / M3 = M4 matched pairs, nominal LUT metrics, per-constraint
  margins with PASS/FAIL chips, guard provenance with user vs internal
  GBW and policy version), unresolved/error states clear stale results
  and never show dimensions, scope warning attached to every result,
  dark-mode aware, mobile single-column, keyboard accessible
  (native form controls, focus-visible, aria-live regions).
- Created `scripts/run_web_app.py` (localhost bind by default; startup
  banner documents memory cost and scope).
- Live-server checks: static assets 200; JS syntax OK. Interactive
  browser pass (layout/UX on real screens) left for the user.
  **W3 exit gate: automated paths verified end-to-end; manual visual pass
  pending user.**

## 2026-09-03 — Phase W4 (verification against the pipeline)

- Full non-LUT regression suite re-run against the live server running:
  **exit 0, no failures** (121 tests).
- Real-LUT smoke through the served API (`127.0.0.1:8017`):
  - `32 dB / 120 MHz / 2 pF / 250 µW` → HTTP 200 in 7.7 s,
    `local_refinement_verified`, 75 oracle evals.
  - `44.5 dB / 290 MHz / 5 pF / 55 µW` (extreme corner) → HTTP 200,
    **unresolved** after 3,944 oracle evals (~9.4 min), zero geometry —
    fail-closed behaviour confirmed through the full ladder including
    global fallback.
  - `GBW 900 MHz` → HTTP 422 with field-level message.
- **Fault found and fixed**: first success response raised
  `TypeError: list - list` in `_constraint_out` — the verifier's
  `L_domain` constraint carries tuple `limit`/`achieved`. Fix: margin is
  computed only for scalar min/max constraints; domain constraints keep
  `margin = None` with tuple fields serialised as JSON arrays. Regression
  test `test_domain_constraint_tuple_fields_are_json_safe` added.
- Web/direct parity (same request, seed 0, direct `size_ideal_tail_ota`
  in a separate process): identical design variables, LUT metrics, both
  verdicts, policy version, internal guarded GBW, oracle-eval count, and
  pipeline status. **PARITY: PASS** — record saved to
  `evaluation_results/web_app/parity_smoke_001.json`.
  **W4 exit gate met.**

## 2026-09-03 — Phase W5 (documentation and handoff)

- Wrote `docs/WEB_APP_USER_GUIDE.md` (install, launch, inputs, outputs,
  unresolved semantics, HTTP API, troubleshooting).
- Wrote this log. Updated `README.md` and `docs/HANDOFF.md` with the
  supported launch path.
- Remaining known items: interactive visual pass on real devices;
  authentication/rate-limiting before any non-localhost exposure;
  concurrency beyond one worker requires proving engine thread-safety.

## 2026-09-03 — UI revision: clean-and-simple + length unit fix (user feedback)

- User asked "is L 1.4 nm?" — the display showed `1,408.8 nm` (a thousands
  separator, i.e. 1.409 µm, a valid long-channel device inside the
  60 nm–1.5 µm domain, chosen for gain). Treated as a display failure:
  `_presentation` now emits `l_um` (µm, 3 dp) instead of `l_nm`, matching
  the width column; schema test updated.
- Simplified the UI per user request: removed the long subtitle, per-field
  hint paragraphs, verbose section titles, matched-pair annotations, the
  large footer, and the node-voltage rows (still in the API JSON);
  compressed banners to one line + short meta; guard provenance condensed
  to one line; scope warning kept (one short line) on every result;
  unresolved keeps its one-line honesty note (budget evidence, not
  infeasibility proof).
- `node --check` clean; 32 web tests green; server restarted; live
  end-to-end check: same request as the user's screenshot renders
  `L 1.409 µm` with a bit-identical design (W 147.082 µm, 157.932 µA).

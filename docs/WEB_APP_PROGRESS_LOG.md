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

## 2026-09-04 — UI redesign to the stitch_UI studio design (user request)

- Replaced the minimal UI with the design from `stitch_UI/` (Tailwind CDN +
  Inter/JetBrains Mono): header with engine status pill / Reset Defaults /
  Export Spectre .scs, topology strip, left spec-input card with live
  1.25x-overshoot hint and Internal Target / Policy Algorithm box, right
  dashboard (status banner, 4 metric cards, geometry table, constraint
  verification matrix), scope disclaimer, footer with backend status.
- Honest substitutions for the mock's placeholder data: multiplier "16x/12x"
  -> "1x" (single matched devices, m=1 in the golden netlist); "Vov ~168 mV"
  -> real tail-node voltage from the LUT metrics; "Stable (> 60)" -> the
  verifier's actual 45-degree floor; "OPTIMAL CONVERGENCE" -> "VERIFIED
  CANDIDATE" (a verified candidate is not proven optimal); fabricated
  "v2.4.19" -> oracle v0.1.0; constraint rows show real W_nmos_max/W_pmos_max
  limits (250/750 um) and the real L_domain range instead of 0.00/NaN.
- New endpoint `POST /api/v1/netlist`: renders the golden Spectre netlist
  for a verified sizing via the canonical `spectre_job.render_netlist`
  (pure text, independent of the LUT engine; validator rejects
  out-of-domain geometry with 422). The Export button downloads the .scs.
- Verified live (35dB/100MHz/1pF/200uW -> local_refinement_verified, 306
  evals, 8/8 checks): identical design to the mock's numbers; netlist
  export 200 with correct parameters line + analyses. 34 web tests green
  (2 new netlist tests). Note: Tailwind CDN + Google Fonts require
  internet; offline the layout degrades (API unaffected).

## 2026-09-04 — UI fix: removed circuit card + disclaimer; stale-cache fix

- Removed (user request): the "Differential 5-Transistor Cell" card and the
  visible scope-disclaimer line. The scope warning remains in every API
  response (scope_warning field) but is no longer shown in the browser.
- Bug "Size button shows nothing": root cause was a stale browser-cached
  app.js from the previous layout — its handlers reference element ids that
  no longer exist, so the submit handler died silently on null elements.
  Fixes: (1) static files now served with Cache-Control: no-cache (ETag
  revalidation, never stale); (2) explicit ?v=2 on style.css/app.js;
  (3) app.js renders the idle banner on load so the page always shows a
  status banner, giving immediate feedback when the engine runs.
- Verified: no-cache header live, both elements gone from the served page,
  JS syntax OK, 34 web tests green.

## 2026-09-04 — stitch_UI v2 redesign + automation test plan

- Redesigned web_app/static to the updated stitch_UI mock: circuit-trace
  PCB watermark with pulse animations, enhanced header (h-20, backdrop
  blur, silicon-die icon badge, gradient title), shimmer topology strip
  with live LUT-engine state, spec-field icons + Open-Loop/Unity
  Freq/Output Pin/VDD Budget tags, animated gradient submit button,
  gradient success banner with LUT-Verified pill and VERIFIED CANDIDATE
  badge, interactive metric cards, ring-dot geometry rows. Honest
  substitutions kept: multiplier 1x, V_tail (not Vov), 45-degree PM floor,
  LUT-Verified (not "Spectre Verified"), oracle v0.1.0, real W-limit and
  L_domain rows. The circuit-description card and the scope disclaimer line
  stay removed per the user's explicit earlier request (the regenerated
  mock incidentally re-includes them).
- Fixed a malformed pill/badge HTML-concatenation bug in the new banner
  code (caught by node --check before serving) and a duplicate const.
- Added tests/test_web_static.py (4 tests): JS-to-HTML id cross-reference,
  duplicate-id, cache-busting version, innerHTML-target checks - this is
  the regression guard for the stale-markup "button does nothing" bug
  class. Web suite now 38 tests; full non-LUT suite green.
- Wrote docs/WEB_APP_TEST_PLAN.md: L0-L5 layers, test matrix (implemented
  vs specified), Playwright E2E blueprint, real-LUT E2E scripting, CI
  gates, exit criteria.

## 2026-09-04 — L4 Playwright suite + L5 scripted checks; constraint-unit fix; de-branding

- **Constraint-display bug fixed (user screenshot)**: the matrix showed
  0.00 for Power_max and the W-limit rows because display scaling divided
  where it had to multiply (W -> µW, m -> µm are x1e6; only Hz -> MHz is
  x1e-6). Corrected rows: Power_max 200.00 / 189.52 µW, +10.48 µW margin.
  The two internal W-bounds rows are now hidden from display entirely
  (always "bound"-type PASS; still in the API payload and in the pass
  count? no - badge counts visible rows: 6 / 6).
- **De-branding (user request)**: all user-visible "TSMC" wording removed;
  the app now says "65nm CMOS" (header badge, topology chip, footer).
- **L4 implemented**: tests/e2e/test_ui.py - 11 Playwright scenarios
  (E1-E9, E11, E12) against the real FastAPI app with a stubbed sizing
  runtime on port 8123; skips cleanly without Playwright. Two real bugs
  found by writing the suite: (1) stale "8 / 8" selector after hiding the
  W rows (test-side), (2) header action buttons overflowed 390px viewport
  by 31px -> buttons are icon-only below the sm breakpoint now.
- **L5 scripted**: scripts/run_web_e2e_checks.py launches the real server,
  checks R1 parity (8/8 sub-checks identical vs direct API, seed 0),
  R2 repeat determinism (bit-identical), R3 latency (7.0-34.6 s on
  local_refinement path; envelope <= 90 s). Evidence:
  evaluation_results/web_app/l5_checks_20260904.json. PASS.
- Playwright + Chromium installed into .venv (dev dependency; not added to
  the core web extra). Docs/WEB_APP_TEST_PLAN.md statuses updated to
  implemented.

## 2026-09-04 — stitch_UI v3 redesign (user: "must look exactly like the design")

- Rewrote web_app/static to the new stitch mock: light frost background,
  5T badge + large title header with Engine pill / Reset / Export, clean
  Target Specifications card (unit chips inside inputs, shimmer CTA), 4 KPI
  cards with cyan top bars and green check chips, and the redesigned
  Circuit Parameters table (NMOS/PMOS/Bias chips, relative-scale progress
  bars, operating-point column). Removed elements the v3 mock drops:
  topology strip, status/constraint cards, footer, watermark.
- Mock placeholder data replaced with real, computed values: multiplier 1x
  (netlist m=1), "Sat. margin ~= 419 mV / Saturation Checked" from the
  verifier's Sat_margin_min (mock's Vov/Vdsat are not per-device available),
  branch bias = Itail/2, relative scale = W/W1 (mock's own 68.4% matches
  this formula), aspect ratio from full-precision W/L, Stable (> 45 deg)
  per the verifier floor, "Ideal Tail Current Sink" (no M5 device).
- Functional states kept: slim white status cards in the same design
  language for unresolved (amber) and errors (red); results hidden until a
  verified run; export gating; no-cache + ?v=5.
- Fixed another watts-scaling bug in the power-budget chip (same class as
  the constraint-table bug; caught by the E2E suite this time).
- Header wraps on narrow screens (E11 passes at 390px).
- Verified: 38 pytest + 10 Playwright green; screenshot comparison vs
  screen.png at 1629px (ui_v3_screenshot.png stub, ui_v3_live_real.png
  real engine) - layout and styling match the mock; real data shown.

## 2026-09-04 — Removed Multiplier + Relative Scale columns (user request)

- Dropped both columns (headers and cells) from the Circuit Parameters
  table; the tail row's colspan layout re-balanced to the 5-column grid.
  Assets bumped to ?v=6; E2E updated to assert the columns stay absent.
- 38 pytest + 10 Playwright green.

## 2026-09-04 — Removed Aspect Ratio column + "/ leg" suffix (user request)

- Circuit Parameters table is now 4 columns: Device / Role, Width, Length,
  Operating Point / Bias. Branch Bias shows "78.966 µA" without "/ leg".
  Assets bumped to ?v=7; E2E asserts both stay absent. Tests green.

## 2026-09-04 — Hang diagnosis + watchdog logging; logo and attribution

- User-reported hang ("same specs took 25 s, now nothing"): the long-lived
  server process (up ~12 h) lost its sizing worker - py-spy showed no
  thread inside the sizing path, so queued requests waited on the worker
  lock forever. Not caused by any UI/backend code change. Killed and
  restarted the server; the previously-hanging specs returned in 29.4 s
  with the bit-identical design (306 evals).
- Watchdog/observability added so the next hang is diagnosable:
  runtime.size logs "size <id> start" when the worker picks a request and
  tracks current_request; /api/v1/health now reports busy + elapsed for
  the in-flight request.
- Branding (user request): stitch_UI/Logo.png copied to web_app/static;
  header 5T badge replaced with the personal logo; footer added with
  "Eng. Hassan Shehata · Analog IC Design" and a LinkedIn link
  (linkedin.com/in/hshehata). Screenshot ui_v3_logo.png verified.
- 4 static + 10 Playwright tests green.

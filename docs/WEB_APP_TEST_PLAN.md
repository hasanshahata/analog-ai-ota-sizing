# Web App Test Plan — UI, API, Runtime, and Pipeline

**Created:** 2026-09-04 · **Status:** L0–L4 implemented and green (38 pytest + 11 Playwright); L5 scripted (`scripts/run_web_e2e_checks.py`, PASS 2026-09-04).

Covers everything from the browser form down to the verified-sizing oracle:
`web_app/static/*` → `analog_ai/web/{schemas,runtime,app}.py` →
`analog_ai/sizing.py` → surrogate + LUT engine → hard-constraint verifier.

## 0. Principles

1. **The verifier is the only pass/fail authority** — no test may accept a
   design that the hard-constraint verifier rejected, and no test treats an
   `unresolved` result as a failure of honesty (it is a valid outcome).
2. **Tests must not require the 5.5 GB LUTs** except the explicitly marked
   real-LUT layer (L5); CI runs L0–L3 anywhere.
3. **Honesty invariants are testable**: unresolved ⇒ no geometry anywhere in
   the payload; success ⇒ `user_verdict` true and the frozen guard policy
   provenance present; the word "infeasible" never appears as a label.
4. Every UI element the JS touches must exist — stale-markup regressions
   (the "button does nothing" class) are caught without a browser.

## 1. Layers

| Layer | Target | Tooling | LUTs | Status |
|---|---|---|---|---|
| **L0** static consistency | `index.html` ↔ `app.js` ↔ `style.css` | plain pytest (regex cross-refs) | no | ✅ `tests/test_web_static.py` (4 tests) |
| **L1** contract units | `schemas.py`: validation, units, frozen display rule | pytest + pydantic | no | ✅ `test_web_schemas.py` (14) |
| **L2** runtime logic | `runtime.py`: forwarding, locking, error hygiene | pytest + fakes + monkeypatch | no | ✅ `test_web_runtime.py` (9) |
| **L3** HTTP API | `app.py`: status codes, error format, netlist export | pytest + FastAPI TestClient | no | ✅ `test_web_api.py` (11) |
| **L4** browser E2E | rendered UI behavior | Playwright (stubbed backend) | no | ✅ `tests/e2e/test_ui.py` (11) |
| **L5** real-LUT E2E | full stack parity + latency | `scripts/run_web_e2e_checks.py` | yes | ✅ PASS 2026-09-04 (`l5_checks_20260904.json`) |

## 2. Test matrix

### L0 — static consistency (implemented)

| ID | Test | Asserts |
|---|---|---|
| S1 | js-id cross-ref | every `$("id")` in app.js exists as `id=` in index.html |
| S2 | duplicate ids | no duplicated `id=` in index.html |
| S3 | cache busting | style.css and app.js referenced with `?v=N` |
| S4 | innerHTML targets | every `.innerHTML` target exists statically |

### L1 — contract (implemented; keep green)

Valid input + unit conversion (MHz→Hz, µW→W, exactness), all four boundary
values accepted, missing field / NaN / ±inf / out-of-range / boolean /
unknown-field rejection **without clipping**, unresolved response contains no
geometry keys and no "infeasible" wording, success factory refuses
`user_verdict=false` or missing design, NaN→null sanitisation, strict-JSON
producibility (`json.dumps(..., allow_nan=False)`), domain-constraint tuple
safety, presentation rounding (W µm 3dp, L µm 3dp, I µA 3dp, GBW MHz 3dp).

### L2 — runtime (implemented)

Verbatim request forwarding, caller-dict preservation, guard policy applied
only inside `size_ideal_tail_ota`, unresolved ⇒ no geometry, exception →
sanitised `SizingFailure` (no internals leaked), not-ready refusal, health
without engine load, **serialized concurrency** (alternating enter/exit
under 3 threads), failed-load recording with sanitised detail.

### L3 — HTTP API (implemented)

200 success (full contract present), 200 unresolved (no geometry), 422
missing / out-of-range / unknown field / raw `NaN` JSON, 503 not-ready,
500 sanitised sizing failure, health reflects state without loading, failed
health detail sanitised, static index served, **netlist export**: 200 with
golden template + analyses lines, 422 on bad geometry.

### L4 — browser E2E (implemented: `tests/e2e/test_ui.py`; E10 covered for the ready state)

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| E1 | idle state | load `/` | idle banner visible; export disabled; engine pill shows state |
| E2 | verified run | fill 35/100/1/200, click Size | button disabled + "Synthesizing… Ns"; within timeout: emerald banner, VERIFIED CANDIDATE badge, 4 metric cards populated, 3 geometry rows, 8 constraint rows, checks badge "8 / 8", export enabled, Internal Target = 125.000 MHz |
| E3 | overshoot hint live | type GBW 80 | hint reads "Overshoot target: 100.000 MHz (1.25×)" |
| E4 | out-of-range input | set GBW 900, submit | red banner, code validation_error, no results rendered |
| E5 | unresolved path | submit a known-hard request (stub returns unresolved) | amber banner UNRESOLVED, zero geometry rows visible, guidance shown |
| E6 | error path | stub returns 500 | red banner with sanitised message; no stack trace text |
| E7 | reset | click Reset Defaults | inputs 35/100/1/200; idle banner; export disabled |
| E8 | netlist download | click Export after E2 | download event; filename `ota_sizing_100MHz.scs`; content starts "simulator lang=spectre" |
| E9 | double-submit guard | click twice rapidly | only one `/api/v1/size` request in flight (network log) |
| E10 | engine states | stub /health loading→ready | pill amber "Engine Loading" → green "Engine Ready"; strip text updates |
| E11 | narrow viewport | 390px wide | no horizontal overflow; grid single-column |
| E12 | keyboard-only | tab to inputs, Enter to submit | focus visible; form submits; result announced (aria-live region) |

### L5 — real-LUT end-to-end (manual today; scripting spec in §5)

| ID | Scenario | Expected |
|---|---|---|
| R1 | web vs direct parity | served JSON design/metrics/verdicts/policy/eval-count identical to a direct `size_ideal_tail_ota(seed=0)` call in a separate process (see `evaluation_results/web_app/parity_smoke_001.json`) |
| R2 | deterministic repeat | same request twice ⇒ bit-identical design (seed fixed) |
| R3 | latency envelope | direct path ≤ 15 s; local-refinement path ≤ 90 s; full-fallback unresolved ≤ 12 min; record p50/p95 |
| R4 | concurrency queue | two simultaneous requests ⇒ second completes after first (lock), both verified |
| R5 | netlist round-trip | exported .scs parameters match the verified design's W/L/Itail exactly |

## 3. Commands

```bash
# L0–L3 (no LUTs, <1 min) — CI default
.venv/Scripts/python -m pytest tests/test_web_static.py tests/test_web_schemas.py \
    tests/test_web_runtime.py tests/test_web_api.py -p no:warnings

# full regression incl. non-web units
.venv/Scripts/python -m pytest tests/ --ignore=tests/test_integration_real_luts.py

# JS syntax gate
node --check web_app/static/app.js
```

## 4. L4 implementation notes (Playwright, Python)

Setup (one-time, ~120 MB browser download):

```bash
uv pip install --python .venv/Scripts/python.exe playwright pytest-playwright
.venv/Scripts/python.exe -m playwright install chromium
```

Suggested file `tests/e2e/test_ui.py` — serve the app with a **stubbed
runtime** (fast, deterministic, no LUTs) by launching uvicorn on a thread:

```python
import threading, uvicorn, pytest
from fastapi.testclient import TestClient  # noqa: F401  (httpx present)
from analog_ai.web.app import create_app
from analog_ai.web.runtime import SizingRuntime
from analog_ai.web.schemas import json_safe

SUCCESS = { ... }   # reuse the fixture record from tests/test_web_api.py
UNRESOLVED = { ... }

@pytest.fixture(scope="module")
def server():
    rt = SizingRuntime(project_root="/nonexistent"); rt.state = "ready"
    rt.ota = rt.model = object()
    import numpy as np; rt.feat_lo = np.zeros(4); rt.feat_hi = np.ones(4)
    import analog_ai.sizing as s
    calls = []
    def fake(ota, model, specs, lo, hi, **k):
        calls.append(dict(specs))
        return UNRESOLVED if specs["GBW_min"] > 3.5e8 else SUCCESS
    s.size_ideal_tail_ota, orig = fake, s.size_ideal_tail_ota
    app = create_app(runtime=rt, load_on_startup=False)
    config = uvicorn.Config(app, host="127.0.0.1", port=8077, log_level="warning")
    srv = uvicorn.Server(config)
    t = threading.Thread(target=srv.run, daemon=True); t.start()
    yield "http://127.0.0.1:8077", calls
    srv.should_exit = True; t.join(timeout=5)

def test_verified_run(page, server):
    base, _ = server
    page.goto(base)
    page.fill("#min-gain", "35")
    page.click("#submit-btn")
    page.wait_for_selector("#checks-text:has-text('8 / 8 Checks Passed')")
    assert page.is_disabled("#export-btn") is False
    assert page.locator("#geometry-body tr").count() == 3
```

Notes: monkeypatching must happen before `create_app` serves requests (the
runtime calls `analog_ai.sizing.size_ideal_tail_ota` lazily inside `size()`,
so patching the module attribute works — same seam as the L2 tests). Keep
E2E off the real LUTs so it runs in seconds.

## 5. L5 scripting sketch

Parameterize `scripts/run_web_app.py` (already supported: `--port`), launch
once, then drive with `httpx`:

```python
r = httpx.post(f"{base}/api/v1/size", json={...}, timeout=900)
direct = size_ideal_tail_ota(ota, ck["proposal"], user, lo, hi, seed=0)
assert r.json()["design_variables"] == direct["design_variables"]
```

Persist each run under `evaluation_results/web_app/` (parity, latency,
repeats) as the R1–R5 evidence trail.

## 6. CI wiring (proposed)

1. Gate 1 (every commit): `pytest tests/ --ignore=tests/test_integration_real_luts.py`
   + `node --check` — already green locally, ~1 min.
2. Gate 2 (nightly or pre-release): L5 R1–R3 on a machine with the LUTs;
   fail if parity breaks or p95 latency doubles.
3. Gate 3 (optional): L4 suite with Playwright chromium; skip cleanly when
   browsers are not installed (`pytest.importorskip("playwright")`).

## 7. Exit criteria for "fully automated"

- [x] L0–L3 in the default pytest run (38 web tests, green)
- [x] L4 committed (11 Playwright scenarios against a stubbed backend;
      skips cleanly when Playwright is not installed)
- [x] L5 R1–R3 scripted with evidence auto-written under
      `evaluation_results/web_app/` (PASS 2026-09-04)
- [x] All gates runnable via a single command each
- [ ] E10 loading→ready transition (needs a controllable stub; ready state
      is covered)

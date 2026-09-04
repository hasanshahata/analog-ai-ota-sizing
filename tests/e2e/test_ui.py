"""L4 browser E2E tests for the sizing web UI (Playwright, stubbed backend).

Runs the real FastAPI app with a stubbed sizing runtime on a local port and
drives a headless Chromium through the scenarios defined in
docs/WEB_APP_TEST_PLAN.md (E1-E12, v3 design). No LUTs required; the whole
module skips cleanly when Playwright is not installed.

    uv pip install --python .venv/Scripts/python.exe playwright pytest-playwright
    .venv/Scripts/python.exe -m playwright install chromium
    .venv/Scripts/python.exe -m pytest tests/e2e -p no:cacheprovider
"""

from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

BASE_URL = "http://127.0.0.1:8123"

SUCCESS = {
    "topology": "5t_ota_ideal_tail", "corner": "tt_lib",
    "user_specs": {"Gain_min": 35.0, "GBW_min": 1e8, "CL_pF": 1.0,
                   "Power_max": 2e-4},
    "internal_specs": {"Gain_min": 35.0, "GBW_min": 1.18e8, "CL_pF": 1.0,
                       "Power_max": 2e-4},
    "calibration": {"version": "tt-ideal-tail-gbw-v2-tiered",
                    "gbw_guard_band": 0.18},
    "status": "local_refinement_verified", "n_oracle_evals": 306,
    "pipeline": {"stages": []},
    "design_variables": {"L1": 0.5e-6, "gmid1": 12.0, "L3": 0.6e-6,
                         "gmid3": 14.0, "Itail": 75e-6},
    "physical_design": {"L1": 1.4088e-6, "W1": 147.0817e-6,
                        "L3": 1.3540e-6, "W3": 100.5785e-6, "Itail": 157.932e-6},
    "lut_metrics": {"DC_Gain_dB": 35.0, "GBW": 125.83e6, "PM": 73.32,
                    "Power": 189.52e-6, "Vout": 0.6606, "Vtail": 0.1288,
                    "Vmirror": 0.6606},
    "user_constraints": [
        {"name": "Gain_min", "kind": "min", "limit": 35.0, "achieved": 35.0,
         "residual": 0.0, "scale": 10.0, "passed": True, "detail": ""},
        {"name": "GBW_min", "kind": "min", "limit": 1e8, "achieved": 1.2583e8,
         "residual": -0.2583, "scale": 1e8, "passed": True, "detail": ""},
        {"name": "Power_max", "kind": "max", "limit": 2e-4,
         "achieved": 1.8952e-4, "residual": -0.0524, "scale": 2e-4,
         "passed": True, "detail": ""},
        {"name": "PM_min", "kind": "min", "limit": 45.0, "achieved": 73.32,
         "residual": -0.6293, "scale": 45.0, "passed": True, "detail": ""},
        {"name": "Sat_margin_min", "kind": "min", "limit": 0.05,
         "achieved": 0.42, "residual": -7.4, "scale": 0.05, "passed": True,
         "detail": ""},
        {"name": "W_nmos_max", "kind": "max", "limit": 250e-6,
         "achieved": 147.08e-6, "residual": -0.41, "scale": 250e-6,
         "passed": True, "detail": ""},
        {"name": "W_pmos_max", "kind": "max", "limit": 750e-6,
         "achieved": 100.58e-6, "residual": -0.87, "scale": 750e-6,
         "passed": True, "detail": ""},
        {"name": "L_domain", "kind": "domain", "limit": (60e-9, 1.5e-6),
         "achieved": (1.354e-6, 1.4088e-6), "residual": 0.0, "scale": 1.0,
         "passed": True, "detail": ""},
    ],
    "internal_constraints": [],
    "user_verdict": True, "internal_verdict": True,
}

UNRESOLVED = {
    "topology": "5t_ota_ideal_tail", "status": "unresolved",
    "n_oracle_evals": 3944, "pipeline": {"stages": []},
    "user_specs": {"Gain_min": 44.0, "GBW_min": 3e8, "CL_pF": 5.0,
                   "Power_max": 5e-5},
    "internal_specs": {"Gain_min": 44.0, "GBW_min": 3.75e8, "CL_pF": 5.0,
                       "Power_max": 5e-5},
    "design_variables": None, "physical_design": None, "lut_metrics": None,
    "user_constraints": [], "internal_constraints": [],
    "user_verdict": False, "internal_verdict": False,
}

CALLS: list[dict] = []


def _fake_size(ota, model, specs, lo, hi, **kwargs):
    CALLS.append(dict(specs))
    gain = specs["Gain_min"]
    if gain >= 44.5:
        raise ZeroDivisionError("internal detail /secret/path")
    if gain >= 44.0:
        return dict(UNRESOLVED,
                    user_specs=dict(specs),
                    internal_specs={**specs, "GBW_min": specs["GBW_min"] * 1.18})
    if gain == 33.0:
        time.sleep(1.0)   # E9: keep the button disabled long enough to race it
    return dict(SUCCESS,
                user_specs=dict(specs),
                internal_specs={**specs, "GBW_min": specs["GBW_min"] * 1.18})


@pytest.fixture(scope="module")
def server():
    import numpy as np
    import uvicorn
    import analog_ai.sizing as sizing_mod
    from analog_ai.web.app import create_app
    from analog_ai.web.runtime import SizingRuntime

    orig = sizing_mod.size_ideal_tail_ota
    sizing_mod.size_ideal_tail_ota = _fake_size
    rt = SizingRuntime(project_root="/nonexistent")
    rt.state = "ready"
    rt.ota, rt.model = object(), object()
    rt.feat_lo, rt.feat_hi = np.zeros(4), np.ones(4)
    app = create_app(runtime=rt, load_on_startup=False)
    config = uvicorn.Config(app, host="127.0.0.1", port=8123,
                            log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            import urllib.request
            urllib.request.urlopen(BASE_URL + "/api/v1/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    yield BASE_URL
    srv.should_exit = True
    thread.join(timeout=5)
    sizing_mod.size_ideal_tail_ota = orig


def _size(page, gain="35", gbw="100", cl="1", power="200"):
    page.fill("#min-gain", gain)
    page.fill("#min-gbw", gbw)
    page.fill("#load-cap", cl)
    page.fill("#max-power", power)
    page.click("#submit-btn")


# ------------------------------------------------------------- E1 idle --
def test_e1_idle_state(page, server):
    page.goto(server)
    assert not page.locator("#results-area").is_visible()
    assert page.locator("#export-btn").is_disabled()
    assert "Engine Ready" in page.locator("#engine-text").inner_text()


# -------------------------------------------------------- E2 verified --
def test_e2_verified_run(page, server):
    page.goto(server)
    _size(page)
    page.wait_for_selector("#geometry-body tr", timeout=15000)
    assert page.locator("#geometry-body tr").count() == 3
    assert page.locator("#m-gain").inner_text().startswith("35.00")
    assert page.locator("#m-gbw").inner_text().startswith("125.83")
    assert page.locator("#m-pm").inner_text().startswith("73.32")
    assert page.locator("#m-pwr").inner_text().startswith("189.52")
    # KPI chips (real data)
    assert "≥ 35.00 Target" in page.locator("#m-gain-sub").inner_text()
    assert "+25.8% Margin" in page.locator("#m-gbw-sub").inner_text()
    assert "Stable (> 45°)" in page.locator("#m-pm-sub").inner_text()
    assert "5.2% Budget" in page.locator("#m-pwr-sub").inner_text()
    # circuit parameters rows: roles, real multiplier, relative scale, bias
    rows = page.locator("#geometry-body tr")
    assert "Differential Input Pair" in rows.nth(0).inner_text()
    assert "Active Current Mirror Load" in rows.nth(1).inner_text()
    assert "Ideal Tail Current Sink" in rows.nth(2).inner_text()
    body = page.locator("#geometry-body").inner_text()
    # display values snapped: W/L to the 5 nm grid, currents to 1 µA
    assert "147.080" in body and "1.410" in body
    assert "158 µA" in body                      # snapped tail current
    assert "79 µA" in body                       # snapped branch (Itail / 2)
    assert "Sat. margin ≈ 420 mV" in body        # from the verifier
    assert "Saturation Checked" in body
    # multiplier, relative-scale and aspect-ratio columns are removed
    assert "1×" not in body and "Multiplier" not in body
    assert "Relative Scale" not in page.locator("table").inner_text()
    assert "Aspect Ratio" not in page.locator("table").inner_text()
    assert "/ leg" not in body
    assert not page.locator("#export-btn").is_disabled()
    assert not page.locator("#status-banner").is_visible()
    # cost chip: pipeline path, oracle evals, wall time
    chip = page.locator("#meta-chip-text").inner_text()
    assert chip.startswith("local_refinement_verified · 306 evals · ")
    assert "expected Spectre UGF ≈ 118 MHz" in chip   # 125.83 * 0.94


# --------------------------------------------------- E4 out of range ---
def test_e4_out_of_range_rejected(page, server):
    page.goto(server)
    _size(page, gbw="900")
    page.wait_for_selector("#status-banner:not(.hidden)")
    text = page.locator("#status-banner").inner_text()
    assert "Request refused" in text
    assert "300" in text                       # field-level bound message
    assert not page.locator("#results-area").is_visible()


# ---------------------------------------------------- E5 unresolved ----
def test_e5_unresolved_no_geometry(page, server):
    page.goto(server)
    _size(page, gain="44")
    page.wait_for_selector("#status-banner:not(.hidden)")
    text = page.locator("#status-banner").inner_text()
    assert "No verified sizing within budget" in text
    assert "not proof of infeasibility" in text
    assert "UNRESOLVED" in text
    assert not page.locator("#results-area").is_visible()


# ------------------------------------------------------- E6 500 error --
def test_e6_internal_error_sanitised(page, server):
    page.goto(server)
    _size(page, gain="44.8")
    page.wait_for_selector("#status-banner:not(.hidden)")
    text = page.locator("#status-banner").inner_text()
    assert "Request refused" in text
    assert "secret" not in text and "Traceback" not in text


# ---------------------------------------------------------- E7 reset ---
def test_e7_reset_defaults(page, server):
    page.goto(server)
    _size(page, gain="30", gbw="150", cl="2", power="300")
    page.wait_for_selector("#geometry-body tr", timeout=15000)
    page.click("#reset-btn")
    assert page.input_value("#min-gain") == "35"
    assert page.input_value("#min-gbw") == "100"
    assert page.input_value("#load-cap") == "1"
    assert page.input_value("#max-power") == "200"
    assert not page.locator("#results-area").is_visible()
    assert not page.locator("#status-banner").is_visible()
    assert page.locator("#export-btn").is_disabled()


# ------------------------------------------------------ E8 netlist -----
def test_e8_netlist_download(page, server):
    page.goto(server)
    _size(page)
    page.wait_for_selector("#geometry-body tr", timeout=15000)
    with page.expect_download() as dl:
        page.click("#export-btn")
    download = dl.value
    assert download.suggested_filename == "ota_sizing_100MHz.scs"
    body = open(download.path(), "r", encoding="utf-8").read()
    assert body.startswith("// Generated for: spectre") or \
        "simulator lang=spectre" in body
    assert "W12" in body and "acCorr" in body


# ----------------------------------------------- E9 double-submit -----
def test_e9_double_submit_guard(page, server):
    requests = []
    page.on("request", lambda r: requests.append(r.url)
            if "/api/v1/size" in r.url else None)
    page.goto(server)
    _size(page, gain="33")          # stub holds this one in-flight for ~1 s
    assert page.locator("#submit-btn").is_disabled()
    try:
        page.click("#submit-btn", timeout=2000, force=True)
    except Exception:
        pass  # pointer-events interception is also an acceptable guard
    page.wait_for_selector("#geometry-body tr", timeout=15000)
    assert len(requests) == 1


# ------------------------------------------------- E11 narrow screen ---
def test_e11_narrow_viewport_no_overflow(page, server):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(server)
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 1, f"horizontal overflow of {overflow}px at 390px"


# ------------------------------------------------- E12 keyboard-only ---
def test_e12_keyboard_submit(page, server):
    page.goto(server)
    page.focus("#min-gain")
    page.keyboard.press("Enter")     # implicit form submission
    page.wait_for_selector("#geometry-body tr", timeout=15000)

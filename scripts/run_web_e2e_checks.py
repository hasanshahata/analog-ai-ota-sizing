"""L5 real-LUT web checks (R1-R3 in docs/WEB_APP_TEST_PLAN.md).

Launches the real sizing server (needs tech_luts/), then verifies:

  R1  parity   - served JSON design == direct size_ideal_tail_ota(seed=0)
  R2  repeat   - same request twice => bit-identical design
  R3  latency  - per-path wall times recorded

Evidence is written to evaluation_results/web_app/l5_checks_*.json.
Run:  .venv/Scripts/python scripts/run_web_e2e_checks.py [--port 8093]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUESTS = [
    {"Gain_min_dB": 35.0, "GBW_min_MHz": 100.0, "CL_pF": 1.0,
     "Power_max_uW": 200.0},
    {"Gain_min_dB": 32.0, "GBW_min_MHz": 120.0, "CL_pF": 2.0,
     "Power_max_uW": 250.0},
]


def _post(base: str, path: str, payload: dict) -> tuple[dict, float]:
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=1800) as resp:
        body = json.loads(resp.read())
    return body, time.perf_counter() - t0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8093)
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    # ---- start the real server -------------------------------------------
    print("starting sizing server (loads ~5.5 GB LUTs)...", flush=True)
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "run_web_app.py"),
         "--port", str(args.port)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        state = None
        for _ in range(240):
            try:
                with urllib.request.urlopen(base + "/api/v1/health",
                                            timeout=2) as r:
                    state = json.loads(r.read())["state"]
                if state == "ready":
                    break
            except Exception:
                pass
            time.sleep(2)
        assert state == "ready", f"server never became ready (state={state})"
        print("server ready.", flush=True)

        results = {"date": str(date.today()), "checks": {}}

        # ---- R2 repeat determinism + R3 latency (served path) -------------
        timings = {}
        designs = {}
        for req in REQUESTS:
            body1, dt1 = _post(base, "/api/v1/size", req)
            body2, dt2 = _post(base, "/api/v1/size", req)
            assert body1["status"] == body2["status"] == "success", \
                body1.get("status")
            designs[json.dumps(req, sort_keys=True)] = (body1, body2, dt1, dt2)
            timings[f"{req['Gain_min_dB']}dB/{req['GBW_min_MHz']}MHz"] = {
                "run1_s": round(dt1, 2), "run2_s": round(dt2, 2),
                "path": body1["sizing_path"]["pipeline_status"],
                "evals": body1["sizing_path"]["n_oracle_evals"]}
        identical = all(
            b1["design_variables"] == b2["design_variables"]
            and b1["lut_metrics"] == b2["lut_metrics"]
            for b1, b2, _, _ in designs.values())
        results["checks"]["R2_repeat_identical"] = {
            "pass": bool(identical), "timings": timings}
        print(f"R2 repeat identical: {identical}; timings: {timings}",
              flush=True)

        # ---- R1 parity (direct API in-process, second LUT copy) -----------
        print("loading direct engine for parity check...", flush=True)
        sys.path.insert(0, str(ROOT))
        import numpy as np
        from analog_ai.loader import load_engine
        from analog_ai.sizing import size_ideal_tail_ota
        from analog_ai.surrogate.train import load_checkpoint

        _, ota = load_engine(op_point="solved", tail_device="ideal")
        champ = Path(json.loads(
            (ROOT / "models/surrogate/poc/champion.json").read_text()
        )["champion"]).name
        ck = load_checkpoint(str(ROOT / "models/surrogate/poc" / champ))
        req = REQUESTS[0]
        user = {"Gain_min": req["Gain_min_dB"],
                "GBW_min": req["GBW_min_MHz"] * 1e6,
                "CL_pF": req["CL_pF"],
                "Power_max": req["Power_max_uW"] * 1e-6}
        direct = size_ideal_tail_ota(
            ota, ck["proposal"], user,
            np.asarray(ck["meta"]["feat_lo"]),
            np.asarray(ck["meta"]["feat_hi"]), seed=0)
        served = designs[json.dumps(req, sort_keys=True)][0]
        checks = {
            "design_variables": direct["design_variables"]
            == served["design_variables"],
            "lut_metrics": direct["lut_metrics"] == served["lut_metrics"],
            "user_verdict": direct["user_verdict"]
            == served["verdict"]["user_verdict"] is True,
            "internal_verdict": direct["internal_verdict"]
            == served["verdict"]["internal_verdict"] is True,
            "policy": direct["calibration"]["version"]
            == served["calibration"]["version"],
            "internal_gbw": direct["internal_specs"]["GBW_min"]
            == served["internal_specs"]["GBW_min"],
            "n_evals": direct["n_oracle_evals"]
            == served["sizing_path"]["n_oracle_evals"],
            "path": direct["status"]
            == served["sizing_path"]["pipeline_status"],
        }
        parity = all(checks.values())
        results["checks"]["R1_parity"] = {"pass": bool(parity),
                                          "detail": checks}
        print(f"R1 parity: {parity} {checks}", flush=True)

        # ---- write evidence ------------------------------------------------
        results["checks"]["R3_latency"] = {
            "note": "served wall times per request in R2.timings; "
                    "envelope: direct <= 15 s, refinement <= 90 s"}
        out = ROOT / "evaluation_results" / "web_app"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"l5_checks_{date.today():%Y%m%d}.json"
        path.write_text(json.dumps(results, indent=2))
        print(f"wrote {path}", flush=True)
        assert parity and identical, "L5 checks FAILED"
        print("L5 checks: PASS")
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()

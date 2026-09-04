# Web App User Guide — Ideal-Tail 5T OTA Sizing

A small local web application for the verified nominal-TT sizing pipeline.
Enter four specifications; receive either a hard-verified candidate sizing
or an explicit `unresolved` result with **no** transistor dimensions.

## 1. What it supports (and what it does not)

Supported — exactly this, nothing else:

- topology: matched NMOS input pair (M1 = M2) + matched PMOS current-mirror
  load (M3 = M4), **ideal tail-current source** (no finite M5);
- TSMC 65 nm LUT device data at the typical `tt_lib` corner;
- VDD = 1.2 V, Vincm = 0.6 V, solved LUT operating point;
- deployment guard policy `tt-ideal-tail-gbw-v2-tiered` (internal GBW
  target is 1.18 × your requested GBW minimum for requests up to 300 MHz;
  validated 2026-09-04 on a third disjoint blind Cadence campaign:
  25/25 user-spec passes, 0 false proxy passes).

**Not** supported: finite M5, other corners / PVT / Monte Carlo, other
supplies or common-mode points, other technologies, post-layout parasitics.
Results are **nominal LUT-based sizing candidates**, not signoff. Cadence
remains the final authority.

## 2. Installation

From the repository root (Python 3.11 venv):

```bash
# core + web dependencies (torch is required by the surrogate model)
uv pip install --python .venv/Scripts/python.exe -e ".[web]" torch
```

The LUT files `tech_luts/TSMC_fast_65nm_nch.pkl` and `..._pch.pkl`
(~2.76 GB each) must be present; they are excluded from git.

The deployed browser assets are fully local and require no CDN. Only frontend
developers rebuilding the committed stylesheet need Node.js: run `npm install`
and `npm run build:web-css` after changing Tailwind utility classes.

## 3. Launch

```bash
.venv/Scripts/python scripts/run_web_app.py          # http://127.0.0.1:8000/
```

Options: `--host 127.0.0.1 --port 8000`. Keep the default localhost bind;
the service has no authentication and must not be exposed to a network.

## 4. First start vs. later requests

- **Startup**: the ~5.5 GB LUT engine loads once in a background thread
  (tens of seconds on a warm cache; allow a few minutes cold). The status
  line at the top of the page shows `loading → ready`. The sizing endpoint
  answers HTTP 503 until ready.
- **Per request**: a direct verified proposal returns in ~2–10 s; requests
  that need local refinement take ~10–60 s; requests that exhaust global
  fallback can take several minutes. The UI shows an elapsed timer and
  blocks duplicate submissions.

## 5. The four inputs

| Field | Unit | Allowed range | Meaning |
|---|---|---|---|
| Minimum DC gain | dB | 20 – 45 | `Gain_min` |
| Minimum GBW | MHz | 50 – 300 | `GBW_min` |
| Load capacitance | pF | 0.1 – 5 | `CL_pF` |
| Maximum power | µW | 50 – 400 | `Power_max` |

Out-of-range or non-finite values are **rejected** (HTTP 422), never
clipped. Phase margin (≥ 45°) and device domain limits are enforced by the
hard-constraint verifier with frozen defaults; they are not editable.

## 6. Reading a result

**Success** (`✔ Verified sizing candidate`) shows:

- device sizing: M1 = M2 width/length, M3 = M4 width/length, ideal tail
  current (display-rounded; verdicts use full precision);
- predicted nominal LUT metrics: gain, GBW, phase margin, power, output /
  tail / mirror node voltages;
- per-constraint margins with PASS/FAIL chips (user contract);
- deployment-guard provenance: your GBW vs the internal guarded target,
  the guard band, policy version, and the internal-contract verdict;
- oracle-evaluation count and the scope warning.

**Unresolved** (`⚠ No verified design within budget`) shows **no
dimensions**. This is evidence of optimizer difficulty within the declared
budget, **not** proof that no design exists. Suggestions: relax a
specification (lower GBW/gain, allow more power, reduce load) or run a
larger offline search budget.

**Errors** are explicit: `validation_error` (fix the inputs),
`not_ready` (engine still loading — wait for the status line),
`sizing_failed` (internal failure; nothing was sized; see server logs),
or `server unreachable`.

## 7. HTTP API (for scripting)

```bash
curl -s http://127.0.0.1:8000/api/v1/health
curl -s -X POST http://127.0.0.1:8000/api/v1/size \
     -H "Content-Type: application/json" \
     -d '{"Gain_min_dB": 32, "GBW_min_MHz": 120, "CL_pF": 2, "Power_max_uW": 250}'
```

`GET /api/v1/health` → `{"state": "loading|ready|failed", ...}`.
`POST /api/v1/size` returns the full-precision SI record (canonical units:
GBW in Hz, power in W, CL in pF, gain in dB) plus a display `presentation`
layer. Responses are versioned under `/api/v1/`.

## 8. Verification status

- Fake-runtime unit/API tests run in CI without LUTs
  (`tests/test_web_*.py`).
- One real-LUT parity smoke compares a served request with a direct
  `size_ideal_tail_ota` call (same seed): identical design, metrics,
  verdicts, policy, and oracle cost. See
  `evaluation_results/web_app/parity_smoke_001.json` (PASS, 2026-09-03).

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Status line stuck on loading | First LUT load is large; wait, watch server console. |
| Health `failed` with "files are missing" | LUTs or `models/surrogate/poc/` checkpoint missing. |
| `sizing_failed` after long wait | Optimizer hit an internal error; nothing is returned by design. Retry or report with the server log. |
| Very long request | Hard requests can spend the whole fallback budget (minutes). The button re-enables when done. |
| Two browsers at once | Requests serialize through a single worker; the second waits. |

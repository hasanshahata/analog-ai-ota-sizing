# Design Contract (frozen)

Version 0.1.0 — 2026-09-01. This is the machine-checkable agreement about what
a "passing" design means. The constants live in `analog_ai/config.py`; this
document is their normative description. Changes require bumping
`ORACLE_VERSION`.

## Request schema

A request is a JSON object (see `configs/test_cases/`):

| Field | Unit | Meaning |
|---|---|---|
| `Gain_min` | dB | minimum DC gain |
| `GBW_min` | Hz | minimum gain-bandwidth product |
| `CL_pF` | pF | load capacitance the design must drive |
| `Power_max` | W | maximum supply power |
| `PM_min` *(optional)* | deg | phase margin; default 45° |
| `Sat_margin_min` *(optional)* | V | per-device VDS−VDSAT floor; default 50 mV |
| `SR_min`, `Swing_min`, `ICMR_max` *(optional)* | V/s, V, V | enforced only if present |

**Ambiguity resolved:** SR / swing / ICMR are *not* product requirements of the
current five tests; they remain optional request fields, always reported by the
evaluator, never silently assumed.

## Design vector

Canonical: `x = [L1, gmid1, L3, gmid3, Itail]` within
`L ∈ [60 nm, 1.5 µm]`, `gm/Id ∈ [5, 25]`, `Itail ∈ [10 µA, 500 µA]`.
The 7-parameter variant adds `[L5, gmid5]` for a physical tail device
(`tail_device="finite"`); the shipped trained models (V2–V12) are all 5-parameter
and use an ideal tail.

## Scope decision (2026-09-03): ideal-tail research abstraction

Until finite-M5 support lands in solved mode, every dataset, trained model,
and pass rate in this project describes the **five-parameter ideal-tail
research abstraction**, not the physical 5T-OTA: the tail device contributes
no output resistance, capacitance, area, headroom, saturation, or noise.
This abstraction is a deliberate, documented scoping choice for the ML
proof of concept — **not** a product claim. Scaling the dataset beyond
pilot size, or describing any result as 5T-OTA sizing, requires finite-M5
solved operation first (see CORRECTION_LOG.md still-open list).

## Hard constraints (acceptance)

A design **passes** iff every residual ≤ 0 (residual convention in
`analog_ai/evaluation/constraints.py`):

| Constraint | Default limit | Normalization scale |
|---|---|---|
| Gain ≥ `Gain_min` | per request | 10 dB |
| GBW ≥ `GBW_min` | per request | request value |
| Power ≤ `Power_max` | per request | request value |
| PM ≥ 45° | 45° | 45° |
| min device saturation margin ≥ 50 mV | 50 mV | 50 mV |
| NMOS width ≤ 250 µm | 250 µm | 250 µm |
| PMOS width ≤ 750 µm | 750 µm | 750 µm |
| L within LUT domain | [60 nm, 1.5 µm] | — |

An invalid design (no consistent operating point, out-of-domain parameter,
unverifiable GBW) **fails by definition**.

## Nominal-Cadence deployment guard (provisional v1)

The oracle contract above remains unchanged for dataset/model reproducibility.
The deployment-facing ideal-tail sizing API adds a separate, versioned safety
layer derived from the first 25-case `tt_lib` correlation campaign:

```text
user GBW contract:     GBW >= user_GBW_min
internal LUT contract: GBW >= 1.25 * user_GBW_min
```

`analog_ai.sizing.size_ideal_tail_ota` sends the protected target through the
proposal, local-refinement, and global-fallback stages. It records and checks
both contracts and never mutates the caller's request. Policy
`tt-ideal-tail-gbw-v1` applies only to the nominal 1.2 V, 0.6 V common-mode,
ideal-tail, typical-corner scope. It is provisional until a new disjoint blind
Cadence campaign passes the zero-false-pass gate.

**Deployment update 2026-09-04 (v2 tiered, provisional):** the sizing
service now defaults to the tiered policy `tt-ideal-tail-gbw-v2-tiered`:
`internal GBW = user_GBW_min * 1.18` inside the request domain
(GBW <= 300 MHz) and `* 1.25` beyond it. Rationale: measured in-domain
Spectre/LUT ratios need at most 16.1% uplift (n = 25 across both
campaigns), so the flat 25% over-designed in-domain requests. The 18%
tier is provisional until a third disjoint blind Cadence campaign
(restricted to the app domain, disjoint from both prior campaigns) passes
the zero-false-pass gate. The validated v1 flat 25% remains the fallback
configuration.

## Target sampling ranges (training only)

`Gain 20–45 dB, GBW 50–300 MHz, CL 0.1–5 pF, Power 50–400 µW` — sampled
independently, as in V9–V12. **These ranges carry no feasibility guarantee**;
joint combinations near the corners are likely infeasible. Until Phase 3
delivers a feasibility-labeled dataset, treat any policy trained on these
targets as a compromiser, not a solver. Known mismatch: regression test 1
requests GBW = 20 MHz, below the training range.

## Proxy scope (what this codebase can and cannot claim)

The evaluator (`analog_ai/circuit/`) has two operating-point modes:

- **`imposed`** (legacy semantics, V9–V12 comparability): Vicm = Vocm = VDD/2,
  branch currents = Itail/2, with `pair/mirror_current_mismatch` diagnostics
  quantifying how far the imposed point is from current balance (measured
  −23 % to −46 % on real designs).
- **`solved`** (canonical): the DC operating point is computed from the LUT
  device curves by Newton iteration on the KCL residuals
  (`circuit/dc_solver.py`). The device data itself is Spectre-characterized,
  so this chain is device data + circuit laws end to end — no simulator and
  no imposed bias. KCL residuals at the solution are ≤ 1e-9 A by construction,
  and achieved gm/Id is verified against the target per device.

Common to both modes (documented small-signal modeling choices, not
simulator-substitution gaps):
- ideal tail device by default (finite-M5 variant available in imposed mode);
- source-bulk capacitances neglected; first 0 dB crossing only;
- gm/Id LUT interpolation; matched-pair geometry enforced.

**Honest framing of "LUTs replace Spectre":** device-level physics *is*
Spectre data (the LUTs), and in `solved` mode the circuit bias point is
derived from that data by KCL — there is no remaining simulator to correlate
against for DC. What a one-time transistor-level check would still add is
validation of the *small-signal assembly choices* (neglected capacitances,
GBW/PM extraction) against a full-circuit AC run; the architecture of that
check belongs to gate G1 if a simulator/PDK is ever available.

## Provenance

Every evaluation record carries `oracle_version` and a timestamp. Models are
auditable via their SB3 zip metadata (obs/action dims, timesteps). Historical
evaluation tables (`evaluation_results/*.md`) were produced by *different*
oracle code with different targets per version — they are not comparable to
canonical results and are kept for history only.

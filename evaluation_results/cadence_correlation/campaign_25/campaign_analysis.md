# Ideal-tail 5T-OTA Cadence correlation analysis

Date: 2026-09-03  
Corner: TSMC 65 nm `tt_lib`  
Cases: 25/25 completed successfully

## Executive result

- 19/25 designs (76%) satisfy every initial LUT-to-Spectre correlation
  tolerance.
- 5/25 designs (20%) satisfy all original requested specifications in
  Spectre.
- 20/25 are therefore LUT-verifier passes that fail at least one requested
  constraint in Spectre.
- Every requested-constraint failure is caused by GBW. Gain, phase-margin
  threshold, power, and DC operating-point constraints pass in all 25 cases.

This campaign does **not** validate the current pipeline for unguarded
physical sign-off. It shows that the topology, DC solution, gain, power, and
most AC predictions correlate well, but the optimizer consumes nearly all
of the proxy GBW margin. A modest systematic Spectre shortfall therefore
turns otherwise correlated predictions into specification failures.

## Results by operating regime

| Regime | Correlation pass | All Spectre constraints pass |
|---|---:|---:|
| Low power | 5/5 | 1/5 |
| High gain | 4/5 | 0/5 |
| High GBW | 0/5 | 0/5 |
| Heavy load | 5/5 | 1/5 |
| Near boundary | 5/5 | 3/5 |
| **Total** | **19/25** | **5/25** |

## Aggregate prediction error

Signed error is Spectre minus the solved-LUT prediction.

| Metric | Mean signed error | Mean absolute error | Worst absolute error |
|---|---:|---:|---:|
| DC gain | +0.174 dB | 0.212 dB | 0.287 dB |
| GBW | -6.05% | 6.05% | 16.74% |
| Phase margin | -1.91 deg | 1.91 deg | 6.18 deg |
| Power | -0.00013% | 0.00013% | 0.00052% |
| Vout | -2.14 mV | 2.17 mV | 4.34 mV |
| Tail voltage | -7.26 mV | 7.26 mV | 16.54 mV |
| Mirror voltage | -2.06 mV | 2.14 mV | 4.34 mV |

Six correlation failures exceed the 10% GBW tolerance; two of those also
exceed the 5-degree phase-margin tolerance. All five high-GBW cases exceed
the GBW correlation tolerance, identifying that regime as the primary model
gap.

## Why 20 constraint failures occur despite 19 correlation passes

The solved-LUT verifier often accepts a design with essentially zero GBW
headroom. Across the 25 cases, the median LUT-predicted GBW margin above the
request is only 1.35%; the minimum is effectively zero. The measured Spectre
GBW is systematically lower, so even a correlation error of only 1-6% can
cross the requested boundary. The median Spectre GBW margin is -2.00%.

This distinguishes two separate questions:

1. Correlation: is the LUT prediction close to Spectre? Mostly yes (19/25).
2. Robust sizing: does a LUT-verified design still meet the requested target
   in Spectre? Usually not without a guard band (5/25).

## Evidence integrity

- Spectre and OCEAN completed all 25 jobs.
- Each Spectre log reports zero errors and zero simulator warnings.
- OCEAN emitted only environment/UI warnings about `CDS.log` locking and a
  font setting; these did not affect measurements.
- The guest received no private request or expected-result files.
- Raw result JSON and both logs for every case are archived under `raw/`.
- Per-case comparisons are in `campaign_summary.md`; full machine-readable
  evidence is in `campaign_records.json`.

## Required next engineering action

Do not claim arbitrary physical sizing readiness yet. Add a Spectre-informed
GBW safety margin to the sizing contract, initially treating high-GBW cases
separately. Then regenerate a new blind validation set and require zero false
proxy passes. The present 25 cases must be retained as calibration evidence,
not reused as the final validation set.

## Step 1 calibration decision

The machine-readable calibration analysis in `gbw_calibration_v1.json`
computes the one-sided ratio `Spectre GBW / LUT GBW` for all 25 cases:

- mean ratio: 0.9395;
- minimum ratio: 0.8326;
- largest LUT-target uplift needed to cover an observed case: 20.11%.

Policy `tt-ideal-tail-gbw-v1` freezes a **25% internal GBW guard band**:

```text
internal_GBW_target = user_GBW_min * 1.25
```

Thus, a user request of 100 MHz remains a 100 MHz external contract, but the
sizing optimizer must find a design that the LUT predicts at 125 MHz or
higher. The 25% value is the observed 20.11% requirement rounded upward to
the next five percentage points. It must now be tested on new source rows;
the 25 calibration cases cannot serve as validation evidence.

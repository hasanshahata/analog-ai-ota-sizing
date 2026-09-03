# Guard-band validation analysis

Date: 2026-09-03  
Policy: `tt-ideal-tail-gbw-v1`  
Guard band: 25%  
Validation relationship: zero source-row overlap with calibration campaign

## Decision

The primary safety gate **passes** on this campaign:

- 25/25 Cadence simulations completed;
- 25/25 accepted sizings meet every original user specification in Spectre;
- false proxy passes: **0/25**.

The fixed 25% guard band is therefore effective on this disjoint nominal-TT
sample. It is not a universal guarantee: this remains one technology,
topology, supply, common-mode voltage, process corner, and ideal-tail model.

## Coverage and sizing cost

The guarded pipeline attempted 34 held-out requests to produce 25 validated
designs. Nine requests remained unresolved after the declared fallback budget:

| Regime | Accepted for Spectre | LUT-side rejected attempts |
|---|---:|---:|
| Low power | 5 | 2 |
| High gain | 5 | 3 |
| High GBW | 5 | 0 |
| Heavy load | 5 | 3 |
| Boundary | 5 | 1 |
| **Total** | **25** | **9** |

Acceptance among attempted requests was 25/34 = 73.5%. Rejection is safe but
reduces coverage and can be expensive because each rejected candidate exhausts
global fallback.

## Spectre result

| Regime | All user specs pass | All correlation tolerances pass |
|---|---:|---:|
| Low power | 5/5 | 5/5 |
| High gain | 5/5 | 4/5 |
| High GBW | 5/5 | 0/5 |
| Heavy load | 5/5 | 5/5 |
| Boundary | 5/5 | 1/5 |
| **Total** | **25/25** | **15/25** |

All original constraints pass. The minimum Spectre GBW headroom above the
user request is 4.45%; median headroom is 22.51%.

## Remaining model discrepancy

Signed error is Spectre minus LUT:

- gain mean absolute error: 0.211 dB;
- GBW mean signed error: -7.63%, worst -19.74%;
- phase-margin mean absolute error: 1.83 degrees, worst 6.66 degrees;
- power mean absolute relative error: 0.00013%;
- worst DC-node absolute error: 15.45 mV.

Only 15/25 pass every initial correlation tolerance. Ten exceed the 10% GBW
error tolerance and one also exceeds the 5-degree phase-margin tolerance.
The guard band absorbs this error, but the underlying high-frequency proxy
remains inaccurate.

The minimum new `Spectre GBW / LUT GBW` ratio is 0.8026. A 25% uplift protects
an exact internal-boundary design down to 0.8000, leaving little model-error
reserve. Actual user margin is larger because accepted designs exceeded their
internal target.

## Engineering conclusion

Keep 25% as the conservative nominal-TT deployment policy for now. Do not
reduce it based on this campaign. Investigate richer calibration to reduce
the 26.5% LUT-side rejection rate and unnecessary overdesign in low-error
regions while retaining fail-closed behavior. Any adaptive replacement must
be validated on a third disjoint campaign before replacing v1.

Raw Spectre JSON, Spectre stdout, and OCEAN logs for all cases are archived
under `raw/`. Per-case comparisons are in `campaign_summary.md`; complete
machine-readable joins are in `campaign_records.json`.

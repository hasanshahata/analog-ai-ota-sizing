# Surrogate PoC evaluation (surrogate_poc_repro)

Held-out verified requests: n=1500

| Metric | Value |
|---|---|
| Raw head-0 pass rate | 0.679 |
| Best-of-K pass rate | 0.853 |
| After DE fallback | 0.853 |
| Nearest-neighbor baseline pass | 0.577 |
| Constant-median pass | False |
| Worst normalized violation | 0.780 |
| Avg oracle evals/request | 5.0 |
| DE pass rate (same requests, n=0) | None |

## Five regression cases

| Case | Status |
|---|---|
| test1_low_power | verified_best_of_k |
| test2_high_gain | fallback_verified |
| test3_heavy_load | verified |
| test4_light_load | verified |
| test5_balanced | verified |

## Goal sensitivity (G4)

- req_Gain_min: moves=True, verified along sweep=2/5
- req_GBW_min: moves=True, verified along sweep=1/5
- req_CL_pF: moves=True, verified along sweep=3/5
- req_Power_max: moves=True, verified along sweep=1/5

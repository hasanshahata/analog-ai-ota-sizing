# Risk-head evidence report (Phase E)

Two cohorts, reported separately and never blended:

- **synthetic_ood**: beyond-sample-envelope negatives - these
  test detection of the dataset's negative-generation RULES;
- **certified_boundary**: independently sampled requests with
  optimizer-certified evidence classes.

**`unresolved_after_budget` is not infeasibility**: a failed
optimization run within a declared budget is evidence of
difficulty, never proof that no design exists.

## Cohort: synthetic_ood

n = 2211, failure-evidence = 2211, AUC = None

Reliability (predicted risk vs observed failure-evidence rate):

| bin | n | predicted_mean | observed_fail_rate |
|---|---|---|---|
| [0.0, 0.2] | 0 | None | None |
| [0.2, 0.4] | 1 | 0.25482630729675293 | 1.0 |
| [0.4, 0.6000000000000001] | 0 | None | None |
| [0.6000000000000001, 0.8] | 0 | None | None |
| [0.8, 1.0] | 2210 | 0.9999593275974239 | 1.0 |

Precision / recall / coverage at thresholds:

| threshold | flagged_fraction | precision | recall |
|---|---|---|---|
| 0.3 | 0.9995477159656264 | 1.0 | 0.9995477159656264 |
| 0.5 | 0.9995477159656264 | 1.0 | 0.9995477159656264 |
| 0.7 | 0.9995477159656264 | 1.0 | 0.9995477159656264 |
| 0.9 | 0.9995477159656264 | 1.0 | 0.9995477159656264 |

## Cohort: certified_boundary

n = 103, failure-evidence = 25, AUC = 0.9987179487179487

Reliability (predicted risk vs observed failure-evidence rate):

| bin | n | predicted_mean | observed_fail_rate |
|---|---|---|---|
| [0.0, 0.2] | 82 | 0.0032786988630527404 | 0.04878048780487805 |
| [0.2, 0.4] | 2 | 0.3488466441631317 | 1.0 |
| [0.4, 0.6000000000000001] | 1 | 0.5673654079437256 | 1.0 |
| [0.6000000000000001, 0.8] | 0 | None | None |
| [0.8, 1.0] | 18 | 0.9984228787607043 | 1.0 |

Precision / recall / coverage at thresholds:

| threshold | flagged_fraction | precision | recall |
|---|---|---|---|
| 0.3 | 0.20388349514563106 | 1.0 | 0.84 |
| 0.5 | 0.18446601941747573 | 1.0 | 0.76 |
| 0.7 | 0.17475728155339806 | 1.0 | 0.72 |
| 0.9 | 0.17475728155339806 | 1.0 | 0.72 |

Are flagged requests genuinely harder?

- flagged (p>=0.5): n=19, pipeline pass rate = 0.0
- unflagged: n=84, pipeline pass rate = 0.9285714285714286


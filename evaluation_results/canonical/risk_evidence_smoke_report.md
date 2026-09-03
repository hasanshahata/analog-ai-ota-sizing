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

n = 1, failure-evidence = 1, AUC = None

Reliability (predicted risk vs observed failure-evidence rate):

| bin | n | predicted_mean | observed_fail_rate |
|---|---|---|---|
| [0.0, 0.2] | 0 | None | None |
| [0.2, 0.4] | 0 | None | None |
| [0.4, 0.6000000000000001] | 0 | None | None |
| [0.6000000000000001, 0.8] | 0 | None | None |
| [0.8, 1.0] | 1 | 0.9999997019767761 | 1.0 |

Precision / recall / coverage at thresholds:

| threshold | flagged_fraction | precision | recall |
|---|---|---|---|
| 0.3 | 1.0 | 1.0 | 1.0 |
| 0.5 | 1.0 | 1.0 | 1.0 |
| 0.7 | 1.0 | 1.0 | 1.0 |
| 0.9 | 1.0 | 1.0 | 1.0 |

## Cohort: certified_boundary

n = 1, failure-evidence = 0, AUC = None

Reliability (predicted risk vs observed failure-evidence rate):

| bin | n | predicted_mean | observed_fail_rate |
|---|---|---|---|
| [0.0, 0.2] | 1 | 0.0 | 0.0 |
| [0.2, 0.4] | 0 | None | None |
| [0.4, 0.6000000000000001] | 0 | None | None |
| [0.6000000000000001, 0.8] | 0 | None | None |
| [0.8, 1.0] | 0 | None | None |

Precision / recall / coverage at thresholds:

| threshold | flagged_fraction | precision | recall |
|---|---|---|---|
| 0.3 | 0.0 | 0.0 | 0.0 |
| 0.5 | 0.0 | 0.0 | 0.0 |
| 0.7 | 0.0 | 0.0 | 0.0 |
| 0.9 | 0.0 | 0.0 | 0.0 |

Are flagged requests genuinely harder?

- flagged (p>=0.5): n=0, pipeline pass rate = None
- unflagged: n=1, pipeline pass rate = 1.0


# Evaluation results

- `v2…v12_evaluation_results.md` — **historical** tables from the archived
  trainer-era scripts. They report only Gain/GBW/Power (+ geometry), with no
  PM/saturation/width verdicts, and the underlying targets changed between
  versions — do not compare them across versions.
- `canonical/` — outputs of `scripts/evaluate_tests.py` and
  `scripts/optimize_baseline.py`: full per-constraint residuals, programmatic
  verdicts, JSON records with provenance.

Canonical results are produced by the `analog_ai` proxy, whose physics fixes
(matched pairs, gmbs, domain rejection) make its numbers **not directly
comparable** to the historical tables. See `docs/DESIGN_CONTRACT.md`.

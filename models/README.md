# Models

- `universal_ppo_agent_65nm.zip` — V1, 16-obs/7-action (legacy root system)
- `universal_ppo_agent_65nm_v2…v8.zip` — 5-action, 8-obs delta-action era
- `universal_ppo_agent_65nm_v9…v12.zip` — 15-obs / 5-action absolute-action era
  (V12 is the current best: 1,001,472 steps, SB3 2.9.0, MLP [256, 256],
  lr 1e-4, batch 512 — extracted from the SB3 zip metadata)
- `checkpoints/` — intermediate checkpoints retained for V7 and V9 only;
  V10–V12 checkpoints were not kept when the Kaggle runs finished
- `training_telemetry/` — the two TensorBoard event files that are *not*
  duplicates of the V7–V12 shared file (see `archive/README.md`)

All zips load with `stable_baselines3==2.9.0` (Python 3.11, matching the
Kaggle training environment).

**Known caveats** (details in `docs/PROJECT_REVIEW.md`): no seed is recorded
for any run (the legacy env ignored Gymnasium seeding), models were saved
last-not-best, and no per-version training curves exist for V7–V12.

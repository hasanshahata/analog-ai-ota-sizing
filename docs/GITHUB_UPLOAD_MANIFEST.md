# Private GitHub Upload Manifest

**Prepared:** 2026-09-04

**Intended visibility:** private

**Uploaded repository:** `https://github.com/hasanshahata/analog-ai-ota-sizing`

**Initial uploaded commit:** `976d3dc`

## Included in the repository

- canonical source, scripts, tests, configuration, and documentation;
- trained model/checkpoint files already tracked by Git;
- pilot Parquet dataset and evaluation reports;
- Cadence correlation jobs and archived evidence;
- verbatim `E:\Cadence_AI_Share` snapshot under
  `cadence_shared_snapshot/` (1,523 source files, 38,799,458 bytes,
  byte-for-byte checked);
- local, precompiled web assets and their pinned frontend build files.

## Intentionally excluded generated environments

These are reproducible machine-local artifacts, not project source:

- `.venv/` and `venv/`;
- `node_modules/`;
- Python caches and `.pytest_cache/`;
- transient server/debug logs;
- Git's own `.git/` database.

## LUT upload blocker

The two required LUTs remain local and are represented by the checked hashes
in `configs/lut_manifest.json`:

| File | Bytes | SHA-256 |
|---|---:|---|
| `TSMC_fast_65nm_nch.pkl` | 2,763,639,830 | `20c15dd9215789d94a438ffd14229f8ab09459474bb965371077a5435ed87e01` |
| `TSMC_fast_65nm_pch.pkl` | 2,763,639,830 | `ea80ded3113fb3b701b5bbca9fc4f854c1b1742bb716e668dc95fe92ac169a6c` |

GitHub blocks ordinary Git objects above 100 MiB. Git LFS currently limits an
individual file to 2 GiB on GitHub Free and Pro, while each LUT is about
2.57 GiB. Therefore these files cannot be uploaded unchanged on those plans.
They also contain Spectre-characterized, PDK-derived device data, so cloud
storage must comply with the applicable TSMC/PDK license even in a private
repository.

Do not mark the GitHub backup as containing the LUT bytes until both the
GitHub-plan limit and PDK license are resolved. Possible approved solutions
are licensed private object storage with hash verification, a GitHub Team plan
with Git LFS, or lossless chunking into sub-2-GiB LFS objects plus a verified
reconstruction script.

## Pre-push gates

- no detected credential/private-key patterns in project or shared snapshot;
- no tracked file above 100 MiB (excluding any future Git LFS pointers);
- full non-real-LUT tests: 139 passed;
- real-LUT integration tests: 3 passed;
- focused web suite: 49 passed;
- third Cadence raw archive: 75 files, zero empty, zero report mismatches.

## Upload result

- repository created under the authenticated `hasanshahata` account;
- GitHub reported the repository as private at creation;
- local `main` was pushed successfully and configured to track
  `origin/main`;
- the two ignored LUT binaries were not uploaded, following the selected
  first-choice policy above.

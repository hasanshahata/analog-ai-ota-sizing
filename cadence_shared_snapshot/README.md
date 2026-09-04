# Cadence Shared-Folder Snapshot

This directory is a verbatim repository snapshot of
`E:\Cadence_AI_Share` taken on 2026-09-04 after the three nominal ideal-tail
correlation campaigns.

Snapshot audit at creation:

- source files: 1,523;
- copied source files: 1,523;
- source and copied byte count: 38,799,458;
- per-file SHA-256 mismatches: 0.

Contents:

- `jobs/`: public job inputs plus Cadence/Spectre PSF outputs created by the
  Debian guest;
- `logs/`: Spectre stdout and OCEAN logs;
- `results/`: parsed JSON measurement records;
- `runner/`: the resumable Debian runner.

The snapshot contains absolute include references to the local TSMC 65 nm PDK
installation on the Debian VM. It does **not** contain that PDK or its model
files. Reusing the jobs on another machine requires editing those include
paths and having separately licensed PDK access.

This directory is evidence/history. The maintained job-generation source of
truth remains under `analog_ai/correlation/` and `scripts/`.

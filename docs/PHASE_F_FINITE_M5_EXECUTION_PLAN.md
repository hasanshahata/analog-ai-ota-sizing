# Phase F Execution Plan — Finite-M5 Solved 5T OTA

**Created:** 2026-09-04

**Status:** F0 architecture audit complete; implementation not started
**Prerequisite state:** ideal-tail web pipeline and nominal Cadence guard validated

## Objective

Replace the ideal tail-current source research abstraction with a physical NMOS
M5 in the solved LUT oracle. The resulting seven-parameter design is:

```text
[L1, gm/Id1, L3, gm/Id3, L5, gm/Id5, Itail]
```

The oracle must return W/L for all five transistors and a realizable M5 gate
bias. The existing ideal-tail path remains frozen and reproducible.

## F0 audit result and circuit contract

The repository already contains useful partial support:

- seven-parameter names and bounds in `analog_ai/config.py`;
- finite-M5 evaluation in the legacy/imposed operating-point path;
- M5 small-signal stamping in `analog_ai/circuit/mna.py`;
- M5-aware width, area, saturation, and netlist helpers;
- a test proving imposed finite-tail geometry is produced.

The blocking guard is explicit: `OTA5T(..., tail_device="finite",
op_point="solved")` raises `NotImplementedError`. The solved DC routine accepts
only M1/M3 sizing variables and treats the tail current as ideal.

### Frozen bias decision

M5 is an NMOS current sink with source and bulk at ground, drain at `Vtail`,
and an externally supplied DC gate bias. Because the requested design variable
is `Itail`, the solver will determine and return `Vbias_tail` together with W5.
The bias generator itself remains outside the OTA sizing boundary and its power,
area, mismatch, and noise are not included.

This makes the physical output explicit:

```text
M5: W5, L5
tail bias: Vbias_tail
nominal drain current: Itail
```

The UI must not adopt finite mode until this contract passes LUT and Cadence
validation.

## F1 — extend the solved DC operating point

1. Add a finite-tail solver path receiving L5 and gm/Id5.
2. Include the actual M5 LUT drain current in tail-node KCL:
   `Id1 + Id2 - Id5 = 0`.
3. Size W5 and solve its gate bias self-consistently at the converged Vtail so
   M5 reaches the target current and gm/Id at its own VDS.
4. Preserve mirror and output equations:
   `Id1 - Id3 = 0`, `Id4 - Id2 = 0`.
5. Return W5, Vbias_tail, achieved gm/Id5, M5 operating data, KCL residuals,
   and all LUT-domain clamp diagnostics.
6. Reject nonphysical tail voltage, bias, width, saturation, or convergence.

**Gate:** synthetic-LUT tests prove all three KCL residuals, current
consistency, target-gm/Id reporting, physical voltages, and deterministic
failure behavior.

## F2 — complete circuit metrics and constraints

1. Feed the solved M5 parameters into the existing MNA tail stamp.
2. Include M5 `gds`, `gmbs`, Cgs/Cgd/Cdd and verify its gate is AC-grounded.
3. Include M5 in area, minimum saturation margin, width limits, ICMR, and
   output-swing estimates.
4. Add explicit M5 constraint evidence rather than relying only on aggregate
   minima.
5. Compare finite versus ideal behavior on controlled synthetic examples.

**Gate:** AC-stamp, width-limit, saturation-boundary, area, and regression
tests pass; ideal-tail results remain unchanged.

## F3 — propagate the seven-parameter contract

Update, without silently changing the ideal-tail API:

- evaluator and optimization bounds;
- dataset schemas and sampling;
- local and global search;
- sizing response schema;
- netlist export, including `Vbias_tail`;
- oracle/contract version and provenance;
- CLI tools and test fixtures.

Use an explicit mode field. A five-parameter checkpoint must be rejected for
finite mode rather than padded or reused as if it predicted M5.

**Gate:** round-trip tests show all seven parameters and M5 bias survive
request → optimizer → evaluator → result → netlist.

## F4 — feasibility baseline before learning

1. Run global optimization for the five frozen regression cases using the
   finite-tail solved oracle.
2. Record feasibility, failure categories, evaluation counts, and runtimes.
3. Adjust only physically justified bounds/constraints; version every contract
   change.
4. Do not train a new surrogate until this oracle baseline is stable.

**Gate:** all five cases have verified finite-M5 solutions, or each unresolved
case has a documented physical/contract explanation.

## F5 — Cadence correlation

1. Build a new golden Cadence testbench using an NMOS M5 and the returned
   `Vbias_tail`.
2. Correlate DC nodes, device currents/operating points, gain, GBW, PM, power,
   and saturation margins.
3. Use a disjoint stratified campaign and archive every raw result and log.
4. Derive a separate finite-M5 calibration policy; never inherit the
   ideal-tail GBW guard without evidence.

**Gate:** declared finite-M5 correlation tolerances and zero-false-pass policy
gate pass before dataset generation or web exposure.

## Definition of Phase F complete

- finite-tail solved mode no longer raises `NotImplementedError`;
- every accepted design has M1–M5 finite geometry and `Vbias_tail`;
- KCL and achieved gm/Id evidence include M5;
- M5 affects AC response, area, headroom, and constraints;
- ideal-tail historical tests remain bit-compatible;
- five regression cases have verified finite-tail baseline results;
- finite-tail Cadence correlation is archived and versioned;
- no five-parameter model is represented as a seven-parameter model.

## Immediate next coding task

Implement F1 behind the existing `tail_device="finite"` switch and add
synthetic-LUT DC tests first. Do not change the current web default or v2
ideal-tail calibration policy during F1.

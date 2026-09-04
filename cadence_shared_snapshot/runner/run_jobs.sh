#!/usr/bin/env bash
# Resumable Spectre/OCEAN worker for VMware shared-folder correlation jobs.
# Usage inside Debian: bash /mnt/hgfs/Cadence_AI_Share/runner/run_jobs.sh

set -u

SHARED_ROOT="${1:-/mnt/hgfs/Cadence_AI_Share}"
SPECTRE_BIN="${SPECTRE_BIN:-/usr/local/cadence/MMSIM141/tools/bin/spectre}"
OCEAN_BIN="${OCEAN_BIN:-/usr/local/cadence/IC617/tools/dfII/bin/ocean}"
JOBS_DIR="$SHARED_ROOT/jobs"
RESULTS_DIR="$SHARED_ROOT/results"
LOGS_DIR="$SHARED_ROOT/logs"

mkdir -p "$RESULTS_DIR" "$LOGS_DIR"

if [ ! -x "$SPECTRE_BIN" ]; then
    echo "spectre executable not found: $SPECTRE_BIN" >&2
    exit 2
fi
if [ ! -x "$OCEAN_BIN" ]; then
    echo "ocean executable not found: $OCEAN_BIN" >&2
    exit 2
fi
if [ ! -d "$JOBS_DIR" ]; then
    echo "jobs directory not found: $JOBS_DIR" >&2
    exit 2
fi

found=0
for case_dir in "$JOBS_DIR"/*; do
    [ -d "$case_dir" ] || continue
    case_id="$(basename "$case_dir")"
    found=1
    if [ -f "$RESULTS_DIR/$case_id.json" ] || [ -f "$case_dir/.done" ]; then
        echo "[$case_id] already complete - skipping"
        continue
    fi
    if [ ! -f "$case_dir/input.scs" ] || [ ! -f "$case_dir/measure.ocn" ]; then
        echo "[$case_id] missing input.scs or measure.ocn" >&2
        printf '%s\n' "missing job input" > "$case_dir/.failed"
        continue
    fi

    rm -f "$case_dir/.failed" "$case_dir/measurements.json.tmp"
    printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$case_dir/.running"
    echo "[$case_id] spectre"
    (cd "$case_dir" && "$SPECTRE_BIN" input.scs -raw ./psf +log ./spectre.log) \
        > "$LOGS_DIR/$case_id.spectre.stdout.log" 2>&1
    spectre_rc=$?
    if [ "$spectre_rc" -ne 0 ]; then
        printf '%s\n' "spectre failed with exit $spectre_rc" > "$case_dir/.failed"
        rm -f "$case_dir/.running"
        echo "[$case_id] spectre FAILED ($spectre_rc)" >&2
        continue
    fi

    echo "[$case_id] ocean measurements"
    (cd "$case_dir" && timeout 120 "$OCEAN_BIN" -nograph -restore measure.ocn) \
        > "$LOGS_DIR/$case_id.ocean.log" 2>&1
    ocean_rc=$?
    metrics_line="$(grep '^ANALOG_AI_METRICS ' "$LOGS_DIR/$case_id.ocean.log" | tail -1)"
    if [ "$ocean_rc" -ne 0 ] || [ -z "$metrics_line" ]; then
        printf '%s\n' "ocean failed with exit $ocean_rc" > "$case_dir/.failed"
        rm -f "$case_dir/.running"
        echo "[$case_id] ocean FAILED ($ocean_rc)" >&2
        continue
    fi

    set -- $metrics_line
    # $1 is the marker; the remaining fields follow the fixed schema below.
    printf '{\n  "schema_version": 1,\n  "case_id": "%s",\n  "status": "completed",\n  "dc_gain_dB": %s,\n  "bw_3db_Hz": %s,\n  "gbw_Hz": %s,\n  "phase_at_gbw_deg": %s,\n  "phase_margin_deg": %s,\n  "vout_dc_V": %s,\n  "vtail_dc_V": %s,\n  "vmirror_dc_V": %s,\n  "vdd_current_A": %s,\n  "power_W": %s\n}\n' \
        "$case_id" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" \
        "${10}" "${11}" > "$case_dir/measurements.json.tmp"
    mv "$case_dir/measurements.json.tmp" "$RESULTS_DIR/$case_id.json"
    printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$case_dir/.done"
    rm -f "$case_dir/.running"
    echo "[$case_id] complete"
done

if [ "$found" -eq 0 ]; then
    echo "no jobs found under $JOBS_DIR"
fi

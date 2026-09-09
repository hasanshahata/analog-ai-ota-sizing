#!/usr/bin/env bash
# Dedicated Phase F5 finite-M5 manual-reference worker.

set -u

SHARED_ROOT="${1:-/mnt/hgfs/Cadence_AI_Share/finite_m5}"
SPECTRE_BIN="${SPECTRE_BIN:-/usr/local/cadence/MMSIM141/tools/bin/spectre}"
OCEAN_BIN="${OCEAN_BIN:-/usr/local/cadence/IC617/tools/dfII/bin/ocean}"
RUNNER_DIR="$(cd "$(dirname "$0")" && pwd)"
JOBS_DIR="$SHARED_ROOT/jobs"
RESULTS_DIR="$SHARED_ROOT/results"
LOGS_DIR="$SHARED_ROOT/logs"

mkdir -p "$RESULTS_DIR" "$LOGS_DIR"
for executable in "$SPECTRE_BIN" "$OCEAN_BIN"; do
    [ -x "$executable" ] || { echo "executable not found: $executable" >&2; exit 2; }
done
[ -d "$JOBS_DIR" ] || { echo "jobs directory not found: $JOBS_DIR" >&2; exit 2; }
[ -f "$RUNNER_DIR/write_finite_result.py" ] || {
    echo "result writer not found beside runner" >&2; exit 2;
}

found=0
for case_dir in "$JOBS_DIR"/*; do
    [ -d "$case_dir" ] || continue
    case_id="$(basename "$case_dir")"
    found=1
    if [ -f "$RESULTS_DIR/$case_id.json" ] || [ -f "$case_dir/.done" ]; then
        echo "[$case_id] already complete - skipping"
        continue
    fi
    required="input.scs measure.ocn capacitance_probe.scs measure_caps.ocn job.json tolerances.json"
    missing=0
    for name in $required; do
        [ -f "$case_dir/$name" ] || { echo "[$case_id] missing $name" >&2; missing=1; }
    done
    if [ "$missing" -ne 0 ]; then
        printf '%s\n' "missing finite job input" > "$case_dir/.failed"
        continue
    fi

    rm -f "$case_dir/.failed" "$case_dir/.running"
    printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$case_dir/.running"
    echo "[$case_id] verify source bindings and resolve/hash PDK"
    python3 "$RUNNER_DIR/write_finite_result.py" --case-dir "$case_dir" \
        --ota-log "$LOGS_DIR/$case_id.ocean.log" \
        --cap-log "$LOGS_DIR/$case_id.caps.ocean.log" \
        --out "$RESULTS_DIR/$case_id.json" --verify-only \
        > "$LOGS_DIR/$case_id.pdk.sha256.log" 2>&1
    verify_rc=$?
    if [ "$verify_rc" -ne 0 ]; then
        printf '%s\n' "source/PDK verification failed with exit $verify_rc" > "$case_dir/.failed"
        rm -f "$case_dir/.running"
        continue
    fi
    echo "[$case_id] finite OTA Spectre"
    (cd "$case_dir" && "$SPECTRE_BIN" input.scs -raw ./psf +log ./spectre.log) \
        > "$LOGS_DIR/$case_id.spectre.stdout.log" 2>&1
    ota_rc=$?
    if [ "$ota_rc" -eq 0 ]; then
        (cd "$case_dir" && timeout 180 "$OCEAN_BIN" -nograph -restore measure.ocn) \
            > "$LOGS_DIR/$case_id.ocean.log" 2>&1
        ota_rc=$?
    fi
    if [ "$ota_rc" -ne 0 ]; then
        printf '%s\n' "finite OTA measurement failed with exit $ota_rc" > "$case_dir/.failed"
        rm -f "$case_dir/.running"
        continue
    fi

    echo "[$case_id] M5 capacitance provenance probe"
    (cd "$case_dir" && "$SPECTRE_BIN" capacitance_probe.scs -raw ./psf_caps \
        +log ./spectre_caps.log) > "$LOGS_DIR/$case_id.caps.spectre.stdout.log" 2>&1
    cap_rc=$?
    if [ "$cap_rc" -eq 0 ]; then
        (cd "$case_dir" && timeout 180 "$OCEAN_BIN" -nograph -restore measure_caps.ocn) \
            > "$LOGS_DIR/$case_id.caps.ocean.log" 2>&1
        cap_rc=$?
    fi
    if [ "$cap_rc" -ne 0 ]; then
        printf '%s\n' "capacitance probe failed with exit $cap_rc" > "$case_dir/.failed"
        rm -f "$case_dir/.running"
        continue
    fi

    python3 "$RUNNER_DIR/write_finite_result.py" \
        --case-dir "$case_dir" \
        --ota-log "$LOGS_DIR/$case_id.ocean.log" \
        --cap-log "$LOGS_DIR/$case_id.caps.ocean.log" \
        --out "$RESULTS_DIR/$case_id.json"
    result_rc=$?
    if [ "$result_rc" -ne 0 ]; then
        printf '%s\n' "result validation failed with exit $result_rc" > "$case_dir/.failed"
        rm -f "$case_dir/.running"
        continue
    fi
    printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$case_dir/.done"
    rm -f "$case_dir/.running"
    echo "[$case_id] complete"
done

[ "$found" -ne 0 ] || echo "no finite jobs found under $JOBS_DIR"

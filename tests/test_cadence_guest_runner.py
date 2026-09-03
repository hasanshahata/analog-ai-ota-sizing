from pathlib import Path


def test_guest_runner_is_resumable_and_atomic():
    text = Path("scripts/cadence_guest/run_jobs.sh").read_text()
    assert "already complete - skipping" in text
    assert "measurements.json.tmp" in text
    assert "ANALOG_AI_METRICS" in text
    assert "dc_gain_dB" in text and "phase_margin_deg" in text
    assert 'mv "$case_dir/measurements.json.tmp"' in text
    assert ".running" in text and ".done" in text and ".failed" in text
    assert "/usr/local/cadence/MMSIM141/tools/bin/spectre" in text
    assert "/usr/local/cadence/IC617/tools/dfII/bin/ocean" in text
    assert "/mnt/hgfs/Cadence_AI_Share" in text
    assert 'timeout 120 "$OCEAN_BIN"' in text


def test_guest_runner_does_not_read_private_expected_results():
    text = Path("scripts/cadence_guest/run_jobs.sh").read_text()
    assert "expected_private" not in text
    assert "request_private" not in text

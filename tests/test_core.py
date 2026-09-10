import json
import subprocess
from pathlib import Path

import pytest

from usbsmart_doctor.core import (
    CANDIDATE_TYPES,
    ProbeResult,
    _json_has_smart_data,
    load_cache,
    probe_device_type,
    save_cache,
    summarize,
)


def fake_runner_factory(good_type: str, sat_json: dict):
    """Return a runner function that only 'succeeds' for good_type."""

    def runner(smartctl_bin, args, timeout=20):
        # args like: ["-a", "-j", "-d", TYPE, DEVICE] or ["-a", "-j", DEVICE] for auto
        if "-d" in args:
            dtype = args[args.index("-d") + 1]
        else:
            dtype = "auto"
        if dtype == good_type:
            stdout = json.dumps(sat_json)
        else:
            stdout = json.dumps(
                {
                    "smartctl": {
                        "messages": [{"string": "Unable to detect device type"}]
                    }
                }
            )
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")

    return runner


SAMPLE_SAT_JSON = {
    "smart_status": {"passed": True},
    "model_name": "WD My Passport 2TB",
    "serial_number": "ABC123",
    "device": {"protocol": "ATA"},
    "smart_support": {"available": True, "enabled": True},
    "temperature": {"current": 34},
    "power_on_time": {"hours": 1200},
    "power_cycle_count": 88,
    "ata_smart_attributes": {
        "table": [
            {"id": 5, "raw": {"value": 0}},
            {"id": 197, "raw": {"value": 0}},
        ]
    },
}


def test_json_has_smart_data_true_for_smart_status():
    assert _json_has_smart_data({"smart_status": {"passed": True}})


def test_json_has_smart_data_false_for_empty():
    assert not _json_has_smart_data({})
    assert not _json_has_smart_data(
        {"smartctl": {"messages": [{"string": "Unable to detect device type"}]}}
    )


def test_probe_device_type_finds_correct_type_after_trying_others(tmp_path, monkeypatch):
    monkeypatch.setattr("usbsmart_doctor.core.get_usb_identity", lambda device: None)
    runner = fake_runner_factory("usbjmicron", SAMPLE_SAT_JSON)
    result = probe_device_type(
        "/dev/sdz",
        smartctl_bin="smartctl",
        candidates=["auto", "sat", "usbjmicron", "usbprolific"],
        cache_path=tmp_path / "cache.json",
        use_cache=False,
        runner=runner,
    )
    assert result.ok
    assert result.device_type == "usbjmicron"
    assert result.tried == ["auto", "sat", "usbjmicron"]


def test_probe_device_type_returns_error_when_nothing_works(tmp_path):
    def always_fails(smartctl_bin, args, timeout=20):
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="{}", stderr="err")

    result = probe_device_type(
        "/dev/sdz",
        smartctl_bin="smartctl",
        candidates=["auto", "sat"],
        cache_path=tmp_path / "cache.json",
        use_cache=False,
        runner=always_fails,
    )
    assert not result.ok
    assert result.error is not None
    assert result.tried == ["auto", "sat"]


def test_probe_device_type_uses_cache_first(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.json"
    save_cache({"1234:5678:SERIAL": "usbprolific"}, cache_path)
    monkeypatch.setattr(
        "usbsmart_doctor.core.get_usb_identity", lambda device: "1234:5678:SERIAL"
    )
    runner = fake_runner_factory("usbprolific", SAMPLE_SAT_JSON)
    result = probe_device_type(
        "/dev/sdz",
        smartctl_bin="smartctl",
        candidates=["auto", "sat", "usbjmicron", "usbprolific"],
        cache_path=cache_path,
        use_cache=True,
        runner=runner,
    )
    assert result.ok
    # cached type tried first -> only one attempt needed
    assert result.tried == ["usbprolific"]


def test_cache_round_trip(tmp_path):
    cache_path = tmp_path / "sub" / "cache.json"
    assert load_cache(cache_path) == {}
    save_cache({"a": "b"}, cache_path)
    assert load_cache(cache_path) == {"a": "b"}


def test_summarize_flags_reallocated_sectors():
    data = dict(SAMPLE_SAT_JSON)
    data["ata_smart_attributes"] = {
        "table": [
            {"id": 5, "raw": {"value": 3}},
            {"id": 197, "raw": {"value": 0}},
        ]
    }
    probe = ProbeResult(device_type="usbjmicron", tried=["auto", "usbjmicron"], raw_json=data)
    summary = summarize("/dev/sdz", probe)
    assert summary.reallocated_sectors == 3
    assert any("reallocated" in w for w in summary.warnings)


def test_summarize_clean_drive_has_no_warnings():
    probe = ProbeResult(device_type="sat", tried=["auto", "sat"], raw_json=SAMPLE_SAT_JSON)
    summary = summarize("/dev/sdz", probe)
    assert summary.warnings == []
    assert summary.overall_health_passed is True


def test_summarize_requires_successful_probe():
    probe = ProbeResult(device_type=None, tried=["auto"], error="nope")
    with pytest.raises(ValueError):
        summarize("/dev/sdz", probe)


def test_candidate_types_starts_with_auto():
    assert CANDIDATE_TYPES[0] == "auto"

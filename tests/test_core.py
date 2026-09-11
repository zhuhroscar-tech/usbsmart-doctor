import json
import subprocess
from pathlib import Path

import pytest

from usbsmart_doctor.core import (
    CANDIDATE_TYPES,
    ProbeResult,
    _decode_nvme_critical_warning,
    _is_permission_denied,
    _json_has_smart_data,
    get_usb_identity,
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


def test_decode_nvme_critical_warning_single_bit():
    warnings = _decode_nvme_critical_warning(0b001)
    assert len(warnings) == 1
    assert "available spare capacity" in warnings[0]


def test_decode_nvme_critical_warning_multiple_bits():
    # bit 0 (spare capacity) + bit 2 (reliability degraded)
    warnings = _decode_nvme_critical_warning(0b101)
    assert len(warnings) == 2
    assert any("available spare capacity" in w for w in warnings)
    assert any("reliability is degraded" in w for w in warnings)


def test_decode_nvme_critical_warning_zero_is_empty():
    assert _decode_nvme_critical_warning(0) == []


def test_decode_nvme_critical_warning_unrecognized_bit_still_surfaced():
    # bit 6 is outside the documented 0-5 range but still nonzero
    warnings = _decode_nvme_critical_warning(1 << 6)
    assert len(warnings) == 1
    assert "unrecognized bit" in warnings[0]


def test_summarize_flags_nvme_critical_warning():
    data = dict(SAMPLE_SAT_JSON)
    data["nvme_smart_health_information_log"] = {
        "percentage_used": 10,
        "media_errors": 0,
        "critical_warning": 0b001,
    }
    probe = ProbeResult(device_type="auto", tried=["auto"], raw_json=data)
    summary = summarize("/dev/nvme0", probe)
    assert any("available spare capacity" in w for w in summary.warnings)


def test_summarize_no_critical_warning_key_is_silent():
    # Older smartctl/older drives may omit critical_warning entirely --
    # must not raise or fabricate a warning for a key that isn't there.
    probe = ProbeResult(device_type="sat", tried=["auto", "sat"], raw_json=SAMPLE_SAT_JSON)
    summary = summarize("/dev/sdz", probe)
    assert summary.warnings == []


def test_summarize_flags_pending_sectors():
    data = dict(SAMPLE_SAT_JSON)
    data["ata_smart_attributes"] = {
        "table": [
            {"id": 5, "raw": {"value": 0}},
            {"id": 197, "raw": {"value": 2}},
        ]
    }
    probe = ProbeResult(device_type="sat", tried=["auto", "sat"], raw_json=data)
    summary = summarize("/dev/sdz", probe)
    assert summary.pending_sectors == 2
    assert any("pending sector" in w for w in summary.warnings)


def test_summarize_flags_nvme_wear_at_or_above_90_percent():
    data = dict(SAMPLE_SAT_JSON)
    data["nvme_smart_health_information_log"] = {
        "percentage_used": 90,
        "media_errors": 0,
        "critical_warning": 0,
    }
    probe = ProbeResult(device_type="auto", tried=["auto"], raw_json=data)
    summary = summarize("/dev/nvme0", probe)
    assert summary.percentage_used == 90
    assert any("wear at 90%" in w for w in summary.warnings)


def test_summarize_silent_on_nvme_wear_below_90_percent():
    data = dict(SAMPLE_SAT_JSON)
    data["nvme_smart_health_information_log"] = {
        "percentage_used": 89,
        "media_errors": 0,
        "critical_warning": 0,
    }
    probe = ProbeResult(device_type="auto", tried=["auto"], raw_json=data)
    summary = summarize("/dev/nvme0", probe)
    assert summary.warnings == []


def test_summarize_flags_nvme_media_errors():
    data = dict(SAMPLE_SAT_JSON)
    data["nvme_smart_health_information_log"] = {
        "percentage_used": 5,
        "media_errors": 4,
        "critical_warning": 0,
    }
    probe = ProbeResult(device_type="auto", tried=["auto"], raw_json=data)
    summary = summarize("/dev/nvme0", probe)
    assert summary.media_errors == 4
    assert any("media error" in w for w in summary.warnings)


def test_summarize_flags_failed_overall_smart_status():
    data = dict(SAMPLE_SAT_JSON)
    data["smart_status"] = {"passed": False}
    probe = ProbeResult(device_type="sat", tried=["auto", "sat"], raw_json=data)
    summary = summarize("/dev/sdz", probe)
    assert summary.overall_health_passed is False
    assert any("FAILED" in w for w in summary.warnings)


# --- get_usb_identity ---------------------------------------------------


def test_get_usb_identity_none_when_udevadm_missing(monkeypatch):
    import usbsmart_doctor.core as core_mod

    monkeypatch.setattr(core_mod.shutil, "which", lambda name: None)
    assert get_usb_identity("/dev/sdz") is None


def test_get_usb_identity_parses_vendor_product_serial(monkeypatch):
    import usbsmart_doctor.core as core_mod

    monkeypatch.setattr(core_mod.shutil, "which", lambda name: "/usr/bin/udevadm")
    sample = (
        "ID_VENDOR_ID=0951\n"
        "ID_MODEL_ID=1666\n"
        "ID_SERIAL_SHORT=AB12CD34\n"
    )

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=sample, stderr="")

    monkeypatch.setattr(core_mod.subprocess, "run", fake_run)
    assert get_usb_identity("/dev/sdz") == "0951:1666:AB12CD34"


def test_get_usb_identity_falls_back_to_id_serial(monkeypatch):
    import usbsmart_doctor.core as core_mod

    monkeypatch.setattr(core_mod.shutil, "which", lambda name: "/usr/bin/udevadm")
    sample = "ID_VENDOR_ID=0951\nID_MODEL_ID=1666\nID_SERIAL=full-serial-string\n"

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=sample, stderr="")

    monkeypatch.setattr(core_mod.subprocess, "run", fake_run)
    assert get_usb_identity("/dev/sdz") == "0951:1666:full-serial-string"


def test_get_usb_identity_none_when_vendor_or_product_missing(monkeypatch):
    import usbsmart_doctor.core as core_mod

    monkeypatch.setattr(core_mod.shutil, "which", lambda name: "/usr/bin/udevadm")
    sample = "ID_SERIAL_SHORT=AB12CD34\n"  # no vendor/product ids at all

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=sample, stderr="")

    monkeypatch.setattr(core_mod.subprocess, "run", fake_run)
    assert get_usb_identity("/dev/sdz") is None


def test_get_usb_identity_none_on_nonzero_returncode(monkeypatch):
    import usbsmart_doctor.core as core_mod

    monkeypatch.setattr(core_mod.shutil, "which", lambda name: "/usr/bin/udevadm")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not found")

    monkeypatch.setattr(core_mod.subprocess, "run", fake_run)
    assert get_usb_identity("/dev/sdz") is None


def test_get_usb_identity_none_on_oserror(monkeypatch):
    import usbsmart_doctor.core as core_mod

    monkeypatch.setattr(core_mod.shutil, "which", lambda name: "/usr/bin/udevadm")

    def raising_run(cmd, **kwargs):
        raise OSError("udevadm vanished")

    monkeypatch.setattr(core_mod.subprocess, "run", raising_run)
    assert get_usb_identity("/dev/sdz") is None


def test_get_usb_identity_none_on_subprocess_error(monkeypatch):
    import usbsmart_doctor.core as core_mod

    monkeypatch.setattr(core_mod.shutil, "which", lambda name: "/usr/bin/udevadm")

    def raising_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 10)

    monkeypatch.setattr(core_mod.subprocess, "run", raising_run)
    assert get_usb_identity("/dev/sdz") is None


def test_get_usb_identity_empty_serial_defaults_to_empty_string(monkeypatch):
    import usbsmart_doctor.core as core_mod

    monkeypatch.setattr(core_mod.shutil, "which", lambda name: "/usr/bin/udevadm")
    sample = "ID_VENDOR_ID=0951\nID_MODEL_ID=1666\n"  # no serial at all

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=sample, stderr="")

    monkeypatch.setattr(core_mod.subprocess, "run", fake_run)
    assert get_usb_identity("/dev/sdz") == "0951:1666:"


def test_is_permission_denied_true_on_smartctl_permission_message():
    data = {
        "smartctl": {
            "messages": [{"string": "Smartctl open device: /dev/sdz failed: Permission denied"}]
        }
    }
    assert _is_permission_denied(data) is True


def test_is_permission_denied_false_on_unrelated_message():
    data = {"smartctl": {"messages": [{"string": "Unable to detect device type"}]}}
    assert _is_permission_denied(data) is False


def test_is_permission_denied_false_on_non_dict():
    assert _is_permission_denied(None) is False
    assert _is_permission_denied([]) is False


def test_probe_device_type_reports_permission_denied_not_bridge_mismatch(tmp_path):
    """Regression test: before this fix, a device we simply can't read
    (permission denied) was misreported as 'no smartctl device type
    produced SMART data' -- the generic bridge-chip-incompatibility
    message -- sending users down the wrong troubleshooting path instead
    of telling them to fix permissions. This would have failed before the
    _is_permission_denied() short-circuit was added to probe_device_type.
    """

    def runner(smartctl_bin, args, timeout=20):
        stdout = json.dumps(
            {
                "smartctl": {
                    "messages": [
                        {"string": "Smartctl open device: /dev/sdz failed: Permission denied"}
                    ]
                }
            }
        )
        return subprocess.CompletedProcess(args=[], returncode=1, stdout=stdout, stderr="")

    result = probe_device_type(
        "/dev/sdz",
        smartctl_bin="smartctl",
        cache_path=tmp_path / "cache.json",
        use_cache=False,
        runner=runner,
    )
    assert result.device_type is None
    assert "permission denied" in result.error.lower()
    assert "no smartctl device type produced smart data" not in result.error.lower()
    # Only the first candidate should be tried -- permission denied is a
    # terminal condition, not something a different -d TYPE can fix.
    assert len(result.tried) == 1

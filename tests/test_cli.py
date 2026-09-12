import json
import subprocess
import sys

from usbsmart_doctor.cli import main
from usbsmart_doctor.core import SmartctlNotFound


def test_cli_missing_smartctl(monkeypatch, capsys):
    def raise_not_found():
        raise SmartctlNotFound("smartctl not found on PATH. Install smartmontools.")

    monkeypatch.setattr("usbsmart_doctor.cli.find_smartctl", raise_not_found)
    rc = main(["/dev/sdz"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "smartmontools" in captured.err


def test_cli_success_json(monkeypatch, capsys):
    monkeypatch.setattr("usbsmart_doctor.cli.find_smartctl", lambda: "smartctl")

    sample = {
        "smart_status": {"passed": True},
        "model_name": "Test Drive",
        "serial_number": "SN1",
        "device": {"protocol": "ATA"},
        "smart_support": {"available": True, "enabled": True},
        "ata_smart_attributes": {"table": []},
    }

    from usbsmart_doctor.core import ProbeResult

    monkeypatch.setattr(
        "usbsmart_doctor.cli.probe_device_type",
        lambda *a, **k: ProbeResult(device_type="sat", tried=["auto", "sat"], raw_json=sample),
    )

    rc = main(["/dev/sdz", "--json", "--no-cache"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["device_type"] == "sat"
    assert out["summary"]["model"] == "Test Drive"


def test_cli_probe_failure_returns_1(monkeypatch, capsys):
    monkeypatch.setattr("usbsmart_doctor.cli.find_smartctl", lambda: "smartctl")

    from usbsmart_doctor.core import ProbeResult

    monkeypatch.setattr(
        "usbsmart_doctor.cli.probe_device_type",
        lambda *a, **k: ProbeResult(device_type=None, tried=["auto", "sat"], error="nope"),
    )

    rc = main(["/dev/sdz"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "nope" in captured.err


def test_cli_human_readable_output_shows_health_and_fields(monkeypatch, capsys):
    monkeypatch.setattr("usbsmart_doctor.cli.find_smartctl", lambda: "smartctl")

    sample = {
        "smart_status": {"passed": True},
        "model_name": "Test Drive",
        "serial_number": "SN1",
        "device": {"protocol": "ATA"},
        "smart_support": {"available": True, "enabled": True},
        "ata_smart_attributes": {"table": []},
    }

    from usbsmart_doctor.core import ProbeResult

    monkeypatch.setattr(
        "usbsmart_doctor.cli.probe_device_type",
        lambda *a, **k: ProbeResult(device_type="sat", tried=["auto", "sat"], raw_json=sample),
    )

    rc = main(["/dev/sdz", "--no-cache", "--no-color"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "PASSED" in out
    assert "Test Drive" in out
    assert "SN1" in out
    assert "No warnings" in out


def test_cli_probe_failure_json_includes_tried(monkeypatch, capsys):
    monkeypatch.setattr("usbsmart_doctor.cli.find_smartctl", lambda: "smartctl")

    from usbsmart_doctor.core import ProbeResult

    monkeypatch.setattr(
        "usbsmart_doctor.cli.probe_device_type",
        lambda *a, **k: ProbeResult(device_type=None, tried=["auto", "sat"], error="nope"),
    )

    rc = main(["/dev/sdz", "--json"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["error"] == "nope"
    assert out["tried"] == ["auto", "sat"]


def test_cli_health_failed_returns_3(monkeypatch, capsys):
    monkeypatch.setattr("usbsmart_doctor.cli.find_smartctl", lambda: "smartctl")

    sample = {
        "smart_status": {"passed": False},
        "model_name": "Dying Drive",
        "serial_number": "SN2",
        "device": {"protocol": "ATA"},
        "smart_support": {"available": True, "enabled": True},
        "ata_smart_attributes": {"table": []},
    }

    from usbsmart_doctor.core import ProbeResult

    monkeypatch.setattr(
        "usbsmart_doctor.cli.probe_device_type",
        lambda *a, **k: ProbeResult(device_type="sat", tried=["auto", "sat"], raw_json=sample),
    )

    rc = main(["/dev/sdz", "--no-cache", "--no-color"])
    assert rc == 3
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "back up this drive now" in out


def test_cli_warnings_present_returns_4(monkeypatch, capsys):
    monkeypatch.setattr("usbsmart_doctor.cli.find_smartctl", lambda: "smartctl")

    sample = {
        "smart_status": {"passed": True},
        "model_name": "Flaky Drive",
        "serial_number": "SN3",
        "device": {"protocol": "NVMe"},
        "smart_support": {"available": True, "enabled": True},
        "nvme_smart_health_information_log": {
            "percentage_used": 85,
            "media_errors": 2,
            "critical_warning": 1,
        },
    }

    from usbsmart_doctor.core import ProbeResult, HealthSummary

    monkeypatch.setattr(
        "usbsmart_doctor.cli.probe_device_type",
        lambda *a, **k: ProbeResult(device_type="nvme", tried=["auto", "nvme"], raw_json=sample),
    )

    def fake_summarize(device, probe):
        return HealthSummary(
            device=device,
            device_type="nvme",
            model="Flaky Drive",
            serial="SN3",
            protocol="NVMe",
            smart_supported=True,
            smart_enabled=True,
            overall_health_passed=True,
            temperature_celsius=None,
            power_on_hours=None,
            power_cycle_count=None,
            reallocated_sectors=None,
            pending_sectors=None,
            percentage_used=85,
            media_errors=2,
            critical_warning=1,
            warnings=["NVMe wear used is at 85%, consider replacement planning."],
        )

    monkeypatch.setattr("usbsmart_doctor.cli.summarize", fake_summarize)

    rc = main(["/dev/sdz", "--no-cache", "--no-color"])
    assert rc == 4
    out = capsys.readouterr().out
    assert "NVMe wear used" in out
    assert "85%" in out
    assert "NVMe critical_warning" in out
    assert "0x1" in out
    assert "consider replacement planning" in out


def test_cli_summarize_valueerror_falls_back_to_none(monkeypatch, capsys):
    monkeypatch.setattr("usbsmart_doctor.cli.find_smartctl", lambda: "smartctl")

    from usbsmart_doctor.core import ProbeResult

    monkeypatch.setattr(
        "usbsmart_doctor.cli.probe_device_type",
        lambda *a, **k: ProbeResult(device_type="sat", tried=["auto", "sat"], raw_json={}),
    )

    def raise_value_error(device, probe):
        raise ValueError("malformed smartctl output")

    monkeypatch.setattr("usbsmart_doctor.cli.summarize", raise_value_error)

    rc = main(["/dev/sdz", "--no-cache", "--no-color"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Types tried" in out


def test_cli_unknown_health_and_ata_fields_all_render(monkeypatch, capsys):
    monkeypatch.setattr("usbsmart_doctor.cli.find_smartctl", lambda: "smartctl")

    from usbsmart_doctor.core import ProbeResult, HealthSummary

    monkeypatch.setattr(
        "usbsmart_doctor.cli.probe_device_type",
        lambda *a, **k: ProbeResult(device_type="sat", tried=["auto", "sat"], raw_json={}),
    )

    def fake_summarize(device, probe):
        return HealthSummary(
            device=device,
            device_type="sat",
            model=None,
            serial=None,
            protocol="ATA",
            smart_supported=True,
            smart_enabled=True,
            overall_health_passed=None,
            temperature_celsius=42,
            power_on_hours=1000,
            power_cycle_count=50,
            reallocated_sectors=0,
            pending_sectors=0,
            percentage_used=None,
            media_errors=None,
            critical_warning=None,
            warnings=[],
        )

    monkeypatch.setattr("usbsmart_doctor.cli.summarize", fake_summarize)

    rc = main(["/dev/sdz", "--no-cache", "--no-color"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Overall health: unknown" in out
    assert "42\u00b0C" in out
    assert "1000 hours" in out
    assert "Power cycles" in out
    assert "Reallocated sectors" in out
    assert "Pending sectors" in out
    assert "No warnings detected" in out

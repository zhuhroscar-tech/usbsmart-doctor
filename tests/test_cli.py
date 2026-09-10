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

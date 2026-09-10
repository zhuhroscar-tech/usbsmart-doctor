"""usbsmart-doctor CLI: find the right smartctl device type and show health."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import __version__
from .core import (
    HealthSummary,
    ProbeResult,
    SmartctlNotFound,
    find_smartctl,
    probe_device_type,
    summarize,
)
from .style import bool_badge, print_fields, resolve_style, status_headline


def _print_human(device: str, probe: ProbeResult, summary: HealthSummary | None, style) -> None:
    print(f"Device:        {style.bold(device)}")
    print(f"Working -d:    smartctl -d {probe.device_type} -a {device}")
    print(f"Types tried:   {style.dim(', '.join(probe.tried))}")
    if summary is None:
        return

    status = summary.overall_health_passed
    print()
    if status is True:
        print(status_headline(style, "ok", "Overall health: PASSED"))
    elif status is False:
        print(status_headline(style, "fail", "Overall health: FAILED -- back up this drive now"))
    else:
        print(status_headline(style, "info", "Overall health: unknown"))

    rows = [
        ("Model", summary.model or style.dim("unknown")),
        ("Serial", summary.serial or style.dim("unknown")),
        ("Protocol", summary.protocol or style.dim("unknown")),
        ("SMART supported", bool_badge(style, summary.smart_supported)),
        ("SMART enabled", bool_badge(style, summary.smart_enabled)),
    ]
    if summary.temperature_celsius is not None:
        rows.append(("Temperature", f"{summary.temperature_celsius}\u00b0C"))
    if summary.power_on_hours is not None:
        rows.append(("Power-on time", f"{summary.power_on_hours} hours"))
    if summary.power_cycle_count is not None:
        rows.append(("Power cycles", str(summary.power_cycle_count)))
    if summary.reallocated_sectors is not None:
        rows.append(("Reallocated sectors", str(summary.reallocated_sectors)))
    if summary.pending_sectors is not None:
        rows.append(("Pending sectors", str(summary.pending_sectors)))
    if summary.percentage_used is not None:
        rows.append(("NVMe wear used", f"{summary.percentage_used}%"))
    if summary.media_errors is not None:
        rows.append(("NVMe media errors", str(summary.media_errors)))
    if summary.critical_warning is not None and summary.critical_warning != 0:
        rows.append(("NVMe critical_warning", style.bold_red(f"0x{summary.critical_warning:x}")))
    print()
    print_fields(rows)

    print()
    if summary.warnings:
        for w in summary.warnings:
            print(status_headline(style, "warn", w))
    else:
        print(status_headline(style, "ok", "No warnings detected in the metrics this tool checks."))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="usbsmart-doctor",
        description=(
            "Find the smartctl device type your USB drive's bridge chip needs, "
            "then print a clean SMART health summary. Read-only: never writes "
            "to the drive or runs self-tests."
        ),
    )
    p.add_argument("device", help="Block device to probe, e.g. /dev/sdb")
    p.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON instead of text"
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Don't read/write the learned-device-type cache (~/.cache/usbsmart-doctor/)",
    )
    p.add_argument(
        "--type",
        dest="force_type",
        default=None,
        help="Skip probing and use this smartctl -d TYPE directly",
    )
    p.add_argument("--no-color", action="store_true", help="Disable colored output.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        smartctl_bin = find_smartctl()
    except SmartctlNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    candidates = [args.force_type] if args.force_type else None
    probe = probe_device_type(
        args.device,
        smartctl_bin=smartctl_bin,
        candidates=candidates,
        use_cache=not args.no_cache,
    )

    if not probe.ok:
        if args.json:
            print(json.dumps({"device": args.device, "ok": False, "error": probe.error, "tried": probe.tried}))
        else:
            print(f"error: {probe.error}", file=sys.stderr)
            print(f"Types tried: {', '.join(probe.tried)}", file=sys.stderr)
        return 1

    try:
        summary = summarize(args.device, probe)
    except ValueError:
        summary = None

    if args.json:
        out = {"device": args.device, "ok": True, "device_type": probe.device_type, "tried": probe.tried}
        if summary is not None:
            out["summary"] = asdict(summary)
        print(json.dumps(out, indent=2))
    else:
        style = resolve_style(no_color_flag=args.no_color)
        _print_human(args.device, probe, summary, style)

    if summary is not None and summary.overall_health_passed is False:
        return 3
    if summary is not None and summary.warnings:
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())

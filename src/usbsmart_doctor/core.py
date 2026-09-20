"""Core probing/parsing logic for usbsmart-doctor.

Many external/USB hard drives and SSDs report *no* SMART data under Linux
with plain `smartctl -a /dev/sdX` because the USB-to-SATA/USB-to-NVMe bridge
chip needs an explicit `-d TYPE` hint (usbjmicron, usbprolific, sat, sntjmicron,
...) that smartctl's autodetection cannot always guess correctly. Users are
left manually iterating documented bridge types from forum threads and the
smartctl man page. usbsmart-doctor automates that iteration, caches the type
that worked for a given drive (by USB vendor:product + serial when available),
and prints a clean, human-readable health report instead of raw smartctl
output.

This module never *writes* to a device and never selects a test that could
alter drive state; it only issues read-only smartctl probes (`-i`, `-a`, `-H`).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Ordered from "works for the overwhelming majority of modern USB-SATA/NVMe
# enclosures" to "old/rare bridge chips", per smartctl(8) `-d TYPE`. auto is
# tried first since smartctl usually gets it right for well-known VID:PIDs;
# the rest is only exercised when auto fails to produce SMART data.
CANDIDATE_TYPES = [
    "auto",
    "sat",
    "sat,12",
    "sat,16",
    "sntjmicron",
    "sntasmedia",
    "sntasmedia/sat",
    "usbjmicron",
    "usbjmicron,x",
    "usbprolific",
    "usbsunplus",
    "usbcypress",
    "scsi",
    "ata",
]

DEFAULT_CACHE_PATH = Path(
    os.environ.get("USBSMART_DOCTOR_CACHE")
    or (Path.home() / ".cache" / "usbsmart-doctor" / "known_bridges.json")
)


class SmartctlNotFound(RuntimeError):
    pass


@dataclass
class ProbeResult:
    device_type: Optional[str]
    tried: list = field(default_factory=list)
    raw_json: Optional[dict] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.device_type is not None


@dataclass
class HealthSummary:
    device: str
    device_type: str
    model: Optional[str]
    serial: Optional[str]
    protocol: Optional[str]
    smart_supported: bool
    smart_enabled: bool
    overall_health_passed: Optional[bool]
    temperature_celsius: Optional[int]
    power_on_hours: Optional[int]
    power_cycle_count: Optional[int]
    reallocated_sectors: Optional[int]
    pending_sectors: Optional[int]
    percentage_used: Optional[int]  # NVMe wear indicator
    media_errors: Optional[int]  # NVMe
    critical_warning: Optional[int]  # NVMe critical_warning bitmask, raw value
    warnings: list = field(default_factory=list)


def find_smartctl() -> str:
    path = shutil.which("smartctl")
    if not path:
        raise SmartctlNotFound(
            "smartctl not found on PATH. Install smartmontools: "
            "'sudo apt install smartmontools' (Debian/Ubuntu), "
            "'sudo pacman -S smartmontools' (Arch), "
            "'sudo dnf install smartmontools' (Fedora)."
        )
    return path


def _run_smartctl(smartctl_bin: str, args: list, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        [smartctl_bin, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _json_has_smart_data(data: dict) -> bool:
    """Heuristic: does this smartctl -j output actually carry SMART data?"""
    if not isinstance(data, dict):
        return False
    if data.get("smart_status") is not None:
        return True
    # smartctl's own JSON schema documents several object-valued keys
    # (ata_smart_attributes, smartctl, nvme_smart_health_information_log,
    # ...) as *optional*, and in practice some smartctl builds/probe paths
    # serialize an unpopulated optional object as an explicit JSON `null`
    # rather than omitting the key entirely (e.g. when a device type is
    # accepted but the attribute-table sub-command subsequently fails, or
    # for SCSI/USB-passthrough devices with no ATA attribute table at all).
    # `dict.get(key, {})` only supplies the {} default when the key is
    # *absent* -- a present-but-null value passes straight through and the
    # chained `.get("table")` call then raises AttributeError on it. `or {}`
    # normalizes both "absent" and "present but null" to the same safe {}.
    if (data.get("ata_smart_attributes") or {}).get("table"):
        return True
    if data.get("nvme_smart_health_information_log"):
        return True
    # smartctl sets smartctl.exit_status bit 0x02 when the device could not
    # be opened at all -- never treat that as success even if some
    # boilerplate JSON keys exist.
    messages = (data.get("smartctl") or {}).get("messages", [])
    for m in messages:
        text = (m.get("string") or "").lower()
        if "unable to detect device type" in text or "device open failed" in text:
            return False
    return False


def _is_permission_denied(data: dict) -> bool:
    """Did smartctl fail to even open the device due to insufficient
    permissions, rather than a bridge-chip/device-type mismatch?

    smartctl reports this as a "Permission denied" message when the
    invoking user lacks read access to the block device (the common case:
    running as a non-root user without being in the right group, or a udev
    rule that doesn't grant access to removable USB drives). This is a
    fundamentally different problem than "no -d TYPE produced SMART data",
    and misattributing it to the USB bridge chip sends users down the wrong
    troubleshooting path (trying every -d TYPE) when the real fix is a
    one-line permission/group change.
    """
    if not isinstance(data, dict):
        return False
    # `smartctl` is documented as an optional object key and some probe
    # paths serialize it as JSON `null` rather than omitting it (see
    # _json_has_smart_data's comment above) -- `or {}` avoids an
    # AttributeError on the chained `.get("messages")` call in that case.
    messages = (data.get("smartctl") or {}).get("messages", [])
    for m in messages:
        text = (m.get("string") or "").lower()
        if "permission denied" in text:
            return True
    return False


def load_cache(cache_path: Path = DEFAULT_CACHE_PATH) -> dict:
    try:
        return json.loads(cache_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_cache(cache: dict, cache_path: Path = DEFAULT_CACHE_PATH) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True))


def get_usb_identity(device: str) -> Optional[str]:
    """Best-effort USB vendor:product[:serial] key for cache lookups.

    Uses udevadm (present on virtually all Linux systems) if available;
    silently returns None when it isn't (e.g. non-USB device, or udevadm
    missing), which just disables caching for that device.
    """
    udevadm = shutil.which("udevadm")
    if not udevadm:
        return None
    try:
        proc = subprocess.run(
            [udevadm, "info", "--query=property", "--name", device],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    props = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            props[k] = v
    vendor = props.get("ID_VENDOR_ID")
    product = props.get("ID_MODEL_ID")
    serial = props.get("ID_SERIAL_SHORT") or props.get("ID_SERIAL")
    if not vendor or not product:
        return None
    return f"{vendor}:{product}:{serial or ''}"


def probe_device_type(
    device: str,
    smartctl_bin: Optional[str] = None,
    candidates: Optional[list] = None,
    cache_path: Path = DEFAULT_CACHE_PATH,
    use_cache: bool = True,
    runner=_run_smartctl,
) -> ProbeResult:
    """Try candidate -d types against `device` until one yields real SMART data."""
    smartctl_bin = smartctl_bin or find_smartctl()
    candidates = candidates or CANDIDATE_TYPES
    tried = []

    cache = load_cache(cache_path) if use_cache else {}
    identity = get_usb_identity(device) if use_cache else None
    # Only let the cache reorder/inject a type when the caller is exploring
    # the full candidate list (the normal auto-probe path). When exactly one
    # candidate was supplied -- the CLI's `--type TYPE` "skip probing and use
    # this type directly" override -- a cache hit must never prepend a
    # *different* cached type ahead of it: that would silently ignore the
    # user's explicit choice (e.g. a stale/wrong cache entry from a prior
    # drive sharing the same USB vendor:product id) and return health data
    # read with the wrong device type instead of the one the user asked for.
    if identity and identity in cache and len(candidates) > 1:
        cached_type = cache[identity]
        ordered = [cached_type] + [c for c in candidates if c != cached_type]
    else:
        ordered = candidates

    for dtype in ordered:
        tried.append(dtype)
        args = ["-a", "-j"]
        if dtype != "auto":
            args += ["-d", dtype]
        args.append(device)
        try:
            proc = runner(smartctl_bin, args)
        except (subprocess.SubprocessError, OSError) as exc:
            continue
        try:
            data = json.loads(proc.stdout) if proc.stdout else {}
        except json.JSONDecodeError:
            data = {}
        if _is_permission_denied(data):
            return ProbeResult(
                device_type=None,
                tried=tried,
                error=(
                    f"smartctl could not open {device}: permission denied. "
                    "This is not a USB bridge/device-type problem -- your "
                    "user lacks read access to the block device. Re-run "
                    "with 'sudo', or add your user to the 'disk' group "
                    "(some distros use a udev rule instead) and log back "
                    "in."
                ),
            )
        if _json_has_smart_data(data):
            if use_cache and identity:
                cache[identity] = dtype
                save_cache(cache, cache_path)
            return ProbeResult(device_type=dtype, tried=tried, raw_json=data)

    return ProbeResult(
        device_type=None,
        tried=tried,
        error=(
            "No smartctl device type produced SMART data for this drive. "
            "The USB bridge chip may not expose SMART pass-through at all "
            "(common on older/cheap USB-to-SATA adapters); see `smartctl -l scterc` "
            "or the drive vendor's own diagnostic tool as a fallback."
        ),
    )


def _get(d: dict, *path, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


# NVMe Base Spec "Critical Warning" byte (SMART/Health Information Log,
# byte 0): each bit flags an independent, spec-defined failure condition.
# smartctl's -j output surfaces this as a small integer bitmask under
# nvme_smart_health_information_log.critical_warning.
_NVME_CRITICAL_WARNING_BITS = {
    0: "NVMe available spare capacity has fallen below its threshold",
    1: "NVMe temperature is above/below a critical threshold",
    2: "NVMe subsystem reliability is degraded (excessive media/internal errors)",
    3: "NVMe media has been placed in read-only mode",
    4: "NVMe volatile memory backup device has failed",
    5: "NVMe Persistent Memory Region (PMR) has become read-only or unreliable",
}


def _decode_nvme_critical_warning(bitmask: int) -> list:
    """Decode the NVMe critical_warning bitmask into human-readable warnings.

    Any bit this table doesn't recognize is still surfaced generically
    rather than silently dropped, since an unrecognized-but-nonzero value
    still means the drive is reporting *something* critical."""
    warnings = []
    for bit, message in _NVME_CRITICAL_WARNING_BITS.items():
        if bitmask & (1 << bit):
            warnings.append(message)
    known_mask = sum(1 << bit for bit in _NVME_CRITICAL_WARNING_BITS)
    unknown_bits = bitmask & ~known_mask
    if unknown_bits:
        warnings.append(
            f"NVMe critical_warning has unrecognized bit(s) set (0x{unknown_bits:x}) "
            f"-- check `smartctl -a` output directly"
        )
    return warnings


def summarize(device: str, probe: ProbeResult) -> HealthSummary:
    if not probe.ok or probe.raw_json is None:
        raise ValueError("Cannot summarize a failed probe")
    data = probe.raw_json
    warnings = []

    model = _get(data, "model_name") or _get(data, "model_family")
    serial = _get(data, "serial_number")
    protocol = _get(data, "device", "protocol")

    smart_status = _get(data, "smart_status", "passed")
    smart_support_available = _get(data, "smart_support", "available", default=True)
    smart_support_enabled = _get(data, "smart_support", "enabled", default=True)

    temperature = _get(data, "temperature", "current")

    power_on_hours = _get(data, "power_on_time", "hours")
    power_cycles = _get(data, "power_cycle_count")

    reallocated = None
    pending = None
    # `_get(..., default=[])` only substitutes the default when the "table"
    # key is *absent* -- smartctl's own JSON schema documents it as an
    # optional sub-key, and real-world probe paths (device type accepted but
    # the attribute-table sub-read itself failing, or certain SCSI/USB-
    # passthrough responses) can serialize it as an explicit JSON `null`
    # rather than omitting it. That present-but-null value passed straight
    # through here and crashed the loop below with "TypeError: 'NoneType'
    # object is not iterable" -- the same failure shape already guarded
    # against for the sibling ata_smart_attributes/smartctl reads in
    # _json_has_smart_data() and _is_permission_denied() via `or {}`, but
    # missed at this call site. `or []` normalizes both "absent" and
    # "present but null" to the same safe empty iterable.
    for attr in _get(data, "ata_smart_attributes", "table", default=[]) or []:
        if attr.get("id") == 5:
            reallocated = attr.get("raw", {}).get("value")
        elif attr.get("id") == 197:
            pending = attr.get("raw", {}).get("value")

    percentage_used = _get(data, "nvme_smart_health_information_log", "percentage_used")
    media_errors = _get(data, "nvme_smart_health_information_log", "media_errors")
    critical_warning = _get(data, "nvme_smart_health_information_log", "critical_warning")

    if reallocated and reallocated > 0:
        warnings.append(f"{reallocated} reallocated sector(s) — drive has remapped bad blocks")
    if pending and pending > 0:
        warnings.append(f"{pending} pending sector(s) — unstable sectors awaiting remap")
    if percentage_used is not None and percentage_used >= 90:
        warnings.append(f"NVMe wear at {percentage_used}% of rated life")
    if media_errors and media_errors > 0:
        warnings.append(f"{media_errors} NVMe media error(s) logged")
    if critical_warning:
        warnings.extend(_decode_nvme_critical_warning(critical_warning))
    if smart_status is False:
        warnings.append("Overall SMART self-assessment: FAILED — back up this drive now")

    return HealthSummary(
        device=device,
        device_type=probe.device_type,
        model=model,
        serial=serial,
        protocol=protocol,
        smart_supported=bool(smart_support_available),
        smart_enabled=bool(smart_support_enabled),
        overall_health_passed=smart_status,
        temperature_celsius=temperature,
        power_on_hours=power_on_hours,
        power_cycle_count=power_cycles,
        reallocated_sectors=reallocated,
        pending_sectors=pending,
        percentage_used=percentage_used,
        media_errors=media_errors,
        critical_warning=critical_warning,
        warnings=warnings,
    )

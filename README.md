# usbsmart-doctor

[![CI](https://github.com/zhuhroscar-tech/usbsmart-doctor/actions/workflows/ci.yml/badge.svg)](https://github.com/zhuhroscar-tech/usbsmart-doctor/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/zhuhroscar-tech/usbsmart-doctor?include_prereleases&label=release)](https://github.com/zhuhroscar-tech/usbsmart-doctor/releases)
![Linux](https://img.shields.io/badge/platform-Linux-111111?logo=linux)

Find the `smartctl` device type your USB drive's bridge chip actually needs,
then print a clean, human-readable SMART health report — instead of the
generic `smartctl -a /dev/sdX` failure ("Unable to detect device type") that
so many external/USB hard drives and SSDs hit on Linux.

## Simple explanation

Figures out the right way to talk to your external USB hard drive or SSD so
you can see its health report (temperature, wear, warning signs of
failure) — something the standard smartctl tool often fails to do
automatically on USB drives. Run one command and get a clear health
summary instead of a cryptic "Unable to detect device type" error.

## The problem

`smartctl` (from smartmontools) can read SMART health data from almost any
drive — but only if it knows which USB-to-SATA/USB-to-NVMe bridge chip sits
between the drive and your USB port. Autodetection (`-d auto`) frequently
fails on external enclosures, and the fix is to manually guess one of a dozen
`-d TYPE` values (`usbjmicron`, `usbprolific`, `sat`, `sntjmicron`, ...) from
the `smartctl(8)` man page — a well-documented, recurring source of confusion
for people trying to check the health of an external drive
(see e.g. [Unix & Linux SE], [r/linuxquestions], [r/linux4noobs] threads on
exactly this).

Existing GUI tools like GSmartControl still hit the same wall because the
underlying detection problem is smartctl's, not the GUI's.

## What this does

```
$ sudo usbsmart-doctor /dev/sdb
Device:        /dev/sdb
Working -d:    smartctl -d usbjmicron -a /dev/sdb
Types tried:   auto, sat, usbjmicron

Model:         Seagate Backup Plus 4TB
Serial:        NA1A2B3C
Protocol:      ATA
SMART support: available=True enabled=True
Overall health: PASSED
Temperature:   31C
Power-on time: 8452 hours
Power cycles:  310
Reallocated sectors: 0
Pending sectors:     0

No warnings detected in the metrics this tool checks.
```

It automatically tries `auto` first, then walks a documented list of
USB-bridge device types until one returns real SMART data, remembers what
worked for that exact drive (by USB vendor:product:serial) so future runs are
instant, and translates the raw attributes into a summary with plain-English
warnings (reallocated/pending sectors, NVMe wear, failed self-assessment).

**Read-only. It never writes to a device, never runs a self-test, and never
requires network access.** It only shells out to `smartctl` with `-a`/`-i`
style read commands.

## Install

Requires Python 3.9+ and `smartmontools` (provides `smartctl`):

```bash
# Debian/Ubuntu
sudo apt install smartmontools
# Arch
sudo pacman -S smartmontools
# Fedora
sudo dnf install smartmontools
```

Then either:

```bash
pip install --user usbsmart-doctor    # once published to PyPI (source install below always works)
```

or, from a GitHub Release, grab `usbsmart-doctor.pyz` (no pip/venv needed):

```bash
curl -LO https://github.com/zhuhroscar-tech/usbsmart-doctor/releases/download/v0.1.0/usbsmart-doctor.pyz
python3 usbsmart-doctor.pyz --help
```

Or from source:

```bash
git clone https://github.com/zhuhroscar-tech/usbsmart-doctor.git
cd usbsmart-doctor
pip install --user .
```

## Usage

```bash
usbsmart-doctor /dev/sdb            # human-readable report (needs root/sudo for SMART reads on most systems)
usbsmart-doctor /dev/sdb --json     # machine-readable JSON
usbsmart-doctor /dev/sdb --type sat # skip probing, force a known -d TYPE
usbsmart-doctor /dev/sdb --no-cache # ignore/skip the learned-type cache
```

Exit codes: `0` healthy, `1` no working device type found, `2` smartctl
missing, `3` SMART overall self-assessment failed, `4` other warnings
present.

## Uninstall

```bash
pip uninstall usbsmart-doctor
rm -rf ~/.cache/usbsmart-doctor   # clears the learned device-type cache
```

## Privacy & permissions

- No network access, no telemetry, no data leaves your machine.
- Reading SMART data typically requires root (raw device access) — run with
  `sudo` if you get a permission error.
- The only persistent state is `~/.cache/usbsmart-doctor/known_bridges.json`,
  a small cache mapping USB vendor:product:serial → the smartctl device type
  that worked, so repeat checks on the same drive are instant. Delete it any
  time; it is fully optional (`--no-cache`).

## Distro / architecture support

Pure Python (stdlib only) — works on any Linux distribution with Python 3.9+
and `smartmontools` installed, on any CPU architecture. Tested in CI on
Ubuntu (`ubuntu-latest` GitHub Actions runners), Python 3.9 and 3.12.

## Reproducible build & test

```bash
git clone https://github.com/zhuhroscar-tech/usbsmart-doctor.git
cd usbsmart-doctor
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest
pytest -v
python -m build          # produces dist/*.whl and dist/*.tar.gz
python -m zipapp build/pyz-deps -m "usbsmart_doctor.cli:main" -o dist/usbsmart-doctor.pyz
```

CI (`.github/workflows/ci.yml`) runs the same steps on real Ubuntu Linux
GitHub Actions runners for every push/PR, plus a smoke test of the installed
console script and the standalone `.pyz`.

## License

MIT — see [LICENSE](LICENSE).

[Unix & Linux SE]: https://unix.stackexchange.com
[r/linuxquestions]: https://www.reddit.com/r/linuxquestions/
[r/linux4noobs]: https://www.reddit.com/r/linux4noobs/

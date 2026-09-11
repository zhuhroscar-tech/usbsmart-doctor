"""Guard against version drift between pyproject.toml and __init__.py.

Regression coverage for a real released bug (found while auditing the
sibling repo reboot-safety-check, then confirmed to exist here too):
pyproject.toml's [project] version was bumped for a release, but
usbsmart_doctor/__init__.py's __version__ (what `--version` actually
prints) was left pointing at the previous release. The wheel's package
metadata correctly reported the new version while the CLI's own
`--version` output lied -- only caught by an independent post-release
smoke test against the real published artifact. This test makes that
drift fail CI immediately next time.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from usbsmart_doctor import __version__


def test_init_version_matches_pyproject_version():
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text())
    pyproject_version = data["project"]["version"]
    assert __version__ == pyproject_version, (
        f"__init__.py __version__ ({__version__!r}) does not match "
        f"pyproject.toml's [project].version ({pyproject_version!r}). "
        "These must be bumped together on every release."
    )

"""Regression coverage for packaging metadata accepted by modern setuptools."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def _pyproject_text() -> str:
    return PYPROJECT.read_text()


def test_project_license_uses_spdx_string_not_deprecated_table():
    text = _pyproject_text()

    assert 'license = "MIT"' in text
    assert 'license = { text = "MIT" }' not in text
    assert 'license-files = ["LICENSE"]' in text


def test_deprecated_license_classifier_is_not_reintroduced():
    text = _pyproject_text()

    assert "License :: OSI Approved :: MIT License" not in text


def test_build_backend_supports_license_files_key():
    text = _pyproject_text()
    match = re.search(r'requires\s*=\s*\["setuptools>=(\d+)"', text)

    assert match, "pyproject.toml must pin a setuptools lower bound"
    assert int(match.group(1)) >= 77

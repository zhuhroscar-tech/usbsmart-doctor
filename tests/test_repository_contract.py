"""Repository completeness contracts for release/documentation hygiene."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_required_project_files_exist():
    for relative in [
        "LICENSE",
        "README.md",
        "README.zh-CN.md",
        "CHANGELOG.md",
        "pyproject.toml",
        ".github/workflows/ci.yml",
        ".github/workflows/codeql.yml",
    ]:
        assert (ROOT / relative).is_file(), f"missing required project file: {relative}"


def test_readmes_link_release_history_and_license():
    for relative in ["README.md", "README.zh-CN.md"]:
        text = _read(relative)
        assert "CHANGELOG.md" in text
        assert "https://github.com/zhuhroscar-tech/usbsmart-doctor/releases" in text
        assert "LICENSE" in text


def test_changelog_contains_current_version():
    pyproject = _read("pyproject.toml")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert match, "pyproject.toml must declare a project version"

    changelog = _read("CHANGELOG.md")
    assert f"## v{match.group(1)}" in changelog


def test_ci_runs_tests_and_builds_release_artifacts():
    ci = _read(".github/workflows/ci.yml")

    assert "pytest" in ci
    assert "python -m build" in ci
    assert "usbsmart-doctor.pyz" in ci
    assert "SHA256SUMS" in ci


def test_codeql_workflow_is_enabled_for_python():
    codeql = _read(".github/workflows/codeql.yml")

    assert "github/codeql-action/init" in codeql
    assert "python" in codeql.lower()

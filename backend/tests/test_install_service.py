"""Dry-run tests for the systemd user-service installer (no systemctl)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "install_service.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash is not available"
)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )


def test_default_dry_run_renders_unit() -> None:
    result = run_script("--dry-run")

    assert result.returncode == 0, result.stderr
    output = result.stdout
    lines = output.splitlines()
    assert lines[0].startswith("# Managed by Kerstin scripts/install_service.sh")
    assert f"ExecStart={REPO}/.venv/bin/python -m kerstin" in output
    assert f"WorkingDirectory={REPO}/backend" in output
    assert "Restart=on-failure" in output
    assert "StartLimitBurst=3" in output
    assert "Environment=KERSTIN_PORT" not in output
    assert "SyslogIdentifier=kerstin" in output


def test_named_port_dry_run_renders_override() -> None:
    result = run_script("--name", "kerstin-dev", "--port", "8771", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "Environment=KERSTIN_PORT=8771" in result.stdout
    assert "SyslogIdentifier=kerstin-dev" in result.stdout


@pytest.mark.parametrize("name", ["sunny-brain", "../x", "other"])
def test_unsafe_names_are_rejected(name: str) -> None:
    result = run_script("--name", name, "--dry-run")

    assert result.returncode == 2
    assert "--name must match" in result.stderr


def test_dry_run_leaves_no_placeholders() -> None:
    result = run_script("--name", "kerstin-dev", "--port", "8771", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert re.search(r"@[A-Z_]+@", result.stdout) is None

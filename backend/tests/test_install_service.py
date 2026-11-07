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


def test_tts_unit_dry_run() -> None:
    result = run_script(
        "--unit", "tts", "--name", "kerstin-tts-dev", "--port", "8881",
        "--env", "KOKORO_IDLE_RELEASE_S=60", "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    assert "ExecStart=" + str(REPO / ".venv-kokoro/bin/python") + " -m tts_server.server" in result.stdout
    assert "Environment=KOKORO_DEVICE=cuda" in result.stdout
    assert "Environment=HF_HUB_OFFLINE=1" in result.stdout
    assert "Environment=KOKORO_PORT=8881" in result.stdout
    assert "SyslogIdentifier=kerstin-tts-dev" in result.stdout


def test_app_wants_tts_only_when_assets_exist() -> None:
    result = run_script("--name", "kerstin-dev", "--dry-run")
    assert result.returncode == 0, result.stderr
    if (REPO / ".venv-kokoro/bin/python").exists() and (REPO / "voices/kokoro/kerstin").is_dir():
        assert "Wants=kerstin-tts-dev.service" in result.stdout
        assert "After=kerstin-tts-dev.service" in result.stdout
    else:
        assert "Wants=" not in result.stdout


def test_env_keys_are_validated() -> None:
    bad = run_script("--env", "BAD_KEY=1", "--dry-run")
    assert bad.returncode == 2
    assert "KERSTIN_* or KOKORO_*" in bad.stderr

    good = run_script(
        "--env", "KERSTIN_TTS_URL=http://127.0.0.1:8881", "--dry-run"
    )
    assert good.returncode == 0, good.stderr
    assert "Environment=KERSTIN_TTS_URL=http://127.0.0.1:8881" in good.stdout

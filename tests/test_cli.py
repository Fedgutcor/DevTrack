import subprocess
import sys


def test_cli_help_exits_cleanly():
    result = subprocess.run(
        [sys.executable, "-m", "devtrack.cli", "help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "devtrack" in result.stdout.lower() or result.stdout != ""


def test_cli_unknown_command_exits_nonzero():
    result = subprocess.run(
        [sys.executable, "-m", "devtrack.cli", "nonexistent_command_xyz"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0

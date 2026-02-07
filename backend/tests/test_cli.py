"""Tests for the Ungula CLI."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ungula.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_home(tmp_path):
    """Set UNGULA_HOME to a temp directory for isolated tests."""
    home = tmp_path / ".ungula"
    home.mkdir()
    with patch.dict(os.environ, {"UNGULA_HOME": str(home)}):
        yield home


class TestHelp:
    def test_help_shows_all_commands(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "stop" in result.output
        assert "status" in result.output
        assert "logs" in result.output
        assert "init" in result.output
        assert "rotate-key" in result.output

    def test_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "ungula" in result.output


class TestInit:
    def test_init_creates_config(self, runner, tmp_home):
        result = runner.invoke(main, ["init", "--force"])
        assert result.exit_code == 0
        config_path = tmp_home / "config.yaml"
        assert config_path.exists()
        content = config_path.read_text()
        assert "server:" in content
        assert "auth:" in content
        assert "secret_key:" in content
        # Secret should NOT be the default
        assert "CHANGE-ME-IN-PRODUCTION" not in content

    def test_init_creates_directories(self, runner, tmp_home):
        result = runner.invoke(main, ["init", "--force"])
        assert result.exit_code == 0
        assert (tmp_home / "workspace").is_dir()
        assert (tmp_home / "data").is_dir()
        assert (tmp_home / "logs").is_dir()
        assert (tmp_home / "skills").is_dir()
        assert (tmp_home / "plugins").is_dir()

    def test_init_no_overwrite_without_force(self, runner, tmp_home):
        config_path = tmp_home / "config.yaml"
        config_path.write_text("existing: true\n")
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0
        assert "already exists" in result.output
        # Original content preserved
        assert config_path.read_text() == "existing: true\n"


class TestStatus:
    def test_status_not_running(self, runner, tmp_home):
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "not running" in result.output

    def test_status_stale_pid(self, runner, tmp_home):
        """Stale PID file should be cleaned up."""
        pid_file = tmp_home / "ungula.pid"
        pid_file.write_text("99999999")  # Very unlikely to be a real PID
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "not running" in result.output


class TestStop:
    def test_stop_not_running(self, runner, tmp_home):
        result = runner.invoke(main, ["stop"])
        assert result.exit_code == 0
        assert "not running" in result.output

    def test_stop_stale_pid(self, runner, tmp_home):
        pid_file = tmp_home / "ungula.pid"
        pid_file.write_text("99999999")
        result = runner.invoke(main, ["stop"])
        assert result.exit_code == 0
        assert "not running" in result.output


class TestLogs:
    def test_logs_no_file(self, runner, tmp_home):
        result = runner.invoke(main, ["logs"])
        assert result.exit_code == 0
        assert "No log file" in result.output

    def test_logs_reads_lines(self, runner, tmp_home):
        log_dir = tmp_home / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "ungula.log"
        lines = [f"Line {i}" for i in range(100)]
        log_file.write_text("\n".join(lines))

        result = runner.invoke(main, ["logs", "-n", "5"])
        assert result.exit_code == 0
        assert "Line 95" in result.output
        assert "Line 99" in result.output
        # Earlier lines should not appear
        assert "Line 50" not in result.output


class TestRotateKey:
    def test_rotate_key_with_yes(self, runner, tmp_home):
        # Write a minimal config first
        config_path = tmp_home / "config.yaml"
        config_path.write_text("auth:\n  secret_key: old-key\n")

        result = runner.invoke(main, ["rotate-key", "-y"])
        assert result.exit_code == 0
        assert "New secret key:" in result.output
        assert "Restart" in result.output

        # Verify the config was updated
        new_content = config_path.read_text()
        assert "old-key" not in new_content

    def test_rotate_key_aborts_without_confirm(self, runner, tmp_home):
        config_path = tmp_home / "config.yaml"
        config_path.write_text("auth:\n  secret_key: old-key\n")

        result = runner.invoke(main, ["rotate-key"], input="n\n")
        assert result.exit_code != 0  # Aborted
        # Config should be unchanged
        assert "old-key" in config_path.read_text()


class TestStart:
    def test_start_already_running(self, runner, tmp_home):
        """Start should fail if PID file points to a live process (our own PID)."""
        pid_file = tmp_home / "ungula.pid"
        pid_file.write_text(str(os.getpid()))  # Use our own PID — known alive
        result = runner.invoke(main, ["start"])
        assert result.exit_code == 1
        assert "already running" in result.output

    @patch("ungula.cli.subprocess.Popen")
    def test_start_daemon(self, mock_popen, runner, tmp_home):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        result = runner.invoke(main, ["start", "-d"])
        assert result.exit_code == 0
        assert "daemon" in result.output
        assert "12345" in result.output

        # PID file should be written
        pid_file = tmp_home / "ungula.pid"
        assert pid_file.exists()
        assert pid_file.read_text().strip() == "12345"

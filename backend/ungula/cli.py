"""
Ungula CLI — manage the Ungula server from the command line.

Commands:
    ungula start [-d] [--host] [--port] [--tls-cert] [--tls-key]
    ungula stop
    ungula status
    ungula logs [-n 50] [-f]
    ungula init [--force]
    ungula rotate-key [-y]
"""

import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

import click

from . import __version__
from .config import get_logs_dir, get_ungula_home, init_ungula_dirs, load_config, save_config


def _pid_file() -> Path:
    """Return the path to the PID file."""
    return get_ungula_home() / "ungula.pid"


def _log_file() -> Path:
    """Return the path to the main log file."""
    return get_logs_dir() / "ungula.log"


def _read_pid() -> int | None:
    """Read PID from file, returning None if missing or stale."""
    pid_path = _pid_file()
    if not pid_path.exists():
        return None
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return None
    # Check if process is alive
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        # Stale PID file — clean up
        _cleanup_pid()
        return None


def _cleanup_pid() -> None:
    """Remove the PID file if it exists."""
    try:
        _pid_file().unlink(missing_ok=True)
    except OSError:
        pass


def _write_pid(pid: int) -> None:
    """Write PID to the PID file."""
    pid_path = _pid_file()
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(pid))


@click.group()
@click.version_option(version=__version__, prog_name="ungula")
def main():
    """Ungula — Autonomous AI Agent Platform."""
    pass


@main.command()
@click.option("-d", "--daemon", is_flag=True, help="Run as a background daemon")
@click.option("--host", default=None, help="Server bind host")
@click.option("--port", default=None, type=int, help="Server port")
@click.option("--tls-cert", default=None, type=click.Path(exists=True), help="Path to TLS certificate")
@click.option("--tls-key", default=None, type=click.Path(exists=True), help="Path to TLS private key")
def start(daemon: bool, host: str | None, port: int | None, tls_cert: str | None, tls_key: str | None):
    """Start the Ungula server."""
    # Check if already running
    existing_pid = _read_pid()
    if existing_pid is not None:
        click.echo(f"Ungula is already running (PID {existing_pid})")
        sys.exit(1)

    if daemon:
        # Ensure log directory exists
        log_path = _log_file()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Build command for subprocess
        cmd = [sys.executable, "-m", "ungula.main"]

        # Pass config via environment
        env = os.environ.copy()
        if host:
            env["UNGULA_SERVER_HOST"] = host
        if port:
            env["UNGULA_SERVER_PORT"] = str(port)

        # Start as daemon
        with open(log_path, "a") as log_fd:
            proc = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=log_fd,
                start_new_session=True,
                env=env,
            )

        _write_pid(proc.pid)
        click.echo(f"Ungula started as daemon (PID {proc.pid})")
        click.echo(f"Logs: {log_path}")
    else:
        # Foreground mode — call run() directly
        click.echo(f"Starting Ungula v{__version__}...")
        from .main import run

        run(host=host, port=port, ssl_certfile=tls_cert, ssl_keyfile=tls_key)


@main.command()
def stop():
    """Stop the Ungula daemon."""
    pid = _read_pid()
    if pid is None:
        click.echo("Ungula is not running.")
        return

    click.echo(f"Stopping Ungula (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        click.echo(f"Failed to send SIGTERM: {e}")
        _cleanup_pid()
        return

    # Wait up to 10 seconds for graceful shutdown
    for _ in range(100):
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except OSError:
            break
    else:
        # Process still alive — force kill
        click.echo("Graceful shutdown timed out, sending SIGKILL...")
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    _cleanup_pid()
    click.echo("Ungula stopped.")


@main.command()
def status():
    """Show server status."""
    pid = _read_pid()
    if pid is None:
        click.echo("Ungula is not running.")
        return

    click.echo(f"Ungula is running (PID {pid})")

    # Try health check
    try:
        import httpx

        config = load_config()
        base_url = f"http://{config.server.host}:{config.server.port}"
        if config.server.host == "0.0.0.0":
            base_url = f"http://127.0.0.1:{config.server.port}"
        resp = httpx.get(f"{base_url}/api/health", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            click.echo(f"  Version: {data.get('version', 'unknown')}")
            click.echo(f"  Status:  {data.get('status', 'unknown')}")
    except Exception:
        click.echo("  Health check unavailable (server may still be starting)")


@main.command()
@click.option("-n", "--lines", default=50, help="Number of lines to show")
@click.option("-f", "--follow", is_flag=True, help="Follow log output")
def logs(lines: int, follow: bool):
    """View server logs."""
    log_path = _log_file()
    if not log_path.exists():
        click.echo(f"No log file found at {log_path}")
        return

    if follow:
        # Use tail -f for follow mode
        try:
            subprocess.run(["tail", f"-n{lines}", "-f", str(log_path)])
        except KeyboardInterrupt:
            pass
    else:
        # Read last N lines
        try:
            text = log_path.read_text()
            all_lines = text.splitlines()
            for line in all_lines[-lines:]:
                click.echo(line)
        except OSError as e:
            click.echo(f"Error reading logs: {e}")


@main.command(name="init")
@click.option("--force", is_flag=True, help="Overwrite existing config")
def init_cmd(force: bool):
    """Initialize Ungula directory structure and config."""
    home = get_ungula_home()
    config_path = home / "config.yaml"

    if config_path.exists() and not force:
        click.echo(f"Config already exists at {config_path}")
        click.echo("Use --force to overwrite.")
        return

    # Create directory structure
    init_ungula_dirs()
    click.echo(f"Created directory structure at {home}")

    # Generate config with a fresh secret
    secret = secrets.token_urlsafe(32)
    config_content = f"""\
# Ungula configuration
# Generated by `ungula init`

server:
  host: 0.0.0.0
  port: 8001

auth:
  secret_key: {secret}

llm:
  default_provider: anthropic
  anthropic:
    api_key: YOUR_KEY_HERE

# See docs/deployment.md for full configuration reference
"""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config_content)
    try:
        config_path.chmod(0o600)
    except OSError:
        pass

    click.echo(f"Created config at {config_path}")
    click.echo("Edit the config file to add your LLM API keys, then run: ungula start")


@main.command(name="rotate-key")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt")
def rotate_key(yes: bool):
    """Generate a new JWT secret key."""
    if not yes:
        click.confirm(
            "This will invalidate all existing JWT tokens. Continue?",
            abort=True,
        )

    config = load_config()
    new_key = secrets.token_urlsafe(32)
    config.auth.secret_key = new_key
    save_config(config)

    click.echo(f"New secret key: {new_key}")
    click.echo("Restart the server to apply the new key.")


if __name__ == "__main__":
    main()

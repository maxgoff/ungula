"""
Background process manager.

Tracks running background processes with captured stdout/stderr buffers.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BackgroundProcess:
    """A tracked background process."""

    id: str
    command: str
    process: asyncio.subprocess.Process
    started_at: datetime = field(default_factory=datetime.utcnow)
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    return_code: int | None = None
    _reader_task: asyncio.Task | None = field(default=None, repr=False)

    @property
    def is_running(self) -> bool:
        return self.return_code is None and self.process.returncode is None

    @property
    def status(self) -> str:
        if self.is_running:
            return "running"
        rc = self.return_code if self.return_code is not None else self.process.returncode
        return "completed" if rc == 0 else "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "command": self.command,
            "status": self.status,
            "return_code": self.return_code or self.process.returncode,
            "started_at": self.started_at.isoformat(),
        }


class ProcessManager:
    """Manages background processes."""

    def __init__(self, max_concurrent: int = 5, max_output_size: int = 50_000):
        self._processes: dict[str, BackgroundProcess] = {}
        self.max_concurrent = max_concurrent
        self.max_output_size = max_output_size

    @property
    def running_count(self) -> int:
        return sum(1 for p in self._processes.values() if p.is_running)

    async def start(self, command: str, cwd: str | None = None, timeout: int | None = None) -> BackgroundProcess:
        """Start a background process."""
        if self.running_count >= self.max_concurrent:
            raise RuntimeError(f"Max concurrent processes ({self.max_concurrent}) reached")

        proc_id = str(uuid.uuid4())[:8]

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        bg = BackgroundProcess(id=proc_id, command=command, process=process)
        self._processes[proc_id] = bg

        # Start background reader
        bg._reader_task = asyncio.create_task(self._read_output(bg, timeout))

        return bg

    async def _read_output(self, bg: BackgroundProcess, timeout: int | None) -> None:
        """Read process output in background."""
        try:
            if timeout:
                stdout, stderr = await asyncio.wait_for(
                    bg.process.communicate(), timeout=timeout
                )
            else:
                stdout, stderr = await bg.process.communicate()

            bg.stdout_buffer = stdout.decode("utf-8", errors="replace")[:self.max_output_size]
            bg.stderr_buffer = stderr.decode("utf-8", errors="replace")[:self.max_output_size]
            bg.return_code = bg.process.returncode
        except asyncio.TimeoutError:
            bg.process.kill()
            bg.return_code = -1
            bg.stderr_buffer += "\n(process killed: timeout)"
        except Exception as e:
            logger.error("Error reading process output: %s", e)
            bg.return_code = -1

    def get(self, process_id: str) -> BackgroundProcess | None:
        return self._processes.get(process_id)

    def list_all(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self._processes.values()]

    async def kill(self, process_id: str) -> bool:
        """Kill a running process."""
        bg = self._processes.get(process_id)
        if not bg or not bg.is_running:
            return False
        try:
            bg.process.kill()
            bg.return_code = -9
            return True
        except ProcessLookupError:
            return False

    async def write_stdin(self, process_id: str, data: str) -> bool:
        """Write to a process's stdin."""
        bg = self._processes.get(process_id)
        if not bg or not bg.is_running or bg.process.stdin is None:
            return False
        try:
            bg.process.stdin.write(data.encode("utf-8"))
            await bg.process.stdin.drain()
            return True
        except Exception:
            return False

    async def cleanup(self) -> None:
        """Kill all running processes."""
        for bg in self._processes.values():
            if bg.is_running:
                try:
                    bg.process.kill()
                except ProcessLookupError:
                    pass
        self._processes.clear()

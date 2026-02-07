"""
Docker sandbox manager.

Creates isolated Docker containers for executing commands safely.
Containers have resource limits, optional network isolation, and
configurable filesystem mounts. Security hardening includes read-only
root, capability dropping, PID limits, and optional container reuse.
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import SandboxConfig

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of running a command in the sandbox."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class DockerSandbox:
    """
    Manages Docker containers for sandboxed command execution.

    Creates ephemeral containers with resource limits and
    optional volume mounts for secure code execution.
    """

    def __init__(
        self,
        config: SandboxConfig,
        workspace_path: Path | None = None,
    ):
        self.config = config
        self.workspace_path = workspace_path
        self._client = None

    async def initialize(self) -> bool:
        """
        Initialize Docker client and verify connectivity.

        Returns True if Docker is available.
        """
        try:
            import docker

            self._client = docker.from_env()
            self._client.ping()
            logger.info("Docker sandbox initialized (image=%s)", self.config.image)
            return True
        except ImportError:
            logger.error("docker package not installed. Install with: pip install docker")
            return False
        except Exception as e:
            logger.error("Docker not available: %s", e)
            return False

    async def execute(
        self,
        command: str,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """
        Execute a command in a sandboxed Docker container.

        Args:
            command: Shell command to execute.
            timeout: Override timeout in seconds.
            env: Additional environment variables.

        Returns:
            ExecutionResult with stdout, stderr, and exit code.
        """
        if not self._client:
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr="Docker client not initialized",
            )

        effective_timeout = timeout or self.config.timeout

        # Build container config
        container_config = self._build_container_config(command, env)

        try:
            # Run in thread pool since docker-py is synchronous
            loop = asyncio.get_event_loop()

            if self.config.reuse_containers:
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, self._run_in_reusable_container, command, env, effective_timeout
                    ),
                    timeout=effective_timeout + 5,
                )
            else:
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, self._run_container, container_config),
                    timeout=effective_timeout + 5,
                )
            return result

        except asyncio.TimeoutError:
            logger.warning("Sandbox execution timed out after %ds", effective_timeout)
            return ExecutionResult(
                exit_code=124,
                stdout="",
                stderr=f"Command timed out after {effective_timeout} seconds",
                timed_out=True,
            )
        except Exception as e:
            logger.error("Sandbox execution error: %s", e)
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
            )

    def _build_container_config(
        self,
        command: str,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build Docker container run configuration with security hardening."""
        config: dict[str, Any] = {
            "image": self.config.image,
            "command": ["sh", "-c", command],
            "working_dir": self.config.working_dir,
            "detach": True,
            "mem_limit": self.config.memory_limit,
            "nano_cpus": int(self.config.cpu_limit * 1e9),
            "auto_remove": False,  # We need logs before removal
        }

        # Security hardening: read-only root filesystem
        if self.config.read_only_root:
            config["read_only"] = True

        # Security hardening: drop capabilities
        if self.config.cap_drop:
            config["cap_drop"] = list(self.config.cap_drop)

        # Security hardening: security options
        security_opt = []
        if self.config.no_new_privileges:
            security_opt.append("no-new-privileges")
        if self.config.seccomp_profile:
            security_opt.append(f"seccomp={self.config.seccomp_profile}")
        if security_opt:
            config["security_opt"] = security_opt

        # Security hardening: PID limit
        if self.config.pids_limit > 0:
            config["pids_limit"] = self.config.pids_limit

        # Security hardening: tmpfs mounts for writable dirs
        if self.config.tmpfs_mounts and self.config.read_only_root:
            config["tmpfs"] = {mount: "size=64m,noexec" for mount in self.config.tmpfs_mounts}

        # Security hardening: user
        if self.config.user:
            config["user"] = self.config.user

        # DNS
        if self.config.dns:
            config["dns"] = list(self.config.dns)

        # Network
        if not self.config.network_enabled:
            config["network_mode"] = "none"

        # Environment
        if env:
            config["environment"] = env

        # Volume mounts
        volumes = {}
        if self.workspace_path and self.config.mount_mode != "none":
            read_only = self.config.mount_mode == "readonly"
            volumes[str(self.workspace_path)] = {
                "bind": self.config.working_dir,
                "mode": "ro" if read_only else "rw",
            }

        # Extra binds
        for bind in self.config.extra_binds:
            parts = bind.split(":")
            if len(parts) >= 2:
                host_path = parts[0]
                container_path = parts[1]
                mode = parts[2] if len(parts) > 2 else "ro"
                volumes[host_path] = {"bind": container_path, "mode": mode}

        if volumes:
            config["volumes"] = volumes

        # Labels for management
        config["labels"] = {
            "ungula.sandbox": "1",
            "ungula.created_at": str(int(time.time())),
            "ungula.config_hash": self._config_hash(),
        }

        return config

    def _config_hash(self) -> str:
        """Generate a hash of the sandbox config for container matching."""
        key_fields = {
            "image": self.config.image,
            "memory_limit": self.config.memory_limit,
            "cpu_limit": self.config.cpu_limit,
            "network_enabled": self.config.network_enabled,
            "read_only_root": self.config.read_only_root,
            "cap_drop": sorted(self.config.cap_drop),
        }
        return hashlib.sha256(json.dumps(key_fields, sort_keys=True).encode()).hexdigest()[:12]

    def _run_container(self, container_config: dict[str, Any]) -> ExecutionResult:
        """Run a container synchronously (called from thread pool)."""
        container = None
        try:
            container = self._client.containers.run(**container_config)

            # Wait for completion
            result = container.wait(timeout=self.config.timeout)
            exit_code = result.get("StatusCode", 1)

            # Get logs
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

            return ExecutionResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            )

        except Exception as e:
            logger.error("Container execution error: %s", e)
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
            )
        finally:
            if container and self.config.auto_cleanup:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    def _run_in_reusable_container(
        self,
        command: str,
        env: dict[str, str] | None,
        timeout: int,
    ) -> ExecutionResult:
        """Run a command in a reusable container (create or reuse existing)."""
        container = self._get_or_create_container(env)
        if container is None:
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr="Failed to get or create reusable container",
            )

        try:
            exec_result = container.exec_run(
                ["sh", "-c", command],
                workdir=self.config.working_dir,
                environment=env or {},
                demux=True,
            )

            stdout_bytes, stderr_bytes = exec_result.output or (b"", b"")
            stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")

            return ExecutionResult(
                exit_code=exec_result.exit_code,
                stdout=stdout,
                stderr=stderr,
            )
        except Exception as e:
            logger.error("Reusable container exec error: %s", e)
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
            )

    def _get_or_create_container(self, env: dict[str, str] | None = None) -> Any:
        """Find an existing reusable container or create a new one."""
        config_hash = self._config_hash()
        container_name = f"{self.config.container_prefix}{config_hash}"

        try:
            # Try to find existing container
            container = self._client.containers.get(container_name)
            if container.status != "running":
                container.start()
            return container
        except Exception:
            pass

        # Create new long-lived container
        create_args = self._build_container_config("sleep infinity", env)
        create_args["name"] = container_name
        create_args["auto_remove"] = False

        try:
            container = self._client.containers.run(**create_args)
            logger.info("Created reusable sandbox container: %s", container_name)
            return container
        except Exception as e:
            logger.error("Failed to create reusable container: %s", e)
            return None

    def prune_stale_containers(self) -> int:
        """Remove sandbox containers idle longer than max_idle_hours.

        Returns the number of containers pruned.
        """
        if not self._client:
            return 0

        pruned = 0
        cutoff = time.time() - (self.config.max_idle_hours * 3600)

        try:
            containers = self._client.containers.list(
                all=True,
                filters={"label": "ungula.sandbox=1"},
            )

            for container in containers:
                created_at_str = container.labels.get("ungula.created_at", "0")
                try:
                    created_at = int(created_at_str)
                except ValueError:
                    created_at = 0

                if created_at < cutoff:
                    try:
                        container.remove(force=True)
                        pruned += 1
                        logger.info("Pruned stale sandbox container: %s", container.name)
                    except Exception as e:
                        logger.warning("Failed to prune container %s: %s", container.name, e)

        except Exception as e:
            logger.error("Error pruning stale containers: %s", e)

        return pruned

    async def cleanup(self) -> None:
        """Clean up Docker resources."""
        if self._client:
            # Prune stale containers if reuse is enabled
            if self.config.reuse_containers:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.prune_stale_containers)

            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

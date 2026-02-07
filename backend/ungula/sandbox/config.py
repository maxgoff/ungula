"""
Sandbox configuration.
"""

from pydantic import BaseModel, Field


class SandboxConfig(BaseModel):
    """Docker sandbox configuration."""

    # Core settings
    enabled: bool = Field(default=False, description="Enable Docker sandbox for command execution")
    image: str = Field(default="python:3.11-slim", description="Docker image for sandbox")
    mount_mode: str = Field(
        default="readonly",
        description="Mount mode: 'readonly', 'readwrite', or 'none'",
    )
    working_dir: str = Field(default="/workspace", description="Working directory inside container")
    memory_limit: str = Field(default="256m", description="Memory limit (Docker format)")
    cpu_limit: float = Field(default=1.0, description="CPU limit (number of CPUs)")
    timeout: int = Field(default=30, description="Command timeout in seconds")
    network_enabled: bool = Field(default=False, description="Enable network access in sandbox")
    auto_cleanup: bool = Field(default=True, description="Auto-remove containers after execution")

    # Security hardening
    read_only_root: bool = Field(default=True, description="Mount root filesystem as read-only")
    cap_drop: list[str] = Field(default=["ALL"], description="Linux capabilities to drop")
    no_new_privileges: bool = Field(default=True, description="Prevent privilege escalation")
    pids_limit: int = Field(default=100, description="Maximum number of PIDs (prevents fork bombs)")
    tmpfs_mounts: list[str] = Field(
        default=["/tmp", "/var/tmp", "/run"],
        description="Ephemeral writable directories (tmpfs)",
    )
    user: str | None = Field(default=None, description="Container user (UID:GID)")
    seccomp_profile: str | None = Field(default=None, description="Path to seccomp profile JSON")
    dns: list[str] = Field(default=[], description="Custom DNS servers")
    extra_binds: list[str] = Field(default=[], description="Additional volume binds (host:container:mode)")

    # Container management
    container_prefix: str = Field(default="ungula-sbx-", description="Container name prefix")
    max_idle_hours: int = Field(default=24, description="Prune containers idle longer than N hours")
    reuse_containers: bool = Field(default=False, description="Keep containers alive for reuse")

"""
Individual security checks for the audit system.

Each check function returns a dict with:
- id: Unique check identifier
- name: Human-readable name
- severity: critical, high, medium, low, info
- status: pass, fail, warning
- detail: Description of the finding
- remediation: Optional auto-fix description
"""

import os
from pathlib import Path
from typing import Any


def check_jwt_secret(config: Any) -> dict:
    """Check if the JWT secret key is the insecure default."""
    secret = config.auth.secret_key
    is_default = secret == "CHANGE-ME-IN-PRODUCTION"
    is_short = len(secret) < 32

    if is_default:
        return {
            "id": "auth-jwt-secret",
            "name": "JWT Secret Key",
            "severity": "critical",
            "status": "fail",
            "detail": "Using default JWT secret 'CHANGE-ME-IN-PRODUCTION'. Tokens can be forged.",
            "remediation": "Set UNGULA_AUTH_SECRET_KEY environment variable to a random 64+ character string.",
            "auto_fixable": False,
        }
    elif is_short:
        return {
            "id": "auth-jwt-secret",
            "name": "JWT Secret Key",
            "severity": "high",
            "status": "warning",
            "detail": f"JWT secret is only {len(secret)} characters. Recommend 64+.",
            "remediation": "Set a longer secret key.",
            "auto_fixable": False,
        }
    return {
        "id": "auth-jwt-secret",
        "name": "JWT Secret Key",
        "severity": "critical",
        "status": "pass",
        "detail": "JWT secret key is configured and sufficiently long.",
        "auto_fixable": False,
    }


def check_cors_origins(config: Any) -> dict:
    """Check if CORS is configured too permissively."""
    origins = config.server.cors_origins
    has_wildcard = "*" in origins

    if has_wildcard:
        return {
            "id": "cors-origins",
            "name": "CORS Origins",
            "severity": "high",
            "status": "fail",
            "detail": "CORS allows all origins ('*'). This permits cross-site request attacks.",
            "remediation": "Set specific allowed origins in config.server.cors_origins.",
            "auto_fixable": False,
        }

    return {
        "id": "cors-origins",
        "name": "CORS Origins",
        "severity": "high",
        "status": "pass",
        "detail": f"CORS restricted to {len(origins)} specific origins.",
        "auto_fixable": False,
    }


def check_config_file_permissions(config_path: Path) -> dict:
    """Check if the config file has restricted permissions."""
    if not config_path.exists():
        return {
            "id": "config-file-perms",
            "name": "Config File Permissions",
            "severity": "medium",
            "status": "pass",
            "detail": "No config file found (using defaults).",
            "auto_fixable": False,
        }

    try:
        mode = config_path.stat().st_mode & 0o777
        if mode & 0o077:  # Group or others have access
            return {
                "id": "config-file-perms",
                "name": "Config File Permissions",
                "severity": "medium",
                "status": "fail",
                "detail": f"Config file has mode {oct(mode)}. Should be 0600 (owner-only).",
                "remediation": f"chmod 600 {config_path}",
                "auto_fixable": True,
            }
    except OSError:
        pass

    return {
        "id": "config-file-perms",
        "name": "Config File Permissions",
        "severity": "medium",
        "status": "pass",
        "detail": "Config file has restricted permissions.",
        "auto_fixable": False,
    }


def check_home_dir_permissions(home_dir: Path) -> dict:
    """Check if the .ungula home directory has restricted permissions."""
    if not home_dir.exists():
        return {
            "id": "home-dir-perms",
            "name": "Home Directory Permissions",
            "severity": "medium",
            "status": "pass",
            "detail": "Home directory does not exist yet.",
            "auto_fixable": False,
        }

    try:
        mode = home_dir.stat().st_mode & 0o777
        if mode & 0o077:
            return {
                "id": "home-dir-perms",
                "name": "Home Directory Permissions",
                "severity": "medium",
                "status": "fail",
                "detail": f"Home directory has mode {oct(mode)}. Should be 0700.",
                "remediation": f"chmod 700 {home_dir}",
                "auto_fixable": True,
            }
    except OSError:
        pass

    return {
        "id": "home-dir-perms",
        "name": "Home Directory Permissions",
        "severity": "medium",
        "status": "pass",
        "detail": "Home directory has restricted permissions.",
        "auto_fixable": False,
    }


def check_debug_mode(config: Any) -> dict:
    """Check if debug/reload mode is enabled."""
    if config.server.reload:
        return {
            "id": "debug-mode",
            "name": "Debug/Reload Mode",
            "severity": "low",
            "status": "warning",
            "detail": "Server reload mode is enabled. Should be disabled in production.",
            "remediation": "Set server.reload to false in config.",
            "auto_fixable": True,
        }
    return {
        "id": "debug-mode",
        "name": "Debug/Reload Mode",
        "severity": "low",
        "status": "pass",
        "detail": "Debug/reload mode is disabled.",
        "auto_fixable": False,
    }


def check_shell_tool(config: Any) -> dict:
    """Check shell tool security configuration."""
    if not config.skills.shell.enabled:
        return {
            "id": "shell-tool",
            "name": "Shell Tool",
            "severity": "info",
            "status": "pass",
            "detail": "Shell tool is disabled.",
            "auto_fixable": False,
        }

    blocked = config.skills.shell.blocked_commands
    if len(blocked) < 5:
        return {
            "id": "shell-tool",
            "name": "Shell Tool",
            "severity": "high",
            "status": "warning",
            "detail": f"Shell tool has only {len(blocked)} blocked patterns. Consider expanding.",
            "remediation": "Add more blocked command patterns to skills.shell.blocked_commands.",
            "auto_fixable": False,
        }

    return {
        "id": "shell-tool",
        "name": "Shell Tool",
        "severity": "high",
        "status": "pass",
        "detail": f"Shell tool has {len(blocked)} blocked patterns.",
        "auto_fixable": False,
    }


def check_api_keys_in_env(config: Any) -> dict:
    """Check if sensitive API keys are set via environment (preferred) vs config."""
    env_keys = {
        "UNGULA_OPENROUTER_API_KEY",
        "UNGULA_ANTHROPIC_API_KEY",
        "UNGULA_OPENAI_API_KEY",
        "UNGULA_AUTH_SECRET_KEY",
    }
    set_in_env = [k for k in env_keys if os.environ.get(k)]

    if len(set_in_env) == 0:
        return {
            "id": "api-keys-env",
            "name": "API Keys in Environment",
            "severity": "low",
            "status": "warning",
            "detail": "No API keys set via environment variables. Keys in config file may be exposed.",
            "remediation": "Set sensitive keys via environment variables instead of config file.",
            "auto_fixable": False,
        }

    return {
        "id": "api-keys-env",
        "name": "API Keys in Environment",
        "severity": "low",
        "status": "pass",
        "detail": f"{len(set_in_env)} API keys set via environment variables.",
        "auto_fixable": False,
    }


def check_token_expiry(config: Any) -> dict:
    """Check JWT token expiration settings."""
    expire_minutes = config.auth.token_expire_minutes
    if expire_minutes > 10080:  # > 7 days
        return {
            "id": "token-expiry",
            "name": "Token Expiration",
            "severity": "medium",
            "status": "warning",
            "detail": f"Token expiry is {expire_minutes} minutes ({expire_minutes // 1440} days). Consider shorter.",
            "remediation": "Set auth.token_expire_minutes to 1440 (24 hours) or less.",
            "auto_fixable": False,
        }
    return {
        "id": "token-expiry",
        "name": "Token Expiration",
        "severity": "medium",
        "status": "pass",
        "detail": f"Token expiry is {expire_minutes} minutes ({expire_minutes // 60} hours).",
        "auto_fixable": False,
    }


def check_bind_address(config: Any) -> dict:
    """Check if server is bound to all interfaces."""
    host = config.server.host
    if host in ("0.0.0.0", "::"):
        return {
            "id": "bind-address",
            "name": "Bind Address",
            "severity": "low",
            "status": "warning",
            "detail": f"Server bound to {host} (all interfaces). Consider 127.0.0.1 for local-only.",
            "remediation": "Set server.host to '127.0.0.1' if only local access is needed.",
            "auto_fixable": False,
        }
    return {
        "id": "bind-address",
        "name": "Bind Address",
        "severity": "low",
        "status": "pass",
        "detail": f"Server bound to {host}.",
        "auto_fixable": False,
    }

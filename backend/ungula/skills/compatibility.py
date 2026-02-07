"""
Platform compatibility analysis and LLM-powered conversion for skills.

Scans SKILL.md content for platform-specific indicators (apt, xdotool,
systemctl, etc.) and uses LLM to convert skills between platforms.
"""

import logging
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import frontmatter

from ..llm.base import CompletionRequest, CompletionResponse, Message, MessageRole

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Severity level for compatibility issues."""

    CRITICAL = "critical"  # Fundamentally incompatible architecture (X11, systemd)
    HIGH = "high"  # Package/service managers (apt -> brew)
    MEDIUM = "medium"  # CLI tools with known equivalents (xdotool -> cliclick)
    LOW = "low"  # Path conventions (/usr/bin -> /usr/local/bin)


@dataclass
class CompatibilityIssue:
    """A single platform compatibility issue found in skill content."""

    pattern: str
    category: str
    severity: Severity
    description: str
    source_platform: str
    file_path: str | None = None
    line_number: int | None = None


@dataclass
class CompatibilityReport:
    """Full compatibility analysis result for a skill."""

    compatible: bool
    current_platform: str
    detected_platforms: list[str] = field(default_factory=list)
    primary_platform: str | None = None
    issues: list[CompatibilityIssue] = field(default_factory=list)
    confidence: float = 0.0
    convertible: bool = True
    summary: str = ""
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0


# Platform-specific indicators: (regex, category, severity, description)
PLATFORM_INDICATORS: dict[str, list[tuple[str, str, Severity, str]]] = {
    "linux": [
        # Critical -- architecture dependencies
        (r"\bXvfb\b", "x11_display", Severity.CRITICAL, "X11 virtual framebuffer"),
        (r"\bxdotool\b", "x11_tools", Severity.CRITICAL, "X11 automation tool"),
        (r"\bxdpyinfo\b", "x11_tools", Severity.CRITICAL, "X11 display info"),
        (r"\bxset\b", "x11_settings", Severity.CRITICAL, "X11 settings tool"),
        (r"\bDISPLAY=:\d+", "x11_display", Severity.CRITICAL, "X11 display variable"),
        (r"\bsystemctl\b", "init_system", Severity.CRITICAL, "systemd service manager"),
        (r"\bsystemd\b", "init_system", Severity.CRITICAL, "systemd init system"),
        (r"\bjournalctl\b", "init_system", Severity.CRITICAL, "systemd journal"),
        (r"/proc/", "proc_fs", Severity.CRITICAL, "/proc filesystem"),
        (r"/sys/", "sys_fs", Severity.CRITICAL, "/sys filesystem"),
        # High -- package/service management
        (r"\bapt(?:-get)?\s+install\b", "package_manager", Severity.HIGH, "APT package manager"),
        (r"\bdpkg\b", "package_manager", Severity.HIGH, "Debian package manager"),
        (r"\byum\s+install\b", "package_manager", Severity.HIGH, "YUM package manager"),
        (r"\bdnf\s+install\b", "package_manager", Severity.HIGH, "DNF package manager"),
        (r"\bpacman\s+-S\b", "package_manager", Severity.HIGH, "Pacman package manager"),
        (r"\bsnap\s+install\b", "package_manager", Severity.HIGH, "Snap package manager"),
        (r"\bflatpak\b", "package_manager", Severity.HIGH, "Flatpak package manager"),
        (r"\.deb\b", "package_format", Severity.HIGH, ".deb package format"),
        # Medium -- tools with known equivalents
        (r"\bscrot\b", "screenshot_tool", Severity.MEDIUM, "Linux screenshot tool (macOS: screencapture)"),
        (r"\bxclip\b", "clipboard_tool", Severity.MEDIUM, "X11 clipboard (macOS: pbcopy/pbpaste)"),
        (r"\bx11vnc\b", "vnc_server", Severity.MEDIUM, "X11 VNC server"),
        (r"\bxfce\b", "desktop_env", Severity.MEDIUM, "XFCE desktop environment"),
        (r"\bgnome-terminal\b", "terminal", Severity.MEDIUM, "GNOME terminal"),
        (r"\bxfwm4\b", "window_manager", Severity.MEDIUM, "XFCE window manager"),
        (r"\bxsetroot\b", "x11_tools", Severity.MEDIUM, "X11 root window settings"),
        # Low -- path conventions
        (r"/usr/bin/", "path_convention", Severity.LOW, "Linux binary path"),
        (r"/etc/", "path_convention", Severity.LOW, "Linux config path"),
        (r"/usr/share/", "path_convention", Severity.LOW, "Linux share path"),
    ],
    "darwin": [
        (r"\bbrew\s+install\b", "package_manager", Severity.HIGH, "Homebrew package manager"),
        (r"\bosascript\b", "automation", Severity.CRITICAL, "AppleScript/osascript"),
        (r"\bpbcopy\b", "clipboard", Severity.MEDIUM, "macOS clipboard copy"),
        (r"\bpbpaste\b", "clipboard", Severity.MEDIUM, "macOS clipboard paste"),
        (r"\bscreencapture\b", "screenshot_tool", Severity.MEDIUM, "macOS screenshot tool"),
        (r"\blaunchctl\b", "init_system", Severity.CRITICAL, "macOS launch daemon manager"),
        (r"\bdefaults\s+(?:read|write)\b", "preferences", Severity.HIGH, "macOS defaults system"),
        (r"/Applications/", "path_convention", Severity.LOW, "macOS application path"),
        (r"\.app\b", "app_bundle", Severity.LOW, "macOS .app bundle"),
        (r"\.dmg\b", "disk_image", Severity.LOW, "macOS disk image"),
        (r"\bopen\s+-a\b", "app_launcher", Severity.MEDIUM, "macOS app launcher"),
        (r"\bhdiutil\b", "disk_util", Severity.MEDIUM, "macOS disk image utility"),
        (r"\bdiskutil\b", "disk_util", Severity.MEDIUM, "macOS disk utility"),
    ],
    "win32": [
        (r"\bchoco(?:latey)?\s+install\b", "package_manager", Severity.HIGH, "Chocolatey package manager"),
        (r"\bwinget\s+install\b", "package_manager", Severity.HIGH, "Windows Package Manager"),
        (r"\bpowershell\b", "shell", Severity.CRITICAL, "PowerShell"),
        (r"\.exe\b", "executable", Severity.LOW, "Windows executable"),
        (r"%APPDATA%", "path_convention", Severity.MEDIUM, "Windows AppData path"),
        (r"\bregedit\b", "registry", Severity.CRITICAL, "Windows Registry editor"),
        (r"\bwmic\b", "management", Severity.HIGH, "Windows Management Instrumentation"),
        (r"\bcmd\.exe\b", "shell", Severity.CRITICAL, "Windows command prompt"),
        (r"\bmsiexec\b", "installer", Severity.HIGH, "Windows Installer"),
    ],
}

# File extensions worth scanning for platform indicators
SCANNABLE_EXTENSIONS = {".md", ".sh", ".bash", ".py", ".yml", ".yaml", ".conf", ".cfg", ".txt"}

PLATFORM_NAMES = {
    "darwin": "macOS",
    "linux": "Linux",
    "win32": "Windows",
}

# Conversion hints per platform pair
CONVERSION_HINTS: dict[tuple[str, str], str] = {
    ("linux", "darwin"): """
Common substitutions (use judgment, not all apply):
- apt/apt-get install -> brew install
- systemctl -> launchctl (or brew services)
- systemd service files -> launchd plist files
- xdotool -> cliclick (for mouse/keyboard) or AppleScript via osascript
- Xvfb -> not needed on macOS (native display server)
- scrot -> screencapture (built-in)
- xclip -> pbcopy/pbpaste
- /usr/bin/ -> /usr/local/bin/ or /opt/homebrew/bin/
- /etc/ -> /usr/local/etc/ or ~/Library/
- DISPLAY=:99 -> not applicable on macOS (Quartz handles display)
- x11vnc -> macOS Screen Sharing (built-in VNC)
- xfce4-terminal -> Terminal.app or iTerm2
- google-chrome --no-sandbox -> open -a "Google Chrome"
- sudo dpkg -i -> brew install --cask or manual .dmg install
- base64 -w0 -> base64 (macOS base64 does not wrap by default)
""",
    ("linux", "win32"): """
Common substitutions:
- apt/apt-get -> choco install or winget install
- systemctl -> sc.exe (Windows services) or Task Scheduler
- bash scripts -> PowerShell scripts
- /usr/bin/ -> C:\\Program Files\\
- /tmp/ -> %TEMP%
- xdotool -> AutoHotkey or pyautogui
""",
    ("darwin", "linux"): """
Common substitutions:
- brew install -> apt install
- osascript -> xdotool or xdg-open
- pbcopy/pbpaste -> xclip
- screencapture -> scrot or gnome-screenshot
- launchctl -> systemctl
- open -a -> xdg-open
- /Applications/ -> /usr/bin/ or /usr/local/bin/
""",
}


def analyze_skill_content(
    content: str,
    current_platform: str | None = None,
    file_path: str | None = None,
) -> tuple[list[CompatibilityIssue], dict[str, int]]:
    """Scan text content for platform-specific indicators.

    Returns:
        Tuple of (issues_found, platform_hit_counts).
    """
    if current_platform is None:
        current_platform = sys.platform

    issues: list[CompatibilityIssue] = []
    platform_hits: dict[str, int] = {}

    lines = content.split("\n")

    for platform, indicators in PLATFORM_INDICATORS.items():
        if platform == current_platform:
            continue  # Skip indicators for the current platform (those are fine)

        for pattern, category, severity, description in indicators:
            for line_num, line in enumerate(lines, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    platform_hits[platform] = platform_hits.get(platform, 0) + 1
                    issues.append(
                        CompatibilityIssue(
                            pattern=pattern,
                            category=category,
                            severity=severity,
                            description=description,
                            source_platform=platform,
                            file_path=file_path,
                            line_number=line_num,
                        )
                    )

    return issues, platform_hits


def analyze_skill_compatibility(
    skill_md_content: str,
    supplementary_files: dict[str, str] | None = None,
    current_platform: str | None = None,
) -> CompatibilityReport:
    """Analyze a skill's content for platform compatibility.

    Args:
        skill_md_content: Full content of SKILL.md (frontmatter + body).
        supplementary_files: Dict of {filename: content} for other scannable files.
        current_platform: Override current platform (for testing).

    Returns:
        CompatibilityReport with full analysis results.
    """
    if current_platform is None:
        current_platform = sys.platform

    all_issues: list[CompatibilityIssue] = []
    total_platform_hits: dict[str, int] = {}

    # Parse frontmatter to check declared platform
    try:
        post = frontmatter.loads(skill_md_content)
        declared_platforms = post.metadata.get("requires", {}).get(
            "platform", []
        ) or post.metadata.get("metadata", {}).get("openclaw", {}).get("os", [])
    except Exception:
        declared_platforms = []

    # If frontmatter explicitly declares platform incompatibility, report immediately
    if declared_platforms and current_platform not in declared_platforms:
        return CompatibilityReport(
            compatible=False,
            current_platform=current_platform,
            detected_platforms=declared_platforms,
            primary_platform=declared_platforms[0] if declared_platforms else None,
            confidence=1.0,
            summary=f"Skill explicitly requires {declared_platforms}, current platform is {_platform_name(current_platform)}",
            issues=[
                CompatibilityIssue(
                    pattern="requires.platform",
                    category="frontmatter_declaration",
                    severity=Severity.CRITICAL,
                    description=f"Frontmatter declares platform: {declared_platforms}",
                    source_platform=declared_platforms[0],
                )
            ],
            critical_count=1,
        )

    # Scan SKILL.md body
    body_issues, body_hits = analyze_skill_content(
        skill_md_content, current_platform, file_path="SKILL.md"
    )
    all_issues.extend(body_issues)
    for plat, count in body_hits.items():
        total_platform_hits[plat] = total_platform_hits.get(plat, 0) + count

    # Scan supplementary files
    if supplementary_files:
        for filename, file_content in supplementary_files.items():
            ext = Path(filename).suffix.lower()
            if ext in SCANNABLE_EXTENSIONS:
                file_issues, file_hits = analyze_skill_content(
                    file_content, current_platform, file_path=filename
                )
                all_issues.extend(file_issues)
                for plat, count in file_hits.items():
                    total_platform_hits[plat] = total_platform_hits.get(plat, 0) + count

    # No indicators found
    if not total_platform_hits:
        return CompatibilityReport(
            compatible=True,
            current_platform=current_platform,
            detected_platforms=[],
            primary_platform=None,
            confidence=0.3,
            summary="No platform-specific content detected",
        )

    primary_platform = max(total_platform_hits, key=total_platform_hits.get)
    detected_platforms = list(total_platform_hits.keys())

    # Deduplicate issues by (category, source_platform) keeping highest severity
    seen: dict[tuple[str, str], CompatibilityIssue] = {}
    severity_order = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
    for issue in all_issues:
        key = (issue.category, issue.source_platform)
        if key not in seen or severity_order[issue.severity] < severity_order[seen[key].severity]:
            seen[key] = issue
    deduped_issues = list(seen.values())

    # Count severities
    critical = sum(1 for i in deduped_issues if i.severity == Severity.CRITICAL)
    high = sum(1 for i in deduped_issues if i.severity == Severity.HIGH)
    medium = sum(1 for i in deduped_issues if i.severity == Severity.MEDIUM)
    low = sum(1 for i in deduped_issues if i.severity == Severity.LOW)

    # Calculate confidence based on number and severity of hits
    total_hits = sum(total_platform_hits.values())
    confidence = min(1.0, 0.3 + (total_hits * 0.05) + (critical * 0.15) + (high * 0.1))

    # Determine if LLM conversion is feasible (more than 5 critical = likely infeasible)
    convertible = critical <= 5

    # Build summary
    compatible = critical == 0 and high == 0
    source_name = _platform_name(primary_platform)
    target_name = _platform_name(current_platform)
    if critical > 0:
        summary = f"Skill targets {source_name}; {critical} critical incompatibilities with {target_name}"
    elif high > 0:
        summary = f"Skill targets {source_name}; {high} significant issues for {target_name}"
    else:
        summary = f"Minor {source_name}-specific references; likely works on {target_name}"

    return CompatibilityReport(
        compatible=compatible,
        current_platform=current_platform,
        detected_platforms=detected_platforms,
        primary_platform=primary_platform,
        issues=deduped_issues,
        confidence=confidence,
        convertible=convertible,
        summary=summary,
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        low_count=low,
    )


def _platform_name(platform: str) -> str:
    """Human-readable platform name."""
    return PLATFORM_NAMES.get(platform, platform)


def _build_conversion_messages(
    skill_content: str,
    source_platform: str,
    target_platform: str,
    issues: list[CompatibilityIssue],
) -> list[Message]:
    """Build the LLM prompt messages for skill conversion."""
    source_name = _platform_name(source_platform)
    target_name = _platform_name(target_platform)

    hints_key = (source_platform, target_platform)
    hints = CONVERSION_HINTS.get(hints_key, "No specific substitution hints available.")

    issue_summary = "\n".join(
        f"- [{i.severity.value.upper()}] {i.description} (category: {i.category})"
        for i in issues
    )

    system_prompt = f"""You are an expert system administrator and technical writer. Your task is to convert a SKILL.md file from {source_name} to {target_name}.

A SKILL.md file defines an AI agent skill. It has YAML frontmatter (delimited by ---) followed by a markdown body with instructions, commands, and configuration.

RULES:
1. Preserve the YAML frontmatter structure exactly. Only modify values that need platform adaptation.
2. Add or update `requires.platform` in the frontmatter to include `{target_platform}`.
3. Convert all {source_name}-specific commands, paths, tools, and instructions to {target_name} equivalents.
4. Where an exact equivalent does not exist, clearly note this with a markdown callout (> **Note**: ...) explaining the limitation and any workaround.
5. If a section is fundamentally impossible to convert (e.g., X11 virtual display on macOS), replace it with the closest {target_name} approach and note the differences.
6. Preserve the document structure, headings, and tables.
7. Do NOT add explanatory preamble or postscript. Return ONLY the converted SKILL.md content.
8. If the conversion is fundamentally infeasible (the skill cannot work on {target_name} at all), respond with exactly: CONVERSION_INFEASIBLE: <reason>

{hints}"""

    user_prompt = f"""Convert this SKILL.md from {source_name} to {target_name}.

Detected compatibility issues:
{issue_summary}

Original SKILL.md content:
```
{skill_content}
```

Return the complete converted SKILL.md file (frontmatter + body). Nothing else."""

    return [
        Message(role=MessageRole.SYSTEM, content=system_prompt),
        Message(role=MessageRole.USER, content=user_prompt),
    ]


async def convert_skill_content(
    skill_content: str,
    source_platform: str,
    target_platform: str,
    issues: list[CompatibilityIssue],
    provider_registry: Any,
) -> tuple[str | None, str | None]:
    """Convert a SKILL.md from one platform to another using LLM.

    Args:
        skill_content: Original SKILL.md content.
        source_platform: Detected source platform (e.g. "linux").
        target_platform: Target platform (e.g. "darwin").
        issues: Compatibility issues found during analysis.
        provider_registry: LLM ProviderRegistry for making completion requests.

    Returns:
        Tuple of (converted_content, error_message).
        If conversion succeeds, error_message is None.
        If conversion fails/is infeasible, converted_content is None.
    """
    messages = _build_conversion_messages(skill_content, source_platform, target_platform, issues)

    request = CompletionRequest(
        messages=messages,
        temperature=0.3,
        max_tokens=8192,
    )

    try:
        response: CompletionResponse = await provider_registry.complete(request)
    except Exception as e:
        logger.warning("LLM conversion failed: %s", e)
        return None, f"LLM conversion failed: {e}"

    content = response.content
    if not content:
        return None, "LLM returned empty response"

    # Check for infeasibility response
    if content.strip().startswith("CONVERSION_INFEASIBLE:"):
        reason = content.strip().split(":", 1)[1].strip()
        return None, f"Conversion infeasible: {reason}"

    # Strip markdown code fences if present
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = lines[1:]  # Remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # Remove closing fence
        content = "\n".join(lines)

    # Validate that result looks like a SKILL.md
    if not content.strip().startswith("---"):
        return None, "LLM output does not start with YAML frontmatter delimiter"

    return content, None


# Extensions to convert for script files
CONVERTIBLE_SCRIPT_EXTENSIONS = {".sh", ".bash", ".py"}


def _build_script_conversion_messages(
    script_content: str,
    filename: str,
    source_platform: str,
    target_platform: str,
) -> list[Message]:
    """Build LLM prompt messages for converting a single script file."""
    source_name = _platform_name(source_platform)
    target_name = _platform_name(target_platform)

    hints_key = (source_platform, target_platform)
    hints = CONVERSION_HINTS.get(hints_key, "")

    system_prompt = f"""You are an expert system administrator. Convert this shell script from {source_name} to {target_name}.

RULES:
1. Replace all {source_name}-specific commands and tools with {target_name} equivalents.
2. Preserve the script's purpose and behavior.
3. Keep the same interface (arguments, output format).
4. Add comments where behavior differs significantly.
5. Return ONLY the converted script. No explanation or markdown fences.
6. If a tool has no equivalent, add a comment explaining the gap and a reasonable fallback.

{hints}"""

    user_prompt = f"""Convert this script ({filename}) from {source_name} to {target_name}:

```
{script_content}
```

Return only the converted script content."""

    return [
        Message(role=MessageRole.SYSTEM, content=system_prompt),
        Message(role=MessageRole.USER, content=user_prompt),
    ]


async def convert_script_file(
    script_content: str,
    filename: str,
    source_platform: str,
    target_platform: str,
    provider_registry: Any,
) -> tuple[str | None, str | None]:
    """Convert a single script file from one platform to another using LLM.

    Returns:
        Tuple of (converted_content, error_message).
    """
    messages = _build_script_conversion_messages(
        script_content, filename, source_platform, target_platform
    )

    request = CompletionRequest(
        messages=messages,
        temperature=0.2,
        max_tokens=4096,
    )

    try:
        response: CompletionResponse = await provider_registry.complete(request)
    except Exception as e:
        logger.warning("Script conversion failed for %s: %s", filename, e)
        return None, f"LLM conversion failed for {filename}: {e}"

    content = response.content
    if not content:
        return None, f"LLM returned empty response for {filename}"

    # Strip markdown code fences if present
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)

    return content, None

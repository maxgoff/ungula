"""
Security threat analysis for skills.

Scans SKILL.md, shell scripts, Python modules, and markdown content
for indicators of malicious behavior: obfuscation, credential theft,
remote code execution, exfiltration, persistence, and social engineering.

Inspired by real-world attacks documented against the OpenClaw ecosystem
(see: 1password.com/blog/from-magic-to-malware).
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from .compatibility import Severity

logger = logging.getLogger(__name__)


class ThreatCategory(str, Enum):
    """Category of security threat detected in a skill."""

    OBFUSCATION = "obfuscation"
    REMOTE_EXECUTION = "remote_execution"
    CREDENTIAL_ACCESS = "credential_access"
    ANTI_DETECTION = "anti_detection"
    EXFILTRATION = "exfiltration"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    PERSISTENCE = "persistence"
    SUSPICIOUS_NETWORK = "suspicious_network"
    PYTHON_RISKS = "python_risks"
    SUSPICIOUS_LINKS = "suspicious_links"


@dataclass
class SecurityThreat:
    """A single security threat found in skill content."""

    pattern: str
    category: ThreatCategory
    severity: Severity
    description: str
    evidence: str
    file_path: str | None = None
    line_number: int | None = None
    recommendation: str = ""


@dataclass
class SecurityReport:
    """Full security analysis result for a skill."""

    safe: bool
    blocked: bool
    threats: list[SecurityThreat] = field(default_factory=list)
    summary: str = ""
    risk_score: float = 0.0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    scanned_files: list[str] = field(default_factory=list)
    scan_timestamp: str = ""


# ---------------------------------------------------------------------------
# Threat pattern definitions
# ---------------------------------------------------------------------------
# Each entry: (regex_pattern, severity, description, recommendation)

THREAT_PATTERNS: dict[ThreatCategory, list[tuple[str, Severity, str, str]]] = {
    # ── Obfuscation ────────────────────────────────────────────────────────
    ThreatCategory.OBFUSCATION: [
        (
            r"base64\s+(?:-d|--decode)\s*.*\|\s*(?:bash|sh|zsh|python|perl|ruby)",
            Severity.CRITICAL,
            "Base64-encoded payload piped to shell execution",
            "Never execute decoded content blindly. Review the decoded content first.",
        ),
        (
            r"base64\s+(?:-d|--decode)\s*.*\|\s*eval",
            Severity.CRITICAL,
            "Base64-encoded payload piped to eval",
            "Classic obfuscation technique for hiding malicious commands.",
        ),
        (
            r"echo\s+-[en]+\s+['\"]?(?:\\x[0-9a-f]{2}|\\[0-7]{3}){4,}",
            Severity.CRITICAL,
            "Hex/octal-encoded string in echo (likely obfuscated payload)",
            "Decode the string manually to inspect its contents.",
        ),
        (
            r"printf\s+['\"](?:\\x[0-9a-f]{2}){4,}['\"].*\|\s*(?:bash|sh)",
            Severity.CRITICAL,
            "Printf hex payload piped to shell",
            "Obfuscated command execution. Decode and review.",
        ),
        (
            r"xxd\s+-r\s*.*\|\s*(?:bash|sh|python)",
            Severity.CRITICAL,
            "Hex-decoded content piped to execution via xxd",
            "Decode and review the hex content before allowing execution.",
        ),
        (
            r"\beval\s+[\"'`$]",
            Severity.HIGH,
            "eval with dynamic content (potential code injection)",
            "Replace eval with direct command invocation where possible.",
        ),
        (
            r"openssl\s+(?:enc|base64)\s+-d\s*.*\|\s*(?:bash|sh)",
            Severity.CRITICAL,
            "OpenSSL-decoded payload piped to shell execution",
            "Obfuscation via openssl. Decode and inspect manually.",
        ),
    ],
    # ── Remote execution ───────────────────────────────────────────────────
    ThreatCategory.REMOTE_EXECUTION: [
        (
            r"curl\s+[^\|]*\|\s*(?:sudo\s+)?(?:bash|sh|zsh|python|perl|ruby)",
            Severity.CRITICAL,
            "Remote script downloaded and piped directly to shell (curl|bash)",
            "Download the script first, review it, then execute if safe.",
        ),
        (
            r"wget\s+[^\|]*(?:-O\s*-|-q\s*-O\s*-)?\s*\|\s*(?:sudo\s+)?(?:bash|sh|zsh)",
            Severity.CRITICAL,
            "Remote script downloaded and piped directly to shell (wget|sh)",
            "Download the script first, review it, then execute if safe.",
        ),
        (
            r"python[3]?\s+-c\s+['\"].*(?:urllib|requests|urlopen|urlretrieve)",
            Severity.CRITICAL,
            "Python one-liner fetching and executing remote content",
            "Review the remote URL and downloaded content before execution.",
        ),
        (
            r"pip[3]?\s+install\s+(?:--index-url|--extra-index-url|-i)\s+(?!https://pypi\.org)",
            Severity.CRITICAL,
            "pip install from non-PyPI package index",
            "Only install from trusted package indexes (pypi.org).",
        ),
        (
            r"pip[3]?\s+install\s+(?:git\+)?https?://(?!.*pypi\.org)",
            Severity.HIGH,
            "pip install from arbitrary URL or git repo",
            "Verify the source repository before installing.",
        ),
        (
            r"npm\s+install\s+https?://",
            Severity.HIGH,
            "npm install from arbitrary URL",
            "Verify the source before installing.",
        ),
        (
            r"(?:curl|wget)\s+.*https?://[^\s]+\.(?:sh|py|pl|rb)\b",
            Severity.MEDIUM,
            "Downloading executable script from remote URL",
            "Review the downloaded script before execution.",
        ),
    ],
    # ── Credential access ──────────────────────────────────────────────────
    ThreatCategory.CREDENTIAL_ACCESS: [
        (
            r"~/\.ssh/|\.ssh/id_|\.ssh/known_hosts|\.ssh/authorized_keys|\.ssh/config",
            Severity.CRITICAL,
            "Accessing SSH keys or configuration",
            "Skills should never need access to SSH credentials.",
        ),
        (
            r"~/\.aws/|\.aws/credentials|\.aws/config|AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID",
            Severity.CRITICAL,
            "Accessing AWS credentials or configuration",
            "Skills should never need access to cloud credentials.",
        ),
        (
            r"~/\.gnupg/|\.gnupg/|gpg\s+--export",
            Severity.CRITICAL,
            "Accessing GPG/PGP keyring",
            "Skills should never need access to cryptographic keys.",
        ),
        (
            r"(?:Chrome|Firefox|Safari|Brave|Edge)/(?:Default|Profile|Cookies|Login\s*Data|History)",
            Severity.CRITICAL,
            "Accessing browser profile data (passwords, cookies, history)",
            "This is a common infostealing technique.",
        ),
        (
            r"\bsecurity\s+(?:find-generic-password|find-internet-password|dump-keychain)",
            Severity.CRITICAL,
            "Accessing macOS Keychain (credential extraction)",
            "Skills must never access the system keychain.",
        ),
        (
            r"cat\s+.*\.env\b|source\s+.*\.env\b",
            Severity.HIGH,
            "Reading .env files (may contain secrets)",
            "Avoid accessing .env files from skills.",
        ),
        (
            r"(?:^|\s)(?:env|printenv)\s*$|(?:^|\s)(?:env|printenv)\s*\||\bexport\s+-p\b",
            Severity.HIGH,
            "Dumping environment variables (may expose secrets)",
            "Avoid dumping all environment variables.",
        ),
        (
            r"defaults\s+read\s+.*(?:password|credential|token|secret|key)",
            Severity.HIGH,
            "Reading macOS defaults that may contain credentials",
            "Review which defaults are being read.",
        ),
        (
            r"(?:cat|less|more|head|tail)\s+/etc/(?:shadow|passwd)",
            Severity.CRITICAL,
            "Reading system password files",
            "Skills should never access system authentication files.",
        ),
    ],
    # ── Anti-detection ─────────────────────────────────────────────────────
    ThreatCategory.ANTI_DETECTION: [
        (
            r"xattr\s+-[rd]\s+com\.apple\.quarantine",
            Severity.CRITICAL,
            "Removing macOS quarantine flag (Gatekeeper bypass)",
            "This disables macOS security warnings on downloaded files.",
        ),
        (
            r"spctl\s+--master-disable",
            Severity.CRITICAL,
            "Disabling macOS Gatekeeper entirely",
            "This removes all code signing verification.",
        ),
        (
            r"csrutil\s+disable",
            Severity.CRITICAL,
            "Attempting to disable System Integrity Protection",
            "SIP protects critical system files. Never disable it.",
        ),
        (
            r"history\s+-c|>.*\.bash_history|>.*\.zsh_history|unset\s+HISTFILE",
            Severity.HIGH,
            "Clearing or disabling shell history (anti-forensics)",
            "Legitimate tools do not clear command history.",
        ),
        (
            r"(?:copy|paste)\s+(?:this|the\s+following)\s+(?:into|in)\s+(?:terminal|command|shell|prompt)",
            Severity.HIGH,
            "ClickFix-style social engineering (instructing user to paste into terminal)",
            "This social engineering technique tricks users into running malicious commands.",
        ),
    ],
    # ── Exfiltration ───────────────────────────────────────────────────────
    ThreatCategory.EXFILTRATION: [
        (
            r"(?:cat|less|head)\s+.*(?:\.ssh|\.aws|\.gnupg|\.env).*\|.*(?:curl|wget|nc|ncat)",
            Severity.CRITICAL,
            "Piping sensitive files to network commands",
            "This is direct credential exfiltration.",
        ),
        (
            r"\b(?:nc|ncat|netcat)\s+.*(?:-e|-c)\s+/bin/(?:bash|sh)",
            Severity.CRITICAL,
            "Netcat reverse shell",
            "Netcat with shell execution is a reverse shell.",
        ),
        (
            r"curl\s+.*(?:-X\s*POST|-d\s|--data\s|--data-binary).*https?://",
            Severity.HIGH,
            "HTTP POST request sending data to remote server",
            "Verify what data is being sent and to which server.",
        ),
        (
            r"wget\s+.*--post-(?:data|file)\s",
            Severity.HIGH,
            "HTTP POST via wget sending data to remote server",
            "Verify what data is being sent and to which server.",
        ),
        (
            r"\bdig\s+.*TXT\s|nslookup\s+.*-type=TXT|(?:base64|xxd).*\|\s*(?:dig|nslookup|host)\b",
            Severity.HIGH,
            "Possible DNS tunneling for data exfiltration",
            "DNS can be used to exfiltrate data covertly.",
        ),
    ],
    # ── Privilege escalation ───────────────────────────────────────────────
    ThreatCategory.PRIVILEGE_ESCALATION: [
        (
            r"\bsudo\s+",
            Severity.HIGH,
            "Command requires sudo (elevated privileges)",
            "Skills should not require root access.",
        ),
        (
            r"\bdoas\s+",
            Severity.HIGH,
            "Command requires doas (elevated privileges)",
            "Skills should not require root access.",
        ),
        (
            r"\bpkexec\s+",
            Severity.HIGH,
            "Command uses pkexec (polkit privilege escalation)",
            "Skills should not require privilege escalation.",
        ),
        (
            r"chmod\s+[ugo]*\+s\s|chmod\s+[0-7]*[4-7][0-7]{2}\s",
            Severity.CRITICAL,
            "Setting setuid/setgid bit on files",
            "Setuid allows programs to run with elevated privileges.",
        ),
        (
            r"(?:cp|mv|install|tee)\s+.*(?:/usr/(?:local/)?(?:bin|sbin|lib)|/etc/|/System/|/Library/)",
            Severity.HIGH,
            "Writing to system directories",
            "Skills should not modify system files.",
        ),
    ],
    # ── Persistence ────────────────────────────────────────────────────────
    ThreatCategory.PERSISTENCE: [
        (
            r"~/Library/LaunchAgents|/Library/Launch(?:Agents|Daemons)",
            Severity.HIGH,
            "Creating macOS LaunchAgent/Daemon (persistence mechanism)",
            "This creates a process that survives reboots.",
        ),
        (
            r"\bcrontab\b|>>?\s*/etc/cron|/var/spool/cron",
            Severity.HIGH,
            "Modifying cron jobs (scheduled task persistence)",
            "Review what scheduled tasks are being created.",
        ),
        (
            r">>?\s*~/?\.\b(?:bash_profile|bashrc|zshrc|zprofile|profile|login)\b",
            Severity.HIGH,
            "Modifying shell profile files (login persistence)",
            "Shell profile modifications execute on every terminal session.",
        ),
        (
            r"/etc/systemd/system/.*\.service|systemctl\s+enable",
            Severity.HIGH,
            "Creating or enabling systemd service (persistence)",
            "This creates a service that survives reboots.",
        ),
        (
            r"schtasks\s+/create",
            Severity.HIGH,
            "Creating Windows scheduled task (persistence)",
            "Review what scheduled task is being created.",
        ),
    ],
    # ── Suspicious network ─────────────────────────────────────────────────
    ThreatCategory.SUSPICIOUS_NETWORK: [
        (
            r"(?:curl|wget|nc|ncat)\s+(?:https?://)?(?!(?:127\.0\.0\.1|0\.0\.0\.0|localhost))\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
            Severity.MEDIUM,
            "Network connection to raw IP address (not domain name)",
            "Connections to raw IPs are harder to audit than named hosts.",
        ),
        (
            r"\.onion\b",
            Severity.HIGH,
            "Reference to .onion (Tor hidden service) address",
            "Tor hidden services are associated with anonymized traffic.",
        ),
        (
            r"\birc[s]?://|:6667\b|:6697\b",
            Severity.MEDIUM,
            "IRC connection (potential C2 channel)",
            "IRC is sometimes used as a command-and-control channel.",
        ),
    ],
    # ── Python-specific risks ──────────────────────────────────────────────
    ThreatCategory.PYTHON_RISKS: [
        (
            r"subprocess\.(?:call|run|Popen)\s*\(.*shell\s*=\s*True",
            Severity.HIGH,
            "subprocess with shell=True (command injection risk)",
            "Use shell=False and pass arguments as a list.",
        ),
        (
            r"\bos\.system\s*\(",
            Severity.HIGH,
            "os.system() call (unsandboxed command execution)",
            "Use subprocess with shell=False instead.",
        ),
        (
            r"\bos\.popen\s*\(",
            Severity.HIGH,
            "os.popen() call (unsandboxed command execution)",
            "Use subprocess with shell=False instead.",
        ),
        (
            r"\b(?:exec|eval)\s*\(",
            Severity.HIGH,
            "exec() or eval() call (arbitrary code execution)",
            "Avoid exec/eval; use explicit function calls.",
        ),
        (
            r"\bcompile\s*\(.*['\"]exec['\"]",
            Severity.HIGH,
            "compile() with exec mode (dynamic code generation)",
            "Dynamic code compilation can hide malicious logic.",
        ),
        (
            r"\b__import__\s*\(",
            Severity.MEDIUM,
            "Dynamic import via __import__()",
            "Use explicit imports for transparency.",
        ),
        (
            r"\bctypes\b.*(?:CDLL|windll|cdll|WinDLL)",
            Severity.HIGH,
            "ctypes FFI usage (native code execution)",
            "Native code execution bypasses Python safety mechanisms.",
        ),
        (
            r"\b(?:requests|httpx|urllib|urllib3|aiohttp|socket)\s*\.\s*"
            r"(?:get|post|put|patch|delete|request|urlopen|connect|create_connection)",
            Severity.MEDIUM,
            "Network operations in tool code",
            "Verify that network calls are expected for this tool's purpose.",
        ),
        (
            r"importlib\.(?:import_module|util\.spec_from_file_location)",
            Severity.MEDIUM,
            "Dynamic module loading via importlib",
            "Dynamic imports can load arbitrary code.",
        ),
    ],
    # ── Suspicious links ───────────────────────────────────────────────────
    ThreatCategory.SUSPICIOUS_LINKS: [
        (
            r"\[.*\]\(https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
            Severity.MEDIUM,
            "Markdown link pointing to raw IP address",
            "Links to raw IPs are harder to verify than named domains.",
        ),
        (
            r"https?://[^\s\)]+\.(?:exe|msi|dmg|pkg|deb|rpm|AppImage|run|bin)\b",
            Severity.MEDIUM,
            "Link to downloadable executable file",
            "Verify the source of executable downloads.",
        ),
        (
            r"https?://[^\s]*(?:%[0-9a-fA-F]{2}){5,}",
            Severity.MEDIUM,
            "URL with heavy percent-encoding (potentially obfuscated)",
            "Decode the URL to inspect its true destination.",
        ),
        (
            r"https?://(?:bit\.ly|tinyurl|t\.co|goo\.gl|is\.gd|v\.gd|rb\.gy|cutt\.ly)/",
            Severity.MEDIUM,
            "URL shortener hiding the actual destination",
            "Resolve the shortened URL to verify its target.",
        ),
    ],
}

# ---------------------------------------------------------------------------
# File-type → category mapping
# ---------------------------------------------------------------------------

_SHELL_CATEGORIES: list[ThreatCategory] = [
    ThreatCategory.OBFUSCATION,
    ThreatCategory.REMOTE_EXECUTION,
    ThreatCategory.CREDENTIAL_ACCESS,
    ThreatCategory.ANTI_DETECTION,
    ThreatCategory.EXFILTRATION,
    ThreatCategory.PRIVILEGE_ESCALATION,
    ThreatCategory.PERSISTENCE,
    ThreatCategory.SUSPICIOUS_NETWORK,
]

SCAN_CONFIG: dict[str, list[ThreatCategory]] = {
    ".md": [
        ThreatCategory.OBFUSCATION,
        ThreatCategory.REMOTE_EXECUTION,
        ThreatCategory.CREDENTIAL_ACCESS,
        ThreatCategory.ANTI_DETECTION,
        ThreatCategory.EXFILTRATION,
        ThreatCategory.PRIVILEGE_ESCALATION,
        ThreatCategory.PERSISTENCE,
        ThreatCategory.SUSPICIOUS_NETWORK,
        ThreatCategory.SUSPICIOUS_LINKS,
    ],
    ".sh": _SHELL_CATEGORIES,
    ".bash": _SHELL_CATEGORIES,
    ".py": [
        ThreatCategory.PYTHON_RISKS,
        ThreatCategory.CREDENTIAL_ACCESS,
        ThreatCategory.SUSPICIOUS_NETWORK,
        ThreatCategory.EXFILTRATION,
    ],
    ".yml": [ThreatCategory.SUSPICIOUS_LINKS, ThreatCategory.REMOTE_EXECUTION],
    ".yaml": [ThreatCategory.SUSPICIOUS_LINKS, ThreatCategory.REMOTE_EXECUTION],
}

DEFAULT_CATEGORIES: list[ThreatCategory] = [
    ThreatCategory.OBFUSCATION,
    ThreatCategory.REMOTE_EXECUTION,
    ThreatCategory.CREDENTIAL_ACCESS,
    ThreatCategory.SUSPICIOUS_LINKS,
]

# Extensions worth scanning (text-based files)
SCANNABLE_EXTENSIONS = {".md", ".sh", ".bash", ".py", ".yml", ".yaml", ".conf", ".cfg", ".txt", ".json"}


# ---------------------------------------------------------------------------
# Scan functions
# ---------------------------------------------------------------------------


def _categories_for_file(file_path: str) -> list[ThreatCategory]:
    """Determine which threat categories to scan based on file extension."""
    ext = Path(file_path).suffix.lower() if file_path else ""
    return SCAN_CONFIG.get(ext, DEFAULT_CATEGORIES)


def scan_content(
    content: str,
    file_path: str | None = None,
    categories: list[ThreatCategory] | None = None,
) -> list[SecurityThreat]:
    """Scan text content for security threats.

    Args:
        content: The text content to scan.
        file_path: Path of the file being scanned (for context).
        categories: Specific threat categories to scan for.
                    If None, determined by file extension.

    Returns:
        List of SecurityThreat instances found.
    """
    if categories is None:
        categories = _categories_for_file(file_path or "")

    threats: list[SecurityThreat] = []
    lines = content.split("\n")

    for category in categories:
        patterns = THREAT_PATTERNS.get(category, [])
        for regex_pattern, severity, description, recommendation in patterns:
            for line_num, line in enumerate(lines, 1):
                if re.search(regex_pattern, line, re.IGNORECASE):
                    evidence = line.strip()[:200]
                    threats.append(
                        SecurityThreat(
                            pattern=regex_pattern,
                            category=category,
                            severity=severity,
                            description=description,
                            evidence=evidence,
                            file_path=file_path,
                            line_number=line_num,
                            recommendation=recommendation,
                        )
                    )

    return threats


def scan_skill_security(
    skill_md_content: str,
    supplementary_files: dict[str, str] | None = None,
) -> SecurityReport:
    """Analyze a skill's content for security threats.

    Args:
        skill_md_content: Full content of SKILL.md.
        supplementary_files: Dict of {filename: content} for other files.

    Returns:
        SecurityReport with full analysis results.
    """
    all_threats: list[SecurityThreat] = []
    scanned_files: list[str] = ["SKILL.md"]

    # Scan SKILL.md
    all_threats.extend(scan_content(skill_md_content, file_path="SKILL.md"))

    # Scan supplementary files
    if supplementary_files:
        for filename, file_content in supplementary_files.items():
            ext = Path(filename).suffix.lower()
            if ext in SCANNABLE_EXTENSIONS:
                scanned_files.append(filename)
                all_threats.extend(scan_content(file_content, file_path=filename))

    # Deduplicate by (pattern, file_path), keeping first occurrence
    seen: set[tuple[str, str | None]] = set()
    deduped: list[SecurityThreat] = []
    for threat in all_threats:
        key = (threat.pattern, threat.file_path)
        if key not in seen:
            seen.add(key)
            deduped.append(threat)

    # Count by severity
    critical = sum(1 for t in deduped if t.severity == Severity.CRITICAL)
    high = sum(1 for t in deduped if t.severity == Severity.HIGH)
    medium = sum(1 for t in deduped if t.severity == Severity.MEDIUM)
    low = sum(1 for t in deduped if t.severity == Severity.LOW)

    # Risk score: 0.0 (safe) to 1.0 (maximum risk)
    risk_score = min(1.0, (critical * 0.25) + (high * 0.15) + (medium * 0.05) + (low * 0.02))

    blocked = critical > 0
    safe = critical == 0 and high == 0

    # Summary
    if not deduped:
        summary = "No security threats detected"
    elif critical > 0:
        summary = f"BLOCKED: {critical} critical security threat{'s' if critical > 1 else ''} detected"
    elif high > 0:
        summary = f"WARNING: {high} high-severity security concern{'s' if high > 1 else ''} detected"
    else:
        summary = f"NOTICE: {medium + low} minor security concern{'s' if (medium + low) > 1 else ''} detected"

    return SecurityReport(
        safe=safe,
        blocked=blocked,
        threats=deduped,
        summary=summary,
        risk_score=risk_score,
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        low_count=low,
        scanned_files=scanned_files,
        scan_timestamp=datetime.now(UTC).isoformat(),
    )


def validate_post_conversion(
    original_report: SecurityReport,
    converted_content: str,
    converted_supplementary: dict[str, str] | None = None,
) -> SecurityReport:
    """Scan converted content and flag NEW threats not present in the original.

    This catches cases where an LLM-powered conversion introduces
    new security risks that were not in the original skill.

    Args:
        original_report: SecurityReport from scanning the original content.
        converted_content: The LLM-converted SKILL.md content.
        converted_supplementary: Any converted supplementary files.

    Returns:
        SecurityReport containing only threats NEW to the converted content.
    """
    converted_report = scan_skill_security(converted_content, converted_supplementary)

    # Build set of original threat signatures
    original_signatures = {(t.pattern, t.category) for t in original_report.threats}

    # Filter to only new threats
    new_threats = [
        t for t in converted_report.threats if (t.pattern, t.category) not in original_signatures
    ]

    if not new_threats:
        return SecurityReport(
            safe=True,
            blocked=False,
            summary="Conversion introduced no new security threats",
            scanned_files=converted_report.scanned_files,
            scan_timestamp=datetime.now(UTC).isoformat(),
        )

    critical = sum(1 for t in new_threats if t.severity == Severity.CRITICAL)
    high = sum(1 for t in new_threats if t.severity == Severity.HIGH)
    medium = sum(1 for t in new_threats if t.severity == Severity.MEDIUM)
    low = sum(1 for t in new_threats if t.severity == Severity.LOW)
    risk_score = min(1.0, (critical * 0.25) + (high * 0.15) + (medium * 0.05) + (low * 0.02))

    return SecurityReport(
        safe=critical == 0 and high == 0,
        blocked=critical > 0,
        threats=new_threats,
        summary=f"Conversion introduced {len(new_threats)} new security concern(s)",
        risk_score=risk_score,
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        low_count=low,
        scanned_files=converted_report.scanned_files,
        scan_timestamp=datetime.now(UTC).isoformat(),
    )

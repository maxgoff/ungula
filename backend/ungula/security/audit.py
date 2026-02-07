"""
Security Auditor for Ungula.

Runs all security checks and produces a structured report.
Supports auto-remediation for fixable issues.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .checks import (
    check_api_keys_in_env,
    check_bind_address,
    check_config_file_permissions,
    check_cors_origins,
    check_debug_mode,
    check_home_dir_permissions,
    check_jwt_secret,
    check_shell_tool,
    check_token_expiry,
)
from .remediate import apply_remediation

logger = logging.getLogger(__name__)


class SecurityAuditor:
    """
    Runs security checks and produces audit reports.

    All checks are non-destructive and read-only by default.
    Auto-remediation must be explicitly requested.
    """

    def __init__(
        self,
        config: Any,
        config_path: Path,
        home_dir: Path,
    ):
        self.config = config
        self.config_path = config_path
        self.home_dir = home_dir
        self._last_report: dict | None = None

    async def run_audit(self) -> dict[str, Any]:
        """
        Run all security checks and return a structured report.

        Returns:
            Audit report dict with timestamp, summary, and findings.
        """
        findings = []

        # Run all checks
        findings.append(check_jwt_secret(self.config))
        findings.append(check_cors_origins(self.config))
        findings.append(check_config_file_permissions(self.config_path))
        findings.append(check_home_dir_permissions(self.home_dir))
        findings.append(check_debug_mode(self.config))
        findings.append(check_shell_tool(self.config))
        findings.append(check_api_keys_in_env(self.config))
        findings.append(check_token_expiry(self.config))
        findings.append(check_bind_address(self.config))

        # Build summary
        counts = {"pass": 0, "fail": 0, "warning": 0}
        for f in findings:
            status = f.get("status", "pass")
            counts[status] = counts.get(status, 0) + 1

        severity_counts = {}
        for f in findings:
            if f["status"] != "pass":
                sev = f.get("severity", "info")
                severity_counts[sev] = severity_counts.get(sev, 0) + 1

        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "summary": {
                "total_checks": len(findings),
                "passed": counts["pass"],
                "failed": counts["fail"],
                "warnings": counts["warning"],
                "severity_breakdown": severity_counts,
            },
            "findings": findings,
            "auto_fixable": [f["id"] for f in findings if f.get("auto_fixable")],
        }

        self._last_report = report
        logger.info(
            "Security audit: %d checks, %d passed, %d failed, %d warnings",
            len(findings), counts["pass"], counts["fail"], counts["warning"],
        )

        return report

    async def auto_fix(self, check_ids: list[str] | None = None) -> dict[str, Any]:
        """
        Apply auto-remediation for fixable issues.

        Args:
            check_ids: Specific check IDs to fix. None = fix all auto-fixable.

        Returns:
            Dict with results of each fix attempt.
        """
        if self._last_report is None:
            self._last_report = await self.run_audit()

        auto_fixable = self._last_report.get("auto_fixable", [])
        if check_ids:
            to_fix = [cid for cid in check_ids if cid in auto_fixable]
        else:
            to_fix = auto_fixable

        context = {
            "config": self.config,
            "config_path": self.config_path,
            "home_dir": self.home_dir,
        }

        results = {}
        for check_id in to_fix:
            success = apply_remediation(check_id, context)
            results[check_id] = "fixed" if success else "failed"
            logger.info("Remediation %s: %s", check_id, results[check_id])

        return {
            "fixes_attempted": len(to_fix),
            "results": results,
        }

    def get_last_report(self) -> dict[str, Any] | None:
        """Return the most recent audit report, or None."""
        return self._last_report

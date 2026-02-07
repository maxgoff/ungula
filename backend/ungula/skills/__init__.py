"""
Ungula Skills Framework.

Skills are extensible capabilities defined by SKILL.md files with
optional Python tool implementations.
"""

from .compatibility import (
    CONVERTIBLE_SCRIPT_EXTENSIONS,
    CompatibilityIssue,
    CompatibilityReport,
    Severity,
    analyze_skill_compatibility,
    convert_script_file,
    convert_skill_content,
)
from .loader import LoadedSkill, SkillLoader, SkillMetadata, SkillRegistry, SkillRequirements
from .repair import (
    repair_script_file,
    repair_skill_content,
)
from .security import (
    SecurityReport,
    SecurityThreat,
    ThreatCategory,
    scan_skill_security,
    validate_post_conversion,
)

__all__ = [
    "CompatibilityIssue",
    "CompatibilityReport",
    "LoadedSkill",
    "SecurityReport",
    "SecurityThreat",
    "Severity",
    "SkillLoader",
    "SkillMetadata",
    "SkillRegistry",
    "SkillRequirements",
    "ThreatCategory",
    "analyze_skill_compatibility",
    "convert_skill_content",
    "repair_script_file",
    "repair_skill_content",
    "scan_skill_security",
    "validate_post_conversion",
]

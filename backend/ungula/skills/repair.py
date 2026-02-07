"""
LLM-powered security repair for skills.

Uses an LLM to rewrite SKILL.md and script files to remove identified
security threats while preserving legitimate functionality. Follows the
same async LLM pattern as compatibility.py for platform conversion.
"""

import logging
from typing import Any

from ..llm.base import CompletionRequest, CompletionResponse, Message, MessageRole
from .security import SecurityThreat

logger = logging.getLogger(__name__)

# Extensions that can be repaired by the LLM
REPAIRABLE_SCRIPT_EXTENSIONS = {".sh", ".bash", ".py"}


def _format_threat_summary(threats: list[SecurityThreat]) -> str:
    """Format threats into a structured summary for the LLM prompt."""
    return "\n".join(
        f"- [{t.severity.value.upper()}] {t.category.value}: {t.description}\n"
        f"  Evidence (line {t.line_number or '?'}): {t.evidence}\n"
        f"  Recommendation: {t.recommendation}"
        for t in threats
    )


def _build_skill_repair_messages(
    skill_content: str,
    threats: list[SecurityThreat],
) -> list[Message]:
    """Build LLM prompt messages for repairing a SKILL.md file."""
    threat_summary = _format_threat_summary(threats)

    system_prompt = f"""You are a security remediation specialist for AI agent skill files. Your task is to rewrite a skill file to remove identified security threats while preserving all legitimate functionality.

A SKILL.md file defines an AI agent skill. It has YAML frontmatter (delimited by ---) followed by a markdown body with instructions, commands, and configuration.

SECURITY THREATS TO REMOVE:
{threat_summary}

RULES:
1. Remove or neutralize ONLY the specific security threats listed above.
2. Preserve the YAML frontmatter structure exactly. Only modify values that contain threats.
3. Preserve all non-malicious functionality, instructions, and content.
4. Preserve the document structure, headings, tables, and formatting.
5. Where a threat is embedded in otherwise useful content, rewrite the content to achieve the same legitimate goal without the security risk. Follow the recommendation provided for each threat.
6. Where a command is entirely malicious with no legitimate purpose, remove it and add a markdown comment noting what was removed and why.
7. Do NOT add explanatory preamble or postscript. Return ONLY the repaired file content.
8. Do NOT introduce any new commands, tools, or network calls that were not in the original.
9. If removing the identified threats would make the skill fundamentally non-functional (the threats ARE the skill's core functionality), respond with exactly: REPAIR_INFEASIBLE: <reason>"""

    user_prompt = f"""Repair this file (SKILL.md) by removing the security threats listed in your instructions.

Original content:
```
{skill_content}
```

Return the complete repaired file content. Nothing else."""

    return [
        Message(role=MessageRole.SYSTEM, content=system_prompt),
        Message(role=MessageRole.USER, content=user_prompt),
    ]


def _build_script_repair_messages(
    script_content: str,
    filename: str,
    threats: list[SecurityThreat],
) -> list[Message]:
    """Build LLM prompt messages for repairing a script file."""
    threat_summary = _format_threat_summary(threats)

    system_prompt = f"""You are a security remediation specialist. Rewrite this script to remove identified security threats while preserving all legitimate functionality.

SECURITY THREATS TO REMOVE:
{threat_summary}

RULES:
1. Remove or neutralize ONLY the specific threats listed above.
2. Preserve the script's legitimate purpose, interface (arguments, output format), and behavior.
3. Where a threat is embedded in useful logic, rewrite to achieve the same goal safely. Follow the recommendation for each threat.
4. Where a command is entirely malicious, remove it and add a comment noting what was removed.
5. Return ONLY the repaired script content. No explanation or markdown fences.
6. Do NOT introduce any new commands, imports, or network calls.
7. If removing threats makes the script non-functional, respond with exactly: REPAIR_INFEASIBLE: <reason>"""

    user_prompt = f"""Repair this script ({filename}) by removing the security threats listed in your instructions.

Original script:
```
{script_content}
```

Return the complete repaired script. Nothing else."""

    return [
        Message(role=MessageRole.SYSTEM, content=system_prompt),
        Message(role=MessageRole.USER, content=user_prompt),
    ]


def _strip_code_fences(content: str) -> str:
    """Strip markdown code fences from LLM output if present."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = lines[1:]  # Remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # Remove closing fence
        content = "\n".join(lines)
    return content


async def repair_skill_content(
    skill_content: str,
    threats: list[SecurityThreat],
    provider_registry: Any,
) -> tuple[str | None, str | None]:
    """Repair a SKILL.md by removing identified security threats using LLM.

    Args:
        skill_content: Original SKILL.md content.
        threats: Security threats found by scan_skill_security.
        provider_registry: LLM ProviderRegistry for making completion requests.

    Returns:
        Tuple of (repaired_content, error_message).
        If repair succeeds, error_message is None.
        If repair fails/is infeasible, repaired_content is None.
    """
    # Filter to threats relevant to SKILL.md
    skill_threats = [
        t for t in threats if t.file_path in ("SKILL.md", None)
    ]
    if not skill_threats:
        return skill_content, None

    messages = _build_skill_repair_messages(skill_content, skill_threats)

    request = CompletionRequest(
        messages=messages,
        temperature=0.2,
        max_tokens=8192,
    )

    try:
        response: CompletionResponse = await provider_registry.complete(request)
    except Exception as e:
        logger.warning("LLM repair failed: %s", e)
        return None, f"LLM repair failed: {e}"

    content = response.content
    if not content:
        return None, "LLM returned empty response"

    # Check for infeasibility
    if content.strip().startswith("REPAIR_INFEASIBLE:"):
        reason = content.strip().split(":", 1)[1].strip()
        return None, f"Repair infeasible: {reason}"

    content = _strip_code_fences(content)

    # Validate that result looks like a SKILL.md
    if not content.strip().startswith("---"):
        return None, "LLM output does not start with YAML frontmatter delimiter"

    return content, None


async def repair_script_file(
    script_content: str,
    filename: str,
    threats: list[SecurityThreat],
    provider_registry: Any,
) -> tuple[str | None, str | None]:
    """Repair a single script file by removing identified security threats.

    Args:
        script_content: Original script content.
        filename: Script filename (for context in the prompt).
        threats: Security threats found in this specific file.
        provider_registry: LLM ProviderRegistry for making completion requests.

    Returns:
        Tuple of (repaired_content, error_message).
    """
    # Filter to threats for this specific file
    file_threats = [t for t in threats if t.file_path == filename]
    if not file_threats:
        return script_content, None

    messages = _build_script_repair_messages(script_content, filename, file_threats)

    request = CompletionRequest(
        messages=messages,
        temperature=0.2,
        max_tokens=4096,
    )

    try:
        response: CompletionResponse = await provider_registry.complete(request)
    except Exception as e:
        logger.warning("Script repair failed for %s: %s", filename, e)
        return None, f"LLM repair failed for {filename}: {e}"

    content = response.content
    if not content:
        return None, f"LLM returned empty response for {filename}"

    # Check for infeasibility
    if content.strip().startswith("REPAIR_INFEASIBLE:"):
        reason = content.strip().split(":", 1)[1].strip()
        return None, f"Repair infeasible for {filename}: {reason}"

    content = _strip_code_fences(content)

    return content, None

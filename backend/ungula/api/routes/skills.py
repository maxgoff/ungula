"""
Skills API routes for Ungula.

Provides endpoints for managing skills: listing, enabling/disabling,
reloading, and ClawHub integration.
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from ...auth import get_current_user
from ...storage.base import User
from ...skills.loader import SkillLoader, SkillRegistry

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Response Models ---


class SkillInfo(BaseModel):
    """Summary info for a skill."""

    name: str
    version: str
    description: str
    author: str | None = None
    emoji: str | None = None
    enabled: bool
    eligible: bool
    eligibility_reason: str | None = None
    source: str
    has_tools: bool
    tool_names: list[str]


class SkillDetail(SkillInfo):
    """Full detail for a skill including body and frontmatter."""

    body: str
    requirements: dict[str, Any]
    raw_frontmatter: dict[str, Any]


class SkillsResponse(BaseModel):
    """Response for listing all skills."""

    skills: list[SkillInfo]
    total_tools: int


class ToolInfo(BaseModel):
    """Info about a tool provided by a skill."""

    name: str
    description: str
    skill_name: str


class ToolsResponse(BaseModel):
    """Response for listing all tools."""

    tools: list[ToolInfo]


class ClawHubSearchResult(BaseModel):
    """A skill from ClawHub search results."""

    slug: str
    name: str
    description: str
    author: str
    version: str
    downloads: int


class ClawHubInstallRequest(BaseModel):
    """Request to install a skill from ClawHub."""

    slug: str
    version: str | None = None
    convert: bool = False
    force: bool = False
    repair: bool = False


class ClawHubCheckRequest(BaseModel):
    """Request to check compatibility of a ClawHub skill."""

    slug: str
    version: str | None = None


class CompatibilityIssueInfo(BaseModel):
    """A single compatibility issue."""

    pattern: str
    category: str
    severity: str
    description: str
    source_platform: str
    file_path: str | None = None


class CompatibilityReportResponse(BaseModel):
    """Response from compatibility check."""

    compatible: bool
    current_platform: str
    detected_platforms: list[str]
    primary_platform: str | None
    issues: list[CompatibilityIssueInfo]
    confidence: float
    convertible: bool
    summary: str
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int


class SecurityThreatInfo(BaseModel):
    """A single security threat found during scanning."""

    pattern: str
    category: str
    severity: str
    description: str
    evidence: str
    file_path: str | None = None
    line_number: int | None = None
    recommendation: str = ""


class SecurityReportResponse(BaseModel):
    """Response from security scan."""

    safe: bool
    blocked: bool
    threats: list[SecurityThreatInfo]
    summary: str
    risk_score: float
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    scanned_files: list[str]
    scan_timestamp: str


# --- Helper ---


def _get_skill_registry(request: Request) -> SkillRegistry:
    """Get the skill registry from app state."""
    registry = getattr(request.app.state, "skill_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Skills system not initialized",
        )
    return registry


def _security_report_to_response(report) -> SecurityReportResponse:
    """Convert a SecurityReport to SecurityReportResponse."""
    return SecurityReportResponse(
        safe=report.safe,
        blocked=report.blocked,
        threats=[
            SecurityThreatInfo(
                pattern=t.pattern,
                category=t.category.value,
                severity=t.severity.value,
                description=t.description,
                evidence=t.evidence,
                file_path=t.file_path,
                line_number=t.line_number,
                recommendation=t.recommendation,
            )
            for t in report.threats
        ],
        summary=report.summary,
        risk_score=report.risk_score,
        critical_count=report.critical_count,
        high_count=report.high_count,
        medium_count=report.medium_count,
        low_count=report.low_count,
        scanned_files=report.scanned_files,
        scan_timestamp=report.scan_timestamp,
    )


def _skill_to_info(skill) -> SkillInfo:
    """Convert a LoadedSkill to SkillInfo."""
    return SkillInfo(
        name=skill.metadata.name,
        version=skill.metadata.version,
        description=skill.metadata.description,
        author=skill.metadata.author,
        emoji=skill.metadata.emoji,
        enabled=skill.metadata.enabled,
        eligible=skill.eligible,
        eligibility_reason=skill.eligibility_reason,
        source=skill.source,
        has_tools=len(skill.tools) > 0,
        tool_names=[t.name for t in skill.tools],
    )


# --- Endpoints ---


@router.get("/", response_model=SkillsResponse)
async def list_skills(request: Request) -> SkillsResponse:
    """List all loaded skills with their status."""
    registry = _get_skill_registry(request)
    skills = registry.list_skills()
    total_tools = len(registry.get_all_tools())

    return SkillsResponse(
        skills=[_skill_to_info(s) for s in skills],
        total_tools=total_tools,
    )


@router.get("/tools", response_model=ToolsResponse)
async def list_tools(request: Request) -> ToolsResponse:
    """List all tools provided by eligible skills."""
    registry = _get_skill_registry(request)
    tool_infos = []

    for skill in registry.list_eligible():
        for tool in skill.tools:
            tool_infos.append(ToolInfo(
                name=tool.name,
                description=tool.description,
                skill_name=skill.metadata.name,
            ))

    return ToolsResponse(tools=tool_infos)


@router.get("/{name}", response_model=SkillDetail)
async def get_skill(request: Request, name: str) -> SkillDetail:
    """Get full detail for a specific skill."""
    registry = _get_skill_registry(request)
    skill = registry.get(name)

    if skill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill not found: {name}",
        )

    reqs = skill.metadata.requirements
    return SkillDetail(
        name=skill.metadata.name,
        version=skill.metadata.version,
        description=skill.metadata.description,
        author=skill.metadata.author,
        emoji=skill.metadata.emoji,
        enabled=skill.metadata.enabled,
        eligible=skill.eligible,
        eligibility_reason=skill.eligibility_reason,
        source=skill.source,
        has_tools=len(skill.tools) > 0,
        tool_names=[t.name for t in skill.tools],
        body=skill.body,
        requirements={
            "bins": reqs.bins,
            "env": reqs.env,
            "config": reqs.config,
            "platform": reqs.platform,
        },
        raw_frontmatter=skill.metadata.raw_frontmatter,
    )


@router.post("/{name}/enable")
async def enable_skill(
    request: Request, name: str, current_user: User = Depends(get_current_user)
) -> dict[str, str]:
    """Enable a skill."""
    registry = _get_skill_registry(request)

    if not registry.enable_skill(name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill not found: {name}",
        )

    logger.info("Enabled skill: %s", name)
    return {"status": "ok", "message": f"Skill '{name}' enabled"}


@router.post("/{name}/disable")
async def disable_skill(
    request: Request, name: str, current_user: User = Depends(get_current_user)
) -> dict[str, str]:
    """Disable a skill."""
    registry = _get_skill_registry(request)

    if not registry.disable_skill(name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill not found: {name}",
        )

    logger.info("Disabled skill: %s", name)
    return {"status": "ok", "message": f"Skill '{name}' disabled"}


@router.post("/{name}/scan", response_model=SecurityReportResponse)
async def scan_installed_skill(
    request: Request, name: str
) -> SecurityReportResponse:
    """Run security scan on an already-installed skill."""
    from ...skills.security import scan_skill_security

    registry = _get_skill_registry(request)
    skill = registry.get(name)

    if skill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill not found: {name}",
        )

    skill_md_path = skill.skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SKILL.md not found for: {name}",
        )

    skill_md_content = skill_md_path.read_text()

    # Gather supplementary files
    from ...skills.security import SCANNABLE_EXTENSIONS

    supplementary_files: dict[str, str] = {}
    for f in skill.skill_dir.rglob("*"):
        if f.is_file() and f.name != "SKILL.md" and f.suffix.lower() in SCANNABLE_EXTENSIONS:
            try:
                rel_path = str(f.relative_to(skill.skill_dir))
                supplementary_files[rel_path] = f.read_text()
            except (UnicodeDecodeError, ValueError):
                pass

    report = scan_skill_security(skill_md_content, supplementary_files)

    return _security_report_to_response(report)


@router.delete("/{name}")
async def uninstall_skill(
    request: Request, name: str, current_user: User = Depends(get_current_user)
) -> dict[str, str]:
    """Uninstall a user or ClawHub skill (cannot uninstall bundled skills)."""
    registry = _get_skill_registry(request)
    skill = registry.get(name)

    if skill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill not found: {name}",
        )

    if skill.source == "bundled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot uninstall bundled skills",
        )

    # Remove skill directory
    import shutil
    if skill.skill_dir.exists():
        shutil.rmtree(skill.skill_dir)
        logger.info("Removed skill directory: %s", skill.skill_dir)

    registry.unregister(name)
    logger.info("Uninstalled skill: %s", name)
    return {"status": "ok", "message": f"Skill '{name}' uninstalled"}


async def _do_reload_skills(request: Request) -> dict[str, Any]:
    """Internal: reload all skills from disk."""
    config = request.app.state.config
    registry = _get_skill_registry(request)
    tool_registry = request.app.state.tool_registry

    # Clear existing skills
    for skill in registry.list_skills():
        for tool in skill.tools:
            if tool.name in tool_registry._tools:
                del tool_registry._tools[tool.name]
        registry.unregister(skill.metadata.name)

    # Re-scan
    loader = SkillLoader(config)
    bundled_dir = Path(__file__).parent.parent.parent / "skills" / "builtin"
    from ...config import get_ungula_home
    user_dir = get_ungula_home() / "skills"
    extra_dirs = [Path(d) for d in config.skills.extra_dirs]

    skills = loader.scan_directories([bundled_dir, user_dir] + extra_dirs)
    for skill in skills:
        registry.register(skill)
        for tool in skill.tools:
            tool_registry.register(tool)

    logger.info("Reloaded %d skills with %d tools", len(skills), len(registry.get_all_tools()))

    return {
        "status": "ok",
        "skills_loaded": len(skills),
        "tools_loaded": len(registry.get_all_tools()),
    }


@router.post("/reload")
async def reload_skills(
    request: Request, current_user: User = Depends(get_current_user)
) -> dict[str, Any]:
    """Reload all skills from disk."""
    return await _do_reload_skills(request)


# --- ClawHub Endpoints ---


@router.get("/clawhub/search")
async def search_clawhub(request: Request, q: str = "") -> dict[str, Any]:
    """Search the ClawHub registry for skills."""
    if not q.strip():
        return {"results": []}

    try:
        from ...skills.clawhub import ClawHubClient

        client = ClawHubClient()
        results = await client.search(q)
        return {"results": [r.__dict__ for r in results]}
    except Exception as e:
        logger.warning("ClawHub search failed: %s", e)
        return {"results": [], "error": str(e)}


@router.get("/clawhub/{slug}")
async def get_clawhub_skill(request: Request, slug: str) -> dict[str, Any]:
    """Get details of a skill from ClawHub."""
    try:
        from ...skills.clawhub import ClawHubClient

        client = ClawHubClient()
        detail = await client.get_skill(slug)
        return {
            "slug": detail.slug,
            "name": detail.name,
            "description": detail.description,
            "author": detail.author,
            "version": detail.version,
            "changelog": detail.changelog,
            "stars": detail.stars,
            "downloads": detail.downloads,
        }
    except Exception as e:
        logger.warning("ClawHub get skill failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ClawHub request failed: {e}",
        )


@router.post("/clawhub/check-compatibility", response_model=CompatibilityReportResponse)
async def check_clawhub_compatibility(
    request: Request, data: ClawHubCheckRequest
) -> CompatibilityReportResponse:
    """Check if a ClawHub skill is compatible with the current platform.

    Downloads the skill to memory (without installing) and scans for
    platform-specific indicators.
    """
    try:
        from ...skills.clawhub import ClawHubClient
        from ...skills.compatibility import analyze_skill_compatibility

        client = ClawHubClient()
        skill_md_content, supplementary_files = await client.fetch_skill_files(
            data.slug, data.version
        )

        report = analyze_skill_compatibility(
            skill_md_content=skill_md_content,
            supplementary_files=supplementary_files,
        )

        return CompatibilityReportResponse(
            compatible=report.compatible,
            current_platform=report.current_platform,
            detected_platforms=report.detected_platforms,
            primary_platform=report.primary_platform,
            issues=[
                CompatibilityIssueInfo(
                    pattern=i.pattern,
                    category=i.category,
                    severity=i.severity.value,
                    description=i.description,
                    source_platform=i.source_platform,
                    file_path=i.file_path,
                )
                for i in report.issues
            ],
            confidence=report.confidence,
            convertible=report.convertible,
            summary=report.summary,
            critical_count=report.critical_count,
            high_count=report.high_count,
            medium_count=report.medium_count,
            low_count=report.low_count,
        )
    except Exception as e:
        logger.warning("Compatibility check failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Compatibility check failed: {e}",
        )


@router.post("/clawhub/check-security", response_model=SecurityReportResponse)
async def check_clawhub_security(
    request: Request, data: ClawHubCheckRequest
) -> SecurityReportResponse:
    """Scan a ClawHub skill for security threats before installation.

    Downloads the skill to memory (without installing) and scans all
    files for obfuscation, credential theft, remote execution, and
    other malicious indicators.
    """
    try:
        from ...skills.clawhub import ClawHubClient
        from ...skills.security import scan_skill_security

        client = ClawHubClient()
        skill_md_content, supplementary_files = await client.fetch_skill_files(
            data.slug, data.version
        )

        report = scan_skill_security(
            skill_md_content=skill_md_content,
            supplementary_files=supplementary_files,
        )

        return _security_report_to_response(report)
    except Exception as e:
        logger.warning("Security scan failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Security scan failed: {e}",
        )


@router.post("/clawhub/install")
async def install_from_clawhub(
    request: Request,
    data: ClawHubInstallRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Install a skill from ClawHub, with security scanning and optional conversion."""
    if data.force:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Force-installing skills with known security threats is not allowed",
        )

    try:
        import json as json_module

        from ...config import get_ungula_home
        from ...skills.clawhub import ClawHubClient
        from ...skills.security import scan_skill_security, validate_post_conversion

        client = ClawHubClient()

        # ── Step 1: Fetch files to memory for security scan BEFORE disk ──
        skill_md_content, supplementary_files = await client.fetch_skill_files(
            data.slug, data.version
        )

        # ── Step 2: Run security scan ────────────────────────────────────
        security_report = scan_skill_security(skill_md_content, supplementary_files)
        logger.info(
            "Security scan for '%s': safe=%s, blocked=%s, threats=%d",
            data.slug,
            security_report.safe,
            security_report.blocked,
            len(security_report.threats),
        )

        # ── Step 3: Repair if requested ────────────────────────────────────
        repaired = False
        repair_error = None
        repair_report = None
        original_skill_md = skill_md_content
        original_supplementary = dict(supplementary_files) if supplementary_files else {}

        if data.repair and security_report.threats:
            from ...skills.repair import (
                REPAIRABLE_SCRIPT_EXTENSIONS,
                repair_script_file,
                repair_skill_content,
            )

            provider_registry = request.app.state.registry

            # Repair SKILL.md in memory
            repaired_md, md_error = await repair_skill_content(
                skill_content=skill_md_content,
                threats=security_report.threats,
                provider_registry=provider_registry,
            )

            if repaired_md:
                skill_md_content = repaired_md

                # Repair supplementary scripts in memory
                if supplementary_files:
                    for filename, file_content in list(supplementary_files.items()):
                        ext = Path(filename).suffix.lower()
                        if ext not in REPAIRABLE_SCRIPT_EXTENSIONS:
                            continue
                        file_threats = [
                            t for t in security_report.threats
                            if t.file_path == filename
                        ]
                        if not file_threats:
                            continue
                        script_repaired, script_err = await repair_script_file(
                            script_content=file_content,
                            filename=filename,
                            threats=file_threats,
                            provider_registry=provider_registry,
                        )
                        if script_repaired:
                            supplementary_files[filename] = script_repaired
                        else:
                            logger.warning(
                                "Failed to repair script %s: %s", filename, script_err
                            )

                # Re-scan repaired content
                repair_report = scan_skill_security(skill_md_content, supplementary_files)
                repaired = True
                logger.info(
                    "Repair scan for '%s': safe=%s, blocked=%s, threats=%d (was %d)",
                    data.slug,
                    repair_report.safe,
                    repair_report.blocked,
                    len(repair_report.threats),
                    len(security_report.threats),
                )

                # Block if still CRITICAL after repair
                if repair_report.blocked and not data.force:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "message": f"Repair reduced threats but {repair_report.summary}",
                            "security_report": _security_report_to_response(
                                repair_report
                            ).model_dump(),
                        },
                    )
            else:
                repair_error = md_error
                logger.warning("Skill repair failed for '%s': %s", data.slug, md_error)

        # ── Step 4: Block if CRITICAL threats and not repaired/forced ────
        if security_report.blocked and not data.force and not repaired:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": f"Installation blocked: {security_report.summary}",
                    "security_report": {
                        "safe": security_report.safe,
                        "blocked": security_report.blocked,
                        "summary": security_report.summary,
                        "risk_score": security_report.risk_score,
                        "critical_count": security_report.critical_count,
                        "high_count": security_report.high_count,
                        "medium_count": security_report.medium_count,
                        "low_count": security_report.low_count,
                        "threats": [
                            {
                                "category": t.category.value,
                                "severity": t.severity.value,
                                "description": t.description,
                                "evidence": t.evidence,
                                "file_path": t.file_path,
                                "recommendation": t.recommendation,
                            }
                            for t in security_report.threats
                        ],
                    },
                },
            )

        # ── Step 5: Download to disk ─────────────────────────────────────
        target_dir = get_ungula_home() / "skills"
        target_dir.mkdir(parents=True, exist_ok=True)

        skill_dir = await client.download_skill(data.slug, target_dir, data.version)
        logger.info("Downloaded skill '%s' to %s", data.slug, skill_dir)

        # ── Step 6: Overwrite with repaired content ──────────────────────
        if repaired:
            # Backup original SKILL.md as .unrepaired
            unrepaired_backup = skill_dir / "SKILL.md.unrepaired"
            unrepaired_backup.write_text(original_skill_md)
            (skill_dir / "SKILL.md").write_text(skill_md_content)
            logger.info("Wrote repaired SKILL.md for '%s'", data.slug)

            # Overwrite repaired scripts
            scripts_dir = skill_dir / "scripts"
            if scripts_dir.is_dir() and supplementary_files:
                for filename, repaired_content in supplementary_files.items():
                    if not filename.startswith("scripts/"):
                        continue
                    script_name = filename.split("/", 1)[1]
                    script_path = scripts_dir / script_name
                    if script_path.exists() and filename in original_supplementary:
                        if repaired_content != original_supplementary[filename]:
                            backup = script_path.with_suffix(
                                script_path.suffix + ".unrepaired"
                            )
                            backup.write_text(original_supplementary[filename])
                            script_path.write_text(repaired_content)
                            logger.info(
                                "Wrote repaired script %s for '%s'",
                                script_name, data.slug,
                            )

        converted = False
        conversion_error = None

        if data.convert:
            from ...skills.compatibility import (
                CONVERTIBLE_SCRIPT_EXTENSIONS,
                analyze_skill_compatibility,
                convert_script_file,
                convert_skill_content,
            )

            skill_md_path = skill_dir / "SKILL.md"
            original_content = skill_md_path.read_text()

            # Analyze to get issues for conversion context
            report = analyze_skill_compatibility(original_content)

            if report.primary_platform and report.primary_platform != report.current_platform:
                provider_registry = request.app.state.registry
                source = report.primary_platform
                target = report.current_platform

                converted_content, error = await convert_skill_content(
                    skill_content=original_content,
                    source_platform=source,
                    target_platform=target,
                    issues=report.issues,
                    provider_registry=provider_registry,
                )

                if converted_content:
                    original_backup = skill_dir / "SKILL.md.original"
                    original_backup.write_text(original_content)
                    skill_md_path.write_text(converted_content)
                    converted = True
                    logger.info(
                        "Converted SKILL.md for '%s' from %s to %s",
                        data.slug, source, target,
                    )

                    scripts_dir = skill_dir / "scripts"
                    if scripts_dir.is_dir():
                        for script_path in sorted(scripts_dir.iterdir()):
                            if script_path.suffix.lower() not in CONVERTIBLE_SCRIPT_EXTENSIONS:
                                continue
                            if not script_path.is_file():
                                continue
                            try:
                                script_content = script_path.read_text()
                            except UnicodeDecodeError:
                                continue

                            script_converted, script_err = await convert_script_file(
                                script_content=script_content,
                                filename=script_path.name,
                                source_platform=source,
                                target_platform=target,
                                provider_registry=provider_registry,
                            )

                            if script_converted:
                                backup = script_path.with_suffix(
                                    script_path.suffix + ".original"
                                )
                                backup.write_text(script_content)
                                script_path.write_text(script_converted)
                                logger.info(
                                    "Converted script %s for '%s'",
                                    script_path.name, data.slug,
                                )
                            else:
                                logger.warning(
                                    "Failed to convert script %s: %s",
                                    script_path.name, script_err,
                                )
                else:
                    conversion_error = error
                    logger.warning(
                        "Skill conversion failed for '%s': %s", data.slug, error
                    )

        # ── Step 5: Post-conversion validation ───────────────────────────
        post_conversion_report = None
        if converted:
            converted_md = (skill_dir / "SKILL.md").read_text()
            converted_supp: dict[str, str] = {}
            scripts_dir = skill_dir / "scripts"
            if scripts_dir.is_dir():
                for f in scripts_dir.iterdir():
                    if f.is_file():
                        try:
                            converted_supp[f"scripts/{f.name}"] = f.read_text()
                        except UnicodeDecodeError:
                            pass
            post_conversion_report = validate_post_conversion(
                security_report, converted_md, converted_supp
            )
            if post_conversion_report.blocked:
                logger.warning(
                    "Post-conversion security scan found new CRITICAL threats for '%s'",
                    data.slug,
                )

        # ── Step 6: Write _meta.json with security audit trail ───────────
        meta: dict[str, Any] = {
            "slug": data.slug,
            "version": data.version,
            "security_scan": {
                "safe": security_report.safe,
                "blocked": security_report.blocked,
                "risk_score": security_report.risk_score,
                "critical_count": security_report.critical_count,
                "high_count": security_report.high_count,
                "medium_count": security_report.medium_count,
                "low_count": security_report.low_count,
                "forced": data.force and security_report.blocked,
                "scan_timestamp": security_report.scan_timestamp,
            },
            "converted": converted,
        }
        if repaired:
            meta["repair"] = {
                "performed": True,
                "original_threats": len(security_report.threats),
                "remaining_threats": len(repair_report.threats) if repair_report else 0,
                "original_risk_score": security_report.risk_score,
                "repaired_risk_score": repair_report.risk_score if repair_report else 0.0,
            }
        elif repair_error:
            meta["repair"] = {"performed": False, "error": repair_error}
        if post_conversion_report and post_conversion_report.threats:
            meta["post_conversion_scan"] = {
                "new_threats": len(post_conversion_report.threats),
                "blocked": post_conversion_report.blocked,
                "risk_score": post_conversion_report.risk_score,
            }

        meta_path = skill_dir / "_meta.json"
        # Preserve existing _meta.json fields if present
        if meta_path.exists():
            try:
                existing = json_module.loads(meta_path.read_text())
                existing.update(meta)
                meta = existing
            except (json_module.JSONDecodeError, ValueError):
                pass
        meta_path.write_text(json_module.dumps(meta, indent=2))

        # ── Step 7: Reload skills ────────────────────────────────────────
        await _do_reload_skills(request)

        result: dict[str, Any] = {
            "status": "ok",
            "message": f"Installed skill '{data.slug}'",
            "converted": converted,
            "security": {
                "safe": security_report.safe,
                "risk_score": security_report.risk_score,
                "threat_count": len(security_report.threats),
                "forced": data.force and security_report.blocked,
            },
        }
        result["repaired"] = repaired
        if repair_error:
            result["repair_error"] = repair_error
        if repair_report:
            result["repair_result"] = {
                "original_threats": len(security_report.threats),
                "remaining_threats": len(repair_report.threats),
            }
        if conversion_error:
            result["conversion_error"] = conversion_error
        if post_conversion_report and post_conversion_report.threats:
            result["post_conversion_warning"] = post_conversion_report.summary
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("ClawHub install failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ClawHub install failed: {e}",
        )

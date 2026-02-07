"""
Configuration API routes.

Provides endpoints for reading and managing workspace files, configuration,
and LLM provider management.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...auth import get_current_user
from ...storage.base import User
from ...config import (
    CustomProviderConfig,
    LLMProviderConfig,
    UngulaConfig,
    get_workspace_dir,
    get_workspace_file,
    load_config,
    load_workspace_file,
    save_config,
    save_workspace_file,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Keys whose values should be masked in API responses
_SECRET_KEY_PATTERNS = frozenset({
    "api_key", "token", "password", "secret_key", "secret",
    "hashed_password", "redis_password",
})


def redact_secrets(obj: Any, _depth: int = 0) -> Any:
    """Recursively mask secret values in a config dict."""
    if _depth > 20:
        return obj
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key in _SECRET_KEY_PATTERNS and isinstance(value, str) and value:
                result[key] = "***REDACTED***"
            else:
                result[key] = redact_secrets(value, _depth + 1)
        return result
    if isinstance(obj, list):
        return [redact_secrets(item, _depth + 1) for item in obj]
    return obj


class WorkspaceFileResponse(BaseModel):
    """Response for workspace file content."""

    filename: str
    content: str | None
    exists: bool


class WorkspaceFileUpdate(BaseModel):
    """Request to update a workspace file."""

    content: str = Field(max_length=1_000_000)


class ConfigResponse(BaseModel):
    """Response with configuration."""

    config: dict[str, Any]


@router.get("/", response_model=ConfigResponse)
async def get_config(request: Request) -> ConfigResponse:
    """Get current configuration (secrets are redacted)."""
    config: UngulaConfig = request.app.state.config
    return ConfigResponse(config=redact_secrets(config.model_dump(exclude_none=True)))


@router.get("/workspace/{filename}", response_model=WorkspaceFileResponse)
async def get_workspace_file_content(filename: str) -> WorkspaceFileResponse:
    """
    Get content of a workspace file.

    Supported files: SOUL.md, USER.md, IDENTITY.md, AGENTS.md, TOOLS.md, MEMORY.md, HEARTBEAT.md
    """
    allowed_files = {
        "SOUL.md",
        "USER.md",
        "IDENTITY.md",
        "AGENTS.md",
        "TOOLS.md",
        "MEMORY.md",
        "HEARTBEAT.md",
    }

    if filename not in allowed_files:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filename. Allowed: {', '.join(sorted(allowed_files))}",
        )

    content = load_workspace_file(filename)
    path = get_workspace_file(filename)

    return WorkspaceFileResponse(
        filename=filename,
        content=content,
        exists=path.exists(),
    )


@router.put("/workspace/{filename}", response_model=WorkspaceFileResponse)
async def update_workspace_file(
    filename: str,
    data: WorkspaceFileUpdate,
    current_user: User = Depends(get_current_user),
) -> WorkspaceFileResponse:
    """
    Update content of a workspace file.

    Supported files: SOUL.md, USER.md, IDENTITY.md, AGENTS.md, TOOLS.md, MEMORY.md, HEARTBEAT.md
    """
    allowed_files = {
        "SOUL.md",
        "USER.md",
        "IDENTITY.md",
        "AGENTS.md",
        "TOOLS.md",
        "MEMORY.md",
        "HEARTBEAT.md",
    }

    if filename not in allowed_files:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filename. Allowed: {', '.join(sorted(allowed_files))}",
        )

    save_workspace_file(filename, data.content)

    return WorkspaceFileResponse(
        filename=filename,
        content=data.content,
        exists=True,
    )


class WorkspaceListResponse(BaseModel):
    """Response for listing workspace files with bootstrap status."""

    files: list[WorkspaceFileResponse]
    bootstrap_needed: bool = False


@router.get("/workspace", response_model=WorkspaceListResponse)
async def list_workspace_files() -> WorkspaceListResponse:
    """List all workspace files and their status."""
    files = [
        "SOUL.md",
        "USER.md",
        "IDENTITY.md",
        "AGENTS.md",
        "TOOLS.md",
        "MEMORY.md",
        "HEARTBEAT.md",
    ]

    result = []
    for filename in files:
        path = get_workspace_file(filename)
        content = load_workspace_file(filename)
        result.append(
            WorkspaceFileResponse(
                filename=filename,
                content=content,
                exists=path.exists(),
            )
        )

    from ...hooks.bootstrap import check_bootstrap_needed

    bootstrap_needed = check_bootstrap_needed(get_workspace_dir())

    return WorkspaceListResponse(
        files=result,
        bootstrap_needed=bootstrap_needed,
    )


@router.post("/initialize-workspace")
async def initialize_workspace(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Initialize workspace with default template files.

    Only creates files that don't already exist.
    """
    from pathlib import Path

    # Try source tree first, then Docker/production path
    templates_dir = Path(__file__).parent.parent.parent.parent.parent / "docs" / "templates"
    if not templates_dir.is_dir():
        templates_dir = Path("/app/docs/templates")
    files_created = []
    files_skipped = []

    template_files = [
        "SOUL.md",
        "USER.md",
        "IDENTITY.md",
        "AGENTS.md",
        "TOOLS.md",
        "MEMORY.md",
        "HEARTBEAT.md",
    ]

    for filename in template_files:
        workspace_path = get_workspace_file(filename)
        template_path = templates_dir / filename

        if workspace_path.exists():
            files_skipped.append(filename)
        elif template_path.exists():
            content = template_path.read_text()
            save_workspace_file(filename, content)
            files_created.append(filename)
        else:
            # Template doesn't exist, create empty file
            save_workspace_file(filename, f"# {filename.replace('.md', '')}\n")
            files_created.append(filename)

    # Check if bootstrap is needed
    from ...hooks.bootstrap import check_bootstrap_needed
    from ...config import get_workspace_dir

    bootstrap_needed = check_bootstrap_needed(get_workspace_dir())

    return {
        "message": "Workspace initialized",
        "files_created": files_created,
        "files_skipped": files_skipped,
        "bootstrap_needed": bootstrap_needed,
    }


class FailoverOrderRequest(BaseModel):
    """Request to update provider failover order."""
    order: list[str] = Field(min_length=1)


@router.put("/failover-order")
async def update_failover_order(
    request: Request,
    data: FailoverOrderRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Update the provider failover order."""
    from ...main import rebuild_registry

    config: UngulaConfig = request.app.state.config
    registry = request.app.state.registry

    # Validate all names are registered providers
    registered = set(registry.list_providers())
    invalid = [p for p in data.order if p not in registered]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown providers: {', '.join(invalid)}. Registered: {', '.join(sorted(registered))}",
        )

    config.llm.failover_order = data.order
    save_config(config)
    await rebuild_registry(request.app)
    logger.info("Updated failover order to: %s", data.order)

    return {"failover_order": request.app.state.registry.failover_order}


@router.post("/reload")
async def reload_config(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ConfigResponse:
    """Reload configuration from disk."""
    config = load_config()
    request.app.state.config = config
    return ConfigResponse(config=redact_secrets(config.model_dump(exclude_none=True)))


# ========================================
# Provider Management Endpoints
# ========================================

# Built-in provider metadata (display names and descriptions)
BUILTIN_PROVIDERS = {
    "openrouter": {"display_name": "OpenRouter", "description": "Multi-provider gateway"},
    "anthropic": {"display_name": "Anthropic", "description": "Claude models"},
    "openai": {"display_name": "OpenAI", "description": "GPT models"},
    "google": {"display_name": "Google", "description": "Gemini models"},
    "xai": {"display_name": "xAI", "description": "Grok models"},
    "nvidia": {"display_name": "NVIDIA NIM", "description": "Llama, Kimi, DeepSeek, Mistral & more"},
    "ollama": {"display_name": "Ollama", "description": "Local LLM server", "local": True},
}


class ProviderInfo(BaseModel):
    """Provider information for the frontend."""
    name: str
    display_name: str
    description: str = ""
    type: str  # "builtin" or "custom"
    enabled: bool
    has_api_key: bool
    default_model: str | None = None
    base_url: str | None = None
    healthy: bool | None = None
    local: bool = False


class ProvidersResponse(BaseModel):
    """Response listing all providers."""
    providers: list[ProviderInfo]
    default_provider: str


class UpdateProviderRequest(BaseModel):
    """Request to update a built-in provider."""
    enabled: bool | None = None
    api_key: str | None = None
    default_model: str | None = None
    base_url: str | None = None


class AddCustomProviderRequest(BaseModel):
    """Request to add a custom provider."""
    name: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    default_model: str | None = None


def _get_builtin_config(config: UngulaConfig, name: str) -> LLMProviderConfig | None:
    """Get a built-in provider's config by name."""
    return getattr(config.llm, name, None)


_ALLOWED_PROVIDER_FIELDS = frozenset({"enabled", "api_key", "default_model", "base_url"})


def _set_builtin_config(config: UngulaConfig, name: str, updates: dict[str, Any]) -> None:
    """Update a built-in provider's config fields (whitelisted fields only)."""
    provider_config = getattr(config.llm, name, None)
    if provider_config is None:
        return
    for key, value in updates.items():
        if value is not None and key in _ALLOWED_PROVIDER_FIELDS:
            setattr(provider_config, key, value)


@router.get("/providers", response_model=ProvidersResponse)
async def list_providers(request: Request) -> ProvidersResponse:
    """List all LLM providers (built-in + custom) with status."""
    config: UngulaConfig = request.app.state.config
    registry = request.app.state.registry

    # Check health for all registered providers
    health = {}
    try:
        health = await registry.check_health()
    except Exception:
        pass

    providers = []

    # Built-in providers
    for name, meta in BUILTIN_PROVIDERS.items():
        pconfig = _get_builtin_config(config, name)
        if pconfig is None:
            continue
        providers.append(ProviderInfo(
            name=name,
            display_name=meta["display_name"],
            description=meta.get("description", ""),
            type="builtin",
            enabled=pconfig.enabled,
            has_api_key=bool(pconfig.api_key),
            default_model=pconfig.default_model,
            base_url=pconfig.base_url,
            healthy=health.get(name),
            local=meta.get("local", False),
        ))

    # Custom providers
    for custom in config.llm.custom_providers:
        providers.append(ProviderInfo(
            name=custom.name,
            display_name=custom.display_name,
            type="custom",
            enabled=custom.enabled,
            has_api_key=bool(custom.api_key),
            default_model=custom.default_model,
            base_url=custom.base_url,
            healthy=health.get(custom.name),
        ))

    return ProvidersResponse(
        providers=providers,
        default_provider=config.llm.default_provider,
    )


@router.put("/providers/{name}")
async def update_provider(
    request: Request,
    name: str,
    data: UpdateProviderRequest,
    current_user: User = Depends(get_current_user),
) -> ProvidersResponse:
    """Update a provider's configuration (built-in or custom)."""
    from ...main import rebuild_registry

    config: UngulaConfig = request.app.state.config

    # Check if it's a built-in provider
    if name in BUILTIN_PROVIDERS:
        updates = {}
        if data.enabled is not None:
            updates["enabled"] = data.enabled
        if data.api_key is not None:
            updates["api_key"] = data.api_key
        if data.default_model is not None:
            updates["default_model"] = data.default_model
        if data.base_url is not None:
            updates["base_url"] = data.base_url
        _set_builtin_config(config, name, updates)
    else:
        # Check custom providers
        found = False
        for custom in config.llm.custom_providers:
            if custom.name == name:
                if data.enabled is not None:
                    custom.enabled = data.enabled
                if data.api_key is not None:
                    custom.api_key = data.api_key
                if data.default_model is not None:
                    custom.default_model = data.default_model
                if data.base_url is not None:
                    custom.base_url = data.base_url
                found = True
                break
        if not found:
            raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    # Save and rebuild
    save_config(config)
    await rebuild_registry(request.app)
    logger.info("Updated provider '%s' and rebuilt registry", name)

    return await list_providers(request)


@router.post("/providers")
async def add_custom_provider(
    request: Request,
    data: AddCustomProviderRequest,
    current_user: User = Depends(get_current_user),
) -> ProvidersResponse:
    """Add a new custom OpenAI-compatible provider."""
    from ...main import rebuild_registry

    config: UngulaConfig = request.app.state.config

    # Check name doesn't conflict with built-in or existing custom
    if data.name in BUILTIN_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Name '{data.name}' conflicts with a built-in provider",
        )
    for custom in config.llm.custom_providers:
        if custom.name == data.name:
            raise HTTPException(
                status_code=400,
                detail=f"Custom provider '{data.name}' already exists",
            )

    # Add custom provider
    config.llm.custom_providers.append(CustomProviderConfig(
        name=data.name,
        display_name=data.display_name,
        api_key=data.api_key,
        base_url=data.base_url,
        default_model=data.default_model,
    ))

    # Save and rebuild
    save_config(config)
    await rebuild_registry(request.app)
    logger.info("Added custom provider '%s' and rebuilt registry", data.name)

    return await list_providers(request)


@router.delete("/providers/{name}")
async def delete_custom_provider(
    request: Request,
    name: str,
    current_user: User = Depends(get_current_user),
) -> ProvidersResponse:
    """Delete a custom provider (cannot delete built-in providers)."""
    from ...main import rebuild_registry

    config: UngulaConfig = request.app.state.config

    if name in BUILTIN_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete built-in providers. Disable them instead.",
        )

    original_len = len(config.llm.custom_providers)
    config.llm.custom_providers = [
        c for c in config.llm.custom_providers if c.name != name
    ]

    if len(config.llm.custom_providers) == original_len:
        raise HTTPException(status_code=404, detail=f"Custom provider '{name}' not found")

    # Save and rebuild
    save_config(config)
    await rebuild_registry(request.app)
    logger.info("Deleted custom provider '%s' and rebuilt registry", name)

    return await list_providers(request)

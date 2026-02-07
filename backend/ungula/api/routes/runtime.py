"""
Runtime configuration API routes.

Provides endpoints for updating agent runtime settings and default
provider/model without editing config.yaml.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...auth import get_current_user
from ...config import save_config
from ...storage.base import User

logger = logging.getLogger(__name__)

router = APIRouter()


class RuntimeConfigResponse(BaseModel):
    """Current runtime configuration."""
    max_context_tokens: int
    max_history_share: float
    reserve_tokens_floor: int
    pruning_enabled: bool
    soft_trim_ratio: float
    hard_clear_ratio: float
    default_provider: str
    default_model: str | None = None


class UpdateRuntimeRequest(BaseModel):
    """Request to update runtime config fields."""
    max_context_tokens: int | None = Field(default=None, ge=1000)
    max_history_share: float | None = Field(default=None, ge=0.1, le=0.9)
    reserve_tokens_floor: int | None = Field(default=None, ge=1000)
    pruning_enabled: bool | None = None
    soft_trim_ratio: float | None = Field(default=None, ge=0.1, le=0.9)
    hard_clear_ratio: float | None = Field(default=None, ge=0.1, le=0.9)


class SetProviderRequest(BaseModel):
    """Request to change default provider."""
    provider: str = Field(min_length=1)


class SetModelRequest(BaseModel):
    """Request to change default model."""
    model: str = Field(min_length=1)


@router.get("/", response_model=RuntimeConfigResponse)
async def get_runtime_config(request: Request) -> RuntimeConfigResponse:
    """Get current agent runtime configuration."""
    config = request.app.state.config
    rt = config.agent_runtime
    return RuntimeConfigResponse(
        max_context_tokens=rt.max_context_tokens,
        max_history_share=rt.max_history_share,
        reserve_tokens_floor=rt.reserve_tokens_floor,
        pruning_enabled=rt.pruning_enabled,
        soft_trim_ratio=rt.soft_trim_ratio,
        hard_clear_ratio=rt.hard_clear_ratio,
        default_provider=config.llm.default_provider,
        default_model=getattr(request.app.state.agent_runner, "default_model", None),
    )


@router.put("/", response_model=RuntimeConfigResponse)
async def update_runtime_config(
    request: Request,
    data: UpdateRuntimeRequest,
    current_user: User = Depends(get_current_user),
) -> RuntimeConfigResponse:
    """Update agent runtime configuration fields."""
    config = request.app.state.config
    rt = config.agent_runtime

    updates = data.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(rt, key, value)

    save_config(config)

    # Update live runner compaction/pruning configs
    runner = request.app.state.agent_runner
    if runner.compaction_config:
        runner.compaction_config.max_context_tokens = rt.max_context_tokens
        runner.compaction_config.max_history_share = rt.max_history_share
        runner.compaction_config.reserve_tokens_floor = rt.reserve_tokens_floor
    if runner.pruning_config:
        runner.pruning_config.enabled = rt.pruning_enabled
        runner.pruning_config.soft_trim_ratio = rt.soft_trim_ratio
        runner.pruning_config.hard_clear_ratio = rt.hard_clear_ratio

    logger.info("Updated runtime config: %s", updates)
    return await get_runtime_config(request)


@router.put("/default-provider", response_model=RuntimeConfigResponse)
async def set_default_provider(
    request: Request,
    data: SetProviderRequest,
    current_user: User = Depends(get_current_user),
) -> RuntimeConfigResponse:
    """Change the default LLM provider."""
    from ...main import rebuild_registry

    config = request.app.state.config
    registry = request.app.state.registry

    if data.provider not in registry.providers:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{data.provider}' not registered. Available: {registry.list_providers()}",
        )

    config.llm.default_provider = data.provider
    save_config(config)
    await rebuild_registry(request.app)

    # Update runner's default provider
    request.app.state.agent_runner.default_provider = data.provider

    logger.info("Changed default provider to '%s'", data.provider)
    return await get_runtime_config(request)


@router.put("/default-model", response_model=RuntimeConfigResponse)
async def set_default_model(
    request: Request,
    data: SetModelRequest,
    current_user: User = Depends(get_current_user),
) -> RuntimeConfigResponse:
    """Change the default model for the agent runner."""
    request.app.state.agent_runner.default_model = data.model
    logger.info("Changed default model to '%s'", data.model)
    return await get_runtime_config(request)

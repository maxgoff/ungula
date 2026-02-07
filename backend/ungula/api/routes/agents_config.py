"""
Agent configuration CRUD API routes.

Provides endpoints for managing agent configurations at runtime.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...auth import get_current_user
from ...config import AgentConfig, save_config
from ...storage.base import User

logger = logging.getLogger(__name__)

router = APIRouter()


class AgentConfigResponse(BaseModel):
    """Agent config response."""
    id: str
    name: str
    type: str
    enabled: bool
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    max_tool_iterations: int | None = None
    system_prompt: str | None = None
    persona: str | None = None
    default_provider_params: dict[str, Any] = Field(default_factory=dict)


class CreateAgentRequest(BaseModel):
    """Request to create an agent."""
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    provider: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    max_tool_iterations: int | None = Field(default=None, ge=1, le=50)
    system_prompt: str | None = None
    persona: str | None = None
    default_provider_params: dict[str, Any] = Field(default_factory=dict)


class UpdateAgentRequest(BaseModel):
    """Request to update an agent."""
    name: str | None = None
    type: str | None = None
    enabled: bool | None = None
    provider: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    max_tool_iterations: int | None = Field(default=None, ge=1, le=50)
    system_prompt: str | None = None
    persona: str | None = None
    default_provider_params: dict[str, Any] | None = None


def _agent_to_response(cfg: AgentConfig) -> AgentConfigResponse:
    return AgentConfigResponse(
        id=cfg.id,
        name=cfg.name,
        type=cfg.type,
        enabled=cfg.enabled,
        provider=cfg.provider,
        model=cfg.model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        max_tool_iterations=cfg.max_tool_iterations,
        system_prompt=cfg.system_prompt,
        persona=cfg.persona,
        default_provider_params=cfg.default_provider_params,
    )


@router.get("/", response_model=list[AgentConfigResponse])
async def list_agents(request: Request) -> list[AgentConfigResponse]:
    """List all agent configurations."""
    config = request.app.state.config
    return [_agent_to_response(a) for a in config.agents]


@router.get("/{agent_id}", response_model=AgentConfigResponse)
async def get_agent(request: Request, agent_id: str) -> AgentConfigResponse:
    """Get a single agent configuration."""
    config = request.app.state.config
    for a in config.agents:
        if a.id == agent_id:
            return _agent_to_response(a)
    raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")


@router.post("/", response_model=AgentConfigResponse, status_code=201)
async def create_agent(
    request: Request,
    data: CreateAgentRequest,
    current_user: User = Depends(get_current_user),
) -> AgentConfigResponse:
    """Create a new agent configuration."""
    config = request.app.state.config

    # Check for duplicate ID
    for a in config.agents:
        if a.id == data.id:
            raise HTTPException(status_code=400, detail=f"Agent '{data.id}' already exists")

    agent_config = AgentConfig(**data.model_dump())
    config.agents.append(agent_config)
    save_config(config)

    # Invalidate factory cache
    factory = getattr(request.app.state, "agent_factory", None)
    if factory:
        factory.invalidate(data.id)

    logger.info("Created agent config '%s'", data.id)
    return _agent_to_response(agent_config)


@router.put("/{agent_id}", response_model=AgentConfigResponse)
async def update_agent(
    request: Request,
    agent_id: str,
    data: UpdateAgentRequest,
    current_user: User = Depends(get_current_user),
) -> AgentConfigResponse:
    """Update an agent configuration."""
    config = request.app.state.config

    for a in config.agents:
        if a.id == agent_id:
            updates = data.model_dump(exclude_none=True)
            for key, value in updates.items():
                setattr(a, key, value)
            save_config(config)

            # Invalidate factory cache
            factory = getattr(request.app.state, "agent_factory", None)
            if factory:
                factory.invalidate(agent_id)

            logger.info("Updated agent config '%s'", agent_id)
            return _agent_to_response(a)

    raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")


@router.delete("/{agent_id}")
async def delete_agent(
    request: Request,
    agent_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Delete an agent configuration."""
    config = request.app.state.config

    original_len = len(config.agents)
    config.agents = [a for a in config.agents if a.id != agent_id]

    if len(config.agents) == original_len:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    save_config(config)

    # Invalidate factory cache
    factory = getattr(request.app.state, "agent_factory", None)
    if factory:
        factory.invalidate(agent_id)

    logger.info("Deleted agent config '%s'", agent_id)
    return {"deleted": agent_id}

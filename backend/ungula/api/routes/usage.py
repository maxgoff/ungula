"""
Token usage tracking API routes.

Provides endpoints for viewing token consumption by provider, model, and date.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from ...auth import get_current_user
from ...storage.base import User

logger = logging.getLogger(__name__)

router = APIRouter()


class UsageSummaryResponse(BaseModel):
    """Aggregated usage summary."""
    totals: dict[str, int]
    breakdown: list[dict[str, Any]]


class DailyUsageResponse(BaseModel):
    """Daily usage totals."""
    days: list[dict[str, Any]]


class UsageHistoryResponse(BaseModel):
    """Paginated raw usage records."""
    records: list[dict[str, Any]]
    total: int


@router.get("/summary", response_model=UsageSummaryResponse)
async def get_usage_summary(
    request: Request,
    start_date: str | None = Query(None, description="Start date (ISO format)"),
    end_date: str | None = Query(None, description="End date (ISO format)"),
    conversation_id: str | None = None,
    current_user: User = Depends(get_current_user),
) -> UsageSummaryResponse:
    """Get aggregated token usage summary by provider and model."""
    storage = request.app.state.storage

    kwargs: dict[str, Any] = {"user_id": current_user.id}
    if start_date:
        kwargs["start_date"] = datetime.fromisoformat(start_date)
    if end_date:
        kwargs["end_date"] = datetime.fromisoformat(end_date)
    if conversation_id:
        kwargs["conversation_id"] = UUID(conversation_id)

    summary = await storage.get_token_usage_summary(**kwargs)
    return UsageSummaryResponse(**summary)


@router.get("/daily", response_model=DailyUsageResponse)
async def get_daily_usage(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
) -> DailyUsageResponse:
    """Get daily token usage totals for charts."""
    from sqlalchemy import func as sql_func, select, cast, Date

    storage = request.app.state.storage
    from ...storage.models import TokenUsageModel

    async with storage._session() as session:
        query = (
            select(
                cast(TokenUsageModel.created_at, Date).label("date"),
                sql_func.sum(TokenUsageModel.prompt_tokens).label("prompt_tokens"),
                sql_func.sum(TokenUsageModel.completion_tokens).label("completion_tokens"),
                sql_func.sum(TokenUsageModel.total_tokens).label("total_tokens"),
                sql_func.count(TokenUsageModel.id).label("request_count"),
            )
            .where(TokenUsageModel.user_id == str(current_user.id))
            .group_by(cast(TokenUsageModel.created_at, Date))
            .order_by(cast(TokenUsageModel.created_at, Date).desc())
            .limit(days)
        )
        result = await session.execute(query)
        rows = result.all()

    daily = []
    for row in rows:
        daily.append({
            "date": str(row.date),
            "prompt_tokens": row.prompt_tokens or 0,
            "completion_tokens": row.completion_tokens or 0,
            "total_tokens": row.total_tokens or 0,
            "request_count": row.request_count or 0,
        })

    return DailyUsageResponse(days=list(reversed(daily)))


@router.get("/history", response_model=UsageHistoryResponse)
async def get_usage_history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    provider: str | None = None,
    model: str | None = None,
    current_user: User = Depends(get_current_user),
) -> UsageHistoryResponse:
    """Get paginated raw token usage records."""
    from sqlalchemy import func as sql_func, select

    storage = request.app.state.storage
    from ...storage.models import TokenUsageModel

    async with storage._session() as session:
        # Count total
        count_query = select(sql_func.count(TokenUsageModel.id)).where(
            TokenUsageModel.user_id == str(current_user.id)
        )
        if provider:
            count_query = count_query.where(TokenUsageModel.provider == provider)
        if model:
            count_query = count_query.where(TokenUsageModel.model == model)
        total = (await session.execute(count_query)).scalar() or 0

        # Fetch records
        query = (
            select(TokenUsageModel)
            .where(TokenUsageModel.user_id == str(current_user.id))
            .order_by(TokenUsageModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if provider:
            query = query.where(TokenUsageModel.provider == provider)
        if model:
            query = query.where(TokenUsageModel.model == model)

        result = await session.execute(query)
        models = result.scalars().all()

    records = []
    for m in models:
        records.append({
            "id": m.id,
            "conversation_id": m.conversation_id,
            "provider": m.provider,
            "model": m.model,
            "prompt_tokens": m.prompt_tokens,
            "completion_tokens": m.completion_tokens,
            "total_tokens": m.total_tokens,
            "created_at": m.created_at.isoformat(),
        })

    return UsageHistoryResponse(records=records, total=total)

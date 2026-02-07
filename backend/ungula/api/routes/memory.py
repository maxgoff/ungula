"""
Memory API routes.

Provides endpoints for searching, adding, deleting, syncing,
and checking status of the vector memory system.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ...auth import get_current_user
from ...storage.base import User

logger = logging.getLogger(__name__)

router = APIRouter()


class MemoryAddRequest(BaseModel):
    """Request to add a memory entry."""

    content: str = Field(..., max_length=50_000)
    memory_type: str = Field(default="fact")
    level: str = Field(default="global")
    project_id: str | None = None
    agent_id: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemorySearchRequest(BaseModel):
    """Request to search memory."""

    query: str = Field(..., max_length=10_000)
    memory_type: str | None = None
    level: str | None = None
    project_id: str | None = None
    agent_id: str | None = None
    limit: int = Field(default=10, ge=1, le=100)
    use_hybrid: bool = Field(default=True)


class IndexDocumentRequest(BaseModel):
    """Request to index a document."""

    content: str = Field(..., max_length=500_000)
    source: str = Field(..., max_length=500)
    memory_type: str = Field(default="fact")
    level: str = Field(default="project")
    project_id: str | None = None
    chunk_size: int = Field(default=500, ge=50, le=5000)
    chunk_overlap: int = Field(default=50, ge=0, le=500)


def _get_memory_manager(request: Request):
    """Get the memory manager from app state."""
    manager = getattr(request.app.state, "memory_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="Memory system not initialized",
        )
    return manager


@router.post("/search")
async def search_memory(
    body: MemorySearchRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Search memory using semantic similarity."""
    manager = _get_memory_manager(request)

    results = await manager.search(
        query=body.query,
        memory_type=body.memory_type,
        level=body.level,
        project_id=body.project_id,
        agent_id=body.agent_id,
        limit=body.limit,
    )

    # Optionally apply hybrid re-ranking
    if body.use_hybrid and results:
        from ...memory.hybrid import hybrid_search

        results = hybrid_search(results, body.query, limit=body.limit)

    return {"results": results, "count": len(results)}


@router.post("/add")
async def add_memory(
    body: MemoryAddRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Add a memory entry."""
    manager = _get_memory_manager(request)

    entry = await manager.add_memory(
        content=body.content,
        memory_type=body.memory_type,
        level=body.level,
        project_id=body.project_id,
        agent_id=body.agent_id,
        source=body.source,
        metadata=body.metadata,
    )

    return {"id": str(entry.id), "status": "added"}


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete a memory entry."""
    manager = _get_memory_manager(request)
    deleted = await manager.delete_memory(memory_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Memory entry not found")

    return {"status": "deleted"}


@router.post("/sync")
async def sync_memory(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Sync ChromaDB index from SQLite storage."""
    manager = _get_memory_manager(request)
    count = await manager.sync_from_storage()
    return {"synced": count}


@router.post("/index")
async def index_document(
    body: IndexDocumentRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Index a document by chunking and embedding it."""
    manager = _get_memory_manager(request)

    chunks = await manager.index_document(
        content=body.content,
        source=body.source,
        memory_type=body.memory_type,
        level=body.level,
        project_id=body.project_id,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
    )

    return {"chunks_indexed": chunks, "source": body.source}


@router.get("/status")
async def memory_status(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get memory system status."""
    manager = _get_memory_manager(request)
    return await manager.get_status()

"""HTTP routes for browsing the knowledge base, scoped to the
authenticated user. Read-only: chunks are produced by the asset
processing pipeline, not authored via the API.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.modules.auth.models import User
from app.modules.auth.security import get_current_user
from app.modules.knowledge_base.dependencies import get_knowledge_base_service
from app.modules.knowledge_base.models import KnowledgeChunk
from app.modules.knowledge_base.schemas import KnowledgeChunkRead
from app.modules.knowledge_base.service import (
    KnowledgeBaseService,
    KnowledgeChunkNotFoundError,
    ProjectAccessDeniedError,
)

router = APIRouter(prefix="/knowledge-base", tags=["Knowledge Base"])

_PROJECT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Project not found."
)
_CHUNK_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge chunk not found."
)


@router.get("/chunks", response_model=list[KnowledgeChunkRead])
async def list_chunks(
    project_id: uuid.UUID = Query(...),
    asset_id: uuid.UUID | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> list[KnowledgeChunk]:
    """List knowledge chunks in a project owned by the current user,
    optionally scoped to one asset."""
    try:
        return await service.list_for_owner(
            current_user.id, project_id=project_id, asset_id=asset_id, skip=skip, limit=limit
        )
    except ProjectAccessDeniedError as exc:
        raise _PROJECT_NOT_FOUND from exc


@router.get("/chunks/{chunk_id}", response_model=KnowledgeChunkRead)
async def get_chunk(
    chunk_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> KnowledgeChunk:
    """Fetch a single knowledge chunk owned by the current user."""
    try:
        return await service.get_owned(current_user.id, chunk_id)
    except KnowledgeChunkNotFoundError as exc:
        raise _CHUNK_NOT_FOUND from exc

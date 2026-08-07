"""FastAPI dependency providers for the knowledge base module."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.modules.knowledge_base.service import KnowledgeBaseService


async def get_knowledge_base_service(
    session: AsyncSession = Depends(get_db),
) -> KnowledgeBaseService:
    """FastAPI dependency provider for `KnowledgeBaseService`."""
    return KnowledgeBaseService(session)

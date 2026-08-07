"""FastAPI dependency providers for the research module.

`get_research_service` builds a `ResearchService` from the
request-scoped DB session. `get_owned_run` resolves a run by its path
id and verifies it belongs to the current user, so the read handlers in
`router.py` never repeat that lookup or its not-found handling.
"""

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.modules.auth.models import User
from app.modules.auth.security import get_current_user
from app.modules.research.models import ResearchRun
from app.modules.research.service import ResearchRunNotFoundError, ResearchService


async def get_research_service(session: AsyncSession = Depends(get_db)) -> ResearchService:
    """FastAPI dependency provider for `ResearchService`."""
    return ResearchService(session)


async def get_owned_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: ResearchService = Depends(get_research_service),
) -> ResearchRun:
    """Resolve a research run by id, ensuring it belongs to the current user."""
    try:
        return await service.get_owned_run(current_user.id, run_id)
    except ResearchRunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Research run not found."
        ) from exc

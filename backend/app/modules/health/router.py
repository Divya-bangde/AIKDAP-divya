"""The health route (Sprint 9G).

Replaces the two-line liveness handler that lived in `app.main`. That
one answered "is the process up?", which the TCP connection already
answered; this one answers "is the platform able to do its work?",
which is the question an operator actually has.

Mounted at `/health` with no API version prefix, exactly where the old
handler was. Health is infrastructure, not product surface: monitoring
should not have to be re-pointed when the API version changes, and
nothing about the shape below is part of the versioned contract.

Unauthenticated, like the endpoint it replaces. That is a deliberate
trade — a monitor should not need a credential — and it constrains what
may appear in the response: model ids, endpoints and states, never
credentials, never environment dumps, never raw provider payloads.
Provider error text is scrubbed upstream in `LLMError` before the
registry ever stores it.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.modules.health.schemas import HealthResponse
from app.modules.health.service import HealthService

router = APIRouter(tags=["Health"])


def get_health_service(session: AsyncSession = Depends(get_db)) -> HealthService:
    """Provide a request-scoped health service."""
    return HealthService(session)


@router.get("/health", response_model=HealthResponse)
async def health(
    service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    """Report the operational state of the platform and its dependencies.

    Always answers HTTP 200, whatever it finds. The status lives in the
    body; encoding it in the HTTP status too would mean a liveness
    probe restarting a perfectly healthy container because a
    third-party model provider ran out of free quota for the day.

    Costs nothing meaningful to call: no inference, no reranking, no
    model quota. See `HealthService` for what each component check
    actually does.
    """
    return await service.check()

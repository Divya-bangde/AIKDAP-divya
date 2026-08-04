"""FastAPI application entrypoint.

Creates and configures the FastAPI app: middleware, lifespan hooks,
and the foundation-level routes. Feature routers are mounted under
the versioned API prefix as they are implemented in later milestones.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging.logger import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown events."""
    logger.info(
        "application_startup",
        app_name=settings.app_name,
        app_version=settings.app_version,
        app_env=settings.app_env,
    )
    yield
    logger.info("application_shutdown", app_name=settings.app_name)


app = FastAPI(
    title=settings.app_name,
    description="AI Knowledge Discovery And Analytics Platform API",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Feature routers are registered here under the versioned API prefix
# as they are implemented, e.g.:
# from app.modules.health.router import router as health_router
# app.include_router(health_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """Return basic API metadata."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
    }


@app.get("/health", tags=["Health"])
async def health() -> dict[str, str]:
    """Return the liveness status of the API."""
    return {"status": "ok"}

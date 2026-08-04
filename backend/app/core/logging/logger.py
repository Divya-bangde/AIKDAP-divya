"""Structured logging configuration for the application.

Configures `structlog` to emit either JSON (production) or
human-readable console output (development), bound on top of the
standard library `logging` module so third-party loggers are
formatted consistently.
"""

import logging
import sys

import structlog

from app.core.config import settings

_configured = False


def configure_logging() -> None:
    """Configure structlog and the standard library root logger.

    Safe to call multiple times; configuration is applied only once.
    """
    global _configured
    if _configured:
        return

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level,
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        cache_logger_on_first_use=True,
    )

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structured logger bound to the given name.

    Args:
        name: Logical name for the logger, typically `__name__` of the
            calling module.

    Returns:
        A configured `structlog` bound logger instance.
    """
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)

"""
Structured logging for the platform.

Design rules (enforced here, nowhere else):
  - JSON output in production, colored console in development/staging
  - correlation_id is bound via contextvars — async-safe, automatically
    included in every log record by the merge_contextvars processor
  - configure_logging() is called once at application startup
  - get_logger() is the only import other modules need
  - No module outside platform/ calls structlog.configure() directly

Usage:
    # At app startup (api/main.py, Celery worker entry point):
    from platform.observability.logger import configure_logging
    configure_logging()

    # In any module:
    from platform.observability.logger import get_logger
    log = get_logger(__name__)
    log.info("atom_processed", atom_id="REQ-001", phase=1)

    # At request boundary (FastAPI middleware, Celery task):
    from platform.observability.logger import bind_correlation_id, clear_correlation_id
    bind_correlation_id(request_id)
    ...
    clear_correlation_id()
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
import structlog.contextvars
import structlog.dev
import structlog.processors
import structlog.stdlib

from platform.config.settings import get_settings


def configure_logging(
    *,
    log_level: str | None = None,
    environment: str | None = None,
) -> None:
    """Configure structlog and the stdlib root logger.

    Safe to call multiple times — each call replaces the current
    structlog configuration (idempotent).

    Args:
        log_level: Override settings.log_level.
                   One of: DEBUG | INFO | WARNING | ERROR.
        environment: Override settings.environment.
                     One of: development | staging | production.
                     Controls renderer: JSON for production, ConsoleRenderer otherwise.
    """
    settings = get_settings()
    level_str = (log_level or settings.log_level).upper()
    env = environment or settings.environment
    stdlib_level: int = getattr(logging, level_str)

    shared_processors: list[Any] = [
        # Merge any contextvars (e.g. correlation_id) into the event dict first.
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: Any
    if env == "production":
        renderer = structlog.processors.JSONRenderer()
    else:
        # Use colors only when the stream is an interactive terminal.
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        # make_filtering_bound_logger produces a fast logger that skips
        # log calls below the configured level at the Python level.
        wrapper_class=structlog.make_filtering_bound_logger(stdlib_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        # False so that reconfiguring (e.g. in tests) takes effect immediately.
        cache_logger_on_first_use=False,
    )

    # Mirror level to the stdlib root logger so third-party libraries that
    # use stdlib logging are captured at the same level.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=stdlib_level,
        force=True,
    )


def get_logger(name: str = "") -> Any:
    """Return a structlog BoundLogger for the given name.

    The returned logger automatically includes any values bound via
    bind_correlation_id() in every log record.

    Args:
        name: Logger name, typically __name__ of the calling module.

    Returns:
        A structlog BoundLogger instance.
    """
    return structlog.get_logger(name)


def bind_correlation_id(correlation_id: str) -> None:
    """Bind a correlation_id to the current async/thread context.

    All log calls made after this point in the same context will include
    ``correlation_id`` automatically via the merge_contextvars processor.

    Call clear_correlation_id() at the end of the request/job.
    """
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def clear_correlation_id() -> None:
    """Remove all contextvars bindings from the current context.

    Clears correlation_id and any other values bound via
    structlog.contextvars.bind_contextvars().
    """
    structlog.contextvars.clear_contextvars()

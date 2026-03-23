from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import yaml  # type: ignore[import-untyped]
from fastapi import FastAPI, WebSocket

from api.middleware.cors import add_cors
from api.middleware.logging import RequestLoggingMiddleware
from api.routes.dynafit import public_router
from api.routes.dynafit import router as dynafit_router
from api.websocket.progress import progress_handler
from platform.config.settings import get_settings
from platform.retrieval.vector_store import (
    VectorStore,
    VectorStoreError,
)
from platform.storage.postgres import PostgresStore

log = structlog.get_logger(__name__)

# Root of the project (api/ sits one level below)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _discover_collections() -> tuple[list[str], list[str]]:
    """Derive required Qdrant collections from module manifests.

    Each manifest.yaml may declare a ``product_id``.  The
    pipeline convention is ``{product_id}_capabilities``
    (required) and ``{product_id}_docs`` (optional).
    """
    required: list[str] = []
    optional: list[str] = []
    modules_dir = _PROJECT_ROOT / "modules"
    if not modules_dir.exists():
        return required, optional
    for manifest in modules_dir.rglob("manifest.yaml"):
        try:
            data = yaml.safe_load(
                manifest.read_text(encoding="utf-8"),
            )
        except Exception:
            continue
        pid = data.get("product_id") if data else None
        if pid:
            required.append(f"{pid}_capabilities")
            optional.append(f"{pid}_docs")
    return required, optional


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    # ── Postgres ──────────────────────────────
    store = PostgresStore(settings.postgres_url)
    await store.ensure_schema()
    await store.dispose()

    # ── Qdrant ────────────────────────────────
    await _check_qdrant_collections(settings.qdrant_url)

    yield


async def _check_qdrant_collections(
    qdrant_url: str,
) -> None:
    """Log warnings for missing / empty Qdrant collections.

    Non-fatal: the API starts regardless. Uses platform
    VectorStore abstraction — no direct qdrant_client import.
    """
    import asyncio  # noqa: PLC0415

    required, optional = _discover_collections()

    def _check() -> None:
        try:
            vs = VectorStore(qdrant_url)
            for name in required:
                if not vs.collection_exists(name):
                    log.warning(
                        "qdrant_collection_missing",
                        collection=name,
                        hint="run: make seed-kb-lite",
                    )
                else:
                    count = vs.collection_point_count(name)
                    if count == 0:
                        log.warning(
                            "qdrant_collection_empty",
                            collection=name,
                            hint="run: make seed-kb-lite",
                        )
                    else:
                        log.info(
                            "qdrant_collection_ready",
                            collection=name,
                            points=count,
                        )
            for name in optional:
                if not vs.collection_exists(name):
                    log.info(
                        "qdrant_collection_absent_optional",
                        collection=name,
                    )
        except VectorStoreError as exc:
            log.warning(
                "qdrant_startup_check_failed",
                error=str(exc),
            )
        except Exception as exc:
            log.warning(
                "qdrant_startup_check_failed",
                error=str(exc),
            )

    await asyncio.to_thread(_check)


app = FastAPI(
    title="Enterprise AI Platform",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

add_cors(app)
app.add_middleware(RequestLoggingMiddleware)
app.include_router(dynafit_router, prefix="/api/v1")
app.include_router(public_router, prefix="/api")


@app.websocket("/api/v1/ws/progress/{batch_id}")
async def ws_progress(websocket: WebSocket, batch_id: str) -> None:
    await progress_handler(websocket, batch_id)


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok"}

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket
from prometheus_client import make_asgi_app
from starlette.routing import Mount

import structlog

from api.middleware.cors import add_cors
from api.middleware.logging import RequestLoggingMiddleware
from api.routes.dynafit import router as dynafit_router
from api.websocket.progress import progress_handler
from platform.config.settings import get_settings
from platform.storage.postgres import PostgresStore

log = structlog.get_logger(__name__)

# Qdrant collections the pipeline depends on — checked at startup.
_REQUIRED_COLLECTIONS = ["d365_fo_capabilities"]
_OPTIONAL_COLLECTIONS = ["d365_fo_docs"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    # ── Postgres: apply all pending migrations ────────────────────────────────
    store = PostgresStore(settings.postgres_url)
    await store.ensure_schema()
    await store.dispose()

    # ── Qdrant: warn if required collections are absent or empty ─────────────
    await _check_qdrant_collections(settings.qdrant_url)

    yield


async def _check_qdrant_collections(qdrant_url: str) -> None:
    """Log warnings for missing or empty Qdrant collections.

    Non-fatal: the API starts regardless. An empty capabilities collection
    means retrieval returns 0 hits — run `make seed-kb-lite` to populate.
    """
    import asyncio

    def _check() -> None:
        try:
            from qdrant_client import QdrantClient  # noqa: PLC0415

            client = QdrantClient(url=qdrant_url, timeout=5)
            for name in _REQUIRED_COLLECTIONS:
                if not client.collection_exists(name):
                    log.warning(
                        "qdrant_collection_missing",
                        collection=name,
                        hint="run: make seed-kb-lite",
                    )
                else:
                    info = client.get_collection(name)
                    count = info.points_count or 0
                    if count == 0:
                        log.warning(
                            "qdrant_collection_empty",
                            collection=name,
                            hint="run: make seed-kb-lite",
                        )
                    else:
                        log.info("qdrant_collection_ready", collection=name, points=count)
            for name in _OPTIONAL_COLLECTIONS:
                if not client.collection_exists(name):
                    log.info(
                        "qdrant_collection_absent_optional",
                        collection=name,
                        note="Source B (MS Learn docs) not seeded — retrieval uses A+C only",
                    )
        except Exception as exc:
            log.warning("qdrant_startup_check_failed", error=str(exc))

    await asyncio.to_thread(_check)


app = FastAPI(
    title="Enterprise AI Platform",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    routes=[Mount("/metrics", make_asgi_app())],
    lifespan=lifespan,
)

add_cors(app)
app.add_middleware(RequestLoggingMiddleware)
app.include_router(dynafit_router, prefix="/api/v1")


@app.websocket("/api/v1/ws/progress/{batch_id}")
async def ws_progress(websocket: WebSocket, batch_id: str) -> None:
    await progress_handler(websocket, batch_id)


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok"}

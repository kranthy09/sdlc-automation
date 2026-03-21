from __future__ import annotations

from fastapi import FastAPI, WebSocket

from api.middleware.cors import add_cors
from api.middleware.logging import RequestLoggingMiddleware
from api.routes.dynafit import router as dynafit_router
from api.websocket.progress import progress_handler

app = FastAPI(
    title="Enterprise AI Platform",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
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

"""
Async PostgreSQL store for upload metadata and historical fitment records.

Two tables:
  uploads  — tracks document uploads (metadata only, no file bytes)
  fitments — ClassificationResult + pgvector embedding for Source C retrieval

The fitments table carries a pgvector HNSW index for sub-linear cosine
similarity search. Phase 2 queries it to surface historically validated
fitment decisions that match the current requirement's semantic embedding.

Reviewer overrides (reviewer_override=True) are re-sorted to the front of
get_similar_fitments results so Phase 4 treats consultant decisions as the
strongest available classification evidence.

Every SQL call is wrapped in record_call("postgres", ...) for Prometheus.

Usage:
    from platform.storage.postgres import PostgresStore

    store = PostgresStore(settings.postgres_url)
    await store.ensure_schema()           # idempotent — call once at startup

    # Track an upload
    await store.save_upload(raw_upload)
    await store.update_upload_status(upload_id, "complete")

    # Phase 5 write-back
    await store.save_fitment(result, embedding, upload_id=uid, product_id=pid)

    # Phase 2 retrieval — Source C
    priors = await store.get_similar_fitments(embedding, top_k=5, module="AccountsPayable")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from prometheus_client import CollectorRegistry

from platform.observability.logger import get_logger
from platform.observability.metrics import MetricsRecorder
from platform.schemas.fitment import ClassificationResult, FitLabel
from platform.schemas.requirement import RawUpload
from platform.schemas.retrieval import PriorFitment

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class PostgresError(Exception):
    """Raised when a PostgreSQL operation fails."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        self.cause = cause
        super().__init__(message)


# ---------------------------------------------------------------------------
# UploadRecord DTO  (no file bytes — too large for the DB)
# ---------------------------------------------------------------------------


@dataclass
class UploadRecord:
    """Upload metadata as stored in the DB (file bytes are not persisted)."""

    upload_id: str
    product_id: str
    filename: str
    wave: int
    country: str
    status: str
    created_at: datetime


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL: list[str] = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS uploads (
        upload_id   TEXT         PRIMARY KEY,
        product_id  TEXT         NOT NULL,
        filename    TEXT         NOT NULL,
        wave        INTEGER      NOT NULL DEFAULT 1,
        country     TEXT         NOT NULL DEFAULT '',
        status      TEXT         NOT NULL DEFAULT 'pending',
        created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fitments (
        id                BIGSERIAL    PRIMARY KEY,
        atom_id           TEXT         NOT NULL,
        upload_id         TEXT         NOT NULL,
        product_id        TEXT         NOT NULL,
        module            TEXT         NOT NULL,
        country           TEXT         NOT NULL,
        wave              INTEGER      NOT NULL,
        classification    TEXT         NOT NULL,
        confidence        FLOAT        NOT NULL,
        rationale         TEXT         NOT NULL,
        reviewer_override BOOLEAN      NOT NULL DEFAULT FALSE,
        consultant        TEXT,
        embedding         vector(1024),
        created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS fitments_hnsw
    ON fitments USING hnsw (embedding vector_cosine_ops)
    """,
]


# ---------------------------------------------------------------------------
# PostgresStore
# ---------------------------------------------------------------------------


class PostgresStore:
    """Async SQLAlchemy store for uploads and fitment history.

    Args:
        url:      Async SQLAlchemy DSN — postgresql+asyncpg://user:pw@host/db.
        registry: Prometheus CollectorRegistry. Inject a fresh one in tests.
        _engine:  Pre-built async engine — for testing only; bypasses lazy init.
    """

    def __init__(
        self,
        url: str,
        *,
        registry: CollectorRegistry | None = None,
        _engine: Any = None,
    ) -> None:
        self._url = url
        self._recorder = MetricsRecorder(registry)
        self._engine: Any = _engine

    # ------------------------------------------------------------------
    # Engine (lazy)
    # ------------------------------------------------------------------

    def _get_engine(self) -> Any:
        if self._engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415

            log.info("postgres_connect", url=self._url)
            self._engine = create_async_engine(self._url, pool_pre_ping=True)
        return self._engine

    async def dispose(self) -> None:
        """Close all pooled connections. Call in test teardown."""
        if self._engine is not None:
            await self._engine.dispose()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    async def ensure_schema(self) -> None:
        """Create the vector extension, tables, and HNSW index (idempotent)."""
        from sqlalchemy import text  # noqa: PLC0415

        engine = self._get_engine()
        try:
            with self._recorder.record_call("postgres", "ensure_schema"):
                async with engine.begin() as conn:
                    for stmt in _DDL:
                        await conn.execute(text(stmt))
            log.info("postgres_schema_ready")
        except Exception as exc:
            raise PostgresError(f"ensure_schema failed: {exc}", cause=exc) from exc

    # ------------------------------------------------------------------
    # Uploads
    # ------------------------------------------------------------------

    async def save_upload(self, upload: RawUpload) -> None:
        """Insert upload metadata. Idempotent on upload_id (ON CONFLICT DO NOTHING)."""
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text(
            """
            INSERT INTO uploads (upload_id, product_id, filename, wave, country, status)
            VALUES (:upload_id, :product_id, :filename, :wave, :country, 'pending')
            ON CONFLICT (upload_id) DO NOTHING
            """
        )
        params: dict[str, Any] = {
            "upload_id": upload.upload_id,
            "product_id": upload.product_id,
            "filename": upload.filename,
            "wave": upload.wave,
            "country": upload.country,
        }
        engine = self._get_engine()
        try:
            with self._recorder.record_call("postgres", "save_upload"):
                async with engine.begin() as conn:
                    await conn.execute(stmt, params)
            log.debug("postgres_upload_saved", upload_id=upload.upload_id)
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"save_upload({upload.upload_id!r}) failed: {exc}", cause=exc
            ) from exc

    async def update_upload_status(self, upload_id: str, status: str) -> None:
        """Update the processing status of an upload."""
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text("UPDATE uploads SET status = :status WHERE upload_id = :upload_id")
        engine = self._get_engine()
        try:
            with self._recorder.record_call("postgres", "update_upload"):
                async with engine.begin() as conn:
                    await conn.execute(stmt, {"status": status, "upload_id": upload_id})
            log.debug("postgres_upload_status_updated", upload_id=upload_id, status=status)
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"update_upload_status({upload_id!r}) failed: {exc}", cause=exc
            ) from exc

    # ------------------------------------------------------------------
    # Fitments
    # ------------------------------------------------------------------

    async def save_fitment(
        self,
        result: ClassificationResult,
        embedding: list[float],
        *,
        upload_id: str,
        product_id: str,
        reviewer_override: bool = False,
        consultant: str | None = None,
    ) -> None:
        """Persist a ClassificationResult with its pgvector embedding.

        Only FIT, PARTIAL_FIT, and GAP classifications are accepted.
        REVIEW_REQUIRED decisions are not final and must not be persisted.

        Args:
            result:            Phase 4 or Phase 5 classification result.
            embedding:         1024-dim dense embedding of the requirement text.
            upload_id:         ID of the upload this result belongs to.
            product_id:        Product ID (e.g. "d365_fo").
            reviewer_override: True when a consultant changed the AI verdict.
            consultant:        Consultant identifier (set when reviewer_override=True).
        """
        if result.classification == FitLabel.REVIEW_REQUIRED:
            raise ValueError(
                "Cannot persist REVIEW_REQUIRED fitments — classification must be final."
            )
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text(
            """
            INSERT INTO fitments
                (atom_id, upload_id, product_id, module, country, wave,
                 classification, confidence, rationale,
                 reviewer_override, consultant, embedding)
            VALUES
                (:atom_id, :upload_id, :product_id, :module, :country, :wave,
                 :classification, :confidence, :rationale,
                 :reviewer_override, :consultant, CAST(:embedding AS vector))
            """
        )
        params: dict[str, Any] = {
            "atom_id": result.atom_id,
            "upload_id": upload_id,
            "product_id": product_id,
            "module": result.module,
            "country": result.country,
            "wave": result.wave,
            "classification": str(result.classification),
            "confidence": result.confidence,
            "rationale": result.rationale,
            "reviewer_override": reviewer_override,
            "consultant": consultant,
            "embedding": _vec_str(embedding),
        }
        engine = self._get_engine()
        try:
            with self._recorder.record_call("postgres", "save_fitment"):
                async with engine.begin() as conn:
                    await conn.execute(stmt, params)
            log.debug("postgres_fitment_saved", atom_id=result.atom_id)
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"save_fitment({result.atom_id!r}) failed: {exc}", cause=exc
            ) from exc

    async def get_similar_fitments(
        self,
        embedding: list[float],
        top_k: int,
        *,
        module: str | None = None,
    ) -> list[PriorFitment]:
        """Return fitments semantically similar to *embedding*.

        Results are fetched by cosine distance (closest first). Within the
        returned set, reviewer overrides are re-sorted to the front so Phase 4
        treats consultant-validated decisions as the strongest evidence.

        Fetches 2×top_k from the DB then trims to top_k after re-sort so that
        override records are not lost to the LIMIT before the re-sort runs.

        Args:
            embedding: 1024-dim dense query vector.
            top_k:     Maximum number of results to return.
            module:    Optional D365 module filter (exact match).
        """
        from sqlalchemy import text  # noqa: PLC0415

        fetch_k = top_k * 2
        if module is not None:
            sql = """
                SELECT atom_id, wave, country, classification, confidence,
                       rationale, reviewer_override, consultant
                FROM fitments
                WHERE embedding IS NOT NULL AND module = :module
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :fetch_k
            """
            params: dict[str, Any] = {
                "vec": _vec_str(embedding),
                "module": module,
                "fetch_k": fetch_k,
            }
        else:
            sql = """
                SELECT atom_id, wave, country, classification, confidence,
                       rationale, reviewer_override, consultant
                FROM fitments
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :fetch_k
            """
            params = {"vec": _vec_str(embedding), "fetch_k": fetch_k}

        engine = self._get_engine()
        try:
            with self._recorder.record_call("postgres", "get_similar_fitments"):
                async with engine.connect() as conn:
                    rows = (await conn.execute(text(sql), params)).mappings().all()
            fitments = [_row_to_prior(r) for r in rows]
            # Reviewer overrides to the front; stable sort preserves similarity order within tier.
            fitments.sort(key=lambda f: 0 if f.reviewer_override else 1)
            return fitments[:top_k]
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(f"get_similar_fitments failed: {exc}", cause=exc) from exc


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _vec_str(embedding: list[float]) -> str:
    """Convert a float list to pgvector literal format: '[0.1,0.2,...]'."""
    return "[" + ",".join(map(str, embedding)) + "]"


def _row_to_prior(row: Any) -> PriorFitment:
    return PriorFitment(
        atom_id=row["atom_id"],
        wave=row["wave"],
        country=row["country"],
        classification=row["classification"],
        confidence=row["confidence"],
        rationale=row["rationale"],
        reviewer_override=row["reviewer_override"],
        consultant=row["consultant"],
    )

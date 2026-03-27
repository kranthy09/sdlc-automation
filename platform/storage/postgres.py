"""
Async PostgreSQL store for upload metadata, batch results, and historical fitment records.

Tables:
  uploads       — tracks document uploads (metadata only, no file bytes)
  batches       — pipeline run metadata and summary
  batch_results — per-atom results for completed batches (source of truth for /results API)
  review_items  — HITL review decisions during Phase 5 pause
  fitments      — ClassificationResult + pgvector embedding for Source C retrieval

The fitments table carries a pgvector HNSW index for sub-linear cosine
similarity search. Phase 2 queries it to surface historically validated
fitment decisions that match the current requirement's semantic embedding.

Reviewer overrides (reviewer_override=True) are re-sorted to the front of
get_similar_fitments results so Phase 4 treats consultant decisions as the
strongest available classification evidence.

The batch_results table is populated by the Celery worker during pipeline
completion (via save_batch_results). It replaces the previous pattern of
deriving results on-demand from Redis journey data.

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

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from platform.observability.logger import get_logger
from platform.schemas.fitment import ClassificationResult, FitLabel
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
    content_hash: str = ""
    path: str = ""
    size_bytes: int = 0
    detected_format: str = ""


@dataclass
class BatchRecord:
    """Batch metadata as stored in DB (lifecycle and results summary)."""

    batch_id: str
    upload_id: str
    product_id: str
    country: str
    wave: int
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    report_path: str | None = None
    summary: dict[str, Any] | None = None
    upload_filename: str = ""


@dataclass
class ReviewItemRecord:
    """HITL review decision as stored in DB."""

    batch_id: str
    atom_id: str
    ai_classification: str
    ai_confidence: float | None = None
    decision: str | None = None  # APPROVE, OVERRIDE
    override_classification: str | None = None
    reviewer: str | None = None
    reviewed: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Rich HITL context (V6 migration)
    requirement_text: str = ""
    ai_rationale: str = ""
    review_reason: str = ""
    module: str = ""
    evidence: dict[str, Any] | None = None
    config_steps: str | None = None
    gap_description: str | None = None
    configuration_steps: list[str] | None = None
    dev_effort: str | None = None
    gap_type: str | None = None


@dataclass
class BatchResultRecord:
    """Per-atom result as stored in batch_results table."""

    batch_id: str
    atom_id: str
    requirement_text: str
    classification: str
    confidence: float
    module: str
    country: str
    wave: int
    rationale: str = ""
    reviewer_override: bool = False
    d365_capability: str = ""
    d365_navigation: str = ""
    config_steps: str | None = None
    gap_description: str | None = None
    configuration_steps: list[str] | None = None
    dev_effort: str | None = None
    gap_type: str | None = None
    evidence: dict[str, Any] | None = None


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
        embedding         vector(384),
        created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS fitments_hnsw
    ON fitments USING hnsw (embedding vector_cosine_ops)
    """,
    # V1 migration — idempotent; ensures column exists on both fresh and existing DBs.
    "ALTER TABLE fitments ADD COLUMN IF NOT EXISTS d365_capability_ref TEXT",
    # V2 migration — classification detail columns.
    "ALTER TABLE fitments ADD COLUMN IF NOT EXISTS config_steps TEXT",
    "ALTER TABLE fitments ADD COLUMN IF NOT EXISTS gap_description TEXT",
    "ALTER TABLE fitments ADD COLUMN IF NOT EXISTS configuration_steps JSONB",
    "ALTER TABLE fitments ADD COLUMN IF NOT EXISTS dev_effort TEXT",
    "ALTER TABLE fitments ADD COLUMN IF NOT EXISTS gap_type TEXT",
    # V3 migration — upload metadata columns for route-level persistence.
    "ALTER TABLE uploads ADD COLUMN IF NOT EXISTS content_hash TEXT",
    "ALTER TABLE uploads ADD COLUMN IF NOT EXISTS path TEXT",
    "ALTER TABLE uploads ADD COLUMN IF NOT EXISTS size_bytes BIGINT DEFAULT 0",
    "ALTER TABLE uploads ADD COLUMN IF NOT EXISTS detected_format TEXT DEFAULT ''",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uploads_content_hash_idx
    ON uploads (content_hash) WHERE content_hash IS NOT NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS batches (
        batch_id        TEXT         PRIMARY KEY,
        upload_id       TEXT         NOT NULL REFERENCES uploads(upload_id),
        product_id      TEXT         NOT NULL,
        country         TEXT         NOT NULL,
        wave            INTEGER      NOT NULL,
        status          TEXT         NOT NULL,
        created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        completed_at    TIMESTAMPTZ  NULL,
        report_path     TEXT         NULL,
        summary         JSONB        NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS batches_status_created_at
    ON batches (status, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS review_items (
        id                    BIGSERIAL    PRIMARY KEY,
        batch_id              TEXT         NOT NULL REFERENCES batches(batch_id),
        atom_id               TEXT         NOT NULL,
        ai_classification    TEXT         NOT NULL,
        ai_confidence         FLOAT        NULL,
        decision              TEXT         NULL,
        override_classification TEXT       NULL,
        reviewer              TEXT         NULL,
        reviewed              BOOLEAN      NOT NULL DEFAULT FALSE,
        created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        UNIQUE(batch_id, atom_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS review_items_batch_id
    ON review_items (batch_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS review_items_batch_atom
    ON review_items (batch_id, atom_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS batch_results (
        id                BIGSERIAL    PRIMARY KEY,
        batch_id          TEXT         NOT NULL REFERENCES batches(batch_id),
        atom_id           TEXT         NOT NULL,
        requirement_text  TEXT         NOT NULL,
        classification    TEXT         NOT NULL,
        confidence        FLOAT        NOT NULL,
        module            TEXT         NOT NULL,
        country           TEXT         NOT NULL DEFAULT '',
        wave              INTEGER      NOT NULL DEFAULT 1,
        rationale         TEXT         NOT NULL DEFAULT '',
        reviewer_override BOOLEAN      NOT NULL DEFAULT FALSE,
        d365_capability   TEXT         NOT NULL DEFAULT '',
        d365_navigation   TEXT         NOT NULL DEFAULT '',
        config_steps      TEXT,
        gap_description   TEXT,
        configuration_steps JSONB,
        dev_effort        TEXT,
        gap_type          TEXT,
        evidence          JSONB        NOT NULL DEFAULT '{}',
        created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        UNIQUE(batch_id, atom_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS batch_results_batch_id
    ON batch_results (batch_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS batch_results_batch_classification
    ON batch_results (batch_id, classification)
    """,
    """
    CREATE INDEX IF NOT EXISTS batch_results_batch_module
    ON batch_results (batch_id, module)
    """,
    # V4 migration — add UNIQUE constraint needed by ON CONFLICT upsert in
    # save_batch_results(). Fresh tables get it from DDL above; existing tables
    # need this index-based migration (idempotent via IF NOT EXISTS).
    """
    CREATE UNIQUE INDEX IF NOT EXISTS batch_results_batch_atom_unique
    ON batch_results (batch_id, atom_id)
    """,
    # V5 migration — add ai_confidence to review_items for HITL display.
    "ALTER TABLE review_items ADD COLUMN IF NOT EXISTS ai_confidence FLOAT",
    # V6 migration — add rich HITL context columns so evidence survives Redis expiry.
    "ALTER TABLE review_items ADD COLUMN IF NOT EXISTS requirement_text TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE review_items ADD COLUMN IF NOT EXISTS ai_rationale TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE review_items ADD COLUMN IF NOT EXISTS review_reason TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE review_items ADD COLUMN IF NOT EXISTS module TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE review_items ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '{}'",
    "ALTER TABLE review_items ADD COLUMN IF NOT EXISTS config_steps TEXT",
    "ALTER TABLE review_items ADD COLUMN IF NOT EXISTS gap_description TEXT",
    "ALTER TABLE review_items ADD COLUMN IF NOT EXISTS configuration_steps JSONB",
    "ALTER TABLE review_items ADD COLUMN IF NOT EXISTS dev_effort TEXT",
    "ALTER TABLE review_items ADD COLUMN IF NOT EXISTS gap_type TEXT",
]


# ---------------------------------------------------------------------------
# PostgresStore
# ---------------------------------------------------------------------------


class PostgresStore:
    """Async SQLAlchemy store for uploads and fitment history.

    Args:
        url:      Async SQLAlchemy DSN — postgresql+asyncpg://user:pw@host/db.
        _engine:  Pre-built async engine — for testing only; bypasses lazy init.
    """

    def __init__(
        self,
        url: str,
        *,
        _engine: Any = None,
    ) -> None:
        self._url = url
        self._engine: Any = _engine

    # ------------------------------------------------------------------
    # Engine (lazy)
    # ------------------------------------------------------------------

    def _get_engine(self) -> Any:
        if self._engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415

            log.info("postgres_connect", url=self._url)
            self._engine = create_async_engine(
                self._url,
                pool_pre_ping=True,
                pool_size=1,
                max_overflow=0,
            )
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
            async with engine.begin() as conn:
                for stmt in _DDL:
                    await conn.execute(text(stmt))
            log.info("postgres_schema_ready")
        except Exception as exc:
            raise PostgresError(f"ensure_schema failed: {exc}", cause=exc) from exc

    # ------------------------------------------------------------------
    # Uploads
    # ------------------------------------------------------------------

    async def save_upload(
        self,
        record: UploadRecord,
    ) -> None:
        """Insert upload metadata. Idempotent on upload_id."""
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text(
            """
            INSERT INTO uploads (
                upload_id, product_id, filename, wave,
                country, status, content_hash, path,
                size_bytes, detected_format
            )
            VALUES (
                :upload_id, :product_id, :filename, :wave,
                :country, :status, :content_hash, :path,
                :size_bytes, :detected_format
            )
            ON CONFLICT (upload_id) DO NOTHING
            """
        )
        params: dict[str, Any] = {
            "upload_id": record.upload_id,
            "product_id": record.product_id,
            "filename": record.filename,
            "wave": record.wave,
            "country": record.country,
            "status": record.status,
            "content_hash": record.content_hash,
            "path": record.path,
            "size_bytes": record.size_bytes,
            "detected_format": record.detected_format,
        }
        engine = self._get_engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(stmt, params)
            log.debug(
                "postgres_upload_saved",
                upload_id=record.upload_id,
            )
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"save_upload({record.upload_id!r}) failed",
                cause=exc,
            ) from exc

    async def get_upload_by_hash(
        self,
        content_hash: str,
    ) -> UploadRecord | None:
        """Find an existing upload by SHA-256 content hash."""
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text(
            """
            SELECT upload_id, product_id, filename, wave,
                   country, status, created_at, content_hash,
                   path, size_bytes, detected_format
            FROM uploads
            WHERE content_hash = :content_hash
            LIMIT 1
            """
        )
        engine = self._get_engine()
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        stmt, {"content_hash": content_hash},
                    )
                ).mappings().first()
            if row is None:
                return None
            return _row_to_upload(row)
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                "get_upload_by_hash failed",
                cause=exc,
            ) from exc

    async def get_upload_by_id(
        self,
        upload_id: str,
    ) -> UploadRecord | None:
        """Fetch a single upload by its ID."""
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text(
            """
            SELECT upload_id, product_id, filename, wave,
                   country, status, created_at, content_hash,
                   path, size_bytes, detected_format
            FROM uploads
            WHERE upload_id = :upload_id
            """
        )
        engine = self._get_engine()
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        stmt, {"upload_id": upload_id},
                    )
                ).mappings().first()
            if row is None:
                return None
            return _row_to_upload(row)
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"get_upload_by_id({upload_id!r}) failed",
                cause=exc,
            ) from exc

    async def update_upload_status(
        self,
        upload_id: str,
        status: str,
    ) -> None:
        """Update the processing status of an upload."""
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text(
            "UPDATE uploads SET status = :status"
            " WHERE upload_id = :upload_id"
        )
        engine = self._get_engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    stmt,
                    {"status": status, "upload_id": upload_id},
                )
            log.debug(
                "postgres_upload_status_updated",
                upload_id=upload_id,
                status=status,
            )
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"update_upload_status({upload_id!r}) failed",
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Batches
    # ------------------------------------------------------------------

    async def save_batch(
        self,
        record: BatchRecord,
    ) -> None:
        """Insert batch metadata. Idempotent on batch_id."""
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text(
            """
            INSERT INTO batches (
                batch_id, upload_id, product_id, country,
                wave, status, created_at, completed_at,
                report_path, summary
            )
            VALUES (
                :batch_id, :upload_id, :product_id, :country,
                :wave, :status, :created_at, :completed_at,
                :report_path, :summary
            )
            ON CONFLICT (batch_id) DO NOTHING
            """
        )
        params: dict[str, Any] = {
            "batch_id": record.batch_id,
            "upload_id": record.upload_id,
            "product_id": record.product_id,
            "country": record.country,
            "wave": record.wave,
            "status": record.status,
            "created_at": record.created_at,
            "completed_at": record.completed_at,
            "report_path": record.report_path,
            "summary": (
                json.dumps(record.summary)
                if record.summary else None
            ),
        }
        engine = self._get_engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(stmt, params)
            log.debug(
                "postgres_batch_saved",
                batch_id=record.batch_id,
            )
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"save_batch({record.batch_id!r}) failed",
                cause=exc,
            ) from exc

    async def get_batch_by_id(
        self,
        batch_id: str,
    ) -> BatchRecord | None:
        """Fetch a single batch by its ID."""
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text(
            """
            SELECT batch_id, upload_id, product_id, country,
                   wave, status, created_at, completed_at,
                   report_path, summary
            FROM batches
            WHERE batch_id = :batch_id
            """
        )
        engine = self._get_engine()
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        stmt, {"batch_id": batch_id},
                    )
                ).mappings().first()
            if row is None:
                return None
            return _row_to_batch(row)
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"get_batch_by_id({batch_id!r}) failed",
                cause=exc,
            ) from exc

    async def update_batch_status(
        self,
        batch_id: str,
        status: str,
    ) -> None:
        """Update the processing status of a batch."""
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text(
            """
            UPDATE batches SET status = :status
            WHERE batch_id = :batch_id
            """
        )
        engine = self._get_engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    stmt,
                    {"status": status, "batch_id": batch_id},
                )
            log.debug(
                "postgres_batch_status_updated",
                batch_id=batch_id,
                status=status,
            )
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"update_batch_status({batch_id!r}) failed",
                cause=exc,
            ) from exc

    async def update_batch_on_complete(
        self,
        batch_id: str,
        completed_at: datetime,
        report_path: str,
        summary: dict[str, Any],
    ) -> None:
        """Update batch completion metadata."""
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text(
            """
            UPDATE batches
            SET status = 'complete',
                completed_at = :completed_at,
                report_path = :report_path,
                summary = CAST(:summary AS JSONB)
            WHERE batch_id = :batch_id
            """
        )
        engine = self._get_engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    stmt,
                    {
                        "batch_id": batch_id,
                        "completed_at": completed_at,
                        "report_path": report_path,
                        "summary": json.dumps(summary),
                    },
                )
            log.debug(
                "postgres_batch_completed",
                batch_id=batch_id,
            )
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"update_batch_on_complete({batch_id!r}) failed",
                cause=exc,
            ) from exc

    async def list_batches(
        self,
        country: str | None = None,
        wave: int | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[BatchRecord]:
        """List batches with optional filters, ordered by created_at DESC."""
        from sqlalchemy import text  # noqa: PLC0415

        where_clauses: list[str] = []
        params: dict[str, Any] = {"offset": offset, "limit": limit}

        if country is not None:
            where_clauses.append("b.country = :country")
            params["country"] = country
        if wave is not None:
            where_clauses.append("b.wave = :wave")
            params["wave"] = wave
        if status is not None:
            where_clauses.append("b.status = :status")
            params["status"] = status

        where_clause = (
            "WHERE " + " AND ".join(where_clauses)
            if where_clauses
            else ""
        )

        sql = f"""
            SELECT b.batch_id, b.upload_id, b.product_id, b.country,
                   b.wave, b.status, b.created_at, b.completed_at,
                   b.report_path, b.summary, COALESCE(u.filename, '') AS upload_filename
            FROM batches b
            LEFT JOIN uploads u ON b.upload_id = u.upload_id
            {where_clause}
            ORDER BY b.created_at DESC
            OFFSET :offset LIMIT :limit
        """
        engine = self._get_engine()
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(text(sql), params)
                ).mappings().all()
            return [_row_to_batch(row) for row in rows]
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                "list_batches failed",
                cause=exc,
            ) from exc

    async def count_batches(
        self,
        country: str | None = None,
        wave: int | None = None,
        status: str | None = None,
    ) -> int:
        """Count total batches matching optional filters.

        Returns the total count (without LIMIT) for pagination.
        """
        from sqlalchemy import text  # noqa: PLC0415

        where_clauses: list[str] = []
        params: dict[str, Any] = {}

        if country is not None:
            where_clauses.append("country = :country")
            params["country"] = country
        if wave is not None:
            where_clauses.append("wave = :wave")
            params["wave"] = wave
        if status is not None:
            where_clauses.append("status = :status")
            params["status"] = status

        where_clause = (
            "WHERE " + " AND ".join(where_clauses)
            if where_clauses
            else ""
        )

        sql = f"""
            SELECT COUNT(*) as total
            FROM batches
            {where_clause}
        """
        engine = self._get_engine()
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(text(sql), params)
                ).mappings().first()
            return int(row["total"] if row else 0)
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                "count_batches failed",
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Review Items (HITL decisions)
    # ------------------------------------------------------------------

    async def save_review_decision(
        self,
        batch_id: str,
        atom_id: str,
        ai_classification: str,
        decision: str | None = None,
        override_classification: str | None = None,
        reviewer: str | None = None,
    ) -> None:
        """Save or update a review decision for an atom."""
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text(
            """
            INSERT INTO review_items (
                batch_id, atom_id, ai_classification, decision,
                override_classification, reviewer, reviewed
            )
            VALUES (
                :batch_id, :atom_id, :ai_classification, :decision,
                :override_classification, :reviewer, :reviewed
            )
            ON CONFLICT (batch_id, atom_id) DO UPDATE SET
                decision = :decision,
                override_classification = :override_classification,
                reviewer = :reviewer,
                reviewed = TRUE,
                updated_at = NOW()
            """
        )
        engine = self._get_engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    stmt,
                    {
                        "batch_id": batch_id,
                        "atom_id": atom_id,
                        "ai_classification": ai_classification,
                        "decision": decision,
                        "override_classification": override_classification,
                        "reviewer": reviewer,
                        "reviewed": decision is not None,
                    },
                )
            log.debug(
                "postgres_review_decision_saved",
                batch_id=batch_id,
                atom_id=atom_id,
            )
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"save_review_decision({batch_id!r}, {atom_id!r}) failed",
                cause=exc,
            ) from exc

    async def get_review_items_by_batch(
        self,
        batch_id: str,
    ) -> list[ReviewItemRecord]:
        """Fetch all review items for a batch."""
        from sqlalchemy import text  # noqa: PLC0415

        stmt = text(
            """
            SELECT batch_id, atom_id, ai_classification, ai_confidence,
                   decision, override_classification, reviewer, reviewed,
                   created_at, updated_at,
                   requirement_text, ai_rationale, review_reason, module,
                   evidence, config_steps, gap_description,
                   configuration_steps, dev_effort, gap_type
            FROM review_items
            WHERE batch_id = :batch_id
            ORDER BY created_at ASC
            """
        )
        engine = self._get_engine()
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        stmt, {"batch_id": batch_id},
                    )
                ).mappings().all()
            return [_row_to_review_item(row) for row in rows]
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"get_review_items_by_batch({batch_id!r}) failed",
                cause=exc,
            ) from exc

    async def save_review_items(
        self,
        batch_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        """Bulk insert flagged items into review_items table during HITL.

        Called by _finish_hitl to persist flagged atoms for the review queue.
        Each item is inserted with decision=None, reviewed=False (awaiting review).

        Args:
            batch_id: The batch identifier.
            items: List of dicts from build_hitl_data["review_items"].
                   Each must have: atom_id, ai_classification.
        """
        from sqlalchemy import text  # noqa: PLC0415

        if not items:
            return

        stmt = text(
            """
            INSERT INTO review_items (
                batch_id, atom_id, ai_classification, ai_confidence,
                requirement_text, ai_rationale, review_reason, module,
                evidence, config_steps, gap_description,
                configuration_steps, dev_effort, gap_type,
                decision, reviewed
            )
            VALUES (
                :batch_id, :atom_id, :ai_classification, :ai_confidence,
                :requirement_text, :ai_rationale, :review_reason, :module,
                CAST(:evidence AS JSONB), :config_steps, :gap_description,
                CAST(:configuration_steps AS JSONB), :dev_effort, :gap_type,
                NULL, FALSE
            )
            ON CONFLICT (batch_id, atom_id) DO NOTHING
            """
        )
        engine = self._get_engine()
        try:
            async with engine.begin() as conn:
                for item in items:
                    evidence = item.get("evidence") or {}
                    config_steps_list = item.get("configuration_steps")
                    await conn.execute(
                        stmt,
                        {
                            "batch_id": batch_id,
                            "atom_id": item["atom_id"],
                            "ai_classification": item["ai_classification"],
                            "ai_confidence": item.get("ai_confidence"),
                            "requirement_text": item.get("requirement_text", ""),
                            "ai_rationale": item.get("ai_rationale", ""),
                            "review_reason": item.get("review_reason", ""),
                            "module": item.get("module", ""),
                            "evidence": json.dumps(evidence),
                            "config_steps": item.get("config_steps"),
                            "gap_description": item.get("gap_description"),
                            "configuration_steps": (
                                json.dumps(config_steps_list)
                                if config_steps_list is not None else None
                            ),
                            "dev_effort": item.get("dev_effort"),
                            "gap_type": item.get("gap_type"),
                        },
                    )
            log.debug(
                "review_items_saved_to_postgres",
                batch_id=batch_id,
                count=len(items),
            )
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"save_review_items({batch_id!r}) failed",
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Batch Results
    # ------------------------------------------------------------------

    async def save_batch_results(
        self,
        batch_id: str,
        results: list[dict[str, Any]],
    ) -> None:
        """Bulk insert batch results into the batch_results table.

        Args:
            batch_id: The batch identifier.
            results:  List of result dicts (from build_complete_data or build_hitl_data).
                      Each dict must have at minimum: atom_id, requirement_text,
                      classification, confidence, module, country, wave.
        """
        if not results:
            log.debug("save_batch_results_empty", batch_id=batch_id)
            return

        from sqlalchemy import text  # noqa: PLC0415

        # Build individual INSERT statements for each result
        # Use ON CONFLICT to handle re-writes during HITL resume
        stmt = text(
            """
            INSERT INTO batch_results (
                batch_id, atom_id, requirement_text, classification, confidence,
                module, country, wave, rationale, reviewer_override,
                d365_capability, d365_navigation, config_steps, gap_description,
                configuration_steps, dev_effort, gap_type, evidence
            )
            VALUES (
                :batch_id, :atom_id, :requirement_text, :classification, :confidence,
                :module, :country, :wave, :rationale, :reviewer_override,
                :d365_capability, :d365_navigation, :config_steps, :gap_description,
                :configuration_steps, :dev_effort, :gap_type, CAST(:evidence AS JSONB)
            )
            ON CONFLICT (batch_id, atom_id) DO UPDATE SET
                classification = :classification,
                confidence = :confidence,
                rationale = :rationale,
                reviewer_override = :reviewer_override,
                d365_capability = :d365_capability,
                d365_navigation = :d365_navigation,
                config_steps = :config_steps,
                gap_description = :gap_description,
                configuration_steps = CAST(:configuration_steps AS JSONB),
                dev_effort = :dev_effort,
                gap_type = :gap_type,
                evidence = CAST(:evidence AS JSONB)
            """
        )

        engine = self._get_engine()
        try:
            async with engine.begin() as conn:
                for r in results:
                    params: dict[str, Any] = {
                        "batch_id": batch_id,
                        "atom_id": r["atom_id"],
                        "requirement_text": r.get("requirement_text", ""),
                        "classification": r.get("classification", ""),
                        "confidence": r.get("confidence", 0.0),
                        "module": r.get("module", ""),
                        "country": r.get("country", ""),
                        "wave": r.get("wave", 1),
                        "rationale": r.get("rationale", ""),
                        "reviewer_override": r.get("reviewer_override", False),
                        "d365_capability": r.get("d365_capability", ""),
                        "d365_navigation": r.get("d365_navigation", ""),
                        "config_steps": r.get("config_steps"),
                        "gap_description": r.get("gap_description"),
                        "configuration_steps": (
                            json.dumps(r["configuration_steps"])
                            if r.get("configuration_steps") else None
                        ),
                        "dev_effort": r.get("dev_effort"),
                        "gap_type": r.get("gap_type"),
                        "evidence": (
                            json.dumps(r["evidence"])
                            if r.get("evidence") else "{}"
                        ),
                    }
                    await conn.execute(stmt, params)
            log.debug(
                "postgres_batch_results_saved",
                batch_id=batch_id,
                count=len(results),
            )
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"save_batch_results({batch_id!r}) failed: {exc}",
                cause=exc,
            ) from exc

    async def get_results_by_batch(
        self,
        batch_id: str,
        *,
        classification: str | None = None,
        module: str | None = None,
        sort: str = "confidence",
        order: str = "desc",
        offset: int = 0,
        limit: int = 25,
    ) -> list[BatchResultRecord]:
        """Fetch paginated batch results with optional filters and sorting.

        Args:
            batch_id:       The batch identifier.
            classification: Optional exact match on classification field.
            module:         Optional exact match on module field.
            sort:           Field to sort by (confidence, module, classification, atom_id).
            order:          'asc' or 'desc'.
            offset:         Number of rows to skip.
            limit:          Max rows to return.

        Returns:
            List of BatchResultRecord objects.
        """
        from sqlalchemy import text  # noqa: PLC0415

        # Allowlist sort fields to prevent injection
        _SORTABLE = frozenset(
            {"confidence", "module", "classification", "atom_id"}
        )
        sort_field = sort if sort in _SORTABLE else "confidence"
        order_clause = "DESC" if order.lower() == "desc" else "ASC"

        # Build WHERE clause
        where_parts = ["batch_id = :batch_id"]
        params: dict[str, Any] = {"batch_id": batch_id}

        if classification:
            where_parts.append("classification = :classification")
            params["classification"] = classification

        if module:
            where_parts.append("module = :module")
            params["module"] = module

        where_clause = " AND ".join(where_parts)

        sql = f"""
            SELECT batch_id, atom_id, requirement_text, classification,
                   confidence, module, country, wave, rationale,
                   reviewer_override, d365_capability, d365_navigation,
                   config_steps, gap_description, configuration_steps,
                   dev_effort, gap_type, evidence
            FROM batch_results
            WHERE {where_clause}
            ORDER BY {sort_field} {order_clause}
            OFFSET :offset LIMIT :limit
        """

        params["offset"] = offset
        params["limit"] = limit

        engine = self._get_engine()
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(text(sql), params)
                ).mappings().all()
            return [_row_to_result(row) for row in rows]
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"get_results_by_batch({batch_id!r}) failed: {exc}",
                cause=exc,
            ) from exc

    async def count_results_by_batch(
        self,
        batch_id: str,
        *,
        classification: str | None = None,
        module: str | None = None,
    ) -> int:
        """Count batch results matching optional filters.

        Args:
            batch_id:       The batch identifier.
            classification: Optional exact match on classification field.
            module:         Optional exact match on module field.

        Returns:
            Total count of matching results.
        """
        from sqlalchemy import text  # noqa: PLC0415

        where_parts = ["batch_id = :batch_id"]
        params: dict[str, Any] = {"batch_id": batch_id}

        if classification:
            where_parts.append("classification = :classification")
            params["classification"] = classification

        if module:
            where_parts.append("module = :module")
            params["module"] = module

        where_clause = " AND ".join(where_parts)
        sql = f"SELECT COUNT(*) AS total FROM batch_results WHERE {where_clause}"

        engine = self._get_engine()
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(text(sql), params)
                ).mappings().first()
            return row["total"] if row else 0
        except PostgresError:
            raise
        except Exception as exc:
            raise PostgresError(
                f"count_results_by_batch({batch_id!r}) failed: {exc}",
                cause=exc,
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
            embedding:         384-dim dense embedding of the requirement text.
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
                 reviewer_override, consultant, embedding,
                 d365_capability_ref, config_steps, gap_description,
                 configuration_steps, dev_effort, gap_type)
            VALUES
                (:atom_id, :upload_id, :product_id, :module, :country, :wave,
                 :classification, :confidence, :rationale,
                 :reviewer_override, :consultant, CAST(:embedding AS vector),
                 :d365_capability_ref, :config_steps, :gap_description,
                 CAST(:configuration_steps AS JSONB),
                 :dev_effort, :gap_type)
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
            "d365_capability_ref": result.d365_capability_ref,
            "config_steps": result.config_steps,
            "gap_description": result.gap_description,
            "configuration_steps": (
                json.dumps(result.configuration_steps) if result.configuration_steps else None
            ),
            "dev_effort": result.dev_effort,
            "gap_type": result.gap_type,
        }
        engine = self._get_engine()
        try:
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
            embedding: 384-dim dense query vector.
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


def _row_to_upload(row: Any) -> UploadRecord:
    return UploadRecord(
        upload_id=row["upload_id"],
        product_id=row["product_id"],
        filename=row["filename"],
        wave=row["wave"],
        country=row["country"],
        status=row["status"],
        created_at=row["created_at"],
        content_hash=row["content_hash"] or "",
        path=row["path"] or "",
        size_bytes=row["size_bytes"] or 0,
        detected_format=row["detected_format"] or "",
    )


def _row_to_batch(row: Any) -> BatchRecord:
    raw_summary = row["summary"]
    if raw_summary is None:
        summary = None
    elif isinstance(raw_summary, dict):
        summary = raw_summary  # asyncpg auto-parses JSONB → dict
    else:
        try:
            summary = json.loads(raw_summary)
        except (json.JSONDecodeError, TypeError):
            summary = None
    return BatchRecord(
        batch_id=row["batch_id"],
        upload_id=row["upload_id"],
        product_id=row["product_id"],
        country=row["country"],
        wave=row["wave"],
        status=row["status"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        report_path=row["report_path"],
        summary=summary,
        upload_filename=row.get("upload_filename", ""),
    )


def _row_to_review_item(row: Any) -> ReviewItemRecord:
    evidence: dict[str, Any] = {}
    if row.get("evidence"):
        try:
            evidence = (
                json.loads(row["evidence"])
                if isinstance(row["evidence"], str)
                else row["evidence"]
            )
        except (json.JSONDecodeError, TypeError):
            evidence = {}

    configuration_steps: list[str] | None = None
    if row.get("configuration_steps"):
        try:
            raw = row["configuration_steps"]
            configuration_steps = (
                json.loads(raw) if isinstance(raw, str) else raw
            )
        except (json.JSONDecodeError, TypeError):
            configuration_steps = None

    return ReviewItemRecord(
        batch_id=row["batch_id"],
        atom_id=row["atom_id"],
        ai_classification=row["ai_classification"],
        ai_confidence=row["ai_confidence"],
        decision=row["decision"],
        override_classification=row["override_classification"],
        reviewer=row["reviewer"],
        reviewed=row["reviewed"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        requirement_text=row.get("requirement_text") or "",
        ai_rationale=row.get("ai_rationale") or "",
        review_reason=row.get("review_reason") or "",
        module=row.get("module") or "",
        evidence=evidence,
        config_steps=row.get("config_steps"),
        gap_description=row.get("gap_description"),
        configuration_steps=configuration_steps,
        dev_effort=row.get("dev_effort"),
        gap_type=row.get("gap_type"),
    )


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


def _row_to_result(row: Any) -> BatchResultRecord:
    """Convert a batch_results table row to a BatchResultRecord."""
    evidence = {}
    if row.get("evidence"):
        try:
            evidence = (
                json.loads(row["evidence"])
                if isinstance(row["evidence"], str)
                else row["evidence"]
            )
        except json.JSONDecodeError:
            evidence = {}

    configuration_steps = None
    if row.get("configuration_steps"):
        try:
            configuration_steps = (
                json.loads(row["configuration_steps"])
                if isinstance(row["configuration_steps"], str)
                else row["configuration_steps"]
            )
        except json.JSONDecodeError:
            configuration_steps = None

    return BatchResultRecord(
        batch_id=row["batch_id"],
        atom_id=row["atom_id"],
        requirement_text=row["requirement_text"],
        classification=row["classification"],
        confidence=row["confidence"],
        module=row["module"],
        country=row["country"],
        wave=row["wave"],
        rationale=row.get("rationale", ""),
        reviewer_override=row.get("reviewer_override", False),
        d365_capability=row.get("d365_capability", ""),
        d365_navigation=row.get("d365_navigation", ""),
        config_steps=row.get("config_steps"),
        gap_description=row.get("gap_description"),
        configuration_steps=configuration_steps,
        dev_effort=row.get("dev_effort"),
        gap_type=row.get("gap_type"),
        evidence=evidence,
    )

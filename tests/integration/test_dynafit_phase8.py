"""
Integration tests for Phase 8: Refactored batch management system.

Requires POSTGRES_URL to run. Tests the new PostgreSQL-first architecture:
  - Batch metadata persisted to PostgreSQL (not in-memory dicts)
  - Status transitions written durably
  - Review decisions persisted to PostgreSQL
  - Results derived on-demand from journey
  - Error handling with proper rollback

Mark: integration — requires PostgreSQL.
"""

from __future__ import annotations

import os
from typing import Any
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

# Skip entire module if POSTGRES_URL is not set
pytestmark = pytest.mark.skipif(
    not os.getenv("POSTGRES_URL"),
    reason="POSTGRES_URL not set — run 'make dev' to start PostgreSQL",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store() -> Any:  # type: ignore[misc]
    """Fresh PostgresStore with clean batches and review_items tables."""
    from platform.storage.postgres import PostgresStore

    postgres_url = os.getenv("POSTGRES_URL")
    assert postgres_url

    s = PostgresStore(postgres_url)
    try:
        await s.ensure_schema()
    except Exception as exc:
        await s.dispose()
        pytest.skip(f"PostgreSQL not reachable: {exc}")

    # Truncate batch-related tables
    async with s._get_engine().begin() as conn:
        await conn.execute(text("TRUNCATE TABLE batches, review_items RESTART IDENTITY"))

    yield s
    await s.dispose()


@pytest.fixture
async def upload_in_db(store: Any) -> str:
    """Create an upload record and return upload_id."""
    from platform.schemas.requirement import RawUpload

    upload = RawUpload(
        upload_id="test-upload-001",
        filename="test_requirements.pdf",
        file_bytes=b"%PDF-1.4 test content",
        product_id="d365_fo",
        country="US",
        wave=1,
    )
    await store.save_upload(upload)
    return upload.upload_id


# ---------------------------------------------------------------------------
# Phase 1-3: Batch creation and PostgreSQL persistence
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_save_batch_creates_record_in_postgres(
    store: Any, upload_in_db: str
) -> None:
    """Batch saved to PostgreSQL can be retrieved by ID."""
    from platform.storage.postgres import BatchRecord

    batch = BatchRecord(
        batch_id="bat_phase1_test",
        upload_id=upload_in_db,
        product_id="d365_fo",
        country="US",
        wave=1,
        status="queued",
        created_at=datetime.now(UTC),
        summary={"total": 0, "fit": 0, "partial_fit": 0, "gap": 0},
    )
    await store.save_batch(batch)

    # Retrieve and verify
    retrieved = await store.get_batch_by_id("bat_phase1_test")
    assert retrieved is not None
    assert retrieved.batch_id == "bat_phase1_test"
    assert retrieved.status == "queued"
    assert retrieved.upload_id == upload_in_db


# ---------------------------------------------------------------------------
# Phase 4: Status transitions written to PostgreSQL
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_batch_status_transition_queued_to_processing(
    store: Any, upload_in_db: str
) -> None:
    """Batch status transitions are written durably to PostgreSQL."""
    from platform.storage.postgres import BatchRecord

    batch = BatchRecord(
        batch_id="bat_phase4_test",
        upload_id=upload_in_db,
        product_id="d365_fo",
        country="DE",
        wave=1,
        status="queued",
        created_at=datetime.now(UTC),
        summary={"total": 0, "fit": 0, "partial_fit": 0, "gap": 0},
    )
    await store.save_batch(batch)

    # Update status
    await store.update_batch_status("bat_phase4_test", "processing")

    # Verify status change is durable
    retrieved = await store.get_batch_by_id("bat_phase4_test")
    assert retrieved is not None
    assert retrieved.status == "processing"


# ---------------------------------------------------------------------------
# Phase 5: Results derivation on-demand from journey
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_batch_completion_writes_all_durable_fields(
    store: Any, upload_in_db: str
) -> None:
    """Batch completion writes status, completed_at, report_path, and summary to PostgreSQL."""
    from platform.storage.postgres import BatchRecord

    batch = BatchRecord(
        batch_id="bat_phase5_test",
        upload_id=upload_in_db,
        product_id="d365_fo",
        country="FR",
        wave=2,
        status="processing",
        created_at=datetime.now(UTC),
        summary={"total": 0, "fit": 0, "partial_fit": 0, "gap": 0},
    )
    await store.save_batch(batch)

    # Simulate completion
    completed_at = datetime.now(UTC)
    summary = {"total": 5, "fit": 3, "partial_fit": 1, "gap": 1}
    await store.update_batch_on_complete(
        batch_id="bat_phase5_test",
        completed_at=completed_at,
        report_path="/reports/bat_phase5_test.pdf",
        summary=summary,
    )

    # Verify all fields are persisted
    retrieved = await store.get_batch_by_id("bat_phase5_test")
    assert retrieved is not None
    assert retrieved.status == "complete"
    assert retrieved.completed_at is not None
    assert retrieved.report_path == "/reports/bat_phase5_test.pdf"
    assert retrieved.summary == summary


# ---------------------------------------------------------------------------
# Phase 6-7: Review decision persistence (durable)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_review_decision_persisted_to_postgres(
    store: Any, upload_in_db: str
) -> None:
    """Review decisions are saved durably to PostgreSQL review_items table."""
    from platform.storage.postgres import BatchRecord

    batch = BatchRecord(
        batch_id="bat_review_test",
        upload_id=upload_in_db,
        product_id="d365_fo",
        country="UK",
        wave=1,
        status="review_required",
        created_at=datetime.now(UTC),
        summary={"total": 1, "fit": 0, "partial_fit": 0, "gap": 0},
    )
    await store.save_batch(batch)

    # Save a review decision
    await store.save_review_decision(
        batch_id="bat_review_test",
        atom_id="REQ-001",
        ai_classification="REVIEW_REQUIRED",
        decision="APPROVE",
        override_classification=None,
        reviewer="alice@example.com",
    )

    # Retrieve and verify decision is durable
    items = await store.get_review_items_by_batch("bat_review_test")
    assert len(items) == 1
    assert items[0].atom_id == "REQ-001"
    assert items[0].decision == "APPROVE"
    assert items[0].reviewer == "alice@example.com"


@pytest.mark.integration
async def test_review_decision_override_persists_new_classification(
    store: Any, upload_in_db: str
) -> None:
    """OVERRIDE decisions persist the human-provided classification."""
    from platform.storage.postgres import BatchRecord

    batch = BatchRecord(
        batch_id="bat_override_test",
        upload_id=upload_in_db,
        product_id="d365_fo",
        country="IT",
        wave=1,
        status="review_required",
        created_at=datetime.now(UTC),
        summary={"total": 1, "fit": 0, "partial_fit": 0, "gap": 0},
    )
    await store.save_batch(batch)

    # Save an OVERRIDE decision with new classification
    await store.save_review_decision(
        batch_id="bat_override_test",
        atom_id="REQ-002",
        ai_classification="REVIEW_REQUIRED",
        decision="OVERRIDE",
        override_classification="FIT",
        reviewer="bob@example.com",
    )

    # Verify override is stored
    items = await store.get_review_items_by_batch("bat_override_test")
    assert len(items) == 1
    assert items[0].decision == "OVERRIDE"
    assert items[0].override_classification == "FIT"


# ---------------------------------------------------------------------------
# Phase 8: Error handling and rollback
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_batch_not_found_returns_none(store: Any) -> None:
    """Querying a non-existent batch returns None (not exception)."""
    batch = await store.get_batch_by_id("nonexistent-batch")
    assert batch is None


@pytest.mark.integration
async def test_status_update_idempotent(store: Any, upload_in_db: str) -> None:
    """Multiple status updates to same batch work correctly (idempotent)."""
    from platform.storage.postgres import BatchRecord

    batch = BatchRecord(
        batch_id="bat_idempotent_test",
        upload_id=upload_in_db,
        product_id="d365_fo",
        country="ES",
        wave=1,
        status="queued",
        created_at=datetime.now(UTC),
        summary={"total": 0, "fit": 0, "partial_fit": 0, "gap": 0},
    )
    await store.save_batch(batch)

    # Update status multiple times
    await store.update_batch_status("bat_idempotent_test", "processing")
    await store.update_batch_status("bat_idempotent_test", "processing")  # idempotent

    retrieved = await store.get_batch_by_id("bat_idempotent_test")
    assert retrieved is not None
    assert retrieved.status == "processing"


@pytest.mark.integration
async def test_review_decision_upsert_handles_duplicates(
    store: Any, upload_in_db: str
) -> None:
    """Saving the same review decision twice (upsert) overwrites previous."""
    from platform.storage.postgres import BatchRecord

    batch = BatchRecord(
        batch_id="bat_upsert_test",
        upload_id=upload_in_db,
        product_id="d365_fo",
        country="NL",
        wave=1,
        status="review_required",
        created_at=datetime.now(UTC),
        summary={"total": 1, "fit": 0, "partial_fit": 0, "gap": 0},
    )
    await store.save_batch(batch)

    # Save initial decision
    await store.save_review_decision(
        batch_id="bat_upsert_test",
        atom_id="REQ-003",
        ai_classification="REVIEW_REQUIRED",
        decision="APPROVE",
        override_classification=None,
        reviewer="alice@example.com",
    )

    # Overwrite with different decision
    await store.save_review_decision(
        batch_id="bat_upsert_test",
        atom_id="REQ-003",
        ai_classification="REVIEW_REQUIRED",
        decision="OVERRIDE",
        override_classification="GAP",
        reviewer="bob@example.com",
    )

    # Verify latest decision is returned
    items = await store.get_review_items_by_batch("bat_upsert_test")
    assert len(items) == 1
    assert items[0].decision == "OVERRIDE"
    assert items[0].override_classification == "GAP"
    assert items[0].reviewer == "bob@example.com"


@pytest.mark.integration
async def test_list_batches_with_filters(store: Any, upload_in_db: str) -> None:
    """list_batches respects country, wave, and status filters."""
    from platform.storage.postgres import BatchRecord
    from datetime import datetime, UTC

    # Create batches with different attributes
    batches = [
        BatchRecord(
            batch_id="bat_filter_us_w1",
            upload_id=upload_in_db,
            product_id="d365_fo",
            country="US",
            wave=1,
            status="complete",
            created_at=datetime.now(UTC),
            summary={"total": 1, "fit": 1, "partial_fit": 0, "gap": 0},
        ),
        BatchRecord(
            batch_id="bat_filter_de_w1",
            upload_id=upload_in_db,
            product_id="d365_fo",
            country="DE",
            wave=1,
            status="complete",
            created_at=datetime.now(UTC),
            summary={"total": 2, "fit": 1, "partial_fit": 1, "gap": 0},
        ),
        BatchRecord(
            batch_id="bat_filter_us_w2",
            upload_id=upload_in_db,
            product_id="d365_fo",
            country="US",
            wave=2,
            status="processing",
            created_at=datetime.now(UTC),
            summary={"total": 0, "fit": 0, "partial_fit": 0, "gap": 0},
        ),
    ]

    for batch in batches:
        await store.save_batch(batch)

    # Query by country
    us_batches = await store.list_batches(country="US", limit=10)
    assert len(us_batches) == 2
    assert all(b.country == "US" for b in us_batches)

    # Query by wave
    w1_batches = await store.list_batches(wave=1, limit=10)
    assert len(w1_batches) == 2
    assert all(b.wave == 1 for b in w1_batches)

    # Query by status
    complete_batches = await store.list_batches(status="complete", limit=10)
    assert len(complete_batches) == 2
    assert all(b.status == "complete" for b in complete_batches)

    # Query with multiple filters
    us_w1_batches = await store.list_batches(country="US", wave=1, limit=10)
    assert len(us_w1_batches) == 1
    assert us_w1_batches[0].batch_id == "bat_filter_us_w1"

"""
Lite unit tests for Session B: Celery task + review/complete endpoint.

Mark: unit — no Docker, no real Celery, no real LangGraph.
Strategy:
  - Task tests patch asyncio.run + _emit to stay fully in-process.
  - Route test uses httpx AsyncClient (same pattern as Session A).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import api.routes.dynafit as routes_module
import api.workers.tasks as tasks_module
from api.main import app

BASE = "/api/v1"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_stores() -> None:  # type: ignore[return]
    routes_module._uploads.clear()
    routes_module._batches.clear()
    yield  # type: ignore[misc]
    routes_module._uploads.clear()
    routes_module._batches.clear()


@pytest.fixture
async def client() -> AsyncClient:  # type: ignore[return]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c  # type: ignore[misc]


@pytest.fixture
def upload_file(tmp_path: Path) -> Path:
    """Real PDF file on disk — used to test task file I/O."""
    f = tmp_path / "reqs.pdf"
    f.write_bytes(b"%PDF-1.4 fake content")
    return f


# ---------------------------------------------------------------------------
# Task: auto-resume when no REVIEW_REQUIRED items
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_task_auto_resumes_no_hitl(upload_file: Path) -> None:
    """When graph returns no REVIEW_REQUIRED classifications, Phase 5 runs immediately."""
    mock_classification = MagicMock()
    mock_classification.classification = "FIT"  # not REVIEW_REQUIRED

    mock_vb = MagicMock()
    mock_vb.results = [mock_classification]
    mock_vb.total_atoms = 1
    mock_vb.fit_count = 1
    mock_vb.partial_fit_count = 0
    mock_vb.gap_count = 0
    mock_vb.review_count = 0
    mock_vb.report_path = None

    mock_classification.atom_id = "REQ-001"
    mock_classification.requirement_text = "Three-way matching"
    mock_classification.module = "AccountsPayable"
    mock_classification.country = "DE"
    mock_classification.wave = 1
    mock_classification.confidence = 0.94
    mock_classification.rationale = "Supported."
    mock_classification.d365_capability_ref = "AP Matching"
    mock_classification.config_steps = None
    mock_classification.gap_description = None
    mock_classification.configuration_steps = None
    mock_classification.dev_effort = None
    mock_classification.gap_type = None
    mock_classification.route_used = "FAST_TRACK"
    mock_classification.llm_calls_used = 1

    state_after_phases14 = {"classifications": [mock_classification], "errors": []}
    final_state = {
        "validated_batch": mock_vb,
        "validated_atoms": [],
        "retrieval_contexts": [],
        "match_results": [],
        "classifications": [mock_classification],
        "errors": [],
    }
    phase5_result = ("complete", final_state, set(), {})

    with (
        patch.object(tasks_module, "_emit"),
        patch.object(tasks_module, "_write_batch_state") as mock_write,
        patch("api.workers.tasks.asyncio.run") as mock_run,
    ):
        mock_run.side_effect = [state_after_phases14, phase5_result]

        task = tasks_module.run_dynafit_pipeline
        task.run(
            "bat_test01",
            "upl_test01",
            {
                "_upload_meta": {
                    "path": str(upload_file),
                    "product": "d365_fo",
                    "filename": "reqs.pdf",
                    "wave": 1,
                    "country": "DE",
                }
            },
        )

    # asyncio.run called twice: phases 1-4 and phase 5
    assert mock_run.call_count == 2
    # _write_batch_state called with status=complete
    mock_write.assert_called_once()
    assert mock_write.call_args.kwargs["status"] == "complete"


# ---------------------------------------------------------------------------
# Task: HITL path — emits review_required and stops
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_task_emits_review_required_when_hitl(upload_file: Path) -> None:
    """When graph returns REVIEW_REQUIRED items, review_required event is emitted."""
    mock_classification = MagicMock()
    mock_classification.atom_id = "REQ-001"
    mock_classification.requirement_text = "Custom report"
    mock_classification.classification = "REVIEW_REQUIRED"
    mock_classification.confidence = 0.45
    mock_classification.rationale = "Unclear."
    mock_classification.module = "AccountsPayable"
    mock_classification.d365_capability_ref = None
    mock_classification.config_steps = None
    mock_classification.gap_description = None
    mock_classification.configuration_steps = None
    mock_classification.dev_effort = None
    mock_classification.gap_type = None
    mock_classification.route_used = "DEEP_REASON"
    mock_classification.llm_calls_used = 3
    mock_classification.country = "DE"
    mock_classification.wave = 1

    state_after_phases14 = {
        "classifications": [mock_classification],
        "errors": [],
    }
    final_state = {
        "validated_batch": None,
        "validated_atoms": [],
        "retrieval_contexts": [],
        "match_results": [],
        "classifications": [mock_classification],
        "errors": [],
    }
    flagged = {mock_classification.atom_id}
    reasons = {mock_classification.atom_id: ["low_confidence"]}
    phase5_result = ("hitl", final_state, flagged, reasons)

    with (
        patch.object(tasks_module, "_emit") as mock_emit,
        patch.object(tasks_module, "_write_batch_state"),
        patch("api.workers.tasks.asyncio.run") as mock_run,
    ):
        mock_run.side_effect = [state_after_phases14, phase5_result]
        tasks_module.run_dynafit_pipeline.run(
            "bat_hitl01",
            "upl_test01",
            {
                "_upload_meta": {
                    "path": str(upload_file),
                    "product": "d365_fo",
                    "filename": "reqs.pdf",
                    "wave": 1,
                    "country": "DE",
                }
            },
        )

    emitted_events = [c.args[1]["event"] for c in mock_emit.call_args_list]
    assert "review_required" in emitted_events
    assert "complete" not in emitted_events


# ---------------------------------------------------------------------------
# Task: missing file emits error and returns
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_task_emits_error_on_missing_file() -> None:
    """Missing upload file → error event emitted, no graph call."""
    with (
        patch.object(tasks_module, "_emit") as mock_emit,
        patch("api.workers.tasks.asyncio.run") as mock_run,
    ):
        tasks_module.run_dynafit_pipeline.run(
            "bat_err01",
            "upl_test01",
            {
                "_upload_meta": {
                    "path": "/nonexistent/reqs.pdf",
                    "product": "d365_fo",
                    "filename": "reqs.pdf",
                    "wave": 1,
                    "country": "DE",
                }
            },
        )

    mock_run.assert_not_called()
    emitted_events = [c.args[1]["event"] for c in mock_emit.call_args_list]
    assert "error" in emitted_events


# ---------------------------------------------------------------------------
# Task: resume path skips phases 1-4
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_task_resume_skips_phases14() -> None:
    """config['_resume'] = True → only _resume_phase5 is called."""
    with (
        patch.object(tasks_module, "_write_batch_state"),
        patch("api.workers.tasks.asyncio.run") as mock_run,
    ):
        mock_vb = MagicMock()
        mock_vb.results = []
        mock_vb.total_atoms = 0
        mock_vb.fit_count = 0
        mock_vb.partial_fit_count = 0
        mock_vb.gap_count = 0
        mock_vb.review_count = 0
        mock_vb.report_path = None
        mock_run.return_value = {
            "validated_batch": mock_vb,
            "validated_atoms": [],
            "retrieval_contexts": [],
            "match_results": [],
            "classifications": [],
            "errors": [],
        }
        tasks_module.run_dynafit_pipeline.run(
            "bat_resume01", "", {"_resume": True}
        )

    # Resume path calls asyncio.run once (for _resume_phase5_hitl)
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# Route: POST /review/complete dispatches resume task
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_review_complete_dispatches_resume(client: AsyncClient) -> None:
    """POST /review/complete on a known batch dispatches _dispatch_resume."""
    routes_module._batches["bat_abc"] = {
        "batch_id": "bat_abc",
        "upload_id": "upl_test01",
        "upload_filename": "reqs.pdf",
        "country": "DE",
        "wave": 3,
        "status": "review_pending",
        "results": [],
        "review_items": [],
        "summary": {"total": 0, "fit": 0, "partial_fit": 0, "gap": 0},
        "report_path": None,
        "created_at": "2026-03-21T10:00:00+00:00",
        "completed_at": None,
    }

    with patch.object(routes_module, "_dispatch_resume") as mock_dispatch:
        resp = await client.post(f"{BASE}/d365_fo/dynafit/bat_abc/review/complete")

    assert resp.status_code == 202
    assert resp.json()["status"] == "resumed"
    mock_dispatch.assert_called_once_with("bat_abc", {})

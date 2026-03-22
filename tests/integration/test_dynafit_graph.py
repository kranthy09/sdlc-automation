"""
Smoke test — modules/dynafit/graph.py (Session B)

Verifies:
  - build_dynafit_graph() compiles without errors
  - All 5 phase nodes are wired in the compiled graph
  - HITL interrupt_before=["validate"] is respected: invoke() stops after classify
  - Full end-to-end run (stubs): invoke → resume → validated_batch populated

All tests use langgraph.checkpoint.memory.MemorySaver — no Docker required.
Marked @pytest.mark.unit because no external services are needed.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Compile-time structure tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_graph_compiles() -> None:
    """build_dynafit_graph() returns a compiled graph without errors."""
    from modules.dynafit.graph import build_dynafit_graph

    graph = build_dynafit_graph()

    assert graph is not None


@pytest.mark.unit
def test_graph_has_all_five_nodes() -> None:
    """All 5 phase nodes are present in the compiled graph."""
    from modules.dynafit.graph import build_dynafit_graph

    graph = build_dynafit_graph()
    node_names = set(graph.get_graph().nodes.keys())

    for expected in ("ingest", "retrieve", "match", "classify", "validate"):
        assert expected in node_names, f"Missing node: {expected!r}"


# ---------------------------------------------------------------------------
# Runtime stub tests (MemorySaver — no Postgres)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_stub_run_pauses_before_validate() -> None:
    """With MemorySaver, invoke() runs phases 1-4 and stops before Phase 5."""
    from langgraph.checkpoint.memory import MemorySaver

    from modules.dynafit.graph import build_dynafit_graph
    from platform.testing.factories import make_raw_upload

    graph = build_dynafit_graph(checkpointer=MemorySaver())
    initial = {
        "upload": make_raw_upload(),
        "batch_id": "smoke-001",
        "errors": [],
    }
    config = {"configurable": {"thread_id": "smoke-001"}}

    state = graph.invoke(initial, config)

    # All stub phases return empty lists — the pipeline ran without error
    assert state["classifications"] == []
    assert state["match_results"] == []
    assert state["retrieval_contexts"] == []
    assert state["validated_atoms"] == []

    # Phase 5 has NOT run yet — validated_batch absent (HITL pause point)
    assert state.get("validated_batch") is None


@pytest.mark.unit
def test_stub_resume_completes_phase5(monkeypatch, tmp_path) -> None:
    """Resuming after HITL pause runs Phase 5 and produces a ValidatedFitmentBatch."""
    import modules.dynafit.nodes.phase5_validation as phase5_mod
    from langgraph.checkpoint.memory import MemorySaver

    from modules.dynafit.graph import build_dynafit_graph
    from modules.dynafit.nodes.phase5_validation import ValidationNode
    from platform.schemas.fitment import ValidatedFitmentBatch
    from platform.testing.factories import (
        make_embedder,
        make_postgres_store,
        make_raw_upload,
        make_redis_pub_sub,
    )

    monkeypatch.setattr(
        phase5_mod,
        "_node",
        ValidationNode(
            postgres=make_postgres_store(),
            redis=make_redis_pub_sub(),
            embedder=make_embedder(),
            report_dir=str(tmp_path),
        ),
    )

    checkpointer = MemorySaver()
    graph = build_dynafit_graph(checkpointer=checkpointer)
    initial = {
        "upload": make_raw_upload(),
        "batch_id": "smoke-002",
        "errors": [],
    }
    config = {"configurable": {"thread_id": "smoke-002"}}

    # First invoke — runs phases 1-4, pauses before validate
    graph.invoke(initial, config)

    # Resume — passes None to continue from checkpoint; runs Phase 5
    final_state = graph.invoke(None, config)

    # Phase 5 builds ValidatedFitmentBatch (stub phases produce zero atoms)
    assert isinstance(final_state["validated_batch"], ValidatedFitmentBatch)
    assert final_state["validated_batch"].total_atoms == 0


@pytest.mark.unit
def test_errors_accumulate_across_phases() -> None:
    """The errors field uses operator.add reducer — errors from each phase accumulate."""
    from langgraph.checkpoint.memory import MemorySaver

    from modules.dynafit.graph import build_dynafit_graph
    from platform.testing.factories import make_raw_upload

    graph = build_dynafit_graph(checkpointer=MemorySaver())
    initial = {
        "upload": make_raw_upload(),
        "batch_id": "smoke-003",
        "errors": [],
    }
    config = {"configurable": {"thread_id": "smoke-003"}}

    state = graph.invoke(initial, config)

    # Stubs add no errors; errors list stays empty (reducer doesn't break empty case)
    assert state["errors"] == []

"""
DYNAFIT LangGraph graph — the ONLY public entry point for the dynafit module.

Usage:

    from modules.dynafit.graph import build_dynafit_graph

    graph = build_dynafit_graph(checkpointer=AsyncPostgresSaver(...))
    state = graph.invoke(
        {
            "upload": raw_upload,
            "batch_id": batch_id,
            "errors": [],
        },
        config={"configurable": {"thread_id": batch_id}},
    )

HITL flow:
    graph.invoke() runs phases 1–4, then PAUSES before Phase 5 (validate).
    The API layer serves GET /batches/{id}/review and POST .../review/{atom_id}.
    Once all flagged items are resolved, resume with:
        graph.invoke(None, config={"configurable": {"thread_id": batch_id}})

Checkpointer injection:
    - Production: AsyncPostgresSaver (langgraph.checkpoint.postgres.aio)
    - Tests:      MemorySaver (langgraph.checkpoint.memory)
    - None:       Disables checkpointing — HITL interrupt will not work
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from platform.observability.logger import get_logger

from .nodes.classification import classification_node
from .nodes.ingestion import ingestion_node
from .nodes.matching import matching_node
from .nodes.retrieval import retrieval_node
from .nodes.validation import validation_node
from .state import DynafitState

log = get_logger(__name__)


def build_dynafit_graph(checkpointer: Any = None) -> Any:
    """Build and compile the DYNAFIT 5-phase LangGraph graph.

    Args:
        checkpointer: LangGraph checkpoint saver.
                      - AsyncPostgresSaver in production (enables HITL + crash recovery)
                      - MemorySaver in tests (in-process, no Postgres needed)
                      - None disables checkpointing (interrupt_before has no effect)

    Returns:
        Compiled LangGraph graph. Entry point: "ingest".
        HITL interrupt point: before "validate" (Phase 5).
    """
    graph: StateGraph = StateGraph(DynafitState)

    # --- Phase nodes (linear pipeline, no conditional edges in MVP) ----------
    graph.add_node("ingest", ingestion_node)
    graph.add_node("retrieve", retrieval_node)
    graph.add_node("match", matching_node)
    graph.add_node("classify", classification_node)
    graph.add_node("validate", validation_node)

    # --- Linear edges --------------------------------------------------------
    graph.add_edge("ingest", "retrieve")
    graph.add_edge("retrieve", "match")
    graph.add_edge("match", "classify")
    graph.add_edge("classify", "validate")
    graph.add_edge("validate", END)

    # --- Entry point ---------------------------------------------------------
    graph.set_entry_point("ingest")

    # --- Compile with HITL interrupt before Phase 5 --------------------------
    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["validate"],
    )

    log.debug("dynafit_graph_compiled", has_checkpointer=checkpointer is not None)
    return compiled

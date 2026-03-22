"""End-to-end DYNAFIT pipeline smoke test.

CLI:
    python -m infra.scripts.smoke_test [--file tests/fixtures/sample_requirements.txt]
                                        [--country US] [--wave 1] [--mock-infra]

Runs phases 1-5 against a plain-text requirements file.  Each line starting
with a word followed by a colon (e.g. "REQ-001: ...") is treated as one
requirement.  Blank lines and comment lines (leading #) are skipped.

Requires real services (Qdrant :6333, Postgres :5432, Redis :6379) unless
--mock-infra is passed.  --mock-infra injects mock postgres / redis and
skips knowledge-base lookups (every requirement will route through stubs).

Expected output:
    Table: atom_id | text[:60] | classification | confidence | rationale[:80]
    Summary: atom counts, dedup removed, flagged, FIT/PARTIAL_FIT/GAP/REVIEW
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DYNAFIT end-to-end smoke test")
    p.add_argument(
        "--file",
        default="tests/fixtures/sample_requirements.txt",
        help="Path to requirements text file (one per line, REQ-NNN: text format)",
    )
    p.add_argument("--country", default="US", help="Country code (default: US)")
    p.add_argument("--wave", type=int, default=1, help="Wave number (default: 1)")
    p.add_argument(
        "--mock-infra",
        action="store_true",
        help="Inject mock postgres/redis; skip real Qdrant (all atoms route to stubs)",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# File → raw bytes helper
# ---------------------------------------------------------------------------


def _load_file(path: str) -> tuple[str, bytes]:
    """Return (filename, bytes) for the given path."""
    p = Path(path)
    if not p.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    return p.name, p.read_bytes()


# ---------------------------------------------------------------------------
# Mock-infra injection
# ---------------------------------------------------------------------------


def _inject_mock_infra(report_dir: str) -> None:
    """Monkeypatch the Phase 5 ValidationNode singleton with mock dependencies.

    Must be called BEFORE build_dynafit_graph() so the singleton is in place
    when the graph starts running.
    """
    import modules.dynafit.nodes.phase5_validation as phase5_mod
    from modules.dynafit.nodes.phase5_validation import ValidationNode
    from platform.testing.factories import make_embedder, make_postgres_store, make_redis_pub_sub

    phase5_mod._node = ValidationNode(
        postgres=make_postgres_store(),
        redis=make_redis_pub_sub(),
        embedder=make_embedder(),
        report_dir=report_dir,
    )


# ---------------------------------------------------------------------------
# Table printer
# ---------------------------------------------------------------------------


def _print_table(results: list) -> None:  # type: ignore[type-arg]
    header = f"{'atom_id':<15}  {'classification':<14}  {'conf':>5}  {'text':<60}  rationale"
    print()
    print(header)
    print("-" * len(header))
    for r in results:
        text_preview = r.requirement_text[:60].replace("\n", " ")
        rationale_preview = (r.rationale or "")[:80].replace("\n", " ")
        print(
            f"{r.atom_id:<15}  {str(r.classification):<14}  {r.confidence:>5.2f}"
            f"  {text_preview:<60}  {rationale_preview}"
        )


def _print_summary(
    batch: object,
    flagged_atoms: list,
    n_input_lines: int,
) -> None:
    from platform.schemas.fitment import ValidatedFitmentBatch

    assert isinstance(batch, ValidatedFitmentBatch)

    dedup_removed = n_input_lines - batch.total_atoms - len(flagged_atoms)
    dedup_removed = max(0, dedup_removed)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Input requirements   : {n_input_lines}")
    print(f"  Dedup / quality gate : {len(flagged_atoms)} flagged, ~{dedup_removed} deduped")
    print(f"  Atoms classified     : {batch.total_atoms}")
    print(f"  FIT                  : {batch.fit_count}")
    print(f"  PARTIAL_FIT          : {batch.partial_fit_count}")
    print(f"  GAP                  : {batch.gap_count}")
    print(f"  REVIEW_REQUIRED      : {batch.review_count}")
    if batch.report_path:
        print(f"  CSV report           : {batch.report_path}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = _parse_args()

    # Count non-blank, non-comment input lines for summary
    req_file = Path(args.file)
    raw_lines = [
        ln.strip()
        for ln in req_file.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    n_input_lines = len(raw_lines)

    filename, file_bytes = _load_file(args.file)
    batch_id = str(uuid.uuid4())
    report_dir = "reports"

    if args.mock_infra:
        print("[mock-infra] Injecting mock postgres / redis / embedder")
        _inject_mock_infra(report_dir)

    # Build graph after (optional) mock injection
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    from modules.dynafit.graph import build_dynafit_graph
    from platform.schemas.fitment import FitLabel
    from platform.schemas.requirement import RawUpload

    upload = RawUpload(
        upload_id=str(uuid.uuid4()),
        filename=filename,
        file_bytes=file_bytes,
        product_id="d365_fo",
        country=args.country,
        wave=args.wave,
    )

    graph = build_dynafit_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": batch_id}}
    initial = {"upload": upload, "batch_id": batch_id, "errors": []}

    # -----------------------------------------------------------------
    # Phase 1-4: run until HITL pause point (interrupt_before=["validate"])
    # -----------------------------------------------------------------
    print(f"Running phases 1–4 on {filename!r} ({n_input_lines} requirements)...")
    state = graph.invoke(initial, config)

    classifications = state.get("classifications") or []
    flagged_atoms = state.get("flagged_atoms") or []
    errors = state.get("errors") or []

    if errors:
        print(f"[WARN] Pipeline errors: {errors}", file=sys.stderr)

    print(f"  Validated atoms  : {len(state.get('validated_atoms') or [])}")
    print(f"  Flagged atoms    : {len(flagged_atoms)}")
    print(f"  Classifications  : {len(classifications)}")

    # -----------------------------------------------------------------
    # Phase 5: resume — Phase 5 may call interrupt() if HITL needed
    # -----------------------------------------------------------------
    print("Resuming Phase 5 (validation + report)...")
    state = graph.invoke(None, config)

    if state.get("validated_batch") is None:
        # Phase 5 called interrupt() — HITL needed; auto-approve all flagged items
        flagged_ids = [c.atom_id for c in classifications if c.classification != FitLabel.GAP]
        overrides: dict[str, None] = {atom_id: None for atom_id in flagged_ids}
        print(f"  [HITL] Auto-approving {len(overrides)} flagged item(s)...")
        state = graph.invoke(Command(resume=overrides), config)

    # -----------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------
    batch = state.get("validated_batch")
    if batch is None:
        print("ERROR: validated_batch is still None after Phase 5.", file=sys.stderr)
        sys.exit(1)

    _print_table(batch.results)
    _print_summary(batch, flagged_atoms, n_input_lines)


if __name__ == "__main__":
    main()

"""
Ingestion node — Phase 1 of the DYNAFIT pipeline (Session C).

Responsibility: RawUpload → RequirementAtom[] + ValidatedAtom[] + FlaggedAtom[]

Pipeline steps:
  1.  G1-lite file validation   (platform/guardrails/file_validator.py)
  2.  Document parsing           → table rows + prose chunks (DoclingParser)
  3.  Header column mapping      → synonym resolution (header_synonyms.yaml)
  4.  G3-lite injection scan    (platform/guardrails/injection_scanner.py)
  5.  Atomization + classification → one combined LLM call per raw text
  6.  Deduplication              → cosine similarity (numpy; FAISS deferred)
  7.  Priority enrichment        → keyword-based MoSCoW
  8.  Entity hint extraction     → spaCy NER (best-effort, lazy load)
  9.  Quality gates              → schema consistency, ambiguity, completeness
  10. Phase event publish        → Redis PhaseStartEvent (best-effort)

Post-MVP deferred:
  - Image extraction (spec §Phase1 Sub-step E)
  - Cross-wave linker (historical fitments — handled in Phase 2 retrieval)
  - FAISS / MinHashLSH for batches > 5 K atoms
"""

from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path
from typing import Any

from platform.guardrails.file_validator import validate_file
from platform.guardrails.injection_scanner import scan_for_injection
from platform.guardrails.pii_redactor import redact_pii
from platform.llm.client import LLMClient
from platform.observability.logger import get_logger
from platform.parsers.docling_parser import DoclingParser
from platform.schemas.product import ProductConfig
from platform.schemas.requirement import RawUpload, RequirementAtom

from ..events import (
    publish_phase_complete,
    publish_phase_start,
    publish_step_progress,
)
from ..product_config import get_product_config
from ..state import DynafitState

# Sub-module imports — pipeline stages
from .ingestion_atomiser import (
    _atomise_and_classify_batch,
    _AtomizationResult,
    _ClassifiedAtom,
    _ClassifiedRequirement,
)
from .ingestion_column_mapper import (
    _map_column_to_canonical,
    _map_table_rows_to_canonical,
)
from .ingestion_dedup import _deduplicate_requirements
from .ingestion_quality import (
    _apply_quality_gates,
    _infer_moscow_priority,
    _score_specificity,
)

# Re-export for backward compatibility (tests import these from this module)
__all__ = [
    "IngestionNode",
    "ingestion_node",
    "_AtomizationResult",
    "_ClassifiedAtom",
    "_ClassifiedRequirement",
    "_infer_moscow_priority",
    "_score_specificity",
    "_map_column_to_canonical",
    "_map_table_rows_to_canonical",
    "_atomise_and_classify_batch",
]

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_rejection_result(reason: str) -> dict[str, Any]:
    return {
        "atoms": [],
        "validated_atoms": [],
        "flagged_atoms": [],
        "errors": [reason],
    }


def _collect_requirement_texts(
    parse_result: Any,
) -> list[tuple[str, str]]:
    """Extract (requirement_text, source_ref) pairs from a ParseResult.

    Prefers resolved table rows; falls back to prose chunks when no
    requirement_text column is found in any table.
    """
    texts: list[tuple[str, str]] = []

    resolved = _map_table_rows_to_canonical(parse_result.tables)
    for i, row in enumerate(resolved):
        text = row.get("requirement_text", "").strip()
        if len(text) >= 10:
            texts.append((text, f"table_row_{i}"))

    if not texts:
        for chunk in parse_result.prose:
            text = chunk.text.strip()
            if len(text) >= 30:
                texts.append((text, f"page_{chunk.page}_prose"))

    return texts


def _build_classified_requirements(
    raw_texts: list[tuple[str, str]],
    upload: RawUpload,
    llm: LLMClient,
    config: ProductConfig,
    *,
    batch_id: str = "",
) -> list[_ClassifiedRequirement]:
    """Run batch atomisation + classification on all raw texts.

    Sends chunks in groups of 10 per LLM call instead of one call
    per chunk, reducing N sequential calls to ceil(N/10). Falls back
    to individual calls for any batch that fails or returns a count
    mismatch.
    Returns a flat list of _ClassifiedRequirement, one per atom.
    """
    texts = [t for t, _ in raw_texts]
    source_refs = [r for _, r in raw_texts]

    all_atom_lists = _atomise_and_classify_batch(
        texts,
        llm,
        config,
        batch_size=10,
    )

    publish_step_progress(
        batch_id,
        phase=1,
        step="atomize",
        completed=2,
        total=4,
    )

    results: list[_ClassifiedRequirement] = []
    counter = 0
    id_prefix = upload.upload_id[:8].upper()

    for atom_list, source_ref in zip(all_atom_lists, source_refs, strict=True):
        for atom in atom_list:
            if len(atom.text.strip()) < 10:
                continue
            atom_id = f"REQ-{id_prefix}-{counter:04d}"
            requirement = RequirementAtom(
                atom_id=atom_id,
                upload_id=upload.upload_id,
                requirement_text=atom.text.strip(),
                source_ref=source_ref,
                source_document=upload.filename,
                raw_module_hint=atom.module,
                content_type="text",
            )
            results.append(
                _ClassifiedRequirement(
                    atom=requirement,
                    intent=atom.intent,
                    module=atom.module,
                )
            )
            counter += 1

    return results


# ---------------------------------------------------------------------------
# IngestionNode — injectable dependencies, callable as a LangGraph node
# ---------------------------------------------------------------------------


class IngestionNode:
    """Phase 1 ingestion pipeline with injectable dependencies.

    Instantiate directly in tests with mock infrastructure:

        node = IngestionNode(
            llm_client=make_llm_client(...),
            embedder=make_embedder(),
            redis=make_redis_pub_sub(),
        )
        result = node(state)

    Production code uses the module-level ``ingestion_node`` function
    which creates and caches a default instance.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        parser: DoclingParser | None = None,
        embedder: Any | None = None,
    ) -> None:
        self._llm = llm_client
        self._parser = parser
        self._embedder = embedder

    # ------------------------------------------------------------------
    # Lazy infra
    # ------------------------------------------------------------------

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def _get_parser(self) -> DoclingParser:
        if self._parser is None:
            self._parser = DoclingParser()
        return self._parser

    def _get_embedder(self, product_id: str) -> Any:
        if self._embedder is None:
            from platform.retrieval.embedder import Embedder  # noqa: PLC0415

            config = get_product_config(product_id)
            self._embedder = Embedder(config.embedding_model)
        return self._embedder

    # ------------------------------------------------------------------
    # LangGraph entry point
    # ------------------------------------------------------------------

    def __call__(self, state: DynafitState) -> dict[str, Any]:
        upload: RawUpload = state["upload"]
        batch_id: str = state["batch_id"]
        t0 = time.monotonic()

        log.info(
            "phase_start",
            phase=1,
            batch_id=batch_id,
            filename=upload.filename,
            input_hash=hashlib.sha256(
                upload.file_bytes,
            ).hexdigest()[:16],
        )

        config = get_product_config(upload.product_id)

        # 0. Announce phase start
        publish_phase_start(
            batch_id,
            phase=1,
            phase_name="Ingestion",
        )

        # 1. G1-lite — file validation
        file_check = validate_file(
            upload.file_bytes,
            upload.filename,
        )
        if not file_check.is_valid:
            log.error(
                "ingestion_file_rejected",
                batch_id=batch_id,
                reason=file_check.rejection_reason,
            )
            return _make_rejection_result(f"file_validation_failed: {file_check.rejection_reason}")

        # 2. Document parsing
        parse_result = self._parse_document(upload, batch_id)
        if parse_result is None:
            return _make_rejection_result(
                f"parse_failed: {upload.filename}",
            )

        # 3. Extract raw requirement texts
        raw_texts = _collect_requirement_texts(parse_result)
        if not raw_texts:
            log.warning(
                "ingestion_no_text_found",
                batch_id=batch_id,
            )
            return _make_rejection_result(
                "no_requirements_found: document produced no extractable text"
            )
        publish_step_progress(
            batch_id,
            phase=1,
            step="parse",
            completed=1,
            total=4,
        )

        # 4. G3-lite — injection scan
        combined_text = "\n".join(t for t, _ in raw_texts)
        injection_scan = scan_for_injection(combined_text)
        if injection_scan.action == "BLOCK":
            log.error(
                "ingestion_injection_blocked",
                batch_id=batch_id,
                patterns=injection_scan.matched_patterns,
            )
            return _make_rejection_result(
                f"injection_blocked: patterns={injection_scan.matched_patterns}"
            )

        extra_errors: list[str] = (
            [f"injection_flagged:{p}" for p in injection_scan.matched_patterns]
            if injection_scan.action == "FLAG_FOR_REVIEW"
            else []
        )

        # 4b. G2 — PII redaction (before any text reaches an LLM)
        combined_redaction_map: dict[str, str] = {}
        redacted_texts: list[tuple[str, str]] = []
        for idx, (text, source_ref) in enumerate(raw_texts):
            pii_result = redact_pii(text, prefix=f"T{idx}_")
            redacted_texts.append((pii_result.redacted_text, source_ref))
            combined_redaction_map.update(pii_result.redaction_map)

        if combined_redaction_map:
            log.info(
                "pii_redacted",
                batch_id=batch_id,
                pii_entities=len(combined_redaction_map),
            )

        # 5. Atomise + classify (LLM) — uses redacted text
        classified = _build_classified_requirements(
            redacted_texts,
            upload,
            self._get_llm(),
            config,
            batch_id=batch_id,
        )
        if not classified:
            return _make_rejection_result(
                "atomisation_produced_no_atoms",
            )

        # 6. Deduplicate
        unique, duplicates = _deduplicate_requirements(
            classified,
            self._get_embedder(upload.product_id),
        )
        publish_step_progress(
            batch_id,
            phase=1,
            step="deduplicate",
            completed=3,
            total=4,
        )

        # 7-9. Quality gates
        validated, flagged = _apply_quality_gates(
            unique,
            duplicates,
            upload,
        )
        publish_step_progress(
            batch_id,
            phase=1,
            step="quality",
            completed=4,
            total=4,
        )

        elapsed_ms = (time.monotonic() - t0) * 1000
        log.info(
            "phase_complete",
            phase=1,
            batch_id=batch_id,
            output_hash=hashlib.sha256(
                repr(validated).encode(),
            ).hexdigest()[:16],
            atoms_in=len(raw_texts),
            atoms_out=len(validated),
            flagged=len(flagged),
            guardrails_triggered=(
                (["G3_injection_flagged"] if extra_errors else [])
                + (["G2_pii_redacted"] if combined_redaction_map else [])
            ),
            latency_ms=round(elapsed_ms, 1),
        )
        publish_phase_complete(
            batch_id,
            phase=1,
            phase_name="Ingestion",
            atoms_produced=len(validated),
            atoms_validated=len(validated),
            atoms_flagged=len(flagged),
            latency_ms=round(elapsed_ms, 1),
        )

        result: dict[str, Any] = {
            "atoms": [r.atom for r in unique],
            "validated_atoms": validated,
            "flagged_atoms": flagged,
            "errors": extra_errors,
        }
        if combined_redaction_map:
            result["pii_redaction_map"] = combined_redaction_map
        return result

    # ------------------------------------------------------------------
    # Document parsing
    # ------------------------------------------------------------------

    def _parse_document(
        self,
        upload: RawUpload,
        batch_id: str,
    ) -> Any | None:
        suffix = Path(upload.filename).suffix or ".bin"
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=suffix,
                delete=False,
            ) as tmp:
                tmp.write(upload.file_bytes)
                tmp_path = Path(tmp.name)
            return self._get_parser().parse(tmp_path)
        except Exception as exc:
            log.error(
                "ingestion_parse_error",
                batch_id=batch_id,
                error=str(exc),
            )
            return None
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Module-level singleton + LangGraph entry point
# ---------------------------------------------------------------------------

_node: IngestionNode | None = None
_node_lock = __import__("threading").Lock()


def ingestion_node(state: DynafitState) -> dict[str, Any]:
    """LangGraph Phase 1 node — delegates to cached IngestionNode."""
    global _node
    if _node is None:
        with _node_lock:
            if _node is None:
                _node = IngestionNode()
    return _node(state)

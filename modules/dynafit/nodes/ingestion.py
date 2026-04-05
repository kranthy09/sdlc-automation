"""
Ingestion node — Phase 1 of the REQFIT pipeline (Session C).

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
from platform.ingestion import (
    ArtifactStore,
    DocumentConverter,
    ElementExtractor,
    ImageDescriptor,
    SemanticChunker,
    TableNarrator,
    Unifier,
    get_ingestion_config,
)
from platform.ingestion.schemas import RawDocument
from platform.llm.client import LLMClient
from platform.observability.logger import get_logger
from platform.parsers.docling_parser import DoclingParser
from platform.schemas.product import ProductConfig
from platform.schemas.requirement import CitationRecord, RawUpload, RequirementAtom


from ..events import (
    publish_artifact_path,
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
    ColumnMappingResult,
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
    "ColumnMappingResult",
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
) -> list[tuple[str, str, CitationRecord]]:
    """Extract (requirement_text, source_ref, citation) triples.

    Prefers resolved table rows; falls back to prose chunks when no
    requirement_text column is found in any table.
    """
    texts: list[tuple[str, str, CitationRecord]] = []

    resolved = _map_table_rows_to_canonical(parse_result.tables)
    for i, row in enumerate(resolved):
        text = row.get("requirement_text", "").strip()
        if len(text) >= 10:
            excerpt = " | ".join(
                f"{k}: {v}"
                for k, v in row.items()
                if v and not k.startswith("_")
            )[:500]
            source_ref = f"table_row_{i}"
            texts.append((
                text,
                source_ref,
                CitationRecord(
                    source_ref=source_ref,
                    element_type="table",
                    excerpt=excerpt,
                ),
            ))

    if not texts:
        for chunk in parse_result.prose:
            text = chunk.text.strip()
            if len(text) >= 30:
                source_ref = f"page_{chunk.page}_prose"
                texts.append((
                    text,
                    source_ref,
                    CitationRecord(
                        source_ref=source_ref,
                        element_type="text",
                        page_no=chunk.page,
                        section_path=(
                            [chunk.section] if chunk.section else []
                        ),
                        excerpt=text[:500],
                    ),
                ))

    return texts


def _build_classified_requirements(
    raw_texts: list[tuple[str, str]],
    upload: RawUpload,
    llm: LLMClient,
    config: ProductConfig,
    *,
    batch_id: str = "",
    enriched_chunks: list[dict] | None = None,
    legacy_citation_map: dict[str, CitationRecord] | None = None,
) -> list[_ClassifiedRequirement]:
    """Run batch atomisation + classification on all raw texts.

    Sends chunks in groups of 10 per LLM call instead of one call
    per chunk, reducing N sequential calls to ceil(N/10). Falls back
    to individual calls for any batch that fails or returns a count
    mismatch.
    Returns a flat list of _ClassifiedRequirement, one per atom.

    If enriched_chunks is provided, extracts artifact_ids and builds
    CitationRecord from chunk metadata (unified pipeline path).
    If legacy_citation_map is provided, uses it for citation data
    (legacy DoclingParser path).
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

    # Build maps from source_ref → chunk metadata and citation
    chunk_metadata_map: dict[str, dict] = {}
    chunk_citation_map: dict[str, CitationRecord] = {}
    if enriched_chunks:
        for i, chunk in enumerate(enriched_chunks):
            sr = f"chunk_{i}"
            chunk_metadata_map[sr] = chunk

            # Extract artifact_ids from the chunk's artifact_refs
            refs = chunk.get("artifact_refs", [])
            art_ids = [
                r["artifact_id"]
                for r in refs
                if r.get("artifact_id")
            ]

            # Determine element_type from dominant modality
            mod_comp: dict = chunk.get("modality_composition", {})
            if mod_comp.get("TABLE", 0) > 0:
                el_type: str = "table"
            elif mod_comp.get("IMAGE", 0) > 0:
                el_type = "image"
            else:
                el_type = "text"

            meta: dict = chunk.get("chunk_metadata", {})
            source_pages: list[int] = meta.get("source_pages", [])
            chunk_citation_map[sr] = CitationRecord(
                source_ref=sr,
                element_type=el_type,  # type: ignore[arg-type]
                page_no=source_pages[0] if source_pages else None,
                section_path=chunk.get("section_path", []),
                excerpt=chunk.get("unified_text", "")[:500],
                artifact_ids=art_ids,
            )

    # Merge with legacy citations (legacy path may also provide some)
    citation_map: dict[str, CitationRecord] = {
        **(legacy_citation_map or {}),
        **chunk_citation_map,
    }

    results: list[_ClassifiedRequirement] = []
    counter = 0
    id_prefix = upload.upload_id[:8].upper()

    for atom_list, source_ref in zip(
        all_atom_lists, source_refs, strict=True
    ):
        chunk_meta = chunk_metadata_map.get(source_ref, {})
        mod_comp = chunk_meta.get("modality_composition", {})
        has_visual = (
            "TABLE" in mod_comp or "IMAGE" in mod_comp
        )
        citation = citation_map.get(source_ref)
        chunk_art_ids: list[str] = (
            citation.artifact_ids if citation else []
        )

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
                artifact_ids=chunk_art_ids,
                citations=(
                    [citation] if citation else []
                ),
            )
            results.append(
                _ClassifiedRequirement(
                    atom=requirement,
                    intent=atom.intent,
                    module=atom.module,
                    source_modality=atom.source_modality,
                    has_visual_evidence=(
                        has_visual or atom.has_visual_evidence
                    ),
                )
            )
            counter += 1

    return results


# ---------------------------------------------------------------------------
# IngestionNode — injectable dependencies, callable as a LangGraph node
# ---------------------------------------------------------------------------


class IngestionNode:
    """Phase 1 ingestion pipeline with injectable dependencies.

    Combines two parallel paths:
      Path A (legacy): DoclingParser → raw text extraction → atomization
      Path B (new): DocumentConverter → ElementExtractor → Unifier → SemanticChunker

    Path B output (enriched_chunks, artifacts) is returned in state for downstream use.

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
        table_narrator: TableNarrator | None = None,
        image_descriptor: ImageDescriptor | None = None,
    ) -> None:
        self._llm = llm_client
        self._parser = parser
        self._embedder = embedder
        self._narrator = table_narrator
        self._descriptor = image_descriptor
        self._ingestion_config = get_ingestion_config()
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

    def _get_narrator(self) -> TableNarrator:
        if self._narrator is None:
            self._narrator = TableNarrator(
                llm_client=self._get_llm(),
                concurrency=self._ingestion_config.narration_concurrency,
            )
        return self._narrator

    def _get_descriptor(self) -> ImageDescriptor:
        if self._descriptor is None:
            self._descriptor = ImageDescriptor(
                model=self._ingestion_config.image_description_model,
                llm_client=self._get_llm(),
                concurrency=self._ingestion_config.description_concurrency,
            )
        return self._descriptor

    # ------------------------------------------------------------------
    # Rejection helper — always publishes phase_complete before returning
    # ------------------------------------------------------------------

    def _reject(self, batch_id: str, reason: str, t0: float) -> dict[str, Any]:
        """Publish PhaseCompleteEvent (zeros) then return a rejection result.

        Ensures the Redis ``batch:{batch_id}`` hash transitions from
        ``"status": "active"`` to ``"status": "complete"`` even when
        ingestion exits early, preventing the UI from showing phase 1
        as permanently stuck.
        """
        elapsed_ms = (time.monotonic() - t0) * 1000
        publish_phase_complete(
            batch_id,
            phase=1,
            phase_name="Ingestion",
            atoms_produced=0,
            atoms_validated=0,
            atoms_flagged=0,
            latency_ms=round(elapsed_ms, 1),
        )
        return _make_rejection_result(reason)

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
            return self._reject(batch_id, f"file_validation_failed: {file_check.rejection_reason}", t0)

        # 2a. Try unified multimodal pipeline first (Phases B–E)
        enriched_chunks_output: list[dict] | None = None
        artifact_store_path: str | None = None
        raw_texts: list[tuple[str, str]] = []

        raw_doc = RawDocument(
            doc_id=batch_id,
            file_bytes=upload.file_bytes,
            mime_type=upload.mime_type or "application/pdf",
            filename=upload.filename,
            upload_metadata={"upload_id": upload.upload_id, "product_id": upload.product_id},
        )

        unified_texts, artifact_path, enriched_chunks_output = (
            self._run_unified_pipeline(raw_doc, batch_id)
        )
        legacy_citation_map: dict[str, CitationRecord] = {}
        if unified_texts:
            raw_texts = unified_texts
            artifact_store_path = artifact_path
            log.info(
                "unified_pipeline_success",
                batch_id=batch_id,
                text_count=len(raw_texts),
            )
            # Publish artifact path to Redis for API retrieval
            if artifact_store_path:
                publish_artifact_path(batch_id, artifact_store_path)
        else:
            # 2b. Fall back to legacy parser if unified pipeline fails
            parse_result = self._parse_document(upload, batch_id)
            if parse_result is None:
                return self._reject(
                    batch_id,
                    f"parse_failed: {upload.filename}",
                    t0,
                )
            triples = _collect_requirement_texts(parse_result)
            raw_texts = [(t, sr) for t, sr, _ in triples]
            legacy_citation_map = {
                sr: cit for _, sr, cit in triples
            }

        if not raw_texts:
            log.warning(
                "ingestion_no_text_found",
                batch_id=batch_id,
            )
            return self._reject(batch_id, "no_requirements_found: document produced no extractable text", t0)
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
            return self._reject(batch_id, f"injection_blocked: patterns={injection_scan.matched_patterns}", t0)

        extra_errors: list[str] = (
            [f"injection_flagged:{p}" for p in injection_scan.matched_patterns]
            if injection_scan.action == "FLAG_FOR_REVIEW"
            else []
        )

        # 4b. G2 — PII redaction (before any text reaches an LLM)
        # Dispatched concurrently — presidio AnalyzerEngine singleton is thread-safe.
        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

        def _redact_one(args: tuple[int, str, str]) -> tuple[str, str, dict[str, str], list[Any]]:
            idx, text, source_ref = args
            result = redact_pii(text, prefix=f"T{idx}_")
            return result.redacted_text, source_ref, result.redaction_map, result.entities_found

        combined_redaction_map: dict[str, str] = {}
        redacted_texts: list[tuple[str, str]] = []
        pii_entities_by_source_ref: dict[str, list[Any]] = {}
        _pii_args = [(i, t, r) for i, (t, r) in enumerate(raw_texts)]
        max_pii_workers = min(len(_pii_args), 4)
        with ThreadPoolExecutor(max_workers=max_pii_workers) as _pool:
            for _redacted_text, _source_ref, _rmap, _entities in _pool.map(_redact_one, _pii_args):
                redacted_texts.append((_redacted_text, _source_ref))
                combined_redaction_map.update(_rmap)
                # Store entities by source_ref for later attachment to atoms
                if _entities:
                    pii_entities_by_source_ref[_source_ref] = _entities

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
            enriched_chunks=enriched_chunks_output,
            legacy_citation_map=legacy_citation_map,
        )
        if not classified:
            return self._reject(batch_id, "atomisation_produced_no_atoms", t0)

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
            pii_entities_by_source_ref=pii_entities_by_source_ref,
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
        if artifact_store_path:
            result["artifact_store_batch_path"] = artifact_store_path
        if enriched_chunks_output:
            result["enriched_chunks"] = enriched_chunks_output
        return result

    # ------------------------------------------------------------------
    # Unified multimodal pipeline (Phases B–E)
    # ------------------------------------------------------------------

    def _run_unified_pipeline(
        self,
        raw_doc: RawDocument,
        batch_id: str,
    ) -> tuple[list[tuple[str, str]], str | None, list[dict] | None]:
        """Run the unified multimodal ingestion pipeline (Phases B-E).

        Returns:
            (requirement_texts, artifact_store_batch_path, enriched_chunks)
            where requirement_texts is list of (text, source_ref) tuples
            or ([], None, None) on failure
        """
        try:
            # Phase B: Convert → Extract
            converter = DocumentConverter(self._ingestion_config)
            docling_doc = converter.convert(raw_doc)
            publish_step_progress(batch_id, phase=1, step="convert", completed=1, total=5)

            extractor = ElementExtractor(
                window_size=self._ingestion_config.element_extractor_window_size
                if hasattr(self._ingestion_config, "element_extractor_window_size")
                else 5
            )
            elements = extractor.extract(docling_doc, source_doc=raw_doc.filename)
            publish_step_progress(batch_id, phase=1, step="extract", completed=2, total=5)

            log.debug(
                "extracted_elements",
                batch_id=batch_id,
                count=len(elements),
            )

            # Phase C: Store artifacts
            store = ArtifactStore(batch_id=batch_id)
            artifact_map = store.store_all(elements, extractor)
            publish_step_progress(batch_id, phase=1, step="store_artifacts", completed=3, total=5)

            # Phase D: Narrate & Describe & Unify
            narrator = self._get_narrator()
            descriptor = self._get_descriptor()
            unifier = Unifier(narrator, descriptor)
            unified_elements = unifier.unify(elements, artifact_map)
            publish_step_progress(batch_id, phase=1, step="unify", completed=4, total=5)

            log.debug(
                "unified_elements",
                batch_id=batch_id,
                count=len(unified_elements),
            )

            # Phase E: Semantic Chunking
            chunker = SemanticChunker(
                tokenizer_name=self._ingestion_config.chunk_tokenizer,
                max_tokens=self._ingestion_config.chunk_max_tokens,
                overlap_tokens=self._ingestion_config.chunk_overlap_tokens,
            )
            enriched_chunks = chunker.chunk(unified_elements)
            publish_step_progress(batch_id, phase=1, step="chunk", completed=5, total=5)

            log.debug(
                "enriched_chunks_produced",
                batch_id=batch_id,
                count=len(enriched_chunks),
            )

            # Extract requirement texts from enriched chunks
            requirement_texts: list[tuple[str, str]] = []
            for i, chunk in enumerate(enriched_chunks):
                text = chunk.unified_text.strip()
                if len(text) >= 10:
                    source_ref = f"chunk_{i}"
                    requirement_texts.append((text, source_ref))

            # Serialize enriched chunks for state
            chunks_serialized = [c.model_dump() for c in enriched_chunks]

            return requirement_texts, str(store.batch_path), chunks_serialized

        except Exception as exc:
            log.warning(
                "unified_pipeline_failed",
                batch_id=batch_id,
                error=str(exc),
            )
            return [], None, None

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

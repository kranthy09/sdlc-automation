# Unified Document Chunking Strategy — Multimodal Content Handling

## Implementation Requirement Document

> **Module:** DYNAFIT (Module 1) — Phase 1 Ingestion Agent  
> **Scope:** Redesign Step 1 (Document Parser) to unify text, table, and image modalities into a single chunking pipeline  
> **Layer:** `platform/ingestion/` (new) + `modules/dynafit/nodes/ingestion.py` (refactor)  
> **Owner:** Kranthi Kumar  
> **Date:** April 2, 2026  
> **Version:** 1.0

---

## 1. Problem Statement

The current ingestion pipeline treats text, tables, and images as independent extraction streams. Tables become DataFrame rows with no link to their section context. Images become orphaned blobs with generic captions. Cross-references between modalities ("See Figure 4.2" or "Same as DE Wave 1 requirement per Section 7.3") shatter at chunk boundaries.

This produces incomplete `RequirementAtom` objects that downstream phases cannot reason over truthfully. Phase 4 (Classification) receives atoms that say "3-way matching" but lack the tolerance validation logic from the adjacent process flow diagram. The result is classification decisions made on partial evidence — which directly increases the false-fit rate that HITL must correct in Phase 5.

The fix is structural: unify all modalities into text before chunking, so every chunk carries complete cross-modal context.

---

## 2. Architecture Constraint Summary

All implementation must respect the existing 4-layer dependency rule:

```
api/ → modules/ → agents/ → platform/
```

New chunking infrastructure lives in `platform/ingestion/` because it is reusable across modules (FDD FOR FITS and FDD FOR GAPS will consume the same parsed documents). Module-specific logic (D365 entity recognition, requirement-specific narration prompts) lives in `modules/dynafit/`. The ingestion LangGraph node calls platform abstractions — never the reverse.

Schema contracts are enforced via Pydantic v2 at every boundary. No dict-based data passing between steps.

---

## 3. Implementation Steps

Each step below is a self-contained unit of work. Steps are ordered by dependency — each step's output is the next step's input. All file paths are relative to the repository root.

---

### Step 1: Pydantic Schema Definitions

**Purpose:** Define the data contracts that every subsequent step produces and consumes. Schemas first, code second.

**File:** `platform/ingestion/schemas.py`

**Schemas to define:**

`RawDocument` — Entry point. Wraps the uploaded file bytes with metadata from the API layer. Fields: `doc_id` (str, UUID), `file_bytes` (bytes), `mime_type` (str, detected via `python-magic`), `filename` (str), `upload_metadata` (dict containing `country`, `wave`, `product`). This is what the Celery task passes into the ingestion node.

`DocumentElement` — Single element extracted from the DoclingDocument, before modality unification. Fields: `element_id` (str, content-hash), `raw_content` (str, the original extracted text or table markdown), `modality` (Literal["TEXT", "TABLE", "IMAGE"]), `page_no` (int), `position_index` (int, reading order within the page), `section_path` (list[str], hierarchical heading ancestry from Docling's structure), `bounding_box` (optional tuple of four floats for provenance), `source_doc` (str). For TABLE modality, `raw_content` holds the markdown-serialized table. For IMAGE modality, `raw_content` holds the raw caption if one exists.

`ArtifactRef` — Pointer to a stored original artifact. Fields: `artifact_id` (str, content-hash), `artifact_type` (Literal["TABLE_IMAGE", "TABLE_DATAFRAME", "FIGURE_IMAGE"]), `storage_path` (str, relative path under the artifact store root), `page_no` (int), `section_path` (list[str]).

`UnifiedElement` — Post-unification element where all modalities are represented as natural language text. Fields: `element_id` (str), `text` (str, narrated/described text), `modality` (Literal["TEXT", "TABLE", "IMAGE"]), `section_path` (list[str]), `page_no` (int), `position_index` (int), `artifact_refs` (list[ArtifactRef], pointers to stored originals), `source_doc` (str), `extraction_confidence` (float, from Docling's layout model score where available, default 1.0 for programmatic text).

`ChunkMetadata` — Rich metadata attached to each output chunk. Fields: `headings` (list[str]), `has_table` (bool), `has_image` (bool), `table_row_count` (int or None), `image_descriptions` (list[str] or None), `cross_references` (list[str] or None, detected "See Section X" patterns via regex), `source_pages` (list[int]).

`EnrichedChunk` — Final output of the chunking pipeline, consumed by Step 2 (Atomizer). Fields: `chunk_id` (str, deterministic hash of `unified_text + section_path`), `unified_text` (str), `chunk_metadata` (ChunkMetadata), `modality_composition` (dict[str, float], e.g. `{"TEXT": 0.6, "TABLE": 0.3, "IMAGE": 0.1}` — computed as token-count ratios per modality), `artifact_refs` (list[ArtifactRef]), `section_path` (list[str]), `page_range` (tuple[int, int]), `source_doc` (str), `token_count` (int).

**Validation rules to encode in the models:** `UnifiedElement.text` must be non-empty (validator). `EnrichedChunk.token_count` must be between 1 and 600 (validator, allows buffer above the 512 target). `modality_composition` values must sum to approximately 1.0 (validator with tolerance of 0.05).

**Continuation to Step 2:** These schemas are imported by every subsequent step. The `DocumentElement` schema is the output contract of Step 2, and the `UnifiedElement` schema is the input contract of Step 4. No step writes raw dicts — the Pydantic models are the single source of truth for what flows between steps.

---

### Step 2: Document Conversion via Docling

**Purpose:** Convert raw uploaded documents into Docling's `DoclingDocument` representation, then extract individual `DocumentElement` objects preserving reading order and section hierarchy.

**Files:**
- `platform/ingestion/converter.py` — Docling wrapper with pipeline routing
- `platform/ingestion/element_extractor.py` — DoclingDocument → list[DocumentElement]

**Converter implementation:**

The converter wraps Docling's `DocumentConverter` with two pipeline configurations. The standard pipeline uses Docling's layout analysis model (Heron), TableFormer for table structure recognition, and Tesseract OCR as fallback for mixed documents. The VLM pipeline uses SmolDocling for scanned or image-heavy documents where the standard pipeline would fail.

Pipeline routing logic: Convert the document with the standard pipeline first. After conversion, compute the text extraction ratio — total extracted text length divided by estimated document length (page count × 2000 characters average). If the ratio falls below 0.3, the document is likely scanned or image-heavy, and the converter falls back to the VLM pipeline. This avoids the cost of running SmolDocling on every document while catching cases where the standard pipeline produces insufficient output.

The converter accepts `RawDocument` and returns Docling's `DoclingDocument`. It writes the raw file to a temporary path (Docling requires file paths, not bytes), runs conversion, and cleans up. Error handling: if both pipelines fail, raise `IngestionError` with the Docling exception chain attached. The Celery task catches this and marks the batch as `FAILED` with a human-readable error message.

Configuration via environment variables: `DOCLING_OCR_ENGINE` (default: "tesseract"), `DOCLING_TABLE_MODE` (default: "accurate", alternative: "fast"), `DOCLING_VLM_MODEL` (default: "smoldocling"), `DOCLING_FORCE_VLM` (default: false, for testing).

**Element extractor implementation:**

Iterates the `DoclingDocument` in reading order. Docling's document model stores elements with provenance metadata including page number, bounding box, and parent section headings. For each element:

- Text elements (`DocItemLabel.TEXT`, `SECTION_HEADER`, `LIST_ITEM`, `CAPTION`): Extract the text content and section heading ancestry. Section headers themselves are not emitted as separate elements — they are captured in `section_path` of subsequent text elements.
- Table elements (`DocItemLabel.TABLE`): Serialize the table to markdown using Docling's built-in markdown table serializer (this preserves headers and cell alignment). Store the raw `DoclingTable` object temporarily for DataFrame conversion in Step 3. Record the page number and bounding box for artifact extraction.
- Picture elements (`DocItemLabel.PICTURE`): Extract the image bytes from the `DoclingDocument` (Docling stores these as embedded data). Extract the associated caption if Docling linked one (it groups captions with their respective pictures). Store raw caption text in `raw_content`.

The extractor returns `list[DocumentElement]` sorted by `(page_no, position_index)`. This is the reading-order sequence that preserves the document's original flow.

**Continuation to Step 3:** The element extractor produces a flat list of `DocumentElement` objects where tables are markdown strings and images have raw captions (or empty strings). Step 3 takes this list and enriches the TABLE and IMAGE elements with LLM/VLM-generated natural language, converting them into `UnifiedElement` objects that the chunker can treat uniformly.

---

### Step 3: Artifact Storage Layer

**Purpose:** Persist original table images and figure images to a content-addressable store so that downstream phases (especially Phase 5 HITL review and the `/results` page) can retrieve the original visual evidence alongside the narrated text.

**File:** `platform/ingestion/artifact_store.py`

**Storage design:**

The artifact store is a thin abstraction over the filesystem with content-addressable naming. Each artifact is stored under a deterministic path derived from its content hash: `{ARTIFACT_ROOT}/{batch_id}/{artifact_type}/{content_hash}.{ext}`. The content hash uses SHA-256 truncated to 16 hex characters — collision probability is negligible at the scale of a single batch (hundreds of artifacts, not millions).

Three storage operations:

`store_table_image` — Receives a `DoclingDocument`, a table element's bounding box, and the page number. Rasterizes the page region containing the table using Docling's page image export (or `pdf2image` as fallback if the source was PDF). Saves the cropped region as PNG. Returns an `ArtifactRef` with `artifact_type="TABLE_IMAGE"`.

`store_table_dataframe` — Receives the Docling table object, converts to a Pandas DataFrame, serializes to Parquet. Parquet is chosen over CSV because it preserves column types and handles multi-line cell content without escaping issues. Returns an `ArtifactRef` with `artifact_type="TABLE_DATAFRAME"`.

`store_figure_image` — Receives the raw image bytes extracted by Docling from the document. Saves as PNG (re-encoding if necessary via Pillow to normalize format). Returns an `ArtifactRef` with `artifact_type="FIGURE_IMAGE"`.

A `retrieve` method accepts an `artifact_id` and returns the file bytes plus metadata. This is called by the `/results/{batch_id}` API endpoint when the consultant expands a classification row and wants to see the original table or diagram.

**Configuration:** `ARTIFACT_STORE_ROOT` environment variable, defaulting to `{DATA_DIR}/artifacts/`. In production, this can point to an S3-compatible object store via `s3fs` — the store abstraction uses `pathlib.Path` operations that `s3fs` provides transparently.

**Continuation to Step 4:** Step 3 stores the originals and produces `ArtifactRef` objects. Step 4 receives the `DocumentElement` list from Step 2 and the `ArtifactRef` list from Step 3. For each TABLE element, Step 4 has both the markdown representation (for narration) and the stored artifact reference (for provenance). For each IMAGE element, Step 4 has the raw caption and the stored image reference. Step 4's job is to convert these into natural language.

---

### Step 4: Multimodal Narration and Description

**Purpose:** Convert TABLE and IMAGE elements into natural language text, producing `UnifiedElement` objects where all modalities share the same representation. TEXT elements pass through unchanged (modality tag preserved, text copied as-is).

**Files:**
- `platform/ingestion/narration.py` — LLM-based table narration
- `platform/ingestion/description.py` — VLM-based image description
- `platform/ingestion/unifier.py` — Orchestrates narration + description, emits UnifiedElement list

**Table narration implementation:**

For each TABLE `DocumentElement`, the narrator sends the markdown-serialized table (or individual rows for large tables) to the LLM with a structured prompt. The prompt includes the element's `section_path` as context so the LLM knows the business domain of the table.

Prompt structure (stored as Jinja2 template at `platform/ingestion/templates/table_narration.j2`):

```
You are a D365 F&O requirement analyst. Below is a table from the section
"{{ section_path | join(' > ') }}" of a business requirement document.

Convert each row into a self-contained natural language requirement statement.
Preserve ALL column values in your narration. Do not interpret or add information
— narrate faithfully what the table says.

If the table contains a requirement ID column, include it.
If the table contains a priority or module column, include those as metadata.

Table:
{{ table_markdown }}

Output one paragraph per row. No bullet points, no numbering.
```

The LLM call uses the platform's existing `LLMClient` (`platform/llm/client.py`) with `with_structured_output()` to enforce a response schema: `NarratedTable` with a `rows` field containing `list[NarratedRow]` where each `NarratedRow` has `row_index` (int) and `narration` (str). This ensures one narration per table row with traceability back to the source.

For tables with more than 15 rows, the narrator batches rows (15 per LLM call) to stay within context window limits. Each batch includes the table headers for context continuity.

**Parallelization:** All table narration calls within a batch are independent. Use `asyncio.gather` with a semaphore (limit: `NARRATION_CONCURRENCY`, default 5) to parallelize. This mirrors the pattern already established in the Phase 4 classification parallelization plan from the codebase optimization doc.

**Image description implementation:**

For each IMAGE `DocumentElement`, the descriptor sends the stored image (retrieved via `ArtifactRef` from Step 3) to a VLM for semantic description. Two VLM options, selectable via `IMAGE_DESCRIPTION_MODEL` environment variable:

Option A (default, local): SmolVLM via Docling's picture description pipeline. Fast, private, runs on commodity hardware. Produces adequate descriptions for most diagrams and screenshots.

Option B (high-quality, API): Claude or GPT-4o vision API. Produces richer, more contextually aware descriptions. Useful for complex process flow diagrams where understanding the D365 implications matters. Selected when `IMAGE_DESCRIPTION_MODEL=claude` or `IMAGE_DESCRIPTION_MODEL=gpt4o`.

Prompt structure (stored as `platform/ingestion/templates/image_description.j2`):

```
This image appears in section "{{ section_path | join(' > ') }}"
of a D365 F&O business requirement document.
{% if caption %}Existing caption: "{{ caption }}"{% endif %}

Describe what this image shows in the context of ERP implementation requirements.
Focus on: process flows, approval chains, system interactions, data entity
relationships, UI screenshots showing D365 forms or navigation paths.
If you recognize D365 entities (VendTrans, PurchTable, LedgerJournalTable etc.),
name them specifically.

Respond in 2-4 sentences. Be specific, not generic.
```

If the VLM call fails (timeout, model unavailable), fall back to the existing caption. If no caption exists, emit a minimal description: `"[Image on page {page_no} in section {section_path[-1]}]"`. The element is still included in the unified stream — downstream phases can flag it as low-confidence via the `extraction_confidence` field (set to 0.3 for fallback descriptions).

**Unifier orchestration:**

The unifier iterates the `DocumentElement` list in reading order and produces a `UnifiedElement` for each:

- TEXT elements: Copy `raw_content` to `text` unchanged. Set `artifact_refs` to empty list. Set `extraction_confidence` to 1.0.
- TABLE elements: Replace `raw_content` with the narrated text from the LLM. Attach the `ArtifactRef` objects from Step 3 (both TABLE_IMAGE and TABLE_DATAFRAME). Set `extraction_confidence` based on Docling's table detection confidence if available.
- IMAGE elements: Replace `raw_content` with the VLM description. Attach the FIGURE_IMAGE `ArtifactRef` from Step 3. Set `extraction_confidence` based on whether the description is from the VLM (0.8+) or fallback (0.3).

The unifier returns `list[UnifiedElement]` in the same reading order as the input. The count may differ from the input because each table row narration becomes a separate `UnifiedElement` (a table with 10 rows produces 10 elements, not 1). All 10 share the same `section_path` and `artifact_refs` but have sequential `position_index` values.

**Continuation to Step 5:** The unifier output is a flat list of `UnifiedElement` objects where every element has a `.text` field containing natural language. TABLE elements have been expanded (one per row) and IMAGE elements have been described. Step 5 takes this unified list and chunks it into token-bounded segments for the embedding model.

---

### Step 5: Semantic Chunking with Overlap

**Purpose:** Partition the unified element stream into `EnrichedChunk` objects that respect section boundaries, table atomicity, and embedding model token limits.

**File:** `platform/ingestion/chunker.py`

**Chunking strategy:**

The chunker does not use Docling's `HybridChunker` directly on the raw `DoclingDocument` — that would reintroduce the modality fragmentation problem because Docling chunks before narration. Instead, the chunker operates on the `list[UnifiedElement]` output from Step 4, where all content is already unified text.

The chunking algorithm is a custom implementation that respects three constraints simultaneously:

Constraint 1 — Token budget: Each chunk must contain no more than 512 tokens as measured by the `bge-large-en-v1.5` tokenizer. This aligns with the embedding model used in Phase 2 (Knowledge Retrieval). The tokenizer is loaded once at module import time from `tokenizers` library (`Tokenizer.from_pretrained("BAAI/bge-large-en-v1.5")`).

Constraint 2 — Section boundary respect: Chunks never cross section headings. If the current accumulation would span from section "AP > Invoice Processing" into section "AP > Tax Withholding", the chunker finalizes the current chunk and starts a new one at the section boundary. This prevents chimera chunks that mix unrelated business processes.

Constraint 3 — Table row atomicity: A single narrated table row is never split across chunks. If adding a table-row element would exceed the token budget, the chunker finalizes the current chunk and starts a new one with that row. If a single table row exceeds 512 tokens on its own (rare but possible with very wide tables), it gets its own chunk with `token_count` allowed up to 600 (the buffer encoded in the schema validator).

**Overlap implementation:** When finalizing a chunk, the chunker copies the last N tokens (configurable via `CHUNK_OVERLAP_TOKENS`, default 64) into a buffer. This buffer is prepended to the next chunk's text, creating a sliding window overlap. The overlap ensures that cross-references spanning chunk boundaries ("In addition to the above requirement...") are present in both chunks. Overlap tokens are not double-counted in `modality_composition` — they inherit the modality of the original element.

**Metadata computation:** As elements accumulate into a chunk, the chunker tracks which modalities contributed and how many tokens each contributed. After finalization:

- `modality_composition` = `{modality: tokens_from_modality / total_tokens}` for each modality present.
- `has_table` / `has_image` = boolean flags derived from modality composition.
- `table_row_count` = count of TABLE-modality elements in the chunk.
- `cross_references` = regex scan of the unified text for patterns like "See Section", "Refer to", "Same as REQ-", "per Figure" (captured as strings).
- `source_pages` = deduplicated sorted list of page numbers from constituent elements.
- `page_range` = `(min(source_pages), max(source_pages))`.
- `artifact_refs` = flattened deduplicated list from all constituent elements.

**Output:** `list[EnrichedChunk]` sorted by `(section_path, page_range[0])`. Typical output for a 48-page requirement PDF: 80-120 chunks, depending on document density.

**Continuation to Step 6:** The `EnrichedChunk` list is the final output of Step 1 (Document Parser). It flows into the existing Step 2 (Requirement Extractor / Atomizer) which is an LLM-based extraction step. The atomizer currently receives raw text chunks — it will now receive `EnrichedChunk` objects with richer metadata. The atomizer prompt is updated (Step 6) to leverage `section_path` for module tagging and `modality_composition` for confidence weighting.

---

### Step 6: Ingestion Node Integration into LangGraph

**Purpose:** Wire the chunking pipeline (Steps 2-5) into the DYNAFIT LangGraph graph as the ingestion node, replacing the current document parser logic. Update the `DynafitState` TypedDict to carry `EnrichedChunk` objects instead of raw text.

**Files:**
- `modules/dynafit/nodes/ingestion.py` — Refactored ingestion node
- `modules/dynafit/state.py` — Updated state schema
- `modules/dynafit/graph.py` — Graph wiring (if ingestion node signature changes)

**State schema update:**

The `DynafitState` TypedDict currently carries parsed document content as a list of text strings or a similar flat structure. Update to carry `list[EnrichedChunk]` under a new key `enriched_chunks`. The existing key for raw text remains for backward compatibility but is deprecated — the atomizer node checks for `enriched_chunks` first, falls back to the legacy key if absent.

Add `artifact_store_batch_path` (str) to state — the path under the artifact store where this batch's table images and figure images are stored. This is set by the ingestion node and read by the presentation node (Phase 5) when building journey data for HITL review.

**Ingestion node implementation:**

The node function signature follows the existing LangGraph pattern — it receives `DynafitState` and returns a partial dict with the keys it updates:

```python
def ingestion_node(state: DynafitState) -> dict:
    """Phase 1 · Step 1: Document parsing with multimodal unification."""
    raw_doc = RawDocument(
        doc_id=state["batch_id"],
        file_bytes=state["uploaded_file_bytes"],
        mime_type=state["mime_type"],
        filename=state["filename"],
        upload_metadata={
            "country": state["country"],
            "wave": state["wave"],
            "product": state["product"],
        },
    )

    # Step 2: Convert via Docling
    docling_doc = DocumentConverter(config_from_env()).convert(raw_doc)

    # Step 2b: Extract elements in reading order
    elements = ElementExtractor().extract(docling_doc, source_doc=raw_doc.filename)

    # Step 3: Store artifacts (table images, figure images)
    artifact_store = ArtifactStore(batch_id=state["batch_id"])
    artifact_refs = artifact_store.store_all(docling_doc, elements)

    # Step 4: Narrate tables, describe images, unify
    unified = Unifier(
        llm_client=get_llm_client(),
        vlm_client=get_vlm_client(),
    ).unify(elements, artifact_refs)

    # Step 5: Chunk with overlap
    chunks = SemanticChunker(
        tokenizer_name="BAAI/bge-large-en-v1.5",
        max_tokens=512,
        overlap_tokens=64,
    ).chunk(unified)

    # Publish progress event
    publish_progress(
        batch_id=state["batch_id"],
        phase=1, step=1,
        message=f"Parsed {len(chunks)} chunks from {raw_doc.filename}",
        detail={
            "element_count": len(elements),
            "chunk_count": len(chunks),
            "tables_found": sum(1 for e in elements if e.modality == "TABLE"),
            "images_found": sum(1 for e in elements if e.modality == "IMAGE"),
        },
    )

    return {
        "enriched_chunks": [c.model_dump() for c in chunks],
        "artifact_store_batch_path": artifact_store.batch_path,
    }
```

**WebSocket progress events:** The ingestion node publishes progress events at each sub-step (conversion started, elements extracted, narration in progress, chunking complete). These use the existing Redis pub/sub → WebSocket pipeline. The frontend progress bar for Phase 1 already exists — the events just become more granular.

**Error handling:** Each sub-step is wrapped in a try/except that catches specific exceptions (`DoclingConversionError`, `LLMNarrationError`, `VLMDescriptionError`) and either retries (for transient LLM/VLM failures) or marks the batch as `FAILED` with a diagnostic message. LangGraph's checkpointing ensures that if the node fails after artifact storage (Step 3) but before chunking (Step 5), a retry resumes from the checkpoint without re-storing artifacts.

**Continuation to Step 7:** With the ingestion node producing `EnrichedChunk` objects, the downstream atomizer node (Step 2 of Phase 1) must be updated to consume them. Step 7 handles this integration point.

---

### Step 7: Atomizer Prompt Update

**Purpose:** Update the LLM prompt in the requirement extractor (Step 2 of Phase 1, the atomizer) to leverage the enriched chunk metadata. The atomizer's job is unchanged — extract one `RequirementAtom` per discrete business need — but it now receives richer input.

**File:** `modules/dynafit/nodes/atomizer.py` (existing, modify)

**Prompt update:**

The current atomizer prompt receives raw text and extracts requirements. The updated prompt receives `EnrichedChunk` data and uses the metadata to improve extraction:

```
You are extracting discrete business requirements from a D365 F&O
requirement document chunk.

Section context: {{ chunk.section_path | join(' > ') }}
Content modalities: {{ chunk.modality_composition }}
Page range: {{ chunk.page_range[0] }}–{{ chunk.page_range[1] }}

--- CHUNK TEXT ---
{{ chunk.unified_text }}
--- END ---

Extract each discrete business requirement as a separate item.
One requirement = one testable business need.

For each requirement, provide:
- requirement_text: the requirement in clear, unambiguous language
- module: D365 module (infer from section context: {{ chunk.section_path[0] if chunk.section_path else 'UNKNOWN' }})
- priority: if stated in the text, otherwise null
- has_visual_evidence: {{ 'true' if chunk.chunk_metadata.has_image else 'false' }}
- source_modality: dominant modality from {{ chunk.modality_composition }}

If this chunk contains narrated table rows, each row likely contains
one requirement. Do not merge rows.

If this chunk contains image descriptions, the description may reference
D365 entities or process flows — extract these as requirements only if
they describe a specific business need, not if they are purely descriptive.
```

The structured output schema for the atomizer response adds two new fields to the existing `ExtractedRequirement` model: `has_visual_evidence` (bool) and `source_modality` (str). These flow through to `RequirementAtom` and are available in Phase 4 for classification confidence adjustment.

**Backward compatibility:** If the state contains the legacy raw-text key instead of `enriched_chunks`, the atomizer falls back to the existing prompt. This allows gradual rollout — batches already in progress complete with the old pipeline, new batches use the unified pipeline.

**Continuation to downstream phases:** The atomizer produces `RequirementAtom` objects as before. The atoms now carry `has_visual_evidence` and `source_modality` metadata. Phase 2 (Knowledge Retrieval) and Phase 3 (Semantic Matching) operate on `RequirementAtom.requirement_text` which is unchanged in structure — they receive higher-quality text because the ingestion was more thorough, but their code requires no changes. Phase 4 (Classification) can optionally use `has_visual_evidence` as a confidence signal (a requirement backed by a process flow diagram is more likely to be accurately described). Phase 5 (Validation) uses `artifact_store_batch_path` to render original table images and diagrams in the HITL review interface.

---

### Step 8: Artifact Retrieval API Endpoint

**Purpose:** Expose stored artifacts (table images, figure images, DataFrames) via the existing FastAPI route layer so the `/results/{batch_id}` page can display original visual evidence alongside classification results.

**File:** `api/routes/dynafit.py` (add endpoint)

**Endpoint:**

```
GET /api/v1/d365_fo/dynafit/{batch_id}/artifacts/{artifact_id}
```

Returns the artifact file bytes with appropriate `Content-Type` header (`image/png` for images, `application/octet-stream` for Parquet DataFrames). The route reads `artifact_store_batch_path` from the batch state (Redis), constructs the full path, and serves the file.

Access control: The endpoint inherits the existing JWT RBAC middleware. Only users with access to the batch can retrieve its artifacts.

Response headers include `Cache-Control: public, max-age=86400` because artifacts are immutable (content-addressed). The browser caches them for 24 hours, eliminating redundant fetches when the consultant expands multiple rows referencing the same table.

A second endpoint serves artifact metadata without the file bytes:

```
GET /api/v1/d365_fo/dynafit/{batch_id}/artifacts
```

Returns `list[ArtifactRef]` for all artifacts in the batch. The frontend uses this to pre-render artifact indicators (table icon, image icon) on each result row before the consultant clicks to expand.

**Continuation to existing `/results` page:** The existing `ResultRow.tsx` component already has an evidence panel. The artifact endpoint provides the data source for rendering original table images and diagrams in that panel. The frontend changes are explicitly out of scope for this document — the backend contract (the two endpoints above) is sufficient for a frontend developer to integrate independently.

---

## 4. Configuration Reference

All new configuration is via environment variables, consistent with the existing platform pattern (`platform/config.py` reads from env with defaults).

| Variable | Default | Description |
|---|---|---|
| `DOCLING_OCR_ENGINE` | `tesseract` | OCR engine for Docling standard pipeline |
| `DOCLING_TABLE_MODE` | `accurate` | TableFormer mode: `accurate` or `fast` |
| `DOCLING_VLM_MODEL` | `smoldocling` | VLM model for scanned document fallback |
| `DOCLING_FORCE_VLM` | `false` | Force VLM pipeline for all documents (testing) |
| `DOCLING_VLM_FALLBACK_THRESHOLD` | `0.3` | Text extraction ratio below which VLM fallback triggers |
| `IMAGE_DESCRIPTION_MODEL` | `smolvlm` | VLM for image descriptions: `smolvlm`, `claude`, `gpt4o` |
| `NARRATION_CONCURRENCY` | `5` | Max parallel LLM calls for table narration |
| `DESCRIPTION_CONCURRENCY` | `3` | Max parallel VLM calls for image description |
| `CHUNK_MAX_TOKENS` | `512` | Max tokens per chunk |
| `CHUNK_OVERLAP_TOKENS` | `64` | Token overlap between adjacent chunks |
| `CHUNK_TOKENIZER` | `BAAI/bge-large-en-v1.5` | Tokenizer for token counting |
| `ARTIFACT_STORE_ROOT` | `{DATA_DIR}/artifacts` | Root path for artifact storage |

---

## 5. Dependency Additions

New Python packages required (add to `requirements.txt` / `pyproject.toml`):

| Package | Version | Purpose |
|---|---|---|
| `docling` | `>=2.25` | Document conversion, layout analysis, TableFormer |
| `docling-core` | `>=2.25` | DoclingDocument model, chunkers, serializers |
| `tokenizers` | `>=0.21` | Fast tokenization for bge-large-en-v1.5 |
| `pdf2image` | `>=1.17` | Page rasterization for table image extraction |
| `pyarrow` | `>=18.0` | Parquet serialization for DataFrame artifacts |

Packages already in the stack that are reused: `python-magic` (MIME detection), `Pillow` (image processing), `Jinja2` (prompt templates), `pandas` (DataFrame operations), `pydantic` v2 (schemas).

SmolDocling model weights (`ds4sd/SmolDocling-256M-preview`) are downloaded on first use via Hugging Face `transformers`. For air-gapped deployments, pre-download to a local model cache and set `HF_HOME` environment variable.

---

## 6. Testing Strategy — Cross-Functional Journey Test

Testing follows the minimal strategy: no unit tests per sub-step. One end-to-end journey test that exercises the entire pipeline from raw document to enriched chunks, validating the contract at the output boundary.

**Test file:** `tests/integration/test_ingestion_journey.py`

**Test fixture:** A synthetic requirement document (PDF, 4 pages) containing all three modalities. Page 1: prose paragraph describing AP invoice processing requirements. Page 2: requirement table with 5 rows (REQ-AP-041 through REQ-AP-045), columns: ID, Requirement, Priority, Module. Page 3: process flow diagram (a simple PNG embedded in the PDF) showing the 3-way matching workflow. Page 4: mixed content — prose paragraph referencing the table on page 2 ("As described in the requirements table above") and the diagram on page 3 ("See process flow on previous page").

The fixture PDF is generated once via ReportLab and stored in `tests/fixtures/synthetic_multimodal_req.pdf`. The fixture generation script is committed alongside the test.

**Single journey test — `test_full_ingestion_produces_valid_enriched_chunks`:**

Input: The synthetic PDF as `RawDocument`.

Assertions (in order, short-circuiting):

1. **Conversion succeeds**: No `IngestionError` raised. DoclingDocument is returned with `texts`, `tables`, and `pictures` populated.

2. **Element extraction count**: `DocumentElement` list contains elements from all three modalities. At least 1 TABLE element and 1 IMAGE element are present.

3. **Artifact storage**: `ArtifactStore` contains at least 1 TABLE_IMAGE artifact and 1 FIGURE_IMAGE artifact. Retrieved artifact bytes are valid PNG (first 8 bytes match PNG magic number).

4. **Table narration quality**: The `UnifiedElement` for the table contains narrated text that includes "REQ-AP-041" and "3-way matching" (verifying that the LLM narration preserved the requirement ID and key terms). The narrated text does not contain markdown table syntax (pipes, dashes) — it is natural language.

5. **Image description quality**: The `UnifiedElement` for the image contains descriptive text that is more than 20 characters (not a fallback placeholder). If the test environment has a VLM available, assert the description contains at least one D365-related term (from a predefined list: "purchase order", "invoice", "vendor", "matching", "approval").

6. **Chunk output contract**: All `EnrichedChunk` objects pass Pydantic validation. Every chunk has `token_count` between 1 and 600. Every chunk has `modality_composition` values summing to approximately 1.0. No chunk's `section_path` is empty.

7. **Cross-modal presence**: At least one chunk contains content from multiple modalities (i.e., `modality_composition` has more than one key with value > 0.1). This verifies that the unification correctly interleaved table narrations and image descriptions with surrounding prose.

8. **Section boundary respect**: No chunk's `unified_text` contains content from two different top-level sections (verify by checking that all `section_path[0]` values within a chunk are identical).

**Test environment notes:** The journey test requires the Docling models to be available (downloaded or cached). In CI, set `DOCLING_TABLE_MODE=fast` to reduce test time. For the LLM narration step, the test uses the same `LLMClient` as production — if running against a mock LLM (for CI speed), the mock returns a template narration that includes the requirement ID and key terms from the table markdown.

For the VLM description step, if no VLM is available in CI, set `IMAGE_DESCRIPTION_MODEL=none` (a special value that triggers the fallback path). Assertion 5 adjusts its threshold accordingly (accepts fallback placeholder text).

**Total test count:** 1 test function with 8 sequential assertions. Estimated runtime: 15-30 seconds with real Docling + mock LLM, 45-90 seconds with real Docling + real LLM.

---

## 7. File Tree Summary

```
platform/
  ingestion/
    __init__.py
    schemas.py              ← Step 1: Pydantic models
    converter.py            ← Step 2: Docling wrapper
    element_extractor.py    ← Step 2: DoclingDocument → DocumentElement[]
    artifact_store.py       ← Step 3: Content-addressable artifact storage
    narration.py            ← Step 4: LLM table narration
    description.py          ← Step 4: VLM image description
    unifier.py              ← Step 4: Orchestrates narration + description
    chunker.py              ← Step 5: Semantic chunking with overlap
    templates/
      table_narration.j2    ← Step 4: Narration prompt template
      image_description.j2  ← Step 4: Description prompt template

modules/
  dynafit/
    nodes/
      ingestion.py          ← Step 6: Refactored LangGraph node (modify)
      atomizer.py           ← Step 7: Updated prompt (modify)
    state.py                ← Step 6: DynafitState update (modify)

api/
  routes/
    dynafit.py              ← Step 8: Artifact retrieval endpoints (modify)

tests/
  fixtures/
    synthetic_multimodal_req.pdf   ← Test fixture (generated)
    generate_fixture.py            ← Fixture generation script
  integration/
    test_ingestion_journey.py      ← Single journey test
```

---

## 8. Execution Order and Estimated Effort

| Step | Description | Depends On | Effort |
|---|---|---|---|
| 1 | Schema definitions | None | 2 hours |
| 2 | Document conversion + element extraction | Step 1 | 4 hours |
| 3 | Artifact storage layer | Step 1 | 3 hours |
| 4 | Multimodal narration and description | Steps 1, 2, 3 | 6 hours |
| 5 | Semantic chunking with overlap | Steps 1, 4 | 4 hours |
| 6 | LangGraph node integration | Steps 1–5 | 3 hours |
| 7 | Atomizer prompt update | Steps 1, 6 | 2 hours |
| 8 | Artifact retrieval API | Steps 1, 3 | 2 hours |
| Test | Journey test + fixture | All steps | 3 hours |
| **Total** | | | **~29 hours** |

Steps 2 and 3 can proceed in parallel (both depend only on Step 1). Steps 6, 7, and 8 can proceed in parallel (all depend on earlier steps but not on each other). Critical path: Step 1 → Step 2 → Step 4 → Step 5 → Step 6 → Test. With parallelization, wall-clock time is approximately 22 hours.

---

## 9. Downstream Impact Assessment

**Phase 2 (Knowledge Retrieval):** No code changes. Receives `RequirementAtom.requirement_text` as before. Quality improvement: atoms now contain narrated table content and described image content, so embedding similarity against D365 capability descriptions is higher. Expected retrieval recall improvement: 10-15% for table-heavy requirement documents.

**Phase 3 (Semantic Matching):** No code changes. Cosine similarity and entity overlap operate on the same embedding space. The spaCy EntityRuler's ~2,400 D365 patterns will match more frequently because image descriptions now contain D365 entity names (VendTrans, PurchTable) that were previously invisible.

**Phase 4 (Classification):** Optional enhancement. The `has_visual_evidence` flag on `RequirementAtom` can be used as a confidence boost signal — a requirement backed by a process flow diagram is less likely to be misclassified because the classification LLM has richer evidence. This is a threshold tuning concern, not a code change.

**Phase 5 (Validation & Output):** The HITL review interface can display original artifacts alongside classification results. The `artifact_store_batch_path` in state and the API endpoints from Step 8 provide the backend support. Frontend integration is a separate work item.

**Module 2 (FDD FOR FITS):** Consumes `ValidatedFitmentBatch` which is unchanged in schema. However, the artifact store established here can be reused — FDD generation benefits from having the original process flow diagrams available for inclusion in the generated FDD document.

---

*End of document.*

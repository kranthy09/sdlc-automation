# Plan: Unified Multimodal Chunking Pipeline

## Context

The current ingestion pipeline (`platform/parsers/docling_parser.py`) treats text, tables, and images as independent streams. It uses pdfplumber (not actual Docling), produces flat `ProseChunk` objects with no section hierarchy, and discards cross-modal relationships. This causes incomplete `RequirementAtom` objects — Phase 4 classifies on partial evidence, inflating the false-fit rate corrected by HITL in Phase 5.

The fix introduces a new `platform/ingestion/` package that unifies all modalities into natural language text before chunking, producing `EnrichedChunk` objects with rich metadata. The requirement document is `docs/UNIFIED_CHUNKING_REQUIREMENT.md`.

---

## Architecture Alignment

- New code lives in `platform/ingestion/` (reusable across modules, no module-specific logic)
- Module-specific wiring lives in `modules/dynafit/nodes/ingestion.py`
- Dependency rule: `modules/ → platform/` only — never sideways or downward
- Old `platform/parsers/docling_parser.py` remains (backward-compat) — new ingestion is opt-in via `enriched_chunks` key in state
- All schemas: `PlatformModel` base (`frozen=True`)
- All config: extend `platform/config/settings.py` (`Settings(BaseSettings)`)
- All LLM calls: through `platform/llm/client.py` — never import `anthropic` directly
- Observability: `get_logger(__name__)` first import in every file; `metrics.py` at every external call

---

## File Structure

```
platform/
  ingestion/
    __init__.py               ← public exports: all schemas + main classes
    _errors.py                ← IngestionError, LLMNarrationError, VLMDescriptionError
    _config.py                ← IngestionConfig(BaseSettings) — 12 env vars
    schemas.py                ← Step 1: RawDocument, DocumentElement, ArtifactRef,
                                        UnifiedElement, ChunkMetadata, EnrichedChunk
    converter.py              ← Step 2a: DocumentConverter (Docling wrapper, VLM fallback)
    element_extractor.py      ← Step 2b: ElementExtractor — DoclingDocument → list[DocumentElement]
    artifact_store.py         ← Step 3: ArtifactStore — content-addressable filesystem store
    narration.py              ← Step 4a: TableNarrator — LLM table-row narration
    description.py            ← Step 4b: ImageDescriptor — VLM image description
    unifier.py                ← Step 4c: Unifier — orchestrates narration+description → UnifiedElement[]
    chunker.py                ← Step 5: SemanticChunker — token-bounded, section-respecting
    templates/
      table_narration.j2      ← Jinja2 narration prompt
      image_description.j2    ← Jinja2 description prompt

modules/dynafit/
  nodes/
    ingestion.py              ← Step 6: refactored LangGraph node (replaces pdfplumber flow)
    atomizer.py               ← Step 7: prompt update for EnrichedChunk input
  state.py                    ← Step 6: add enriched_chunks + artifact_store_batch_path

api/routes/
  dynafit.py                  ← Step 8: add two GET artifact endpoints

tests/
  fixtures/
    generate_fixture.py       ← synthetic PDF fixture generator (ReportLab)
    synthetic_multimodal_req.pdf  ← generated fixture (committed)
  integration/
    test_ingestion_journey.py ← single journey test, 8 assertions
```

---

## Implementation Steps

### Phase A — Foundation (no dependencies, do first)

**Task A1 — `platform/ingestion/_errors.py`**
Define three exception classes inheriting from `platform/schemas/errors.py` base:
- `IngestionError(Exception)` — wraps Docling conversion failures
- `LLMNarrationError(Exception)` — transient LLM call failures
- `VLMDescriptionError(Exception)` — transient VLM call failures

**Task A2 — `platform/ingestion/_config.py`**
`IngestionConfig(BaseSettings)` with 12 fields. Extend `platform/config/settings.py` by importing and composing `IngestionConfig` as a nested field on `Settings`. Fields:
```
docling_ocr_engine: str = "tesseract"
docling_table_mode: str = "accurate"        # "accurate" | "fast"
docling_vlm_model: str = "smoldocling"
docling_force_vlm: bool = False
docling_vlm_fallback_threshold: float = 0.3
image_description_model: str = "smolvlm"   # "smolvlm" | "claude" | "gpt4o" | "none"
narration_concurrency: int = 5
description_concurrency: int = 3
chunk_max_tokens: int = 512
chunk_overlap_tokens: int = 64
chunk_tokenizer: str = "BAAI/bge-large-en-v1.5"
artifact_store_root: str = "{DATA_DIR}/artifacts"
```

**Task A3 — `platform/ingestion/schemas.py`**
Six `PlatformModel` classes (all `frozen=True`):
- `RawDocument` — `doc_id`, `file_bytes`, `mime_type`, `filename`, `upload_metadata: dict`
- `DocumentElement` — `element_id`, `raw_content`, `modality: Literal["TEXT","TABLE","IMAGE"]`, `page_no`, `position_index`, `section_path: list[str]`, `bounding_box: tuple[float,float,float,float] | None`, `source_doc`
- `ArtifactRef` — `artifact_id`, `artifact_type: Literal["TABLE_IMAGE","TABLE_DATAFRAME","FIGURE_IMAGE"]`, `storage_path`, `page_no`, `section_path`
- `UnifiedElement` — `element_id`, `text`, `modality`, `section_path`, `page_no`, `position_index`, `artifact_refs: list[ArtifactRef]`, `source_doc`, `extraction_confidence: float`; validator: `text` non-empty
- `ChunkMetadata` — `headings: list[str]`, `has_table: bool`, `has_image: bool`, `table_row_count: int | None`, `image_descriptions: list[str] | None`, `cross_references: list[str] | None`, `source_pages: list[int]`
- `EnrichedChunk` — `chunk_id`, `unified_text`, `chunk_metadata: ChunkMetadata`, `modality_composition: dict[str,float]`, `artifact_refs`, `section_path`, `page_range: tuple[int,int]`, `source_doc`, `token_count`; validators: token_count 1–600; modality_composition sums ≈1.0 (±0.05)

**Task A4 — `platform/ingestion/__init__.py`**
Re-export everything public: all 6 schema classes + main classes (DocumentConverter, ElementExtractor, ArtifactStore, TableNarrator, ImageDescriptor, Unifier, SemanticChunker) + errors.

---

### Phase B — Conversion + Element Extraction (depends on Phase A)

**Task B1 — `platform/ingestion/converter.py`**
`DocumentConverter` class:
- `__init__(config: IngestionConfig)` — builds two Docling pipeline configurations: `standard_pipeline` (Heron layout + TableFormer + Tesseract OCR) and `vlm_pipeline` (SmolDocling)
- `convert(raw_doc: RawDocument) -> DoclingDocument`:
  1. Write `raw_doc.file_bytes` to temp file (`tempfile.NamedTemporaryFile`)
  2. Run `standard_pipeline.convert(temp_path)`
  3. Compute `text_ratio = total_extracted_chars / (page_count * 2000)`
  4. If `text_ratio < config.docling_vlm_fallback_threshold` or `config.docling_force_vlm`: re-run with `vlm_pipeline`
  5. If both fail: raise `IngestionError` with chained exception
  6. Cleanup temp file in `finally`
- Lazy singleton pattern: `_get_converter(product_id)` with `threading.Lock`, same pattern as `platform/retrieval/embedder.py`

**Task B2 — `platform/ingestion/element_extractor.py`**
`ElementExtractor` class:
- `extract(docling_doc: DoclingDocument, source_doc: str) -> list[DocumentElement]`:
  - Walk Docling doc in reading order using Docling's iteration API
  - Track current `section_path: list[str]` — update on `SECTION_HEADER` items
  - For `TEXT`, `LIST_ITEM`, `CAPTION` labels: create `DocumentElement(modality="TEXT")`; use `element_id = hashlib.sha256(raw_content.encode()).hexdigest()[:16]`
  - For `TABLE` labels: serialize to markdown via `table.export_to_markdown()`, create `DocumentElement(modality="TABLE")`; store raw Docling table object in a side-channel dict keyed by element_id (for Step 3 artifact extraction)
  - For `PICTURE` labels: extract caption via Docling's caption grouping, store image bytes reference, create `DocumentElement(modality="IMAGE")`
  - Sort by `(page_no, position_index)` before return

---

### Phase C — Artifact Storage (depends on Phase A, parallel with Phase B)

**Task C1 — `platform/ingestion/artifact_store.py`**
`ArtifactStore` class:
- `__init__(batch_id: str, root: Path | None = None)` — root defaults to `IngestionConfig().artifact_store_root`; creates `{root}/{batch_id}/` directory
- `batch_path: str` — property returning the batch directory path (written to state)
- `store_table_image(docling_doc, element: DocumentElement) -> ArtifactRef`:
  - Rasterize the page region from the bounding box via Docling's page image export (or `pdf2image` fallback)
  - Crop with Pillow; save as PNG
  - Path: `{root}/{batch_id}/TABLE_IMAGE/{content_hash[:16]}.png`
  - Return `ArtifactRef(artifact_type="TABLE_IMAGE", ...)`
- `store_table_dataframe(docling_table_obj, element: DocumentElement) -> ArtifactRef`:
  - `pd.DataFrame` from docling table → `.to_parquet(path)` via pyarrow
  - Path: `{root}/{batch_id}/TABLE_DATAFRAME/{content_hash[:16]}.parquet`
- `store_figure_image(image_bytes: bytes, element: DocumentElement) -> ArtifactRef`:
  - Normalize via Pillow (ensure PNG); save
  - Path: `{root}/{batch_id}/FIGURE_IMAGE/{content_hash[:16]}.png`
- `store_all(docling_doc, elements: list[DocumentElement]) -> dict[str, list[ArtifactRef]]`:
  - Iterates elements; for TABLE → calls both `store_table_image` + `store_table_dataframe`; for IMAGE → `store_figure_image`; returns `{element_id: [ArtifactRef, ...]}`
- `retrieve(artifact_id: str) -> tuple[bytes, str]`:
  - Returns `(file_bytes, mime_type)` — used by the API endpoint

---

### Phase D — Narration, Description, Unification (depends on B + C)

**Task D1 — `platform/ingestion/templates/table_narration.j2`**
Jinja2 template as specified in the requirement doc (section_path context + table_markdown variable).

**Task D2 — `platform/ingestion/templates/image_description.j2`**
Jinja2 template as specified (section_path context + optional caption).

**Task D3 — `platform/ingestion/narration.py`**
`TableNarrator` class:
- `__init__(llm_client: LLMClient, concurrency: int)` — use `platform/llm/client.py`'s `LLMClient`
- `NarratedRow(PlatformModel)` — inner schema: `row_index: int`, `narration: str`
- `NarratedTable(PlatformModel)` — `rows: list[NarratedRow]`
- `narrate(element: DocumentElement, batch_id: str) -> str`:
  - Load `table_narration.j2` via `jinja2.Environment`
  - For tables ≤ 15 rows: single LLM call with `with_structured_output(NarratedTable)`
  - For tables > 15 rows: batch into groups of 15, send in parallel via `asyncio.gather` + `asyncio.Semaphore(concurrency)`, stitch results
  - Return `"\n".join(row.narration for row in result.rows)`
  - On `LLMNarrationError`: re-raise for retry by caller

**Task D4 — `platform/ingestion/description.py`**
`ImageDescriptor` class:
- `__init__(model: str, concurrency: int)` — `model` from `IngestionConfig.image_description_model`
- `describe(element: DocumentElement, image_bytes: bytes, artifact_refs: list[ArtifactRef]) -> tuple[str, float]`:
  - Returns `(description_text, extraction_confidence)`
  - `model="smolvlm"`: SmolVLM via `transformers` pipeline (lazy-loaded singleton)
  - `model="claude"`: Claude API vision call via `LLMClient`
  - `model="none"` or failure: fallback to caption or `"[Image on page {page_no} in section {section_path[-1]}]"`, confidence=0.3

**Task D5 — `platform/ingestion/unifier.py`**
`Unifier` class:
- `__init__(narrator: TableNarrator, descriptor: ImageDescriptor)`
- `unify(elements: list[DocumentElement], artifact_map: dict[str, list[ArtifactRef]]) -> list[UnifiedElement]`:
  - For TEXT elements: pass through, `extraction_confidence=1.0`
  - For TABLE elements: get narrated text from `narrator.narrate(element)`, one `UnifiedElement` per table row (sequential `position_index`)
  - For IMAGE elements: get image bytes from artifact_map, call `descriptor.describe(element, bytes, refs)`
  - Preserve reading order; TABLE expansion assigns sequential positions
  - Returns `list[UnifiedElement]` in reading order

---

### Phase E — Semantic Chunker (depends on Phase A + D output contract)

**Task E1 — `platform/ingestion/chunker.py`**
`SemanticChunker` class:
- `__init__(tokenizer_name: str, max_tokens: int, overlap_tokens: int)`:
  - `self._tokenizer = Tokenizer.from_pretrained(tokenizer_name)` — loaded once at init (not module-level global; use lazy singleton with `threading.Lock`)
- `chunk(elements: list[UnifiedElement]) -> list[EnrichedChunk]`:
  - Walk elements in order; accumulate into `_buffer: list[UnifiedElement]`
  - Token counting: `len(self._tokenizer.encode(text).ids)` per element
  - **Flush conditions** (in priority order):
    1. `section_path[0]` changes — hard flush, no overlap
    2. Adding element would exceed `max_tokens` — flush current buffer, carry `overlap_tokens` from tail
    3. End of elements — flush remaining buffer
  - **Table atomicity**: if a single TABLE element > `max_tokens`, emit as solo chunk (token_count ≤ 600 per schema validator)
  - **Overlap**: extract last `overlap_tokens` tokens from finalized chunk text; prepend to next buffer; mark `has_overlap=True` on metadata
  - **Chunk finalization** — compute:
    - `chunk_id = hashlib.sha256((unified_text + str(section_path)).encode()).hexdigest()[:24]`
    - `modality_composition` — `{modality: tokens_from_modality / total_tokens}` (overlap tokens not double-counted)
    - `cross_references` — regex: `r'(?:See|Refer to|Same as|per) (?:Section|Figure|REQ-)\S+'`
    - `source_pages`, `page_range`, `artifact_refs` — aggregated from constituent elements
    - `ChunkMetadata` from the above
  - Return `list[EnrichedChunk]` sorted by `(section_path, page_range[0])`

---

### Phase F — LangGraph Integration (depends on all platform phases)

**Task F1 — `modules/dynafit/state.py`**
Add two `NotRequired` fields to `DynafitState`:
```python
enriched_chunks: NotRequired[list[dict]]     # serialized EnrichedChunk.model_dump()
artifact_store_batch_path: NotRequired[str]  # path for HITL artifact retrieval
```
Note: `EnrichedChunk` cannot be directly typed here (platform → modules import would be sideways); use `list[dict]` with a docstring explaining the schema. Existing keys unchanged (backward compat).

**Task F2 — `modules/dynafit/nodes/ingestion.py`**
Refactor the ingestion node. Current flow uses `DoclingParser` (pdfplumber). New flow:
1. Build `RawDocument` from `state["upload"]` (`RawUpload`)
2. `DocumentConverter(config).convert(raw_doc)` → `DoclingDocument`
3. `ElementExtractor().extract(docling_doc, source_doc=raw_doc.filename)` → `list[DocumentElement]`
4. `ArtifactStore(batch_id=state["batch_id"]).store_all(docling_doc, elements)` → `artifact_map`
5. `Unifier(narrator, descriptor).unify(elements, artifact_map)` → `list[UnifiedElement]`
6. `SemanticChunker(...).chunk(unified)` → `list[EnrichedChunk]`
7. Publish progress events at each sub-step via `platform/storage/redis_pub.py`
8. Return `{"enriched_chunks": [c.model_dump() for c in chunks], "artifact_store_batch_path": store.batch_path}`
9. Downstream atomizer call remains; it reads `enriched_chunks` preferentially

Singletons (`narrator`, `descriptor`, `chunker`): lazy-loaded module-level with `threading.Lock`, injectable via `__init__` params for testing.

**Task F3 — `modules/dynafit/nodes/atomizer.py`**
Update the `_atomise_and_classify_batch` function:
- Check `state.get("enriched_chunks")` first; if present, reconstruct `EnrichedChunk` objects from dicts
- Update prompt template (`modules/dynafit/prompts/atomizer.j2`) to include `section_path`, `modality_composition`, `page_range`, `has_visual_evidence`
- Add `has_visual_evidence: bool` and `source_modality: str` fields to `_ClassifiedAtom` internal schema
- These flow through to `RequirementAtom` — add same fields to `RequirementAtom` in `platform/schemas/requirement.py`
- Fallback: if no `enriched_chunks` in state, use legacy raw-text path unchanged

---

### Phase G — API Endpoints (depends on Phase C, parallel with F)

**Task G1 — `api/routes/dynafit.py`**
Add two endpoints to the existing router:

```
GET /api/v1/d365_fo/dynafit/{batch_id}/artifacts
  → list[ArtifactRef]  (reads batch state from Redis, returns all artifact metadata)

GET /api/v1/d365_fo/dynafit/{batch_id}/artifacts/{artifact_id}
  → FileResponse  (Content-Type: image/png or application/octet-stream)
  → Cache-Control: public, max-age=86400
```

Both inherit existing JWT RBAC middleware. Read `artifact_store_batch_path` from Redis batch state. Use `ArtifactStore.retrieve(artifact_id)` for file bytes.

---

### Phase H — Tests + Fixture

**Task H1 — `tests/fixtures/generate_fixture.py`**
ReportLab script to generate `synthetic_multimodal_req.pdf` (4 pages as specified in requirement doc). Run once and commit the PDF.

**Task H2 — `tests/integration/test_ingestion_journey.py`**
Single test `test_full_ingestion_produces_valid_enriched_chunks` with 8 sequential assertions:
1. Conversion succeeds (no `IngestionError`)
2. Elements contain TABLE + IMAGE modalities
3. ArtifactStore has ≥1 TABLE_IMAGE and ≥1 FIGURE_IMAGE (PNG magic bytes verified)
4. TABLE narration preserves "REQ-AP-041" and "3-way matching"; no markdown pipes
5. IMAGE description > 20 chars (or fallback accepted if `IMAGE_DESCRIPTION_MODEL=none`)
6. All `EnrichedChunk` objects pass Pydantic validation; token_count 1–600; modality_composition sums ≈1.0
7. At least one chunk has multiple modalities (> 1 key with value > 0.1)
8. No chunk spans two different top-level sections

CI: `DOCLING_TABLE_MODE=fast`, mock LLM via `platform/testing/factories.py`, `IMAGE_DESCRIPTION_MODEL=none`.

---

## Dependency Additions

Add to `requirements.txt` / `pyproject.toml`:
```
docling>=2.25
docling-core>=2.25
tokenizers>=0.21
pdf2image>=1.17
pyarrow>=18.0
```
Already in stack (reused): `python-magic`, `Pillow`, `Jinja2`, `pandas`, `pydantic>=2`.

---

## Critical Files to Modify

| File | Change |
|---|---|
| `platform/config/settings.py` | Compose `IngestionConfig` as nested field |
| `platform/schemas/requirement.py` | Add `has_visual_evidence: bool`, `source_modality: str` to `RequirementAtom` |
| `modules/dynafit/state.py` | Add `enriched_chunks`, `artifact_store_batch_path` |
| `modules/dynafit/nodes/ingestion.py` | Refactor to use new `platform/ingestion/` pipeline |
| `modules/dynafit/nodes/atomizer.py` | Update prompt + schema for `EnrichedChunk` input |
| `api/routes/dynafit.py` | Add two artifact endpoints |

---

## Execution Order (Parallelizable)

```
A (foundation: errors, config, schemas)         ← start here, no deps
    ↓
B (converter, extractor) ──── C (artifact_store)   ← parallel
    ↓                              ↓
D (narration, description, unifier)
    ↓
E (chunker)
    ↓
F (LangGraph integration) ──── G (API endpoints)   ← parallel
    ↓
H (tests + fixture)
```

Critical path: A → B → D → E → F → H

---

## Verification

1. Run journey test: `pytest tests/integration/test_ingestion_journey.py -v` — all 8 assertions pass
2. Run existing module tests: `make test-module M=dynafit` — no regressions
3. Smoke test: `python infra/scripts/smoke_test.py` — seed script still works (old parser untouched)
4. Manual: upload a real requirements PDF via API; confirm `enriched_chunks` in state, artifacts stored, HITL review page shows table images

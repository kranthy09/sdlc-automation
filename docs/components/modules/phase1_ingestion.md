# Phase 1 — Ingestion

**What:** Extract requirements from documents (PDF/DOCX/TXT) → RequirementAtom list.

**File:** `modules/dynafit/nodes/phase1_ingestion.py`

**Input:** `RawUpload(filename, file_bytes, upload_id)`

**Output:** `AtomizedBatch(atoms: list[RequirementAtom])`

---

## What It Does

1. **Validate file** (G1-lite) — Size < 50 MB, format is PDF/DOCX/TXT
2. **Detect format** — Magic bytes + content analysis (`platform/parsers/format_detector.py`)
3. **Parse document** — pdfplumber (PDF), python-docx (DOCX), stdlib (TXT) via `DoclingParser`
4. **OCR fallback** — Scanned PDF pages (< 20 chars of extracted text) trigger pdf2image + pytesseract
5. **Split content** — Tables → `ParseResult.tables`, Prose → `ParseResult.prose` chunks
6. **Map headers** — Fuzzy-match raw column headers to canonical fields (`ingestion_column_mapper.py`)
7. **Scan for injection** (G3-lite) — Block/flag malicious content
8. **Atomize** — Create RequirementAtom for each requirement
9. **Deduplicate** — Remove exact duplicates within batch

## Input Schema

```python
class RawUpload(BaseModel):
    filename: str  # "requirements_2024.pdf"
    file_bytes: bytes  # Raw file content
    upload_id: str  # Unique upload ID
```

## Output Schema

```python
class AtomizedBatch(BaseModel):
    batch_id: str  # Auto-generated
    atoms: list[RequirementAtom]
    document_count: int
    parsed_at: datetime
```

Each atom:
```python
class RequirementAtom(BaseModel):
    id: str  # "REQ-001" or auto-generated
    text: str  # Requirement text
    req_id: str | None  # From document
    module: str | None  # D365 area
    country: str | None  # Legal entity
    priority: str | None  # Must/Should/Could
    source_file: str  # Which document
    source_page: int | None
```

## Supported Formats

| Format | Parsed By | Tables | Prose | OCR fallback |
|--------|-----------|--------|-------|--------------|
| PDF | pdfplumber | ✅ lattice + stream detection | ✅ outside_bbox isolation | ✅ pdf2image + pytesseract |
| DOCX | python-docx | ❌ (always `tables=[]`) | ✅ paragraph-level, headings preserved | ❌ |
| TXT | stdlib pathlib | ❌ | ✅ double-newline split | ❌ |

**Not supported:** Excel (.xlsx), standalone ZIP archives → `UnsupportedFormatError` (quarantined)

**Parser:** `platform/parsers/docling_parser.py` → `DoclingParser.parse(path)` → `ParseResult(tables, prose)`

**OCR trigger threshold:** `_SCANNED_THRESHOLD = 20` chars — pages below this after table removal attempt OCR. Silently skipped if `pdf2image`/`pytesseract` are not installed (requires `--extra ocr` + system packages `poppler-utils`, `tesseract-ocr`).

See [DECISIONS.md](../../DECISIONS.md#pdf-parser-pdfplumber) for why pdfplumber was chosen.

## Implementation Pattern

```python
# platform/parsers/docling_parser.py
parser = DoclingParser()
result = parser.parse(Path("requirements.pdf"))
# result.tables → list[dict[str, str]]  — one dict per table row, keys = raw column headers
# result.prose  → list[ProseChunk]      — ≤1500 char chunks, 2-sentence overlap prefix

# modules/dynafit/nodes/ingestion.py
parse_result = DoclingParser().parse(path)
canonical_rows = _map_table_rows_to_canonical(parse_result.tables)  # RapidFuzz header matching
texts = _collect_requirement_texts(parse_result)  # prefers tables > prose
```

**Table extraction (PDF):**
1. `page.find_tables()` — detects lattice (bordered) and stream (whitespace-aligned) tables
2. First row = headers; blank cells → `col_N` placeholder
3. `page.outside_bbox(table.bbox)` — excludes each table region before prose extraction
4. Empty rows (all cells blank) are dropped

**Prose chunking:**
- Max 1500 chars per chunk (`_MAX_CHUNK_CHARS`)
- 2-sentence overlap prefix on each chunk for retrieval context continuity (`_OVERLAP_SENTENCES = 2`)
- Heading items (DOCX `Heading`/`Title` styles) flush the buffer and reset `section` label
- `ProseChunk.section` tracks the most recent heading above each chunk

## Common Issues

**File too large?**
→ G1-lite blocks > 50 MB. User must split.

**Format not recognized?**
→ Check magic bytes. If PDF/DOCX/TXT not detected, raise `UnsupportedFormatError`.

**Table headers not matched?**
→ Fuzzy match may fail. Use positional fallback. Flag for manual review.

**Injection detected?**
→ G3-lite blocks or flags. Block = drop file. Flag = Phase 5 reviews.

**No requirements extracted?**
→ Check document structure. pdfplumber requires selectable (non-scanned) text. For scanned PDFs install `--extra ocr` and system packages `poppler-utils` + `tesseract-ocr`.

## Testing

```python
@pytest.mark.asyncio
async def test_phase1_extracts_atoms():
    upload = factories.make_raw_upload(filename="test.pdf")
    batch = await phase1_ingestion(upload)
    assert len(batch.atoms) > 0
    assert all(isinstance(a, RequirementAtom) for a in batch.atoms)

def test_phase1_rejects_unsupported_format():
    upload = factories.make_raw_upload(filename="test.zip")
    with pytest.raises(UnsupportedFormatError):
        phase1_ingestion(upload)

@pytest.mark.integration
async def test_phase1_with_real_pdf():
    with open("tests/fixtures/sample_requirements.pdf", "rb") as f:
        upload = RawUpload(
            filename="sample_requirements.pdf",
            file_bytes=f.read(),
            upload_id=str(uuid4())
        )
        batch = await phase1_ingestion(upload)
        assert batch.atoms  # At least one requirement
```

## See Also

- [PATTERNS.md](../../guides/PATTERNS.md) — Node pattern
- [guardrails.md](../platform/guardrails.md) — G1-lite, G3-lite
- [dynafit.md](../../specs/dynafit.md) — Full spec with algorithms

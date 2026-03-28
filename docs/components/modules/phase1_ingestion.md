# Phase 1 — Ingestion

**What:** Extract requirements from documents (PDF/DOCX/TXT) → RequirementAtom list.

**File:** `modules/dynafit/nodes/phase1_ingestion.py`

**Input:** `RawUpload(filename, file_bytes, upload_id)`

**Output:** `AtomizedBatch(atoms: list[RequirementAtom])`

---

## What It Does

1. **Validate file** (G1-lite) — Size < 50 MB, format is PDF/DOCX/TXT
2. **Detect format** — Magic bytes + content analysis
3. **Parse document** — Docling + fallback to Unstructured
4. **Extract images** — Run OCR on diagrams (may contain requirements)
5. **Split content** — Tables → atoms, Prose → chunks → atoms
6. **Map headers** — Fuzzy-match table columns to canonical fields
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

| Format | Parsed By | Notes |
|--------|-----------|-------|
| PDF | Docling | Tables, prose, images extracted |
| DOCX | Docling | Same as PDF |
| TXT | Docling | Plain text split by paragraphs |

Unsupported formats → `UnsupportedFormatError` (quarantined).

## Implementation Pattern

```python
async def phase1_ingestion(upload: RawUpload) -> AtomizedBatch:
    """
    Step 1: Validate file (G1-lite)
    Step 2: Detect format
    Step 3: Parse with Docling
    Step 4: Extract tables, prose, images in parallel
    Step 5: Scan for injection (G3-lite)
    Step 6: Map table headers
    Step 7: Create RequirementAtom for each requirement
    Step 8: Deduplicate
    Step 9: Return batch
    """

    # 1. File validation
    file_check = validate_file(upload.file_bytes, upload.filename)
    if not file_check.passed:
        raise GuardrailError(file_check.flags)

    # 2. Format detection
    detected = detect_format(upload.file_bytes)

    # 3. Parse
    doc = DocumentConverter().convert(upload.filename)

    # 4. Extract (parallel)
    tables, prose_chunks, images = await asyncio.gather(
        extract_tables(doc),
        extract_prose(doc),
        extract_images(doc)
    )

    # 5. Scan for injection
    for chunk in prose_chunks:
        scan = scan_injection(chunk.text)
        if scan.severity == "BLOCK":
            raise GuardrailError(scan.flags)
        if scan.severity == "FLAG_FOR_REVIEW":
            chunk.flagged = True

    # 6. Map headers in tables
    for table in tables:
        headers = map_table_headers(table.headers)

    # 7-8. Atomize
    atoms = []
    for item in tables + prose_chunks:
        atom = create_atom_from(item, upload.filename)
        atoms.append(atom)

    atoms = deduplicate(atoms)

    # 9. Return
    return AtomizedBatch(
        batch_id=str(uuid4()),
        atoms=atoms,
        document_count=1,
        parsed_at=datetime.utcnow()
    )
```

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
→ Check document structure. Docling may fail on non-standard formats. Try Unstructured fallback.

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

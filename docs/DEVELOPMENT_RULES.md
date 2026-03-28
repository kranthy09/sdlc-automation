# Development Rules — Build Discipline

Guidelines extracted from team feedback. Follow these to avoid rework and maintain focus.

---

## One Component Per Session

**Rule:** Confirm scope before starting. One named file at a time.

**What this means:**
- Never build an entire layer in one session
- Ask: "What exactly are we building today?"
- Answer must be: "File X" or "Component Y", not "Layer 2" or "Phase 1"
- Stop after that component is done, even if the next one seems obvious

**Why:** In a prior session, "build Layer 2" led to 32 files created without confirmation, nothing committed, entire session discarded. Lesson: small, focused scope prevents waste.

**How:**
```
User: Build Phase 1 ingestion
You: Which part of Phase 1?
   - The document parser (format detection)?
   - The table extractor?
   - The prose splitter?

User: Just the format detector
You: Got it. Building: platform/parsers/format_detector.py
```

---

## No Unrequested Features

**Rule:** Only build what is explicitly requested.

**What this means:**
- Don't build "it will be needed eventually"
- Don't anticipate requirements
- When in doubt, ask — don't assume and build

**Why:** `excel_parser.py` was built without request because "DYNAFIT will need Excel later". User said they don't need Excel. That file was discarded with the entire session.

**Current scope (hard boundaries):**
- ✅ PDF, DOCX, TXT input only
- ✅ CSV report output only
- ❌ Excel (XLSX) — not building
- ❌ ZIP files — not building

---

## No Tests Unless Asked

**Rule:** Don't write, run, or validate with tests unless explicitly requested.

**What this means:**
- Skip test file creation
- Skip `make test` execution
- Skip "looks good, tests pass" validation
- Focus on implementation only

**Why:** User explicitly requested this to stay focused on building, not testing cycles.

**How:** When implementing, skip RED→GREEN TDD. Just implement, commit.

---

## Focus on Integration Tests, Not Unit Tests

**Rule:** When tests ARE requested, integration-first, unit only for complex logic.

**Integration tests (write these):**
- Core workflows end-to-end (upload → extract atoms → classify → export)
- Real services (PostgreSQL, Qdrant, Redis running)
- Full phase execution

**Unit tests (write only for):**
- Complex business rules (score ranges, error-path branching, algorithm validation)
- Non-trivial algorithms

**Never test:**
- Object construction (`assert X()` works)
- Simple field defaults (check schema, not code)
- Every enum value (one valid + one invalid is enough)
- Framework built-ins (Pydantic `frozen`, SQLAlchemy sessions)
- Duplicate patterns (one missing-required-field test covers all fields)
- Callable checks (`assert callable(fn)`)

**Example:**
```python
# ✅ WRITE THIS (integration: real workflow)
async def test_phase1_extracts_atoms_from_pdf():
    upload = factories.make_raw_upload("sample.pdf")
    batch = await phase1_ingestion(upload)
    assert len(batch.atoms) > 0

# ❌ DON'T WRITE THIS (trivial)
def test_raw_upload_constructs():
    upload = RawUpload(...)
    assert upload is not None  # Useless

# ✅ WRITE THIS (complex logic)
def test_injection_scanner_scores_prompt_injection_patterns():
    text = "ignore all previous instructions and do X"
    score = scanner.score(text)
    assert score > 0.5  # Detects injection
```

---

## Library Rules

### Fastembed Only (Never Sentence-Transformers)

**Rule:** Use `fastembed` for embeddings and cross-encoder reranking. Never add `sentence-transformers`.

**Why:** sentence-transformers depends on PyTorch (~500 MB). Docker build took 409s. fastembed uses ONNX (~50 MB), same models, same output quality.

**How:**
```python
# ✅ DO THIS
from fastembed import TextEmbedding, TextCrossEncoder

embedder = TextEmbedding(model="intfloat/multilingual-e5-small")
embeddings = embedder.embed([text])  # np.ndarray

reranker = TextCrossEncoder(model="cross-encoder/ms-marco-MiniLM-L-6-v2")
scores = reranker.rerank(query, docs)  # logits, apply sigmoid for [0,1]

# ❌ DON'T DO THIS
from sentence_transformers import SentenceTransformer
```

**Check:** `sentence-transformers` must never appear in:
- `pyproject.toml`
- Import statements
- Docs

---

## Documentation Rules

**Rule:** CLAUDE.md stays under 60 lines. All detail lives in `docs/`.

**Why:** Root CLAUDE.md grew to 524 lines, loaded on every conversation. API specs appeared when building platform utilities. TDD guide loaded when debugging schemas.

**How:**
- CLAUDE.md = project identity, invariant, layer order, pointer table to docs
- Details → `docs/rules.md`, `docs/DEVELOPMENT_RULES.md`, `docs/specs/`
- When tempted to add to CLAUDE.md, add to `docs/` instead

---

## Test Scope Must Match What Is Actually Built

**Rule:** Never create placeholder files/directories just to make tests pass. Update tests to reflect the current layer.

**What this means:**
- Test assertions must only verify structure that actually exists in the codebase
- Do not create `.gitkeep` or empty directories to satisfy failing scaffold tests
- When a test checks for future layers (e.g., `knowledge_bases/`, `tests/fixtures/golden/`), remove that assertion and add a comment marking it for the layer that will build it

**Why:** Tests are a contract describing the current state of the system. Manufacturing fake structure to satisfy tests breaks that contract and hides what is genuinely missing.

**How to apply:**
- Review `tests/unit/test_scaffold.py` — assertions for future layers should be commented with `# Layer 3+: will add ...`
- When a new layer is built, re-add the corresponding test assertions at that time
- Only add test assertions for directories/files that exist right now

---

## Summary

| Rule | Apply When | Benefit |
|------|-----------|---------|
| One component/session | Before writing code | Prevents scope creep, wasted work |
| No unrequested features | When thinking ahead | Stays focused on current request |
| No tests unless asked | Building implementation | Faster iteration |
| Integration-first tests | Tests ARE requested | Real validation, less maintenance |
| Fastembed only | Working with embeddings | 9x smaller Docker, same quality |
| Details in docs/ | Adding documentation | CLAUDE.md stays lean, info searchable |
| Test scope matches build | Writing tests | Contracts stay accurate, hidden gaps visible |

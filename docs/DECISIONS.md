# Decisions — Why We Built It This Way

Key architectural and technology decisions. Read to understand tradeoffs.

---

## Supported Document Formats

**Decision:** PDF, DOCX, TXT only. No Excel (XLSX), no ZIP archives.

**What this means:**
- Input: User uploads PDF, Word document, or plain text
- Output: CSV report (Python stdlib `csv` module)
- Excel files (.xlsx) — not supported
- Standalone ZIP archives — not supported
- ZIP as DOCX container — supported (DOCX is a ZIP with `word/document.xml`)

**Why:**
- All real-world requirement documents arrive as PDF, DOCX, or TXT
- Docling parser handles tables natively in these formats
- Excel-specific parsing (openpyxl, sheet iteration, merged cells, multi-row headers) added complexity with no additional coverage
- Minimal foundation principle: only support what users need

**How to apply:**
- `DocumentFormat` enum: three values only (PDF, DOCX, TXT)
- `openpyxl` is NOT a project dependency — do not add it
- Format detector: ZIP magic bytes used only to identify DOCX
- Any ZIP that is not DOCX → `UnsupportedFormatError`
- Phase 5 report builder outputs CSV, not Excel
- No `source_sheet` field on `RequirementAtom`

**If user asks for Excel:** Explain CSV is the current standard, saves 50 MB in dependencies, and they can open CSV in Excel.

---

## Embedding Library: Fastembed Only

**Decision:** Use `fastembed` (ONNX) for embeddings and reranking. Never add `sentence-transformers`.

**What this means:**
- Embeddings: `fastembed.TextEmbedding(model).embed([text])`
- Reranking: `fastembed.TextCrossEncoder(model).rerank(query, docs)`
- Dependencies: fastembed (~50 MB) instead of sentence-transformers (~500 MB)

**Why:**
- sentence-transformers hard-depends on PyTorch (500 MB)
- Docker build time: 409s with sentence-transformers
- fastembed uses ONNX Runtime (50 MB)
- Same model weights, identical output quality, 9x smaller

**Impact:**
- Docker images: 9x smaller
- CI times: 80% faster
- Development VM: Not bloated

**How to apply:**
- Embedder code: `platform/retrieval/embedder.py` uses fastembed
- Reranker code: `platform/retrieval/reranker.py` uses fastembed
- Check `pyproject.toml`: `sentence-transformers` must never appear
- Check imports: No `from sentence_transformers import ...`

**If user asks to use sentence-transformers:** Politely decline. Explain the decision and refer to this doc. It's a hard boundary.

---

## MVP Guardrails: 7 of 14

**Decision:** Build 7 of 14 guardrails in MVP. Remaining 7 in post-MVP.

**MVP Guardrails (7):**

| # | Name | Phase | Where |
|---|------|-------|-------|
| G1-lite | File validator | 1 | `platform/guardrails/file_validator.py` |
| G3-lite | Injection scanner | 1 | `platform/guardrails/injection_scanner.py` |
| G8 | Prompt firewall | 4 | Template pattern (Jinja2 autoescape) |
| G9 | Output enforcer | 4 | LLM client + Pydantic strict validation |
| G10-lite | Sanity gate | 5 | `modules/dynafit/guardrails.py` |
| HITL | Human review checkpoint | 5 | `modules/dynafit/nodes/phase5_validation.py` |
| Audit | Phase boundary logging | All | `platform/observability/logger.py` |

**Post-MVP Guardrails (7, deferred):**
- G2 (PII Redactor — Presidio)
- G4 (Scope fence)
- G5 (KB integrity)
- G6 (Context token cap)
- G7 (Score bounds)
- G11 (Response PII scanner)
- G12–G14 (Context firewall, Export sanitizer, HMAC audit seal)

**Why:**
- MVP focuses on core: extract → retrieve → classify → review
- G1, G3 (input safety), G8, G9 (output safety), G10 (sanity), HITL (human decision) are non-negotiable
- G2, G4–G7, G11–G14 are nice-to-have in MVP; build after Phase 5 is stable
- HITL mandatory: A batch MUST NOT complete until a human has resolved every flagged classification

**How to apply:**
- When building Phase 1 node: include G1-lite and G3-lite
- When building Phase 4 node: include G8 and G9 (already built into platform)
- When building Phase 5 node: include G10-lite and call `interrupt()` for flagged items
- All phases: Audit logging via structlog (already in platform)

---

## HITL at Phase 5: Non-Negotiable

**Decision:** Phase 5 (Validation) requires human review for flagged classifications.

**What this means:**
- G10-lite sanity gate runs on all results
- If any flags → batch pauses (LangGraph `interrupt()`)
- UI shows flagged items, human decides: accept or override
- On human decision → graph resumes, applies override, completes batch

**Why:**
- Classification is probabilistic (LLM + heuristics)
- High-confidence gaps are suspicious (maybe wrong threshold?)
- Low-score fits are shaky (maybe borderline?)
- LLM schema failures need human eyes
- Human in the loop prevents bad decisions shipping

**How to apply:**
- Phase 5 node: run `sanity_check()` on all `ClassificationResult`
- Flagged results → `flagged_for_review` list
- Non-empty list → publish event, call `interrupt()`
- Wait for human override in UI
- Resume from checkpoint, merge overrides, complete

**Checkpoint mechanism:**
- PostgreSQL stores full graph state (already set up)
- LangGraph `interrupt()` pauses execution
- UI calls API to store human decision
- Next `graph.ainvoke()` resumes from checkpoint

See [phase5_validation.md](components/modules/phase5_validation.md) for full flow.

---

## 5-Phase Pipeline (Sequential)

**Decision:** REQFIT uses exactly 5 phases, executed sequentially.

**Phases:**
1. **Ingestion** — Extract requirements from documents
2. **RAG** — Retrieve similar requirements from KB
3. **Matching** — Find candidate D365 modules
4. **Classification** — Determine FIT/GAP via LLM
5. **Validation** — Sanity checks + human review

**Why sequential:**
- Each phase depends on previous output
- Checkpoints save state after each phase
- Easy to pause/resume at any phase
- HITL at Phase 5 requires checkpoint before completion

**If user asks for parallel phases:** These phases have sequential dependencies. Explain the dependency chain. Parallelization would require redesign.

---

## Summary Table

| Decision | What | Why | Hard Boundary |
|----------|------|-----|---|
| Formats | PDF, DOCX, TXT only | Users only upload these; Docling handles them | ✅ Yes |
| Embedder | fastembed only | 9x smaller Docker, same quality | ✅ Yes |
| Guardrails | 7 MVP, 7 post-MVP | Focus on core safety + human loop | ❌ No (defer post-MVP) |
| HITL | Phase 5 mandatory | Prevent bad decisions shipping | ✅ Yes |
| Phases | 5 sequential | Dependency chain, checkpoints | ✅ Yes |


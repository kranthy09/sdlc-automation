# Lessons — Mistakes Made and Rules They Produced

Every entry here came from a real mistake. Rules are concrete, not general advice.

---

## Incident: Layer 2 built entirely in one session (2026-03-20)

**What happened:** Claude built all 15 Layer 2 platform utilities in a single session, including `excel_parser.py` which was not requested and not needed at this stage. The session ended with 32 new files — none committed, all discarded. The codebase was reset to `c5585b6` (platform schemas).

**Root cause:** No scope confirmation before starting. "Build Layer 2" was interpreted as "build all of Layer 2 right now." Excel parser was added by anticipating future need — over-engineering by assumption.

**Rules produced:**

| Rule | Applies When |
|------|-------------|
| Confirm the exact single component before writing any code | Starting any Layer 2+ work |
| Build one component per session, then stop | Every session |
| Only build what is explicitly requested — no anticipatory features | Always |
| Ask "what exactly are we building today?" if the scope is not a single named file | Any time a layer or phase is mentioned without a specific component |

---

## Incident: Root CLAUDE.md grew to 524 lines (2026-03-20)

**What happened:** CLAUDE.md accumulated every specification, build order detail, technology stack, coding standards, and "what not to do" list. At 524 lines it was the largest file in the project and loaded on every conversation, filling the context with irrelevant information.

**Root cause:** No size constraint enforced. Every new concern was added to CLAUDE.md instead of the appropriate `docs/` file.

**Rules produced:**

| Rule | Applies When |
|------|-------------|
| Root CLAUDE.md hard cap: 60 lines | Any time something is being added to CLAUDE.md |
| All detail belongs in `docs/` — CLAUDE.md is a pointer, not a spec | Structuring documentation |
| Subdirectory CLAUDE.md files (`platform/CLAUDE.md`, `modules/CLAUDE.md`) load only when working in that directory | Layer-specific context |

---

## Decision: Excel and ZIP removed from supported formats (2026-03-20)

**What happened:** The initial spec included XLSX input (via openpyxl) and ZIP detection in the format detector. Both were removed before Layer 2 began.

**Reason:** Minimal foundation. All real-world requirement documents arrive as PDF, DOCX, or TXT. Docling handles tables natively in these formats — the Excel-specific parsing path (openpyxl sheet iteration, merged cell handling, multi-row header logic) was complexity with no additional coverage. Output reports are now CSV (stdlib — no extra dependency).

**Rules produced:**

| Rule | Applies When |
|------|-------------|
| Supported input formats are PDF, DOCX, TXT only | Any parser or format detector work |
| Report output is CSV (stdlib csv) — not Excel | Phase 5 report builder |
| `openpyxl` is not a project dependency | Any pyproject.toml change |
| `DocumentFormat` enum has three values: PDF, DOCX, TXT | Format detector implementation |

---

## Decision: sentence-transformers replaced by fastembed (2026-03-21)

**What happened:** `uv sync --frozen --no-dev --extra ml` took 409 seconds in Docker because `sentence-transformers` pulls PyTorch (~500 MB wheel) as a hard dependency. The build was the single largest bottleneck in the Docker image build cycle.

**Root cause:** sentence-transformers is a convenience wrapper that bundles PyTorch regardless of whether GPU inference is needed. For ONNX-compatible models (BGE, ms-marco MiniLM), PyTorch is never used at runtime.

**Resolution:** Replaced with `fastembed` (Qdrant-maintained, ONNX Runtime backend):
- `platform/retrieval/embedder.py` — `SentenceTransformer.encode()` → `fastembed.TextEmbedding.embed()`
- `platform/retrieval/reranker.py` — `CrossEncoder.predict(pairs)` → `fastembed.TextCrossEncoder.rerank(query, docs)`
- Same model IDs, same output shape, same quality — ONNX Runtime executes the identical weights

**Rules produced:**

| Rule | Applies When |
|------|-------------|
| Use `fastembed` for all local embedding and reranking — never `sentence-transformers` | Any new retrieval component |
| `sentence-transformers` is not a project dependency | Any `pyproject.toml` change |
| Prefer ONNX Runtime over PyTorch for inference-only workloads | Evaluating any new ML library |

---

## Standing Principles

These are derived from the above and apply permanently:

1. **Minimal at load time** — root CLAUDE.md stays small so every conversation starts with only what's needed
2. **Precise on demand** — detailed specs live in `docs/specs/`, read only when building that layer
3. **Lessons are permanent** — this file grows, rules are never removed unless the underlying risk is eliminated
4. **One thing, done well** — finish and commit one component before starting the next

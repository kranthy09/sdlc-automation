# DYNAFIT — Open-Source Library Map for LangGraph Enterprise AI Platform

**Complete technology mapping: every agent, every step, every library choice with rationale**

> **Supported input formats: PDF, DOCX, TXT only.**
> **Report output: CSV (Python stdlib `csv` module).**
> These are architectural decisions recorded in `docs/lessons.md`. Do not add Excel/ZIP/email/audio support.

---

## Orchestration layer — the spine

| Component | Library | Version | Why this library |
|-----------|---------|---------|-----------------|
| Agent orchestration | **LangGraph** | ≥0.2 | Graph-based state machine with cycles, conditional branching, and human-in-the-loop checkpointing — exactly maps to DYNAFIT's 5-phase pipeline where each phase is a node and state flows through edges |
| LLM abstraction | **LangChain Core** | ≥0.3 | Provides `ChatModel`, `ToolNode`, and `RunnableConfig` abstractions that let you swap LLM providers (OpenAI, Anthropic, Azure, local) without changing agent logic |
| Observability | **Langfuse** | ≥2.0 (MIT, self-hosted Docker) | Fully open-source LLM tracing: distributed traces for every LLM call, token cost tracking, latency profiling, evaluation runs. Self-hosted via Docker Compose — no data leaves the network. Drop-in replacement for LangSmith via LangChain callback handler |
| State persistence | **LangGraph Checkpointer** (SQLite / Postgres) | built-in | Durable execution — if the pipeline crashes mid-batch processing 2,000 requirements, it resumes from the exact checkpoint |
| Config management | **Pydantic v2** | ≥2.0 | Typed settings for thresholds, model names, prompt templates — validated at startup, not at runtime |

### LangGraph state definition (the contract that flows between all 5 phases)

```python
from typing import TypedDict, Literal
from langgraph.graph import StateGraph

class RequirementState(TypedDict):
    req_id: str
    raw_text: str
    source_doc: str
    country: str
    wave: int
    atoms: list[dict]                # output of Phase 1
    retrieved_capabilities: list[dict] # output of Phase 2
    match_scores: list[dict]          # output of Phase 3
    classification: Literal["FIT", "PARTIAL_FIT", "GAP"] | None
    confidence: float
    rationale: str
    prior_wave_history: list[dict]
    fdd_route: Literal["fits", "gaps", "split"] | None
```

---

## Phase 1 — Ingestion agent

### Step 1.1: Document parser

Supported formats: **PDF, DOCX, TXT only** (architectural decision — see `docs/lessons.md`).

| Sub-component | Library | License | What it does | Why this one |
|---------------|---------|---------|-------------|--------------|
| **Primary parser** | **Docling** (IBM) | MIT | Converts PDF, DOCX into a unified `DoclingDocument` representation with preserved structure (tables, headers, lists, reading order) | MIT license (enterprise-friendly), native LangChain/LlamaIndex integration, processes 1.26s/page, uses IBM's layout analysis model (RT-DETR on DocLayNet) + TableFormer for tables. Runs fully local — critical for enterprise data that can't leave the network |
| **TXT parser** | Python stdlib `pathlib` | stdlib | Reads `.txt` files with encoding detection (`chardet` fallback) | Zero-dependency, instant, covers the plain-text requirement files that CI/CD pipelines emit |
| **Fallback parser** | **Unstructured** | Apache 2.0 | Partition-based parsing for PDF and DOCX when Docling fails. Outputs typed `Element` objects (Title, NarrativeText, ListItem, Table) | Used only as Docling fallback on malformed PDFs/DOCXs — not for format expansion |
| **Language detection** | **lingua-py** | Apache 2.0 | Detects document language for routing to locale-specific processing | Multi-country program needs automatic language detection before translation. lingua-py is more accurate than langdetect for short text |
| **Translation** | **Argos Translate** | MIT | Offline machine translation for non-English requirement documents | Fully local (no API calls), supports DE/FR/JP/ES/PT — the languages ABC's country teams use. Models are ~50MB each |
| **Format detection** | **python-magic** | MIT | MIME type detection from file bytes (not extension) | Catches misnamed files (e.g. `.pdf` that is actually a DOCX). Used by the format router before dispatch |

#### How document parsing works — the decision tree

```
Incoming file
    │
    ├─ MIME detection (python-magic)
    │
    ├─ .pdf         ──→ Docling (primary)
    │                   ├─ Programmatic PDF? → Direct text extraction (30x faster)
    │                   └─ Scanned PDF?      → Docling OCR pipeline (internal Tesseract)
    │                   └─ Failure?           → Unstructured (fallback, PDF only)
    │
    ├─ .docx        ──→ Docling (preserves headers, lists, tables as elements)
    │                   └─ Failure? → Unstructured fallback (DOCX only)
    │
    ├─ .txt         ──→ stdlib pathlib.read_text() with encoding detection
    │
    └─ Other type    ──→ UnsupportedFormatError (quarantine + human review flag)
```

#### Handling new data types

When a new document type is proposed (e.g., XLSX, PPTX, email, audio):

1. **Evaluate against lessons.md first.** The PDF/DOCX/TXT decision was deliberate — adding formats increases pipeline complexity for marginal real-world coverage. Challenge the requirement before building.
2. **If genuinely needed:** implement `DocumentHandler` protocol (see handler registry below), add to `HANDLER_REGISTRY`, update `DocumentFormat` enum. The rest of the pipeline is format-agnostic — it only sees `DocumentChunk` objects.
3. **Docling's extensibility:** Docling supports custom pipeline stages — you can add a custom `DocumentBackend` for new formats without changing the handler registry.

### Step 1.2: Requirement extractor (LLM)

| Sub-component | Library | Why |
|---------------|---------|-----|
| **LLM calls** | **LangChain ChatModel** (wrapping Claude / GPT-4 / Llama 3) | Uniform interface for the 3 chained LLM calls (atomize → classify intent → tag module). Swap models via config without touching prompts |
| **Structured output** | **Pydantic + LangChain `with_structured_output()`** | Forces the LLM to emit valid JSON matching a Pydantic schema. If output is malformed, LangChain retries with the validation error injected into the prompt — handles the "retry on schema fail" loop |
| **Prompt management** | **LangChain PromptTemplate + FewShotPromptTemplate** | Few-shot bank selection (5-8 examples per module) is templated — examples are dynamically injected based on the module tag of the incoming chunk |
| **Prompt versioning** | **Git-tracked YAML files** | Every prompt version is stored in `modules/dynafit/prompts/` and versioned via Git. Diff prompt versions to find regressions. No external SaaS dependency. |
| **Token counting** | **tiktoken** (OpenAI) or **anthropic-tokenizer** | Pre-flight check: does the chunk + system prompt + few-shots fit in the context window? If not, chunk is split further before calling |
| **Text splitting** (pre-LLM) | **LangChain RecursiveCharacterTextSplitter** | If a parsed document section exceeds the LLM's context window, it's recursively split at paragraph → sentence → word boundaries |

#### The 3-call chain in LangGraph

```python
from langgraph.graph import StateGraph, END

def atomize(state: RequirementState) -> RequirementState:
    """LLM Call 1: Split raw text into atomic requirements"""
    # Uses structured output → list[AtomSchema]
    ...

def classify_intent(state: RequirementState) -> RequirementState:
    """LLM Call 2: Classify each atom as functional/NFR/integration/reporting"""
    ...

def tag_module(state: RequirementState) -> RequirementState:
    """LLM Call 3: Assign D365 module + entity hints from taxonomy"""
    ...

extraction_graph = StateGraph(RequirementState)
extraction_graph.add_node("atomize", atomize)
extraction_graph.add_node("classify", classify_intent)
extraction_graph.add_node("tag", tag_module)
extraction_graph.add_edge("atomize", "classify")
extraction_graph.add_edge("classify", "tag")
extraction_graph.add_edge("tag", END)
```

### Step 1.3: Normalizer

| Sub-component | Library | Why |
|---------------|---------|-----|
| **Embedding generation** | **fastembed** (`BAAI/bge-small-en-v1.5`) | Generates 384-dim vectors for deduplication similarity checks. Uses ONNX Runtime — no PyTorch dependency (~50 MB vs ~500 MB). Runs fully local, no API calls |
| **Deduplication similarity** | **FAISS** (Facebook) | In-memory cosine similarity at batch scale. For 5,000 requirements, pairwise comparison completes in <1s on CPU. FAISS is a library (not a DB) — perfect here because we need fast transient similarity, not persistent storage |
| **Fuzzy string matching** | **RapidFuzz** | Levenshtein distance + token sort ratio for header mapping (column name → canonical field). 10x faster than python-Levenshtein |
| **Synonym dictionary** | **Custom YAML + spaCy EntityRuler** | D365-specific synonym map (supplier→vendor, stock→inventory) loaded as spaCy patterns. EntityRuler applies replacements in-context, respecting module tags for disambiguation |
| **NLP pipeline** | **spaCy** (`en_core_web_lg`) | Tokenization, POS tagging, NER for priority keyword detection ("must", "critical" → Must-Have). Also powers the ambiguity detector via dependency parsing |
| **Translation alignment** | **Argos Translate** (same as Step 1.1) | After translation, terms pass through the synonym dictionary to ensure "Lieferant" → "supplier" → "vendor" |
| **MoSCoW classification** | **scikit-learn** (optional: TF-IDF + logistic regression) | For priority enrichment when keywords are ambiguous. Trained on manually labeled requirements from prior waves. Falls back to keyword heuristics when model confidence is low |

### Step 1.4: Validator

| Sub-component | Library | Why |
|---------------|---------|-----|
| **Schema validation** | **Pydantic v2** | Every requirement atom must conform to `RequirementAtom` schema. Missing fields, wrong types, empty strings are caught before the atom enters the pipeline |
| **Ambiguity scoring** | **LangChain ChatModel** (lightweight call) | A single LLM call scores the requirement 0-100 on specificity. Prompt: "Rate how specific and testable this requirement is. Score 0 = completely vague, 100 = implementation-ready" |
| **Completeness scoring** | **Custom rule engine** (Python dataclass) | Deterministic checks: does the atom have module tag? Priority? Country? Entity hints? Each field adds points to the completeness score |
| **Duplicate detection** (final pass) | **datasketch MinHash LSH** | Locality-sensitive hashing for near-duplicate detection at scale. Faster than FAISS pairwise for >10K requirements. Catches duplicates that survived the normalizer |

---

## Phase 2 — Knowledge retrieval agent (RAG)

This is the most infrastructure-heavy phase — it maintains three knowledge bases and runs hybrid retrieval.

### Knowledge base architecture

| Knowledge base | Content | Storage | Indexing | Update frequency |
|---------------|---------|---------|---------|-----------------|
| **D365 capability KB** | Standard D365 F&O feature descriptions (~5,000 capabilities across all modules) | **Qdrant** | Embedding vectors (bge-small-en-v1.5) + BM25 sparse vectors | Quarterly (aligned with D365 release waves) |
| **MS Learn corpus** | Microsoft documentation, task guides, configuration guides | **Qdrant** | Same hybrid index | Monthly (scraped via Docling + scheduled crawler) |
| **Historical fitments** | All prior wave fitment decisions with rationale | **PostgreSQL** + **pgvector** | Structured queries + vector similarity | Real-time (every human-approved fitment writes back) |

### Libraries for Phase 2

| Sub-component | Library | Why |
|---------------|---------|-----|
| **Vector database** | **Qdrant** (Rust-based, open-source) | Production-grade: HNSW indexing, rich payload filtering (filter by module, country, wave), real-time updates, REST/gRPC API, native Python client. Handles the D365 KB + MS Learn corpus (~50K documents, ~500K chunks). Payload filtering is critical — when retrieving for an AP requirement, we filter `module=accounts_payable` BEFORE vector similarity, dramatically reducing search space |
| **Sparse retrieval (BM25)** | **Qdrant sparse vectors** or **rank_bm25** | Hybrid search: BM25 catches exact D365 terminology ("VendInvoiceInfoTable") that embedding models might miss. Qdrant natively supports sparse vectors alongside dense vectors in the same collection |
| **Embedding model** | **fastembed** (`BAAI/bge-small-en-v1.5`) | 384-dim, strong MTEB retrieval benchmarks. ONNX Runtime backend — no PyTorch (~50 MB install). Runs fully local; supports air-gapped enterprise deployments |
| **Hybrid retrieval** | **LangChain EnsembleRetriever** | Combines Qdrant dense retrieval + BM25 sparse retrieval with reciprocal rank fusion (RRF). Configurable weight: `dense_weight=0.7, sparse_weight=0.3` |
| **Reranker** | **fastembed TextCrossEncoder** (`Xenova/ms-marco-MiniLM-L-6-v2`) | After hybrid retrieval returns top-20 candidates, the cross-encoder reranks them for the final top-5. ONNX Runtime backend — same model accuracy with no PyTorch dependency |
| **Historical fitment DB** | **PostgreSQL + pgvector** | Structured storage for fitment records (queryable by wave, country, module, classification) with vector similarity for "find similar requirements from prior waves". pgvector keeps everything in one DB — no separate vector store needed for this smaller dataset |
| **Document ingestion pipeline** | **Docling + LangChain DoclingLoader** | MS Learn pages and D365 docs are periodically crawled, converted via Docling, chunked via `HybridChunker`, embedded, and upserted into Qdrant |
| **Web scraping** (for MS Learn updates) | **Scrapy** (BSD-3) | Scheduled scraping of learn.microsoft.com for D365 documentation updates. Scrapy handles both static HTML and can integrate middleware for JS-rendered pages. Fully open-source, no SaaS dependency |

### How retrieval works per requirement

```
Normalized requirement atom
    │
    ├─ Generate embedding (bge-small-en-v1.5)
    │
    ├─ Qdrant hybrid search (dense + BM25 sparse)
    │   ├─ Filter: module = atom.module_primary
    │   ├─ Dense: cosine similarity on requirement embedding
    │   ├─ Sparse: BM25 on entity_hints + requirement text keywords
    │   └─ RRF fusion → top-20 candidates
    │
    ├─ Cross-encoder rerank → top-5 D365 capabilities
    │
    ├─ PostgreSQL query: historical fitments
    │   WHERE module = atom.module AND similarity(embedding, atom.embedding) > 0.85
    │   └─ Returns prior wave classifications + rationale
    │
    └─ Output: RetrievalContext {
         matched_capabilities: top-5 with scores,
         ms_learn_refs: relevant doc URLs,
         prior_fitments: list of (wave, country, classification, notes)
       }
```

---

## Phase 3 — Semantic matching agent

| Sub-component | Library | Why |
|---------------|---------|-----|
| **Embedding similarity** | **fastembed** (same model as Phase 2) | Cosine similarity between requirement embedding and each retrieved capability embedding. Consistent model ensures comparable scores |
| **Confidence scoring** | **Custom Python** (numpy) | Threshold engine: `>0.85 + historical precedent = HIGH`, `0.6–0.85 = MEDIUM (needs LLM)`, `<0.6 = LOW (likely GAP)`. numpy for fast vectorized computation |
| **Candidate ranking** | **scikit-learn** | When multiple D365 features match, rank by: (1) cosine similarity, (2) historical fit rate, (3) module specificity. Uses `sklearn.preprocessing.normalize` + weighted scoring |
| **Feature extraction** | **spaCy** | Extract key entities from both requirement and capability text for structured comparison (e.g., "tolerance percentage" vs "matching tolerance") |

---

## Phase 4 — Classification agent (LLM reasoning)

| Sub-component | Library | Why |
|---------------|---------|-----|
| **LLM reasoning** | **LangChain ChatModel** (Claude 3.5 Sonnet / GPT-4o / Llama 3.1 70B) | The core classification call. Receives: requirement text + top-5 capabilities + historical fitments + match scores. Outputs: classification + rationale + confidence. This is where model quality matters most — use the strongest available model |
| **Structured output** | **Pydantic + `with_structured_output()`** | Forces output schema: `{classification: FIT\|PARTIAL_FIT\|GAP, confidence: float, rationale: str, config_steps: str\|null, gap_description: str\|null}` |
| **Chain-of-thought** | **LangChain `create_structured_chat_agent`** | Structured CoT prompt that walks the LLM through 4 factors: (1) does a matching feature exist? (2) coverage completeness? (3) gap delta? (4) historical evidence? |
| **Self-consistency** | **Custom voting** (3 calls, majority vote) | For MEDIUM confidence requirements, run the classification 3 times with temperature=0.3 and take majority vote. Reduces LLM variance on borderline cases |
| **Rationale generation** | Same LLM call | The classification prompt requires the LLM to explain its reasoning in 2-3 sentences. This rationale propagates to the FDD agents and human reviewers |
| **Prompt templates** | **Jinja2** | Classification prompts are templated with slots for requirement, capabilities, history, confidence thresholds — versioned in Git under `modules/dynafit/prompts/` |

### LangGraph node with conditional routing

```python
def classify_requirement(state: RequirementState) -> RequirementState:
    """Phase 4: LLM classifies requirement"""
    result = classification_chain.invoke({
        "requirement": state["atoms"],
        "capabilities": state["retrieved_capabilities"],
        "scores": state["match_scores"],
        "history": state["prior_wave_history"],
    })
    state["classification"] = result.classification
    state["confidence"] = result.confidence
    state["rationale"] = result.rationale
    return state

def route_by_confidence(state: RequirementState) -> str:
    if state["confidence"] > 0.85:
        return "validation"          # fast-track to Phase 5
    else:
        return "human_review"        # interrupt for human-in-the-loop

graph.add_conditional_edges("classify", route_by_confidence, {
    "validation": "phase5_validate",
    "human_review": "human_checkpoint",  # LangGraph interrupt()
})
```

---

## Phase 5 — Validation & output agent

| Sub-component | Library | Why |
|---------------|---------|-----|
| **Cross-requirement conflict detection** | **NetworkX** | Build a dependency graph between requirements (edges = "depends on" or "conflicts with"). Cycle detection catches circular dependencies. Connected component analysis finds requirement clusters that must be classified together |
| **Country-specific override rules** | **Custom rule engine** (Python + YAML config) | Regulatory rules per country (e.g., "Germany requires Grundbuch integration" overrides a generic GL fitment). Rules stored as YAML, evaluated deterministically |
| **Human-in-the-loop** | **LangGraph `interrupt()`** | Low-confidence classifications pause execution and surface to the consultant for review. The consultant's override is captured and written back to the historical fitments DB |
| **Report generation** | **Python stdlib `csv`** | Fitment matrix exported as CSV — the format that integrates directly into Excel, Power BI, and any downstream tooling. No extra dependency. Output columns: req_id, classification, confidence, rationale, d365_module, country, wave, reviewer_override |
| **Audit trail** | **PostgreSQL** + **Langfuse traces** | Every classification decision is logged with: requirement text, retrieved capabilities, match scores, LLM reasoning, human override (if any), timestamps. Langfuse stores the full LLM trace tree. Full reproducibility |
| **Metrics & dashboards** | **Prometheus** + **Grafana** | Track: classification distribution (% FIT/PARTIAL/GAP per wave), confidence score histograms, processing latency per phase, LLM token costs, human override rates |

---

## Cross-cutting libraries (used across all phases)

| Concern | Library | Why |
|---------|---------|-----|
| **Async processing** | **asyncio** + **aiohttp** | Batch processing 2,000 requirements in parallel. LLM calls are I/O-bound — async enables 10-20x throughput over sync |
| **Task queue** | **Celery** + **Redis** | For production deployment: distributes requirement batches across worker nodes. Redis as broker + result backend |
| **Containerization** | **Docker** + **Docker Compose** | Each agent runs in its own container: ingestion, retrieval, classification, validation. Qdrant and PostgreSQL as separate services |
| **API layer** | **FastAPI** | REST API for: submitting requirement documents, polling processing status, retrieving fitment results, triggering re-classification |
| **Authentication** | **FastAPI + OAuth2** (via `python-jose`) | Enterprise SSO integration for the consultant review portal |
| **Logging** | **structlog** | Structured JSON logging with correlation IDs per requirement batch. Integrates with ELK stack or Datadog |
| **LLM tracing** | **Langfuse** | Open-source LLM observability. Traces every LLM call graph with inputs, outputs, token counts, latency, cost. Self-hosted. Integrated via `langfuse.callback.CallbackHandler` in LangChain |
| **Testing** | **pytest** + **Langfuse Evaluations** | Unit tests for deterministic logic (normalizer, validator). Langfuse evaluations for LLM output quality (classification accuracy, rationale coherence) — run offline against captured traces |
| **CI/CD** | **GitHub Actions** or **GitLab CI** | Prompt regression testing: when a prompt template changes, re-run classification on a golden dataset of 200 labeled requirements and assert accuracy ≥ threshold |

---

## Complete dependency list (pyproject.toml groups)

```toml
# Orchestration
langgraph>=0.2.0
langchain-core>=0.3.0
langchain-community>=0.3.0
langfuse>=2.0.0          # MIT, self-hosted — replaces LangSmith

# Document parsing (PDF, DOCX, TXT only)
docling>=2.70.0
unstructured>=0.16.0     # Docling fallback only (PDF/DOCX)
python-magic>=0.4.27

# NLP
spacy>=3.8.0
fastembed>=0.3            # ONNX Runtime embedder + cross-encoder (replaces sentence-transformers)
tiktoken>=0.7.0
rapidfuzz>=3.9.0
lingua-py>=2.0.0         # language detection
argostranslate>=1.9.0    # offline translation

# Vector storage & retrieval
qdrant-client>=1.12.0
pgvector>=0.3.0
rank-bm25>=0.2.2
faiss-cpu>=1.8.0         # or faiss-gpu for GPU acceleration

# ML / scoring
scikit-learn>=1.5.0
numpy>=1.26.0
datasketch>=1.6.0        # MinHash LSH for deduplication

# Graph analysis
networkx>=3.3.0

# API & infra
fastapi>=0.115.0
uvicorn>=0.30.0
celery>=5.4.0
redis>=5.0.0
pydantic>=2.9.0
scrapy>=2.11.0           # MS Learn corpus crawling (BSD-3, open-source)

# Reporting
# stdlib csv module — no extra dependency

# Observability
structlog>=24.0.0
prometheus-client>=0.21.0

# LLM providers (install the ones you use)
langchain-anthropic>=0.3.0
langchain-openai>=0.2.0
# langchain-ollama>=0.2.0  # for local Llama models
```

---

## Handler registry — format-aware document routing

```python
from abc import ABC
from typing import Protocol
from pathlib import Path


class DocumentHandler(Protocol):
    """Any format handler implements this interface"""

    def can_handle(self, mime_type: str, extension: str) -> bool: ...
    def parse(self, file_path: Path) -> list[DocumentChunk]: ...


class DoclingHandler:
    """Handles PDF and DOCX via Docling (primary)"""
    SUPPORTED = {".pdf", ".docx"}

    def can_handle(self, mime_type: str, extension: str) -> bool:
        return extension in self.SUPPORTED

    def parse(self, file_path: Path) -> list[DocumentChunk]:
        converter = DocumentConverter()
        result = converter.convert(str(file_path))
        return self._to_chunks(result.document)


class TxtHandler:
    """Handles plain-text requirement files"""

    def can_handle(self, mime_type: str, extension: str) -> bool:
        return extension == ".txt" or mime_type == "text/plain"

    def parse(self, file_path: Path) -> list[DocumentChunk]:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        return [DocumentChunk(text=text, source=str(file_path))]


class UnstructuredHandler:
    """Fallback: used only when Docling fails on PDF or DOCX"""

    def can_handle(self, mime_type: str, extension: str) -> bool:
        return extension in {".pdf", ".docx"}  # fallback scope only

    def parse(self, file_path: Path) -> list[DocumentChunk]:
        from unstructured.partition.auto import partition
        elements = partition(filename=str(file_path))
        return [DocumentChunk(text=str(e), source=str(file_path)) for e in elements]


# Registry — PDF/DOCX/TXT only. Add new handlers here when formats are approved.
HANDLER_REGISTRY: list[DocumentHandler] = [
    DoclingHandler(),        # primary for PDF/DOCX
    TxtHandler(),            # plain text
    UnstructuredHandler(),   # Docling fallback for PDF/DOCX
]


def parse_document(file_path: Path) -> list[DocumentChunk]:
    """Route to the best handler. Raises UnsupportedFormatError for anything else."""
    ext = file_path.suffix.lower()
    mime = magic.from_file(str(file_path), mime=True)

    for handler in HANDLER_REGISTRY:
        if handler.can_handle(mime, ext):
            return handler.parse(file_path)

    raise UnsupportedFormatError(
        f"Format not supported: {ext} ({mime}). "
        f"Supported: .pdf, .docx, .txt — see docs/lessons.md for rationale."
    )
```

Adding a new approved format (e.g., if PPTX is later approved):

1. Implement `DocumentHandler` protocol with `can_handle()` and `parse()`
2. Add to `HANDLER_REGISTRY`
3. Add enum value to `DocumentFormat` (PDF | DOCX | TXT | PPTX)
4. Update `docs/lessons.md` with the decision rationale
5. The rest of the pipeline is format-agnostic — it only sees `DocumentChunk` objects

---

## Architecture decision rationale summary

| Decision | Choice | Alternative considered | Why we chose this |
|----------|--------|----------------------|-------------------|
| Orchestration | LangGraph | CrewAI, AutoGen | LangGraph's graph-based state machine maps 1:1 to DYNAFIT's 5-phase pipeline. Built-in checkpointing, human-in-the-loop, and streaming. 34.5M monthly downloads — largest ecosystem |
| Document parsing | Docling (primary) + Unstructured (fallback) | PyPDF, Marker, MinerU | Docling: MIT license, best table extraction (TableFormer), native LangChain integration, fully local. Unstructured: fallback for Docling edge-case failures on PDF/DOCX |
| Input formats | PDF, DOCX, TXT only | xlsx, csv, pptx, email | Docling handles tables natively in these three formats. Excel-specific parsing (merged cells, multi-row headers) was complexity with no additional real-world coverage. Decision in `docs/lessons.md` |
| Vector DB | Qdrant (primary) + pgvector (historical) | Milvus, Chroma, FAISS-only | Qdrant: payload filtering (filter by module before similarity), real-time updates, production-grade. pgvector: keeps historical fitments in the same PostgreSQL as the audit trail — no extra infrastructure |
| Embedding model | bge-small-en-v1.5 (local) | OpenAI ada-002, Cohere | Runs fully local (air-gapped enterprise), strong MTEB retrieval, 384 dimensions — fast inference, small footprint |
| Embedding library | fastembed (ONNX Runtime) | sentence-transformers (PyTorch) | fastembed: ~50 MB install vs ~500 MB PyTorch. Same model weights (ONNX-converted). Cuts Docker build from 400s+ to ~60s |
| LLM | Configurable (Claude / GPT-4 / Llama 3.1) | Single-vendor lock-in | LangChain abstraction lets you swap. Classification accuracy testing per model ensures you always use the best available |
| LLM observability | Langfuse (MIT, self-hosted) | LangSmith (commercial SaaS) | Langfuse is fully open-source (MIT), self-hosted via Docker, zero data egress. LangSmith is BSL-licensed and requires commercial agreement for self-hosting. |
| Web scraping | Scrapy (BSD-3) | Firecrawl (SaaS) | Scrapy is fully open-source, battle-tested for large-scale crawls, no API key or account required |
| Report output | Python stdlib `csv` | openpyxl Excel | CSV is universally importable into Excel, Power BI, and databases. Zero extra dependency. Decision in `docs/lessons.md` |
| Deduplication | FAISS (transient) + datasketch (at-scale) | All-pairs brute force | FAISS for <5K requirements (fast cosine). datasketch MinHash LSH for >10K (sub-linear time). Both are pure computation, no server needed |
| NLP | spaCy | NLTK, Stanza | Fastest production NLP pipeline. `EntityRuler` for synonym dictionary. Production-proven at enterprise scale |

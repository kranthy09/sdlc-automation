# DYNAFIT — Complete Implementation Specification

> **When to read this file:** Layer 3 of the build order (Weeks 3–4 in TDD_IMPLEMENTATION_GUIDE.md).
> Do not read this to scaffold the project. Read CLAUDE.md first, build Layers 0–2, then come here.
>
> **This file is the brain for Module 1 only.** CLAUDE.md defines the platform architecture.
> This file defines every algorithm, threshold, prompt, decision tree, and data transformation
> for the DYNAFIT module. Without it, implementation will drift. With it, nodes build exactly as designed.
>
> **Nodes in this module call `platform/` utilities. They do not own infrastructure.**
> Every LLM call goes through `platform/llm/client.py`. Every vector search goes through
> `platform/retrieval/vector_store.py`. Nodes never instantiate Anthropic or Qdrant clients directly.

---

## PHASE 1 — INGESTION AGENT

**Problem:** Raw docs (Word/PDF/TXT) → structured RequirementAtom[].
**No LLM calls in Step 1.** Steps 2-3 use LLM. Step 4 is pure validation.

### Step 1: Document Parser (pure data engineering)

#### Sub-step A: Format Detector

**Algorithm:** Three-layer cascade:
1. Read first 8 bytes → match magic bytes (`%PDF` = PDF, `PK\x03\x04` = ZIP-based container)
2. If ZIP: inspect `[Content_Types].xml` inside archive → if contains `word/document.xml` = DOCX; otherwise `UnsupportedFormatError`
3. If neither: `python-magic` MIME detection → TXT/plain text
4. If still unknown: `UnsupportedFormatError` — quarantine file

**Input:** `RawUpload(filename: str, file_bytes: bytes, upload_id: str)`
**Output:** `DetectedFormat(format: PDF|DOCX|TXT, confidence: float, encoding: str)`

**Routing decision:**
- PDF/DOCX/TXT → Docling extraction → Table Extractor AND Prose Splitter AND Image Extractor (Sub-steps B, C, E run in parallel)
- If Docling fails → Unstructured.partition_auto() as fallback; image extraction still runs on raw bytes

**Note on images:** Images are NOT optional. Architecture diagrams in a DOCX can define integration requirements. Screenshots can show AS-IS system behaviour that is the actual requirement. Skipping them silently loses requirements. Sub-step E handles every image extracted from every document.

#### Sub-step B: Table Extractor

**For PDF/DOCX/TXT (Docling path):**
1. `DocumentConverter().convert(file_path)` → `DoclingDocument`
2. Iterate `doc.tables` → each table has rows/cols extracted with layout awareness
3. Docling preserves table structure even in complex PDFs (spanning cells, nested tables)

**Output:** `list[dict[str, str]]` — raw records with original column names

#### Sub-step C: Prose Splitter

**Algorithm:**
1. Extract text from PDF/DOCX preserving heading hierarchy (Docling provides `doc.text_content` with section labels)
2. Split at paragraph boundaries (double newline)
3. Group short paragraphs under same heading into single chunk (max 1500 chars)
4. Stitch overlap: last 2 sentences of chunk N prepended to chunk N+1 for context continuity

**Output:** `list[ProseChunk(text, section, page, char_offset, has_overlap)]`

#### Sub-step D: Header Map

**The multilingual synonym dictionary (YAML):**
```yaml
requirement_text:
  en: ["Business Requirement", "Req Description", "Requirement", "User Need", "Functional Requirement", "Req Desc"]
  de: ["Geschäftsanforderung", "Anforderungsbeschreibung", "Fachliche Anforderung"]
  fr: ["Exigence métier", "Description exigence"]
req_id:
  en: ["Requirement ID", "Req ID", "Req No", "Req #", "ID", "Ref"]
  de: ["Anforderung Nr.", "Anf-Nr"]
  fr: ["Réf", "N° Exigence"]
module:
  en: ["Module", "D365 Module", "Functional Area", "Process Area"]
  de: ["Modul", "Funktionsbereich"]
priority:
  en: ["Priority", "MoSCoW", "Importance", "Must/Should/Could"]
  de: ["Priorität"]
country:
  en: ["Country", "Legal Entity", "Region"]
  de: ["Land", "Buchungskreis"]
```

**Three-tier resolution:**
1. **Exact match:** Lowercase + strip whitespace → lookup in synonym dict → confidence 1.0
2. **Fuzzy match:** `rapidfuzz.fuzz.token_set_ratio(header, synonym)` > 70 → confidence 0.7-0.9
3. **Positional fallback:** Column 1 with short values (<30 chars avg) → likely req_id. Longest-text column → likely requirement_text. Confidence 0.4-0.6, flag for human review.

**Note:** Applies to tables extracted from PDF/DOCX by Docling. Column headers from native document tables are matched to canonical fields using this map.

**Critical rule:** `requirement_text` column MUST be found. If not → ParseError, doc rejected.

---

#### Sub-step E: Image Extractor

**Problem:** Documents embed images that carry structural meaning: architecture diagrams define integration scope, screenshots show AS-IS system behaviour, data charts encode KPIs. Pure OCR on these loses the semantic structure.

**Platform utility:** `platform/parsers/image_extractor.py`
Uses `platform/llm/client.py` for vision calls (Claude is multimodal — same LLM client, different input type).

**Input:** `DoclingDocument` (PDF/DOCX) or raw file bytes (fallback path)
**Output:** `list[ImageDerivedChunk]`

**Pipeline:**

**Step 1 — Image Extraction**
```python
# Docling path (primary)
images: list[Picture] = doc.pictures          # Docling Picture: bbox, page_no, image bytes
# Unstructured fallback path
images = [el for el in elements if el.category == ElementType.IMAGE]
```

**Step 2 — Size Filter (before any LLM call)**
- Skip if image width < 80px OR height < 80px → likely icon/logo/bullet decoration
- Skip if image area < 6400px² → too small to carry semantic content
- Cost guard: this filter eliminates ~60% of embedded images before spending LLM tokens

**Step 3 — Image Type Classifier (Claude vision, fast)**

```jinja2
{# platform/parsers/prompts/image_classifier.j2 #}
Classify this image extracted from an ERP requirements document.

Return exactly one of these types:
- ARCHITECTURE_DIAGRAM: system diagram, process flow, integration map, data flow diagram
- DATA_TABLE: table, matrix, or grid shown as an image instead of native table
- SCREENSHOT: screenshot of existing software (ERP, legacy system, web app)
- CHART: bar chart, pie chart, timeline, KPI dashboard
- DECORATIVE: logo, header graphic, divider, clipart — no information content

Respond with JSON: {"type": "<TYPE>", "confidence": 0.0-1.0}
```

- Model: `claude-haiku-4-5-20251001` (cheapest, classification only — not full Sonnet)
- Confidence < 0.6 → treat as DECORATIVE (safe default, avoids hallucinated "requirements")
- Cost: ~$0.0001 per image classification call

**Step 4 — Route by Image Type**

```
DECORATIVE      → discard immediately
DATA_TABLE      → Tesseract OCR → feed output into Table Extractor (Sub-step B)
                  Tag source_ref as f"page_{page}_image_{idx}" for audit trail
ARCHITECTURE_DIAGRAM → Claude vision (Sonnet) extraction (see prompt below)
SCREENSHOT      → Claude vision (Sonnet) description (see prompt below)
CHART           → Tesseract OCR for axis labels + Claude vision (Haiku) for narrative
```

**Architecture Diagram prompt (Jinja2):**
```jinja2
{# platform/parsers/prompts/image_architecture.j2 #}
This image is an architecture or process diagram from an ERP requirements document
for {{ product_config.display_name }}.

Extract the following as structured information:
1. System/component names visible in the diagram
2. Integration flows: which system sends data to which system, and what data
3. Process steps if this is a process flow (numbered or sequenced)
4. Any labels, annotations, or callouts that describe behaviour

Then write a prose paragraph (3-6 sentences) describing what this diagram specifies
as a business/functional requirement. Start with: "The architecture shows..."

Respond with JSON:
{
  "components": ["SystemA", "SystemB"],
  "integration_flows": [{"from": "SystemA", "to": "SystemB", "data": "invoice data"}],
  "process_steps": ["step description"],
  "requirement_prose": "The architecture shows...",
  "d365_modules_implied": ["AccountsPayable"]
}
```

**Screenshot prompt (Jinja2):**
```jinja2
{# platform/parsers/prompts/image_screenshot.j2 #}
This image is a screenshot of an existing system in an ERP requirements document
for {{ product_config.display_name }}.

Describe:
1. What functional area this screenshot shows (e.g., invoice approval, vendor master)
2. What data fields or columns are visible
3. What actions or workflows are visible (buttons, statuses, menu items)
4. Any visible business rules (colour coding, mandatory fields, validation messages)

Then write a prose requirement (2-4 sentences) that captures what this screenshot implies
the system must support. Start with: "The system must..."

Respond with JSON:
{
  "functional_area": "...",
  "visible_fields": ["field1", "field2"],
  "visible_actions": ["action1"],
  "business_rules": ["rule description"],
  "requirement_prose": "The system must..."
}
```

**Step 5 — Assemble ImageDerivedChunk**

```python
class ImageDerivedChunk(PlatformModel):
    text: str                        # requirement_prose from LLM, or OCR text
    image_type: ImageType            # ARCHITECTURE_DIAGRAM | DATA_TABLE | SCREENSHOT | CHART
    components: list[str]            # systems/entities named (from architecture prompt)
    d365_modules_implied: list[str]  # modules hinted by diagram (used in Phase 2 routing)
    source_page: int
    source_ref: str                  # "page_3_image_1"
    extraction_confidence: float     # vision model confidence
    upload_id: str
```

**Merge into main stream:** ImageDerivedChunks enter the Prose Splitter path (Sub-step C).
They are tagged `content_type="image_derived"` on the resulting RequirementAtoms.

**Cost summary for a typical 50-req document with 10 embedded images:**
- ~6 survive size filter
- ~6 classifier calls (Haiku): ~$0.0006
- ~3 non-decorative: 2 Sonnet vision calls + 1 Haiku OCR+narrative: ~$0.006
- Total image extraction cost per document: **< $0.01**

**Important:** Image-derived atoms enter the same Atomizer → Intent Classifier → Module Tagger → Deduplicator pipeline as text atoms. The deduplicator will merge an image-derived atom with a near-duplicate text atom (cosine > 0.92), keeping the text atom as primary but appending `source_refs` from both. This prevents double-counting.

---

### Step 2: Requirement Extractor (LLM-powered)

#### Sub-step A: Atomizer

**Problem:** One row/chunk may contain multiple bundled requirements.
**Example input:** "We need automatic three-way matching for AP invoices, and we also want the system to flag duplicate invoices based on vendor + invoice number + amount, plus we need a monthly aging report."
**Expected output:** 3 separate atoms.

**LLM prompt template (Jinja2):**
```
You are a D365 F&O requirements analyst. Split the following text into atomic business requirements.
Each atom must describe exactly ONE functional need.

Rules:
- Each atom is a single sentence starting with "The system shall..." or "The system must..."
- Do not combine multiple features into one atom
- Preserve all specific details (thresholds, field names, frequencies)
- If the text contains only one requirement, return it as-is

Text: {{ requirement_text }}

Respond with JSON:
{
  "atoms": [
    {"text": "...", "is_functional": true/false}
  ]
}
```

**Library:** `langchain_anthropic.ChatAnthropic` with `with_structured_output(AtomList)`
**Model:** `claude-sonnet-4-20250514` (configured via ProductConfig)
**Retry:** If Pydantic validation fails, inject error message into prompt and retry (max 2 retries)

#### Sub-step B: Intent Classifier

**LLM classifies each atom:**
- `FUNCTIONAL` — describes what the system does (goes to fitment)
- `NON_FUNCTIONAL` — performance, security, UX (tagged but skipped in fitment)
- `INTEGRATION` — connects D365 to external system (goes to fitment with integration flag)
- `REPORTING` — reports/analytics (goes to fitment with reporting flag)

**Prompt includes 8 few-shot examples (2 per category).**

#### Sub-step C: Module Tagger

**Tags each atom to a D365 module using constrained vocabulary:**
```python
D365_MODULES = [
    "AccountsPayable", "AccountsReceivable", "GeneralLedger",
    "FixedAssets", "Budgeting", "CashAndBankManagement",
    "ProcurementAndSourcing", "InventoryManagement",
    "ProductionControl", "SalesAndMarketing",
    "ProjectManagement", "HumanResources",
    "Warehouse", "Transportation", "MasterPlanning",
    "OrganizationAdministration", "SystemAdministration",
]
```

**LLM prompt forces selection from this list.** If LLM returns unlisted module → retry with explicit constraint.

---

### Step 3: Normalizer

#### Sub-step A: Deduplicator

**Algorithm:**
1. Embed all atoms using `bge-large-en-v1.5` (batch encode)
2. For <5K atoms: FAISS `IndexFlatIP` → pairwise cosine similarity
3. For >10K atoms: `datasketch.MinHashLSH` with 128 permutations, threshold 0.8
4. Pairs with cosine > 0.92 → merge (keep highest completeness score, concatenate source_refs)
5. Pairs with cosine 0.80-0.92 → flag as "potential duplicate, human review"

**Sample flow:** 300 raw atoms → ~15 merges → ~20 flagged → 265 unique atoms

#### Sub-step B: Term Aligner (spaCy EntityRuler)

**Problem:** "three-way matching" vs "3-way match" vs "invoice matching triple" must normalize to canonical term.

**Implementation:**
1. Load `en_core_web_lg` + custom `EntityRuler` with 400-entry D365 synonym YAML
2. For each atom, run NER pipeline
3. Replace recognized entities with canonical forms
4. Add `entity_hints: list[str]` to atom (used by Phase 2 retrieval)

**Synonym YAML excerpt:**
```yaml
- pattern: [{"LOWER": "three"}, {"LOWER": "-"}, {"LOWER": "way"}, {"LOWER": "matching"}]
  canonical: "three-way matching"
  d365_entity: "VendInvoiceMatchingPolicy"
- pattern: [{"LOWER": "3"}, {"LOWER": "-"}, {"LOWER": "way"}, {"LOWER": "match"}]
  canonical: "three-way matching"
  d365_entity: "VendInvoiceMatchingPolicy"
```

#### Sub-step C: Priority Enricher

**If priority not explicitly provided in source doc:**
1. Keyword scan: "must" / "shall" / "required" → MUST. "should" / "expected" → SHOULD. "could" / "nice to have" → COULD.
2. If no keywords: default to SHOULD (safest middle ground)
3. Tag with MoSCoW classification

#### Sub-step D: Cross-Wave Linker

**For multi-wave implementations:**
1. Query `historical_fitments` table in PostgreSQL: `WHERE module = atom.module AND cosine_similarity(embedding, atom_embedding) > 0.85`
2. Attach matching prior decisions: `{wave: 1, country: "FR", classification: "FIT", consultant: "J. Martin"}`
3. This data flows through to Phase 4 as strong classification evidence

---

### Step 4: Validator (quality gate)

#### Sub-step A: Schema Validator (cross-field rules)

NOT re-checking JSON. Checking CONSISTENCY:
- If `module = "AccountsPayable"` but `entity_hints` contain "customer" or "sales order" → flag mismatch
- If `country = "DE"` but requirement mentions "GAAP" (US standard) → flag (should be HGB/IFRS)
- All `atom_id` values must be unique within batch
- `requirement_text` length must be 10-2000 chars

#### Sub-step B: Ambiguity Detector

**Algorithm using spaCy dependency parse:**
1. Count concrete D365 nouns (from entity dictionary): "invoice", "purchase order", "vendor", "journal"
2. Count specific verbs: "create", "validate", "approve", "calculate", "post"
3. Count vague terms: "handle", "manage", "process", "deal with", "support"
4. `specificity_score = (concrete_nouns + specific_verbs) / (concrete_nouns + specific_verbs + vague_terms)`
5. Score < 0.3 → REJECT (too vague, send back for re-extraction)
6. Score 0.3-0.5 → FLAG (borderline, human review)
7. Score > 0.5 → PASS

**Example:** "The system should handle invoices" → specificity 0.25 → REJECT
**Example:** "The system shall validate three-way matching for vendor invoices against purchase orders" → specificity 0.83 → PASS

#### Sub-step C: Completeness Score

**Per-module parameter templates:** Each D365 module has expected parameters for a complete requirement.
```yaml
AccountsPayable:
  expected_params: ["matching_type", "tolerance", "approval_workflow", "payment_terms"]
  min_params_for_complete: 2
GeneralLedger:
  expected_params: ["posting_type", "dimension_set", "period_control", "currency"]
  min_params_for_complete: 2
```

1. For each atom, check how many expected params are mentioned (keyword + NER detection)
2. `completeness = params_found / expected_params_count × 100`
3. Score < 30 → FLAG (incomplete but might be sufficient for fitment)
4. Score ≥ 30 → PASS

**Final gate:** Atom must pass Schema (A) AND not be rejected by Ambiguity (B). Completeness (C) flags but doesn't block.

**Output:** `ValidatedAtom[]` (passed) + `FlaggedAtom[]` (human review) → Phase 2

---

## PHASE 2 — KNOWLEDGE RETRIEVAL AGENT (RAG)

**Problem:** For each validated atom, find the most relevant D365 capabilities, documentation, and historical decisions.

---

### RAG Sources — When and How to Build

There are three sources. They are built at different times by different processes. Understanding this is prerequisite to implementing Phase 2.

---

#### Source A — D365 Capability KB (Qdrant collection: `d365_fo_capabilities`)

**What it is:** The authoritative catalogue of what D365 F&O can do out of the box. One record per feature.
**Who builds it:** The D365 product team authors `knowledge_bases/d365_fo/seed_data/capabilities.jsonl`.
**When it is built:** Week 5 (after platform utilities in Layer 2 are stable). Rebuilt whenever capabilities.jsonl is updated.
**How it is built:** `make seed-kb PRODUCT=d365_fo` runs `infra/scripts/seed_knowledge_base.py`.

**Collection configuration:**
```python
# Qdrant hybrid collection — HNSW for dense + sparse vectors for BM25
VectorsConfig = {
    "dense": VectorParams(size=1024, distance=Distance.COSINE),  # bge-large-en-v1.5
    "sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False)),
}
```

**Record format (capabilities.jsonl — one JSON object per line):**
```jsonl
{
  "id": "cap-ap-0001",
  "module": "AccountsPayable",
  "feature": "Three-way matching",
  "description": "Validates purchase order, product receipt, and vendor invoice quantities and amounts before payment approval. Configurable matching policies per vendor group.",
  "navigation": "AP > Setup > Accounts payable parameters > Invoice matching",
  "version": "10.0.38",
  "tags": ["invoice", "matching", "purchase order", "validation"]
}
```

**Embedding:** `bge-large-en-v1.5.encode(f"{record['feature']}: {record['description']}")` — both fields concatenated so the vector captures feature name AND description.

**Sparse vector:** Computed from `tags` + `feature` + tokenized `description` keywords via BM25 term weighting.

**Refresh policy:** Rebuild the collection when any of the following change:
- capabilities.jsonl updated (new D365 version, new features discovered)
- Embedding model changed
- Collection schema changed
Run `make seed-kb PRODUCT=d365_fo` — it calls `recreate_collection` (full rebuild, not upsert). Downtime: ~2 min. Schedule during off-hours for production.

---

#### Source B — MS Learn Corpus (Qdrant collection: `d365_fo_docs`)

**What it is:** Chunked documentation from Microsoft Learn for D365 F&O. Provides richer prose context than the capability KB — explains *how* features work, not just *that* they exist.
**Who builds it:** Core platform team runs a one-time crawl + periodic refresh.
**When it is built:** Week 5 alongside Source A. Refreshed monthly (new D365 release notes, updated docs).
**How it is built:** `make seed-corpus PRODUCT=d365_fo` runs `infra/scripts/seed_ms_learn_corpus.py`.

**Crawl strategy:**
```python
# infra/scripts/seed_ms_learn_corpus.py
# MS Learn D365 F&O docs are publicly accessible. Crawl the sitemap.
BASE_URLS = [
    "https://learn.microsoft.com/en-us/dynamics365/finance/",
    "https://learn.microsoft.com/en-us/dynamics365/supply-chain/",
]
# Use sitemap.xml to enumerate all pages, then fetch and parse with BeautifulSoup.
# Respect robots.txt. Rate-limit to 1 req/sec.
```

**Chunking strategy:**
1. Strip navigation chrome, keep article body only
2. Split at `<h2>` and `<h3>` boundaries — preserve section context
3. Chunk sections at 512 tokens (bge-large context window), 50-token overlap
4. Each chunk carries: `{url, title, section_heading, text, d365_module_hint, crawled_at}`

**Collection configuration:**
```python
# Dense-only collection — documentation is prose, sparse BM25 less useful
VectorParams(size=1024, distance=Distance.COSINE)
```

**Embedding:** `bge-large-en-v1.5.encode(f"{chunk['section_heading']}: {chunk['text']}")` — heading prepended for context.

**Refresh policy:** Monthly cron job. Does NOT recreate collection — upserts by URL hash, so only changed pages are re-embedded. Deletions handled by comparing URL inventory against existing points and removing stale IDs.

**Scale:** Approximately 15,000–25,000 doc chunks for full D365 F&O coverage. ~25MB Qdrant storage. Seeding time: ~45 min on first load, ~5 min for monthly delta.

---

#### Source C — Historical Fitments (PostgreSQL table: `d365_fo_fitments`)

**What it is:** The output of every completed DYNAFIT wave, stored with embeddings for similarity retrieval. This is the only source that improves over time. Wave 1 classification of a German AP requirement informs Wave 3 classification of a similar French AP requirement.
**Who builds it:** The DYNAFIT pipeline writes to it automatically. No manual curation needed.
**When it is built:** Starts empty. First records written after Wave 1 Phase 5 completes. Grows with each wave.
**How it is built:** Phase 5 (Validation node) writes every `ValidatedFitmentResult` back to this table WITH its embedding.

**Table schema with pgvector:**
```sql
CREATE TABLE d365_fo_fitments (
    id              SERIAL PRIMARY KEY,
    atom_id         TEXT NOT NULL,
    requirement_text TEXT NOT NULL,
    embedding       vector(1024) NOT NULL,          -- bge-large embedding of requirement_text
    module          TEXT NOT NULL,
    country         TEXT NOT NULL,
    wave            INT NOT NULL,
    classification  TEXT NOT NULL,                  -- FIT | PARTIAL_FIT | GAP
    confidence      FLOAT NOT NULL,
    d365_capability_ref TEXT,
    rationale       TEXT NOT NULL,
    consultant      TEXT,                           -- reviewer email if human override
    reviewer_override BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fitments_module ON d365_fo_fitments(module);
CREATE INDEX idx_fitments_embedding ON d365_fo_fitments
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

**Write-back (Phase 5 node, after human review completes):**
```python
# In phase5_validation_node, after ValidatedFitmentBatch is finalized:
for result in validated_batch.results:
    embedding = embedder.encode(result.requirement_text)
    await postgres.insert_fitment(
        atom_id=result.requirement_id,
        requirement_text=result.requirement_text,
        embedding=embedding,
        module=result.d365_module,
        country=result.country,
        wave=result.wave,
        classification=result.classification,
        confidence=result.confidence,
        d365_capability_ref=result.d365_capability_ref,
        rationale=result.rationale,
        consultant=result.reviewer if result.reviewer_override else None,
        reviewer_override=result.reviewer_override,
    )
```

**Critical rule:** Consultant overrides (where `reviewer_override=True`) are HIGHEST QUALITY training signal. When Phase 2 retrieves a prior fitment where a consultant overrode GAP → FIT, Phase 4 must treat that as strong evidence, not just a data point. The `reviewer_override` flag passes through to the Phase 4 prompt as explicit signal.

**Query in Phase 2:**
```sql
-- Find similar prior decisions for the same module
SELECT atom_id, classification, confidence, rationale, wave, country, reviewer_override
FROM d365_fo_fitments
WHERE module = $1
  AND 1 - (embedding <=> $2) > 0.85
ORDER BY reviewer_override DESC, wave DESC   -- consultant overrides ranked first
LIMIT 5;
```

**Growth trajectory:** 50 requirements/wave × 4 waves/year × 3 clients = ~600 records/year. pgvector HNSW handles millions of vectors — no scaling concern for years.

---

**Summary — build timeline:**

| Source | Built when | By whom | Refresh |
|--------|-----------|---------|---------|
| A: Capability KB | Week 5 (once, then on D365 release) | D365 product team authors JSONL | Per D365 update |
| B: MS Learn Corpus | Week 5 (then monthly cron) | Core platform team runs crawl | Monthly delta upsert |
| C: Historical Fitments | Auto-populated after Wave 1 Phase 5 | DYNAFIT pipeline writes on completion | Continuous (every wave) |

**Before Wave 1, only Source A and B exist.** The system still works because Sources A and B provide capability matching. Source C starts contributing from Wave 2 onwards, improving confidence scores and reducing DEEP_REASON routing (fewer 3-LLM-call scenarios because history provides strong priors).

---

### Step 1: Query Builder

**For each RequirementAtom, generate three retrieval signals:**

1. **Dense vector:** `bge-large-en-v1.5.encode(atom.requirement_text)` → 1024-dim float[]
2. **Sparse tokens:** Extract keywords using spaCy NER + TF-IDF top-10 terms → BM25 query
3. **Metadata filter:** `{"module": atom.module, "version": {"$gte": "10.0.30"}}` → Qdrant payload filter

**Special handling for image-derived atoms (`content_type == "image_derived"`):**
- Augment dense vector query: if `atom.image_components` is non-empty, also encode each component name separately and average the embeddings → enriched query vector that includes system names from the diagram
- Augment metadata filter: if `atom.d365_modules_implied` is non-empty, OR it with `atom.module` in the Qdrant filter — diagrams often imply multiple modules (e.g., an AP-to-GL integration diagram implies both AccountsPayable AND GeneralLedger)
- Reduce top-K threshold: retrieve top-30 capabilities instead of top-20 (image extraction is noisier, so cast wider net before reranking)

**Output:** `RetrievalQuery(dense_vector, sparse_tokens, metadata_filter, atom_id, top_k, is_image_derived)`

### Step 2: Parallel Retrieval (3 sources, concurrent)

**Implementation:** `asyncio.gather()` with per-source timeout (5s)

**Source A — D365 Capability KB (Qdrant):**
- Collection: `d365_fo_capabilities`
- Search: Qdrant hybrid (HNSW dense + BM25 sparse, built-in RRF)
- Filter: `module` payload filter from query
- Returns: top-20 `CapabilityHit(id, feature, description, score, module, navigation)`
- Latency: ~50ms

**Source B — MS Learn Corpus (Qdrant):**
- Collection: `d365_fo_docs`
- Search: Dense only (documentation is prose, BM25 less useful)
- Returns: top-10 `DocChunkHit(url, title, excerpt, score)`
- Latency: ~40ms

**Source C — Historical Fitments (PostgreSQL + pgvector):**
- Table: `d365_fo_fitments`
- Query: `SELECT * WHERE module = $1 AND 1 - (embedding <=> $2) > 0.85 ORDER BY reviewer_override DESC, wave DESC LIMIT 5`
- Consultant overrides ranked first — they are the highest-quality signal (human correction)
- Returns: 0-5 `PriorFitment(wave, country, classification, consultant, rationale, reviewer_override)`
- The `reviewer_override` flag is passed through to Phase 4 prompt as explicit signal
- Latency: ~20-200ms
- **Starts empty (Wave 1).** First results appear after Wave 1 Phase 5 completes and write-back runs.

**Failure handling:** If any source times out, proceed with available results. Log warning. Minimum: Source A must return results, otherwise atom gets `retrieval_confidence = LOW`.

### Step 3: RRF Fusion

**Critical design: NOT equal fusion across all sources.**
- Capabilities (Source A) are PRIMARY evidence
- Docs (Source B) provide a BOOST signal to capabilities
- Historical fitments (Source C) BYPASS fusion entirely — passed through as structured evidence

**Algorithm:**
1. Rank capabilities by their Qdrant hybrid score → assign ordinal ranks 1..20
2. Compute RRF: `score(cap) = 1 / (60 + rank_dense) + 1 / (60 + rank_sparse)` where k=60
3. **Doc boost:** For each capability, if ANY doc chunk from Source B mentions the same D365 feature name (exact string match on `feature` field) → add +0.05 to RRF score. This is a FIXED boost, not proportional.
4. Deduplicate: if two capabilities describe the same feature (cosine > 0.95 between their texts), merge, keep higher score
5. Compute `retrieval_quality`:
   - HIGH: top-1 score > threshold AND score_spread (top1 - top5) > 0.01 AND prior fitments exist
   - MEDIUM: any two of the above
   - LOW: fewer than two

**Output:** `FusedRetrievalResults(capabilities[20], doc_refs[10], prior_fitments[0..5], retrieval_quality)`

### Step 4: Cross-Encoder Rerank

**Problem:** Bi-encoder (bge-large) optimizes for retrieval speed, not pairwise accuracy. Cross-encoder reads (atom, capability) jointly.

**Implementation:**
1. Model: `cross-encoder/ms-marco-MiniLM-L-12-v2`
2. Construct 20 pairs: `[(atom.text, cap.description) for cap in fused_capabilities]`
3. Forward pass: `model.predict(pairs)` → raw logits
4. Sigmoid activation: `1 / (1 + exp(-logit))` → relevance score 0-1
5. **Adaptive K selection:** Sort by score descending. Find largest score gap between adjacent positions (top-3..top-7 range). Cut there. Typical: 3-5 capabilities survive.
6. **Confidence calibration:** `final_confidence = CE_score × quality_mult × history_boost` where:
   - `quality_mult` = 1.0 (HIGH), 0.85 (MEDIUM), 0.70 (LOW) — from Step 3
   - `history_boost` = 1.1 if matching prior fitments exist, 1.0 otherwise
   - Clamp at 1.0

**Latency:** ~200ms for 20 pairs on GPU, ~800ms on CPU. Acceptable.

### Step 5: Context Assembly

**Packages everything into the Phase 3/4 contract:**

```python
class AssembledContext(PlatformModel):
    atom: ValidatedAtom
    capabilities: list[RankedCapability]     # 3-5, with CE scores + text
    ms_learn_refs: list[DocReference]         # URLs + relevant excerpts
    prior_fitments: list[PriorFitment]        # structured historical evidence
    retrieval_confidence: Literal["HIGH", "MEDIUM", "LOW"]
    retrieval_latency_ms: float
    sources_available: list[str]              # ["qdrant", "ms_learn", "pgvector"]
    provenance_hash: str                      # SHA256 of all inputs for audit
```

**Token budget:** Trim capability descriptions to fit within 3072 tokens (leaving room for prompt template + few-shots in Phase 4). Longest capabilities get truncated first. Always keep the `feature` name intact.

---

## PHASE 3 — SEMANTIC MATCHING AGENT

**Problem:** Compute a multi-signal match score for each (atom, capability) pair. Route to Phase 4 with confidence tier.

### Step 1: Multi-Signal Scorer

**Five signals, computed for each of the top-K capabilities:**

1. **Embedding cosine:** `numpy.dot(atom_embedding, cap_embedding)` — reuses embeddings from Phase 2. Range 0-1.
2. **Entity overlap:** spaCy NER on both texts. `overlap = |entities_atom ∩ entities_cap| / |entities_atom|`. Catches "purchase order" in both texts.
3. **Token ratio:** `rapidfuzz.fuzz.token_set_ratio(atom.text, cap.description) / 100`. Fuzzy string match.
4. **Historical alignment:** If prior fitment exists for this atom's module + similar text → signal = 1.0. Otherwise 0.0.
5. **Rerank score:** Cross-encoder score from Phase 2 Step 4. Already calibrated 0-1.

### Step 2: Composite Scorer + Router

**Weighted composite:**
```python
weights = {
    "embedding_cosine": 0.25,
    "entity_overlap": 0.20,
    "token_ratio": 0.15,
    "historical_alignment": 0.25,
    "rerank_score": 0.15,
}
composite = sum(signals[k] * weights[k] for k in weights)
```

**Anomaly detection:** If cosine > 0.85 but entity_overlap < 0.2 → FLAG (semantic match without entity agreement = suspicious, could be false positive like "three-way handshake" vs "three-way matching").

**Routing thresholds (from ProductConfig):**
- `composite > 0.85 AND historical_alignment > 0` → **FAST_TRACK** (Phase 4 gets single LLM call)
- `0.60 ≤ composite ≤ 0.85` → **DEEP_REASON** (Phase 4 gets 3 LLM calls + majority vote)
- `composite < 0.60` → **GAP_CONFIRM** (Phase 4 gets 1 LLM call confirming GAP)

### Step 3: Candidate Ranker

**Re-ranks the capabilities using composite scores:**
1. Sort by composite descending
2. Drop duplicates (subsume overlapping capabilities where one is a superset of another)
3. Historical boost: if a capability was confirmed FIT in a prior wave, boost score by 0.1
4. Output: `MatchResult(atom, ranked_capabilities, composite_scores, route, anomaly_flags)`

---

## PHASE 4 — CLASSIFICATION AGENT (LLM REASONING)

**Problem:** Given atom + evidence, classify as FIT / PARTIAL_FIT / GAP with rationale.

### Pre-step: Short-Circuit Check

If zero capabilities retrieved (Phase 2 returned empty) → auto-classify as GAP with rationale "No matching D365 capability found in knowledge base." Skip LLM call entirely.

### Step 1: Prompt Builder

**Jinja2 template (classification_prompt.j2):**
```
<system>
You are a senior D365 F&O functional consultant performing fitment analysis.
Classify the requirement against standard D365 capabilities.
</system>

<requirement>
ID: {{ atom.atom_id }}
Text: {{ atom.requirement_text }}
Module: {{ atom.module }}
Country: {{ atom.country }}
Priority: {{ atom.priority }}
</requirement>

<evidence>
{% for cap in capabilities %}
<capability rank="{{ loop.index }}">
  Feature: {{ cap.feature }}
  Description: {{ cap.description }}
  Navigation: {{ cap.navigation }}
  Match score: {{ "%.2f"|format(cap.composite_score) }}
</capability>
{% endfor %}

{% if prior_fitments %}
<historical_precedent>
{% for pf in prior_fitments %}
  Wave {{ pf.wave }} ({{ pf.country }}): {{ pf.classification }} — {{ pf.rationale }}
{% endfor %}
</historical_precedent>
{% endif %}
</evidence>

<instructions>
Reason through these four factors IN ORDER:
1. FEATURE EXISTENCE: Does a matching D365 feature exist in the evidence above?
2. COVERAGE: Does the feature FULLY cover the requirement, or only partially?
3. GAP DELTA: What specific functionality is missing between D365 and the requirement?
4. HISTORICAL CONSISTENCY: Do prior wave decisions support or contradict your classification?

Then classify:
- FIT: Standard D365 covers this requirement completely. No customization needed.
- PARTIAL_FIT: D365 covers this with configuration (workflow setup, parameter changes, etc.) but no X++ code.
- GAP: D365 does NOT cover this. Custom X++ development is required.

Respond in XML:
<classification>
  <verdict>FIT|PARTIAL_FIT|GAP</verdict>
  <confidence>0.0-1.0</confidence>
  <rationale>2-3 sentence explanation</rationale>
  <d365_capability_ref>capability ID from evidence</d365_capability_ref>
  <config_steps>if PARTIAL_FIT: what configuration is needed</config_steps>
  <gap_description>if GAP: what custom development is needed</gap_description>
  <caveats>any uncertainty or country-specific notes</caveats>
</classification>
</instructions>
```

### Step 2: LLM Reasoning Engine

**Based on route from Phase 3:**

**FAST_TRACK route (composite > 0.85 + history):**
- Single LLM call with temperature=0.0
- Expected: FIT or PARTIAL_FIT

**DEEP_REASON route (0.60-0.85):**
- THREE LLM calls with temperature=0.3
- Majority vote on classification
- If all three disagree → flag for human review in Phase 5
- Rationale: take from the majority vote's response

**GAP_CONFIRM route (< 0.60):**
- Single LLM call with temperature=0.0
- Expected: GAP (but LLM can override if it finds evidence we missed)

### Step 3: Response Parser

**Three-layer defense:**
1. **XML parse:** `xml.etree.ElementTree.fromstring(response)` → extract fields
2. **Regex fallback:** If XML is malformed, regex patterns: `<verdict>(.*?)</verdict>`
3. **Pydantic validation:** Parsed fields → `ClassificationResult` model. If validation fails → retry LLM call (max 2 retries)

### Step 4: Sanity Check

**Score-vs-classification consistency:**
- If classification = FIT but top-1 composite < 0.50 → OVERRIDE to PARTIAL_FIT, add caveat
- If classification = GAP but top-1 composite > 0.85 → FLAG for human review (possible LLM error)
- If confidence < review_confidence_threshold (0.60) → force human review regardless

**Output:** `ClassificationResult` → Phase 5

---

## PHASE 5 — VALIDATION & OUTPUT AGENT

**Problem:** Batch-level consistency, human review, report generation.

### Step 1: Consistency Check

#### A: Dependency Graph (NetworkX)
1. Build `DiGraph` where nodes = atoms, edges = dependency keywords ("depends on", "requires", "extends")
2. Detect conflicts: if atom A = FIT but atom B (which A depends on) = GAP → flag A for review
3. Detect cycles: `nx.find_cycle(G)` → fatal if found (circular dependencies in requirements)

#### B: Country Overrides (YAML rules)
```yaml
DE:
  overrides:
    - if_module: "GeneralLedger"
      if_classification: "FIT"
      check: "requirement mentions 'Grundbuch' or 'HGB'"
      then: "PARTIAL_FIT"
      reason: "German statutory reporting requires Grundbuch integration configuration"
```

#### C: Confidence Filter
- All atoms with confidence < `review_confidence_threshold` (0.60) → forced human review
- All atoms where Phase 3 raised anomaly flags → forced human review

### Step 2: Human Review (LangGraph HITL)

**Implementation:** `LangGraph interrupt()` at this node.

1. Build review queue: items sorted by priority (low confidence first, conflicts second, anomalies third)
2. Present to consultant via API/WebSocket: requirement text, AI classification, rationale, evidence, confidence
3. Consultant can:
   - **Approve** → classification stands
   - **Override** → new classification + reason → written to `historical_fitments` table (feeds future waves)
   - **Flag** → needs more information, atom goes back to business analyst
4. LangGraph resumes after all reviews complete

### Step 3: Report Generator

#### A: CSV Report Builder (stdlib csv)
```
Fitment Matrix columns:
  Req ID | Requirement | Module | Country | Wave | Classification | Confidence |
  D365 Capability | Rationale | Config Steps | Gap Description | Reviewer | Override
```
- One row per validated atom
- Summary section appended as comment rows: counts per classification, per module, per country
- Audit trail written as a second CSV: full provenance per classification

#### B: Audit Trail (PostgreSQL)
Each classification record includes:
- All 5 phase outputs (ingestion → retrieval → matching → classification → validation)
- LLM call IDs (LangSmith trace URLs)
- Consultant override history
- Timestamp + batch correlation ID

#### C: Metrics (Prometheus)
- `dynafit_atoms_total{classification, module, country}` — counter
- `dynafit_phase_latency_seconds{phase}` — histogram
- `dynafit_llm_calls_total{model, phase}` — counter
- `dynafit_llm_cost_usd{model}` — counter
- `dynafit_human_overrides_total{from_class, to_class}` — counter

**Final output:** `ValidatedFitmentBatch` → feeds Module 2 (FDD FOR FITS) and Module 3 (FDD FOR GAPS)

---

## LANGGRAPH WIRING

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver

class RequirementState(TypedDict):
    raw_upload: RawUpload
    parsed_document: ParsedDocument | None
    atoms: list[RequirementAtom]
    validated_atoms: list[ValidatedAtom]
    flagged_atoms: list[FlaggedAtom]
    retrieval_contexts: list[AssembledContext]
    match_results: list[MatchResult]
    classifications: list[ClassificationResult]
    validated_batch: ValidatedFitmentBatch | None
    errors: list[str]
    metrics: dict

def build_dynafit_graph() -> StateGraph:
    graph = StateGraph(RequirementState)
    
    graph.add_node("ingest", phase1_ingestion_node)
    graph.add_node("retrieve", phase2_retrieval_node)
    graph.add_node("match", phase3_matching_node)
    graph.add_node("classify", phase4_classification_node)
    graph.add_node("validate", phase5_validation_node)
    
    graph.add_edge("ingest", "retrieve")
    graph.add_edge("retrieve", "match")
    graph.add_edge("match", "classify")
    graph.add_edge("classify", "validate")
    graph.add_edge("validate", END)
    
    graph.set_entry_point("ingest")
    
    return graph.compile(
        checkpointer=PostgresSaver.from_conn_string(POSTGRES_URL),
        interrupt_before=["validate"],  # HITL pause point
    )
```

**Each node function:** Reads from state, calls the phase's pipeline, writes results back to state.
**Checkpointing:** Every node completion saves state to PostgreSQL. If crash occurs mid-Phase 3, resume from Phase 3 start.

---

## OBSERVABILITY SETUP

**structlog configuration:**
```python
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)
```

**Every phase boundary logs:**
```python
log.info("phase_complete",
    phase="ingestion",
    batch_id=state["batch_id"],
    atoms_in=len(raw_records),
    atoms_out=len(validated_atoms),
    flagged=len(flagged_atoms),
    latency_ms=elapsed,
)
```

**LangSmith tracing:** Every LLM call wrapped with `@traceable` decorator from `langsmith`. Full prompt/response/token counts captured.

---

## SAMPLE END-TO-END FLOW

**Input:** DOCX file from Germany team, 50 requirements for Wave 3 AP module.

1. **Phase 1:** Parse DOCX (Docling) → detect "Geschäftsanforderung" column in embedded table → map to `requirement_text` via synonym dict → extract 50 rows → atomize (LLM splits 3 compound reqs) → 53 atoms → normalize (2 deduped) → validate (1 rejected as too vague) → **50 ValidatedAtoms**

2. **Phase 2:** For each atom → embed with bge-large → parallel search Qdrant (20 caps) + MS Learn (10 docs) + pgvector (0-3 history) → RRF fuse → cross-encoder rerank to top-5 → assemble context → **50 AssembledContexts**

3. **Phase 3:** For each context → compute 5 signals (cosine, entity overlap, token ratio, history, rerank) → weighted composite → route: 30 FAST_TRACK, 15 DEEP_REASON, 5 GAP_CONFIRM → **50 MatchResults**

4. **Phase 4:** FAST_TRACK: 30 single LLM calls → 28 FIT, 2 PARTIAL_FIT. DEEP_REASON: 15 × 3 LLM calls (45 total) → 8 FIT, 5 PARTIAL_FIT, 2 GAP. GAP_CONFIRM: 5 single calls → 5 GAP. **Total: 36 FIT, 7 PARTIAL_FIT, 7 GAP**

5. **Phase 5:** Consistency check → 2 conflicts flagged → country override: 1 FIT → PARTIAL_FIT (German regulatory) → human review queue: 5 items (2 conflicts + 3 low confidence) → consultant approves 4, overrides 1 GAP → FIT → **Final: 37 FIT, 7 PARTIAL_FIT, 6 GAP** → CSV report generated → feeds Modules 2 & 3

**Total LLM calls:** 80 (30 + 45 + 5). At ~$0.003/call (Sonnet) = ~$0.24 per batch.
**Total latency:** ~120 seconds for 50 requirements (parallelized across phases).

# REQFIT Dynafit — Phase Algorithms

**Module:** `modules/dynafit/` — All 5 phases of the REQFIT pipeline.

**Core rule:** Nodes call `platform/` utilities only. Never import `anthropic`, `qdrant_client`, or `sqlalchemy` directly in nodes.

---

## Phase 1: Ingestion Agent

**Input:** Raw document (PDF/DOCX/TXT)
**Output:** `RequirementAtom[]` — structured requirements

**Algorithm:**

### Step 1: Document Parser (Pure data engineering)

1. **Format Detection** (G1-lite):
   - Read first 8 bytes → magic bytes (PDF=`%PDF`, DOCX=`PK\x03\x04`)
   - Validate format or raise `UnsupportedFormatError`
   - Detect encoding (UTF-8, Latin-1, etc.)

2. **Extract Tables & Prose** (Docling):
   - `DocumentConverter().convert(file_path)` → `DoclingDocument`
   - Preserve table structure, heading hierarchy
   - Extract images separately (Phase 1, Step 4)
   - Fallback: `Unstructured.partition_auto()` if Docling fails

3. **Image Processing** (Optional but recommended):
   - Extract all images from document
   - Generate captions via Claude vision: "What requirement does this diagram/screenshot show?"
   - Treat captions as text requirements

### Step 2: Requirement Extractor (LLM-powered)

#### Sub-step A: Atomizer

**Problem:** One row/chunk may contain multiple bundled requirements.
**Example:** "We need automatic three-way matching for AP invoices, and we also want the system to flag duplicate invoices, plus we need a monthly aging report." → **3 atoms**

**LLM Prompt:** Splits text into atomic requirements (each = one functional need starting with "The system shall...").
- **Model:** `claude-sonnet-4-20250514` (via ProductConfig)
- **Library:** `langchain_anthropic.ChatAnthropic` with structured output
- **Retry:** Max 2 retries on Pydantic validation failure

**Output:** List of atoms with `is_functional: true/false` flag.

#### Sub-step B: Intent Classifier

**Classifies each atom into:**
- `FUNCTIONAL` — what the system does (goes to fitment)
- `NON_FUNCTIONAL` — performance, security, UX (tagged, skipped in fitment)
- `INTEGRATION` — connects D365 to external system (fitment + integration flag)
- `REPORTING` — reports/analytics (fitment + reporting flag)

**Prompt:** Includes 8 few-shot examples (2 per category). LLM forced-choice from enum.

#### Sub-step C: Module Tagger

**Tags each atom to D365 module using constrained vocabulary:**
```
AccountsPayable, AccountsReceivable, GeneralLedger, FixedAssets, Budgeting,
CashAndBankManagement, ProcurementAndSourcing, InventoryManagement,
ProductionControl, SalesAndMarketing, ProjectManagement, HumanResources,
Warehouse, Transportation, MasterPlanning, OrganizationAdministration, SystemAdministration
```

**LLM prompt forces selection from this list.** If LLM returns unlisted module → retry with explicit constraint.

---

### Step 3: Normalizer (Quality enrichment)

#### Sub-step A: Deduplicator

1. Embed all atoms using `bge-small-en-v1.5` (batch encode)
2. For <5K atoms: FAISS `IndexFlatIP` → pairwise cosine similarity
3. For >10K atoms: `datasketch.MinHashLSH` (128 permutations, threshold 0.8)
4. Pairs with cosine > 0.92 → **merge** (keep highest completeness score, concatenate source_refs)
5. Pairs with cosine 0.80-0.92 → **flag** as "potential duplicate, human review"

**Sample flow:** 300 raw atoms → ~15 merges → ~20 flagged → 265 unique atoms

#### Sub-step B: Term Aligner (spaCy EntityRuler)

**Normalizes synonyms:** "three-way matching" vs "3-way match" vs "invoice matching triple" → canonical form.

1. Load `en_core_web_lg` + custom `EntityRuler` with 400-entry D365 synonym YAML
2. For each atom, run NER pipeline → replace recognized entities with canonical forms
3. Add `entity_hints: list[str]` to atom (used by Phase 2 retrieval)

#### Sub-step C: Priority Enricher

**If priority not explicitly provided in source:**
1. Keyword scan: "must"/"shall"/"required" → MUST. "should"/"expected" → SHOULD. "could"/"nice to have" → COULD.
2. If no keywords: default to SHOULD
3. Tag with MoSCoW classification

#### Sub-step D: Cross-Wave Linker

**For multi-wave implementations:**
1. Query `historical_fitments` table: `WHERE module = atom.module AND cosine_similarity > 0.85`
2. Attach matching prior decisions: `{wave, country, classification, consultant}`
3. This flows to Phase 4 as strong classification evidence

---

### Step 4: Validator (Quality gate)

#### Sub-step A: Schema Validator

**Cross-field consistency checks:**
- If `module = "AccountsPayable"` but `entity_hints` contain "customer"/"sales order" → flag mismatch
- If `country = "DE"` but requirement mentions "GAAP" (US standard) → flag (should be HGB/IFRS)
- All `atom_id` values unique within batch
- `requirement_text` length: 10-2000 chars

#### Sub-step B: Ambiguity Detector

**Algorithm using spaCy dependency parse:**
1. Count concrete D365 nouns (invoice, PO, vendor, journal)
2. Count specific verbs (create, validate, approve, calculate, post)
3. Count vague terms (handle, manage, process, deal with, support)
4. `specificity_score = (concrete + specific_verbs) / (concrete + specific_verbs + vague)`
5. **Score < 0.3 → REJECT** (too vague)
6. **Score 0.3-0.5 → FLAG** (borderline)
7. **Score > 0.5 → PASS**

**Example:** "The system should handle invoices" → specificity 0.25 → REJECT
**Example:** "The system shall validate three-way matching for vendor invoices against purchase orders" → specificity 0.83 → PASS

#### Sub-step C: Completeness Score

**Per-module parameter templates:** Each D365 module has expected parameters.

```yaml
AccountsPayable:
  expected_params: [matching_type, tolerance, approval_workflow, payment_terms]
  min_params_for_complete: 2
GeneralLedger:
  expected_params: [posting_type, dimension_set, period_control, currency]
  min_params_for_complete: 2
```

1. Check how many expected params are mentioned (keyword + NER detection)
2. `completeness = params_found / expected_params_count × 100`
3. **Score < 30 → FLAG** (incomplete but might be sufficient)
4. **Score ≥ 30 → PASS**

**Final gate:** Atom must pass Schema (A) AND not be rejected by Ambiguity (B). Completeness (C) flags but doesn't block.

**Output:** `ValidatedAtom[]` (passed) + `FlaggedAtom[]` (human review) → Phase 2

---

### Phase 1 Guardrails

- **G1-lite (File Validator):** Size check (max 50 MB), format validation
- **G3-lite (Injection Scanner):** Scan extracted text for prompt injection patterns
  - Patterns: instruction_override, role_switch, act_as, system tags, base64, RTL
  - Score < 0.15 → PASS, 0.15–0.5 → FLAG, ≥ 0.5 → BLOCK
- **G2 (PII Redactor):** Detect & redact PII (names, emails, phone numbers, SSN)
  - Store `pii_redaction_map` in `DynafitState` for Phase 5 restoration

---

## Phase 2: RAG (Retrieval-Augmented Generation)

**Input:** `RequirementAtom[]`
**Output:** `RequirementAtom[]` with `prior_fitments` (past requirement matches)

**Algorithm:**

1. **Embed each atom** via `platform/retrieval/embedder.embed(atom.text)`
   - Model: `BAAI/bge-small-en-v1.5` (from ProductConfig)
   - Embed both: full text + section path

2. **Hybrid search** in Qdrant vector database:
   - Dense search: BM25 + vector similarity (cosine)
   - Filter by `product_id` (namespace)
   - Top-K retrieval (default K=5)

3. **Rerank** results via `platform/retrieval/reranker.rerank(atom.text, retrieved_docs)`
   - Cross-encoder model: `ms-marco-MiniLM-L-6-v2`
   - Return top-3 sorted by score

4. **Store in state:**
   ```python
   {
     "atom_id": "REQ-001",
     "prior_fitments": [
       {
         "prior_requirement_id": "PAST-123",
         "fitted_module": "Order Management",
         "fitted_classification": "FIT",
         "similarity_score": 0.89
       },
       ...
     ],
     "retrieval_confidence": "HIGH|MEDIUM|LOW"
   }
   ```

---

## Phase 3: Matching Agent

**Input:** `RequirementAtom[]` with prior fitments
**Output:** `MatchResult[]` — candidate modules per atom

**Algorithm:**

1. **Extract capability KB** from `ProductConfig.capability_kb_namespace`
   - Qdrant namespace contains D365 module descriptions
   - Modules: Sales, Purchase, AP, AR, GL, Inventory, Manufacturing, etc.

2. **For each atom:**
   - Embed atom text
   - Search capabilities (top-K=10)
   - Score each match: `composite_score = 0.5 * dense_score + 0.5 * semantic_score`
   - Filter by threshold (default 0.60)

3. **Rank matches** by composite_score (descending)

4. **Output:**
   ```python
   {
     "atom_id": "REQ-001",
     "text": "Sales order workflow",
     "matched_modules": [
       {
         "module_name": "Sales Order Management",
         "dense_score": 0.88,
         "semantic_score": 0.92,
         "composite_score": 0.90,
         "top_capability": "Create sales order"
       },
       ...
     ],
     "top_composite_score": 0.90
   }
   ```

---

## Phase 4: Classification Agent

**Input:** `MatchResult[]` + atom text + prior fitments
**Output:** `ClassificationResult[]` — FIT/GAP/PARTIAL_FIT verdict

**Algorithm:**

1. **Construct context:**
   - Matched modules + scores
   - Prior fitment history (2–3 similar past requirements + their classification)
   - Current atom text

2. **Call LLM via `platform/llm/client.classify()`:**
   - Template: `modules/dynafit/prompts/classification_v1.j2` (Jinja2, autoescape=True)
   - Structured output: `ClassificationResult` (Pydantic schema)
   - Max retries: 3

3. **LLM output schema** (enforced by G9):
   ```json
   {
     "classification": "FIT|GAP|PARTIAL_FIT",
     "confidence": 0.0-1.0,
     "rationale": "Why this classification",
     "matched_features": ["Feature 1", "Feature 2"],
     "gap_type": "Missing",
     "gap_description": "What's missing",
     "dev_effort": "S|M|L",
     "configuration_steps": ["Step 1", "Step 2"]
   }
   ```

4. **Route decision** (G8 Prompt Firewall):
   - FAST_TRACK: confidence ≥ 0.85 → skip human review
   - DEEP_REASON: 0.60–0.85 → human review recommended
   - GAP_CONFIRM: confidence < 0.60 → flag for review

5. **Guard rails:**
   - **G11 (Response PII Scanner):** Check rationale/gap_description for leaked PII
   - **G9 (Schema Enforcer):** Pydantic strict validation; on failure, retry or mark REVIEW_REQUIRED

---

## Phase 5: Validation Agent

**Input:** `ClassificationResult[]`
**Output:** `ValidatedFitmentBatch` — final classifications + flagged items for HITL

**Algorithm:**

1. **Run sanity checks** (G10-lite) on each result:
   - **Flag 1:** confidence > 0.85 AND classification = GAP → "high_confidence_gap"
     - *Why:* High confidence suggests strong match, GAP verdict contradicts
   - **Flag 2:** top_match_score < 0.60 AND classification = FIT → "low_score_fit"
     - *Why:* Weak similarity, LLM overconfident on FIT
   - **Flag 3:** route = REVIEW_REQUIRED → "llm_schema_retry_exhausted"
     - *Why:* LLM failed schema validation after max retries
   - **Flag 4:** G11 response_pii_leak detected → "response_pii_leak"
     - *Why:* PII detected in rationale/description

2. **Build flagged_for_review list:**
   - If any flags → add to review queue
   - Never flip classifications; human decides

3. **HITL Checkpoint:**
   - If flagged_count > 0:
     - Publish event to Redis
     - Call LangGraph `interrupt()` → PostgreSQL checkpoints state
     - API routes handle reviewer decisions
   - If flagged_count == 0:
     - Skip directly to completion

4. **On resume** (after human overrides):
   - Merge reviewer decisions into results
   - Apply PII redaction restoration (G2 restore_pii)
   - Build `ValidatedFitmentBatch` with all final classifications
   - Generate CSV export

---

## Thresholds & Configuration

| Parameter | Default | Source | Used In |
|-----------|---------|--------|---------|
| fit_confidence_threshold | 0.85 | ProductConfig | Phase 5 flag detection |
| review_confidence_threshold | 0.60 | ProductConfig | Phase 4 routing decision |
| retrieval_confidence threshold | 0.60 | Phase 2 default | Flag low retrieval confidence |
| retrieval top-K | 5 | Phase 2 code | Qdrant hybrid search |
| matching top-K | 10 | Phase 3 code | Capability search |
| rerank top-K | 3 | Phase 2 code | After cross-encoder |
| pii_redaction_entities | [PERSON, EMAIL, PHONE, CREDIT_CARD, SSN, IP, LOCATION] | G2 config | Phase 1 PII detection |

---

## Phase Dependencies

```
Phase 1 (Ingestion)
    ↓
Phase 2 (RAG) ← Queries Qdrant KB
    ↓
Phase 3 (Matching) ← Searches D365 capabilities
    ↓
Phase 4 (Classification) ← Calls LLM, enforces schema
    ↓
Phase 5 (Validation) ← HITL checkpoint, outputs CSV
```

All phases checkpoint to PostgreSQL after completion. If any phase fails, LangGraph resumes from last checkpoint.

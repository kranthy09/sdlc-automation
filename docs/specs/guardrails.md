# DYNAFIT Guardrails — MVP Specification

> **When to read this file:** Before building any DYNAFIT phase node (Layer 3).
> Read alongside `docs/specs/dynafit.md`. Guardrails are not separate — they are
> built in the same session as the phase node they protect.
>
> This file covers MVP guardrails (9 active) and post-MVP roadmap (5 deferred).
> HITL mandatory.

---

## Design Principle

Guardrails are woven into phase nodes, not bolted on after. Each node is responsible for
calling its guardrail before or after the operation it guards. No guardrail is a standalone
service in the MVP — they are plain Python functions called inline.

**HITL at Phase 5 is non-negotiable.** A batch MUST NOT complete until a human has resolved
every flagged classification.

---

## MVP Guardrail Set

| # | Name | Phase | Where | New libs? |
|---|------|-------|-------|-----------|
| G1-lite | File validator | 1 — Ingestion (pre-parse) | `platform/guardrails/file_validator.py` | None |
| G3-lite | Injection scanner | 1 — Ingestion (post-extract) | `platform/guardrails/injection_scanner.py` | None |
| G2 | PII redactor | 1 — Ingestion (pre-LLM) | `platform/guardrails/pii_redactor.py` | `presidio-analyzer` (regex fallback) |
| G8 | Prompt firewall | 4 — Classification (pre-LLM) | Structural pattern in `prompts/*.j2` | None |
| G9 | Output schema enforcer | 4 — Classification (post-LLM) | Built into `ClassificationResult` + LLM client | None |
| G11 | Response PII scanner | 4 — Classification (post-LLM) | `platform/guardrails/response_pii_scanner.py` | Reuses G2 engine |
| G10-lite | Sanity gate | 5 — Validation (pre-HITL) | `modules/dynafit/guardrails.py` | None |
| HITL | Human review checkpoint | 5 — Validation | `modules/dynafit/nodes/phase5_validation.py` | None |
| Audit | Phase boundary logging | All phases | `platform/observability/logger.py` (existing) | None |

---

## Session A — Platform Guardrail Utilities (build before Layer 3)

These two components extend Layer 2. They go in `platform/` because they are reusable
across all future products. Build in one session before starting any DYNAFIT phase node.

### Files

```
platform/
  schemas/
    guardrails.py              ← FileValidationResult, InjectionScanResult,
                                 PIIEntity, PIIRedactionResult, PIIScanResult
  guardrails/
    __init__.py
    file_validator.py          ← G1-lite
    injection_scanner.py       ← G3-lite
    pii_redactor.py            ← G2 (redact_pii + restore_pii)
    response_pii_scanner.py    ← G11 (scan_response_pii)

tests/unit/
  test_file_validator.py
  test_injection_scanner.py
tests/integration/
  test_pii_guardrails.py
```

---

## G1-lite: File Validator

**File:** `platform/guardrails/file_validator.py`
**Called at:** Top of Phase 1 node, before any bytes touch a parser.

```python
# platform/schemas/guardrails.py
class FileValidationResult(PlatformModel):
    file_hash: str           # SHA-256 of raw bytes (for audit)
    size_bytes: int
    is_valid: bool
    rejection_reason: str | None = None

# platform/guardrails/file_validator.py
def validate_file(file_bytes: bytes, filename: str, max_mb: int = 50) -> FileValidationResult:
    """
    1. detect_format(file_bytes) — raises UnsupportedFormatError if not PDF/DOCX/TXT
    2. Size check: if len(file_bytes) > max_mb * 1024 * 1024 → reject
    3. SHA-256 hash via hashlib.sha256(file_bytes).hexdigest()
    4. Return FileValidationResult
    """
```

**Reuses:** `platform/parsers/format_detector.detect_format()`, `hashlib` (stdlib).
**No new libraries.**

---

## G3-lite: Injection Scanner

**File:** `platform/guardrails/injection_scanner.py`
**Called at:** Phase 1, after text extraction from document, before requirement atomization.

```python
# platform/schemas/guardrails.py
class InjectionScanResult(PlatformModel):
    is_suspicious: bool
    injection_score: float           # 0.0–1.0
    matched_patterns: list[str]
    action: Literal["PASS", "FLAG_FOR_REVIEW", "BLOCK"]

# platform/guardrails/injection_scanner.py
_PATTERNS: list[tuple[str, str]] = [
    ("instruction_override",  r"ignore\s+(?:previous|above|all)\s+instructions"),
    ("role_switch",           r"\byou\s+are\s+now\b"),
    ("act_as",                r"\bact\s+as\b"),
    ("pretend",               r"\bpretend\s+to\s+be\b"),
    ("system_tag",            r"</?system>"),
    ("inst_tag",              r"\[INST\]"),
    ("system_fence",          r"```\s*system"),
    ("new_instructions",      r"new\s+instructions?\s*:"),
    ("base64_payload",        r"(?:[A-Za-z0-9+/]{40,}={0,2})"),
    ("rtl_override",          r"\u202e"),   # Unicode right-to-left override
]

def scan_for_injection(text: str) -> InjectionScanResult:
    """
    Score = matched_count / len(_PATTERNS), clamped [0, 1]
    < 0.15  → PASS
    0.15–0.5 → FLAG_FOR_REVIEW
    ≥ 0.5   → BLOCK
    """
```

**No new libraries.** Uses only `re` (stdlib).

---

## G2: PII Redactor

**File:** `platform/guardrails/pii_redactor.py`
**Called at:** Phase 1, after injection scan, before requirement atomization (pre-LLM).

```python
# platform/schemas/guardrails.py
class PIIEntity(PlatformModel):
    entity_type: str       # "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", etc.
    start: int
    end: int
    score: float
    placeholder: str       # "<PII_PERSON_1>"

class PIIRedactionResult(PlatformModel):
    redacted_text: str
    entities_found: list[PIIEntity]
    entity_count: int
    redaction_map: dict[str, str]  # placeholder → original

# platform/guardrails/pii_redactor.py
def redact_pii(text: str) -> PIIRedactionResult: ...
def restore_pii(redacted_text: str, redaction_map: dict[str, str]) -> str: ...
```

**Detection:** Presidio-analyzer with spaCy NER (`en_core_web_sm`). Regex fallback
(email, phone, SSN, IP, credit card) when presidio is not installed.
**Entities:** PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, IBAN_CODE, IP_ADDRESS, US_SSN, LOCATION.
**Lifecycle:** `pii_redaction_map` stored in `DynafitState`, carried through Phases 2–4.
Phase 5 calls `restore_pii()` in CSV output to produce the final deliverable with original text.
**Thread safety:** Presidio `AnalyzerEngine` singleton uses `threading.Lock` with double-checked locking.

**Library:** `presidio-analyzer>=2.2` in `pyproject.toml` `[ml]` optional deps.

---

## G11: Response PII Scanner

**File:** `platform/guardrails/response_pii_scanner.py`
**Called at:** Phase 4, after LLM response assembly, before sanity checks.

```python
# platform/schemas/guardrails.py
class PIIScanResult(PlatformModel):
    has_pii: bool
    entities_found: list[PIIEntity]
    entity_count: int
    action: Literal["PASS", "FLAG_FOR_REVIEW"]

# platform/guardrails/response_pii_scanner.py
def scan_response_pii(text: str) -> PIIScanResult: ...
```

Scans LLM output fields (`rationale`, `gap_description`, `config_steps`) for leaked/hallucinated PII.
If PII found: adds `G11:` caveat to `ClassificationResult.caveats`. Phase 5 `_check_flags()`
detects this caveat and adds `response_pii_leak` flag → routes to HITL review.
**Never blocks.** Always `FLAG_FOR_REVIEW` — consultant decides.

Reuses the same presidio/regex engine as G2 via module-level import (`from . import pii_redactor as _redactor`).
Must access `_redactor._presidio_available` — never import the flag by name. No additional dependencies.

---

## G8: Prompt Firewall (structural pattern)

**Files:** `modules/dynafit/prompts/classification_v1.j2`, `modules/dynafit/prompts/rationale_v1.j2`
**Enforced in:** Phase 4 node, template loading code.

Rules the Phase 4 node MUST follow:

1. Load templates via `jinja2.Environment(autoescape=True, undefined=jinja2.StrictUndefined)`
2. Check `template_name in ALLOWED_TEMPLATES` before rendering — reject if not in whitelist
3. User content goes ONLY into designated XML-delimited slots:
   ```jinja2
   <requirement_text>{{ requirement_text | e }}</requirement_text>
   ```
4. System instructions are in the template file — NEVER constructed from user data or f-strings
5. Template file header must include: `{# NEVER MODIFY WITHOUT SECURITY REVIEW #}`

**No new library.** Jinja2 already in `pyproject.toml`.

---

## G9: Output Schema Enforcer (built-in)

**No new code.** Already provided by:

- `ClassificationResult` in `platform/schemas/fitment.py` — strict Pydantic v2 model
- `LLMClient.complete()` in `platform/llm/client.py` — tool-use structured output, `max_retries=3`

Phase 4 node responsibility:
```python
# On ValidationError: retry (LLM client handles up to max_retries)
# On exhaustion: set classification=FitLabel.REVIEW_REQUIRED, log WARNING
# Extra fields: stripped silently, log WARNING with field names (not values)
```

---

## G10-lite: Sanity Gate

**File:** `modules/dynafit/guardrails.py`
**Called at:** Start of Phase 5 node, before building `ValidatedFitmentBatch`.

```python
def run_sanity_check(
    result: ClassificationResult,
    match: MatchResult,
) -> list[str]:
    """
    Returns list of flag strings. Non-empty → route result to flagged_for_review.

    Rules:
    1. result.confidence > 0.85 AND result.classification == FitLabel.GAP
       → flag "high_confidence_gap"
       Why: high confidence means strong match — GAP verdict is suspicious.

    2. match.top_composite_score < 0.60 AND result.classification == FitLabel.FIT
       → flag "low_score_fit"
       Why: weak similarity but LLM said FIT — numbers don't support the verdict.

    3. result.route_used == RouteLabel.REVIEW_REQUIRED
       → flag "llm_schema_retry_exhausted"
       Why: LLM failed to produce valid JSON after max retries.

    CRITICAL: never flip result.classification. Only add flags. Human decides.
    """
```

Thresholds (0.85, 0.60) match `ProductConfig.fit_confidence_threshold` and
`ProductConfig.review_confidence_threshold`. Read from config, do not hardcode.

---

## HITL: Human Review Checkpoint

**File:** `modules/dynafit/nodes/phase5_validation.py`
**Mechanism:** LangGraph native `interrupt()` (built into langgraph ≥0.2).

### Flow

```
Phase 5 — first pass:
  for result in all_classification_results:
    flags = run_sanity_check(result, corresponding_match)
    if flags:
      flagged_for_review.append((result, flags))

  if flagged_for_review:
    publish(PhaseStartEvent(phase=5, phase_name="human_review"))   ← Redis
    log.info("hitl_checkpoint", batch_id=..., flagged_count=len(flagged_for_review))
    interrupt({"batch_id": batch_id, "flagged_count": len(flagged_for_review)})
    # ↑ LangGraph freezes here. PostgreSQL checkpoint preserves full state.
    # API layer handles reviewer interactions (Layer 4 concern).

Phase 5 — resume (after all flagged items resolved via API):
  merge human overrides into results
  build ValidatedFitmentBatch(results=..., flagged_for_review=[])
  publish(CompleteEvent(...))
  log.info("batch_complete", batch_id=..., ...)
```

### Existing schemas that make this work

| Schema field | File |
|---|---|
| `ValidatedFitmentBatch.flagged_for_review: list[ClassificationResult]` | `platform/schemas/fitment.py` |
| `PriorFitment.reviewer_override: bool` | `platform/schemas/retrieval.py` |
| `PhaseStartEvent`, `CompleteEvent` | `platform/schemas/events.py` |
| `PostgresStore` — LangGraph checkpoint backend | `platform/storage/postgres.py` |
| `RedisPubSub.publish()` | `platform/storage/redis_pub.py` |

The API endpoints (`GET /batches/{id}/review`, `POST /batches/{id}/review/{atom_id}`) are
Layer 4 work — implement when building `api/routes/`. Phase 5 only calls `interrupt()` and
publishes the event; it does not own the reviewer UI.

---

## Audit Trail (existing structlog — no new code)

Every phase node MUST emit at entry and exit:

```python
log = get_logger(__name__)

# Entry
log.info("phase_start",
    phase=N, batch_id=batch_id,
    input_hash=hashlib.sha256(repr(input).encode()).hexdigest()[:16])

# Exit
log.info("phase_complete",
    phase=N, batch_id=batch_id,
    output_hash=hashlib.sha256(repr(output).encode()).hexdigest()[:16],
    guardrails_triggered=flags_list,
    latency_ms=elapsed)
```

**Never log PII, raw requirement text, or LLM output content** — only hashes, counts, and flag names.

---

## Post-MVP Guardrails (do not build in MVP)

| Guardrail | Purpose | Key libraries | Reason deferred |
|---|---|---|---|
| G4 — Scope fence | Qdrant metadata pre-filter (tenant, module, country, wave) | `qdrant-client` payload filters | Single-tenant MVP; Qdrant already scopes by product_id |
| G5 — KB integrity | SHA-256 hash verification of retrieved chunks vs seed-time hash | `hashlib` (stdlib) | Requires hash-at-seed-time infra |
| G6 — Context token cap | Enforce token budget before LLM prompt construction | `tiktoken` | Easy to add to Phase 2 later |
| G7 — Score bounds validator | Z-score anomaly detection on match scores per batch | `numpy`, `scikit-learn` | Range check absorbed into G10-lite for MVP |
| G12 — Context firewall | NetworkX conflict graph across full batch classifications | `networkx`, `spacy`, `rapidfuzz` | Batch-level cross-req analysis; post-MVP |
| G13 — Export sanitizer | Strip internal metadata, deanonymize PII for final CSV | custom | Add when report export is enhanced |
| G14 — HMAC audit seal | Merkle chain + HMAC-SHA256 tamper-evident audit trail | `hmac` (stdlib) | Full compliance feature; post-MVP |
| RBAC | JWT validation + tenant context via FastAPI dependency injection | `python-jose` | Layer 4 concern |
| Rate limiter | Redis token bucket per tenant (LLM calls + API requests) | `redis` | Layer 4 concern |
| Vault secrets | HashiCorp Vault for API keys, DB creds, audit signing key | `hvac` | Infra/deployment concern |

### OWASP LLM Top 10 Coverage

| OWASP Risk | DYNAFIT Attack Surface | Guardrail(s) |
|---|---|---|
| LLM01: Prompt injection | Malicious text in uploaded docs | G3 (injection scan) + G8 (prompt firewall) |
| LLM02: Sensitive data disclosure | PII in requirements leaks into LLM responses | **G2 (PII redactor) + G11 (response scanner)** + G13 (export sanitizer) |
| LLM03: Supply chain | Poisoned KB documents in Qdrant | G5 (KB integrity) |
| LLM04: Data/model poisoning | Corrupted historical fitments | G5 (KB integrity) + G10 (sanity gate) |
| LLM06: Excessive agency | LLM attempts actions beyond classification | G8 (template-only prompts) + G9 (schema enforcement) |
| LLM07: System prompt leakage | Attacker extracts classification logic | G8 (prompt firewall) + **G11 (response scanner)** |

### Post-MVP Implementation Priority

**Sprint 1 (Weeks 1-2):** G6 (context token cap), RBAC, Rate limiter
**Sprint 2 (Weeks 3-4):** G4 (scope fence), G7 (score validator)
**Sprint 3 (Weeks 5-6):** G5 (KB integrity), G12 (context firewall), G13 (export sanitizer), G14 (audit seal)
**Sprint 4 (Weeks 7-8):** Vault secrets, encryption at rest + mTLS, Grafana alert rules, red team testing

### Cross-Cutting Concerns (post-MVP)

**Observability metrics:** `dynafit_guardrail_triggered{guardrail, phase, action}`, `dynafit_pii_detected{phase, entity_type}`, `dynafit_injection_score{phase}`, `dynafit_classification_confidence{classification}`

**Encryption:** PostgreSQL TDE (pgcrypto), Qdrant disk encryption, Redis in-memory only, API TLS 1.3, internal mTLS, LLM API HTTPS with certificate pinning.

**Secret management:** All API keys, DB credentials, audit signing keys, JWT signing keys via HashiCorp Vault. Never in source code, Docker images, config files, or logs.

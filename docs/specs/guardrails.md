# REQFIT Guardrails — MVP Specification

**Design Principle:** Guardrails woven into phase nodes, not bolted on. Each node calls its guardrail before/after its operation. **HITL at Phase 5 non-negotiable** — batch MUST NOT complete until human resolves every flagged classification.

---

## MVP Guardrail Set (9 Active)

| ID       | Name                    | Phase | Location | Libraries |
|----------|-------------------------|-------|----------|-----------|
| G1-lite  | File validator          | 1     | `platform/guardrails/file_validator.py` | None |
| G3-lite  | Injection scanner       | 1     | `platform/guardrails/injection_scanner.py` | None |
| G2       | PII redactor            | 1     | `platform/guardrails/pii_redactor.py` | `presidio-analyzer` |
| G8       | Prompt firewall         | 4     | `modules/dynafit/prompts/*.j2` | Jinja2 (existing) |
| G9       | Output schema enforcer  | 4     | `platform/llm/client.py` | Pydantic (existing) |
| G11      | Response PII scanner    | 4     | `platform/guardrails/response_pii_scanner.py` | Reuses G2 |
| G10-lite | Sanity gate             | 5     | `modules/dynafit/guardrails.py` | None |
| HITL     | Human review            | 5     | `modules/dynafit/nodes/phase5_validation.py` | LangGraph interrupt() |
| Audit    | Phase boundary logging  | All   | `platform/observability/logger.py` | structlog (existing) |

---

## Key Guardrails

**G1-lite (File Validator):** Detect format (PDF/DOCX/TXT only), size check (max 50 MB), SHA-256 hash.

**G3-lite (Injection Scanner):** Regex patterns for prompt injection (instruction_override, role_switch, act_as, system tags, base64, RTL override). Score = matched_count/10. <0.15=PASS, 0.15–0.5=FLAG, ≥0.5=BLOCK.

**G2 (PII Redactor):** Presidio (spaCy fallback regex) detects PERSON, EMAIL, PHONE, CREDIT_CARD, SSN, IP, LOCATION. Stores `pii_redaction_map` in DynafitState; Phase 5 restores in final CSV.

**G8 (Prompt Firewall):** Jinja2 templates only. User content in XML slots only (`<requirement>{{ text | e }}</requirement>`). Template whitelist enforced. No f-strings. Header: `{# NEVER MODIFY WITHOUT SECURITY REVIEW #}`

**G9 (Output Schema):** `ClassificationResult` (strict Pydantic). LLMClient.complete() tool-use, max_retries=3. On exhaustion: classification=REVIEW_REQUIRED.

**G11 (Response PII Scanner):** Scans LLM output (rationale, gap_description) for leaked PII. Never blocks, always FLAG_FOR_REVIEW. Reuses G2 engine.

**G10-lite (Sanity Gate):** Flags when:
- confidence > 0.85 AND classification = GAP → "high_confidence_gap"
- top_score < 0.60 AND classification = FIT → "low_score_fit"
- route = REVIEW_REQUIRED → "llm_schema_retry_exhausted"

Thresholds from `ProductConfig.fit_confidence_threshold` (0.85), `review_confidence_threshold` (0.60).

**HITL (Phase 5 Interrupt):** LangGraph `interrupt()` freezes batch state at PostgreSQL checkpoint. API layer handles reviewer decisions. On resume: merge overrides, complete batch.

**Audit Trail:** All phases log entry/exit with phase, batch_id, hashes, flags, latency. **Never log PII, raw text, or LLM content** — hashes and counts only.

---

## Phase 5 HITL Flow

```
1. Run sanity checks on all classifications
2. Collect flagged results → flagged_for_review list
3. If non-empty:
   - publish(PhaseStartEvent(phase=5))
   - interrupt({batch_id, flagged_count})
   → PostgreSQL checkpoint preserves state
   → API routes handle /review endpoint
4. On resume (after human decisions):
   - merge overrides into results
   - build ValidatedFitmentBatch(results=..., flagged=[])
   - publish(CompleteEvent(...))
   - batch complete
```

**Existing schemas supporting this:**
- `ValidatedFitmentBatch.flagged_for_review` (platform/schemas/fitment.py)
- `PriorFitment.reviewer_override` (platform/schemas/retrieval.py)
- `PhaseStartEvent`, `CompleteEvent` (platform/schemas/events.py)
- `PostgresStore` checkpoint backend (platform/storage/postgres.py)
- `RedisPubSub.publish()` (platform/storage/redis_pub.py)

---

## Post-MVP Guardrails (Deferred)

G4 (Scope fence), G5 (KB integrity), G6 (Context token cap), G7 (Score bounds), G12 (Context firewall), G13 (Export sanitizer), G14 (HMAC seal), RBAC, Rate limiter, Vault secrets.

**OWASP LLM Top 10 coverage:**
- LLM01 (Prompt injection): G3 + G8
- LLM02 (Sensitive disclosure): **G2 + G11 + G13**
- LLM03 (Supply chain): G5
- LLM04 (Data poisoning): G5 + G10
- LLM06 (Excessive agency): G8 + G9
- LLM07 (System prompt leak): G8 + **G11**

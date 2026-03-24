"""
G2: PII Redactor — detect and redact PII before text reaches any LLM call.

Called at Phase 1, after injection scanning, before requirement atomization.
Uses presidio-analyzer with spaCy NER backend (en_core_web_sm).

Design:
  redact_pii(text)  → PIIRedactionResult  (text with placeholders, mapping for restore)
  restore_pii(text, mapping) → str         (reverse placeholders back to originals)

The redaction_map travels through DynafitState so Phase 5 can restore originals
in the final CSV output after human review.

Fallback: If presidio-analyzer is not installed (dev/CI without [ml] extras),
a regex-only fallback covers email and phone patterns. This keeps unit tests
runnable without heavy deps.
"""

from __future__ import annotations

import re
import threading
from collections import Counter

from platform.observability.logger import get_logger
from platform.schemas.guardrails import PIIEntity, PIIRedactionResult

__all__ = ["redact_pii", "restore_pii"]

log = get_logger(__name__)

# --- Entity types to detect (ordered by priority) ---
_SUPPORTED_ENTITIES: list[str] = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "US_SSN",
    "LOCATION",
]

_MIN_SCORE_THRESHOLD: float = 0.4

# --- Regex fallback patterns (when presidio is unavailable) ---
_FALLBACK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL_ADDRESS", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")),
    ("PHONE_NUMBER", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("US_SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("IP_ADDRESS", re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")),
]

# --- Presidio analyzer (lazy-loaded singleton, thread-safe) ---
_analyzer = None
_presidio_available: bool | None = None
_analyzer_lock = threading.Lock()


def _get_analyzer():  # type: ignore[no-untyped-def]
    """Lazy-load presidio AnalyzerEngine with spaCy NER backend."""
    global _analyzer, _presidio_available
    if _presidio_available is not None:
        return _analyzer

    with _analyzer_lock:
        # Double-check after acquiring lock
        if _presidio_available is not None:
            return _analyzer

        try:
            from presidio_analyzer import AnalyzerEngine  # type: ignore[import-untyped]
            from presidio_analyzer.nlp_engine import NlpEngineProvider  # type: ignore[import-untyped]

            provider = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            })
            _analyzer = AnalyzerEngine(nlp_engine=provider.create_engine())
            _presidio_available = True
            log.info("pii_redactor_init", backend="presidio", model="en_core_web_sm")
        except (ImportError, OSError):
            _presidio_available = False
            log.warning("pii_redactor_init", backend="regex_fallback", reason="presidio not available")

    return _analyzer


def _detect_with_presidio(text: str, prefix: str = "") -> list[PIIEntity]:
    """Detect PII entities using presidio-analyzer."""
    analyzer = _get_analyzer()
    if analyzer is None:
        return []

    results = analyzer.analyze(
        text=text,
        entities=_SUPPORTED_ENTITIES,
        language="en",
        score_threshold=_MIN_SCORE_THRESHOLD,
    )

    # Sort by start position (earliest first), then by score descending for overlaps
    results = sorted(results, key=lambda r: (r.start, -r.score))

    # Remove overlapping detections (keep highest-scoring)
    filtered = []
    last_end = -1
    for r in results:
        if r.start >= last_end:
            filtered.append(r)
            last_end = r.end

    counter: Counter[str] = Counter()
    entities = []
    for r in filtered:
        counter[r.entity_type] += 1
        entities.append(
            PIIEntity(
                entity_type=r.entity_type,
                start=r.start,
                end=r.end,
                score=round(r.score, 3),
                placeholder=f"<PII_{prefix}{r.entity_type}_{counter[r.entity_type]}>",
            )
        )
    return entities


def _detect_with_regex(text: str, prefix: str = "") -> list[PIIEntity]:
    """Fallback PII detection using regex patterns."""
    all_matches: list[tuple[str, int, int]] = []
    for entity_type, pattern in _FALLBACK_PATTERNS:
        for match in pattern.finditer(text):
            all_matches.append((entity_type, match.start(), match.end()))

    # Sort by position
    all_matches.sort(key=lambda m: (m[1], -m[2]))

    # Remove overlaps
    filtered = []
    last_end = -1
    for entity_type, start, end in all_matches:
        if start >= last_end:
            filtered.append((entity_type, start, end))
            last_end = end

    counter: Counter[str] = Counter()
    entities = []
    for entity_type, start, end in filtered:
        counter[entity_type] += 1
        entities.append(
            PIIEntity(
                entity_type=entity_type,
                start=start,
                end=end,
                score=0.85,  # fixed confidence for regex matches
                placeholder=f"<PII_{prefix}{entity_type}_{counter[entity_type]}>",
            )
        )
    return entities


def redact_pii(text: str, *, prefix: str = "") -> PIIRedactionResult:
    """Detect and redact PII entities in text, replacing with placeholders.

    Args:
        text: Raw text to scan (typically extracted document content).
        prefix: Optional prefix for placeholders to avoid collisions when
            redacting multiple texts (e.g. ``prefix="T1_"`` produces
            ``<PII_T1_PERSON_1>`` instead of ``<PII_PERSON_1>``).

    Returns:
        PIIRedactionResult with redacted text, entity list, and a mapping
        that can be passed to restore_pii() to reverse the redaction.
    """
    if not text.strip():
        return PIIRedactionResult(
            redacted_text=text,
            entities_found=[],
            entity_count=0,
            redaction_map={},
        )

    # Try presidio first, fall back to regex
    _get_analyzer()
    if _presidio_available:
        entities = _detect_with_presidio(text, prefix)
    else:
        entities = _detect_with_regex(text, prefix)

    if not entities:
        log.debug("pii_redactor_result", entity_count=0, action="PASS")
        return PIIRedactionResult(
            redacted_text=text,
            entities_found=[],
            entity_count=0,
            redaction_map={},
        )

    # Build redacted text by replacing entities from end to start (preserves offsets)
    redacted = text
    redaction_map: dict[str, str] = {}
    for entity in reversed(entities):
        original = text[entity.start : entity.end]
        redaction_map[entity.placeholder] = original
        redacted = redacted[: entity.start] + entity.placeholder + redacted[entity.end :]

    log.info(
        "pii_redactor_result",
        entity_count=len(entities),
        entity_types=[e.entity_type for e in entities],
        action="REDACTED",
    )

    return PIIRedactionResult(
        redacted_text=redacted,
        entities_found=entities,
        entity_count=len(entities),
        redaction_map=redaction_map,
    )


def restore_pii(redacted_text: str, redaction_map: dict[str, str]) -> str:
    """Reverse PII redaction — replace placeholders with original values.

    Called at Phase 5 (CSV output) after human review, to produce the final
    deliverable with original requirement text intact.

    Args:
        redacted_text: Text containing <PII_*> placeholders.
        redaction_map: Mapping from placeholder to original value.

    Returns:
        Text with all placeholders replaced by their original values.
    """
    result = redacted_text
    for placeholder, original in redaction_map.items():
        result = result.replace(placeholder, original)
    return result

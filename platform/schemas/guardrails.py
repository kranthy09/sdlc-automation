"""
Guardrail result schemas.

Produced by:
  G1-lite  platform/guardrails/file_validator.py       → FileValidationResult
  G3-lite  platform/guardrails/injection_scanner.py    → InjectionScanResult
  G2       platform/guardrails/pii_redactor.py         → PIIRedactionResult
  G11      platform/guardrails/response_pii_scanner.py → PIIScanResult

Consumed by:
  Phase 1 ingestion node — validates, scans, and redacts PII before parsing.
  Phase 4 classification node — scans LLM responses for leaked PII.
"""

from __future__ import annotations

from typing import Literal

from .base import PlatformModel


class FileValidationResult(PlatformModel):
    """Output of G1-lite file validation (format + size gate).

    file_hash is always populated — even on rejection — to give the audit
    trail a reference for the rejected bytes.
    """

    file_hash: str  # SHA-256 hex digest of raw bytes
    size_bytes: int
    is_valid: bool
    rejection_reason: str | None = None


class InjectionScanResult(PlatformModel):
    """Output of G3-lite injection scan (regex pattern matching).

    injection_score = matched_pattern_count / total_patterns, clamped [0, 1].
    matched_patterns contains pattern names (not raw match strings) to avoid
    logging attacker-controlled content.
    """

    is_suspicious: bool  # True if any pattern matched
    injection_score: float  # 0.0–1.0
    matched_patterns: list[str]  # pattern names, e.g. ["instruction_override"]
    action: Literal["PASS", "FLAG_FOR_REVIEW", "BLOCK"]


class PIIEntity(PlatformModel):
    """A single detected PII entity with its location and replacement placeholder."""

    entity_type: str  # e.g. "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"
    start: int  # char offset in original text
    end: int  # char offset in original text
    score: float  # 0.0–1.0 confidence from analyzer
    placeholder: str  # e.g. "<PII_PERSON_1>"


class PIIRedactionResult(PlatformModel):
    """Output of G2 PII redactor — text with PII replaced by placeholders.

    The redaction_map enables restore_pii() to reverse the transformation
    after human review (Phase 5). Map keys are placeholders, values are
    original text fragments.
    """

    redacted_text: str
    entities_found: list[PIIEntity]
    entity_count: int
    redaction_map: dict[str, str]  # {"<PII_PERSON_1>": "John Doe", ...}


class PIIScanResult(PlatformModel):
    """Output of G11 response PII scanner — detects PII in LLM output.

    action follows the same convention as InjectionScanResult:
      PASS           — no PII detected
      FLAG_FOR_REVIEW — PII found, route to HITL
    """

    has_pii: bool
    entities_found: list[PIIEntity]
    entity_count: int
    action: Literal["PASS", "FLAG_FOR_REVIEW"]

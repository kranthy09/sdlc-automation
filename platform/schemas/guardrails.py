"""
Guardrail result schemas — FileValidationResult and InjectionScanResult.

Produced by:
  G1-lite  platform/guardrails/file_validator.py     → FileValidationResult
  G3-lite  platform/guardrails/injection_scanner.py  → InjectionScanResult

Consumed by:
  Phase 1 ingestion node — validates and scans before any requirement is parsed.
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

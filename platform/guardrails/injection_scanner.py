"""
G3-lite: Injection Scanner — regex-only prompt injection detection.

Called at Phase 1, after text extraction from the document, before requirement
atomization.  No ML model — stdlib re only.  Zero new dependencies.

Scoring:
  injection_score = matched_pattern_count / total_patterns
  < 0.15  → PASS
  0.15–0.5 → FLAG_FOR_REVIEW (Phase 1 proceeds; batch flagged for human review)
  ≥ 0.5   → BLOCK (Phase 1 raises immediately; document quarantined)

matched_patterns logs pattern *names* only — never the raw matched text — to
prevent attacker-controlled content from appearing in structured logs.
"""

from __future__ import annotations

import re

from platform.observability.logger import get_logger
from platform.schemas.guardrails import InjectionScanResult

__all__ = ["scan_for_injection"]

log = get_logger(__name__)

# (name, pattern) — name appears in matched_patterns and log output
_PATTERNS: list[tuple[str, str]] = [
    ("instruction_override", r"ignore\s+(?:previous|above|all)\s+instructions"),
    ("role_switch", r"\byou\s+are\s+now\b"),
    ("act_as", r"\bact\s+as\b"),
    ("pretend", r"\bpretend\s+to\s+be\b"),
    ("system_tag", r"</?system>"),
    ("inst_tag", r"\[INST\]"),
    ("system_fence", r"```\s*system"),
    ("new_instructions", r"new\s+instructions?\s*:"),
    ("base64_payload", r"[A-Za-z0-9+/]{40,}={0,2}"),
    ("rtl_override", "\u202e"),  # Unicode right-to-left override character
]

_COMPILED: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pattern, re.IGNORECASE | re.DOTALL)) for name, pattern in _PATTERNS
]

_PASS_THRESHOLD: float = 0.15
_BLOCK_THRESHOLD: float = 0.5


def scan_for_injection(text: str) -> InjectionScanResult:
    """Scan *text* for prompt injection indicators using regex pattern matching.

    Args:
        text: Extracted document text (plain string, post-parse).

    Returns:
        InjectionScanResult with action, score, and matched pattern names.
    """
    matched: list[str] = [name for name, pattern in _COMPILED if pattern.search(text)]
    score = len(matched) / len(_PATTERNS)

    if score >= _BLOCK_THRESHOLD:
        action: str = "BLOCK"
    elif score >= _PASS_THRESHOLD:
        action = "FLAG_FOR_REVIEW"
    else:
        action = "PASS"

    log.debug(
        "injection_scanner_result",
        action=action,
        score=score,
        matched_count=len(matched),
        pattern_names=matched,
    )

    return InjectionScanResult(
        is_suspicious=bool(matched),
        injection_score=score,
        matched_patterns=matched,
        action=action,
    )

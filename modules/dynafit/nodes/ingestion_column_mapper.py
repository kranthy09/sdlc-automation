"""Header column synonym resolution for Phase 1 ingestion.

Loads header_synonyms.yaml and maps raw table column headers to canonical
field names using a three-tier strategy:

  Tier 1 — Exact O(1) dict lookup          (confidence 1.0)
  Tier 2 — RapidFuzz token_set_ratio > 70  (confidence 0.7–0.9)
  Tier 3 — spaCy en_core_web_lg similarity > 0.65  (confidence 0.65–0.95)

Each resolved header returns a ColumnMappingResult carrying the canonical
name, confidence score, and which tier resolved it, enabling downstream
quality gates to flag low-confidence mappings.

Complexity of _map_column_to_canonical:
  Tier 1: O(1) dict lookup
  Tier 2: O(k_total) single rapidfuzz C-call (k_total ≈ 85, constant)
  Tier 3: O(C) spaCy similarity calls (C = number of canonicals, ≤ 10)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from platform.observability.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# ColumnMappingResult — audit trail for every header resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnMappingResult:
    """Result of mapping one raw column header to a canonical field name.

    Attributes:
        canonical:       Resolved canonical field name, or None if unmatched.
        original_header: The raw header string as it appeared in the document.
        confidence:      Resolution confidence in [0.0, 1.0].
        tier_used:       Which resolution tier produced this result.
    """

    canonical: str | None
    original_header: str
    confidence: float
    tier_used: Literal["exact", "fuzzy", "nlp", "unmatched"]


# ---------------------------------------------------------------------------
# Header synonym map  (header_synonyms.yaml, same directory as this pkg)
# ---------------------------------------------------------------------------

_SYNONYMS_PATH: Path = Path(__file__).parent.parent / "header_synonyms.yaml"

# {canonical: [terms]}  — forward map, same shape as YAML
_SYNONYMS_CACHE: dict[str, list[str]] | None = None
# {term: canonical}  — inverted map built once for O(1) exact lookup
_INVERSE_LOOKUP: dict[str, str] | None = None
# Flat list of all terms — passed to rapidfuzz.process.extractOne
_ALL_TERMS: list[str] | None = None

_synonyms_lock = threading.Lock()


def _load_synonyms() -> tuple[dict[str, list[str]], dict[str, str], list[str]]:
    """Lazy-load header_synonyms.yaml.

    Returns (forward_map, inverse_lookup, all_terms).

    Three structures are built in one pass at first call and cached:
      forward_map:    {canonical: [terms]}  — original shape (kept for callers)
      inverse_lookup: {term: canonical}     — O(1) exact match
      all_terms:      flat list of all terms — passed to extractOne
    """
    global _SYNONYMS_CACHE, _INVERSE_LOOKUP, _ALL_TERMS
    if _SYNONYMS_CACHE is None:
        with _synonyms_lock:
            if _SYNONYMS_CACHE is None:
                with _SYNONYMS_PATH.open(encoding="utf-8") as fh:
                    raw: dict[str, Any] = yaml.safe_load(fh)

                forward: dict[str, list[str]] = {}
                inverse: dict[str, str] = {}

                for canonical, lang_map in raw.items():
                    terms: list[str] = []
                    if isinstance(lang_map, dict):
                        for term_list in lang_map.values():
                            if isinstance(term_list, list):
                                terms.extend(
                                    t.strip().lower() for t in term_list
                                )
                    elif isinstance(lang_map, list):
                        terms.extend(t.strip().lower() for t in lang_map)

                    forward[canonical] = terms
                    for term in terms:
                        # First canonical wins on collision (YAML order)
                        inverse.setdefault(term, canonical)

                _SYNONYMS_CACHE = forward
                _INVERSE_LOOKUP = inverse
                _ALL_TERMS = list(inverse.keys())

    return (  # type: ignore[return-value]
        _SYNONYMS_CACHE,
        _INVERSE_LOOKUP,
        _ALL_TERMS,
    )


# ---------------------------------------------------------------------------
# spaCy lazy loader + canonical docs cache (Tier 3)
# ---------------------------------------------------------------------------

_spacy_nlp: Any = None
_spacy_unavailable: bool = False
_spacy_lock = threading.Lock()


def _load_spacy_for_mapper() -> bool:
    """Lazy-load en_core_web_lg.

    Returns True if the model with word vectors is available.
    """
    global _spacy_nlp, _spacy_unavailable
    if _spacy_unavailable:
        return False
    if _spacy_nlp is None:
        with _spacy_lock:
            if _spacy_nlp is None and not _spacy_unavailable:
                try:
                    import spacy  # noqa: PLC0415

                    model = spacy.load("en_core_web_lg")
                    # en_core_web_sm has zero vectors — similarity → 0
                    if model.vocab.vectors.shape[0] == 0:
                        log.warning(
                            "spacy_no_vectors_mapper",
                            model="en_core_web_lg",
                        )
                        _spacy_unavailable = True
                        return False
                    _spacy_nlp = model
                except Exception as exc:
                    log.warning("spacy_load_failed_mapper", error=str(exc))
                    _spacy_unavailable = True
                    return False
    return not _spacy_unavailable


# {canonical: spacy.Doc built from representative English synonyms}
_CANONICAL_DOCS: dict[str, Any] | None = None
_canonical_docs_lock = threading.Lock()


def _get_canonical_docs() -> dict[str, Any]:
    """Build one spacy.Doc per canonical from its first 3 English synonyms.

    Called only after _load_spacy_for_mapper() returns True.
    The forward synonym map is iterated in YAML order; English terms are listed
    first in the YAML file so the first 3 terms per canonical are English.
    """
    global _CANONICAL_DOCS
    if _CANONICAL_DOCS is None:
        with _canonical_docs_lock:
            if _CANONICAL_DOCS is None:
                forward, _, _ = _load_synonyms()
                docs: dict[str, Any] = {}
                for canonical, terms in forward.items():
                    # Take up to first 3 terms (English, per YAML ordering)
                    phrase = " ".join(t for t in terms[:3] if t)
                    docs[canonical] = _spacy_nlp(phrase)
                _CANONICAL_DOCS = docs
    return _CANONICAL_DOCS


# ---------------------------------------------------------------------------
# Core resolution function
# ---------------------------------------------------------------------------


def _map_column_to_canonical(header: str) -> ColumnMappingResult:
    """Map one raw column header to a canonical field name.

    Returns a ColumnMappingResult with the canonical name (or None),
    confidence, and which resolution tier produced the result.

    Three-tier resolution (spec §Phase1 Sub-step D):
      1. Exact lowercase match      → O(1) dict lookup, confidence 1.0
      2. rapidfuzz token_set_ratio > 70 → single C-call, proportional
      3. spaCy en_core_web_lg similarity > 0.65 → semantic fallback
      4. No match                   → (None, 0.0, "unmatched")
    """
    _, inverse, all_terms = _load_synonyms()
    h_lower = header.strip().lower()

    # Tier 1 — O(1) dict lookup
    if h_lower in inverse:
        return ColumnMappingResult(
            canonical=inverse[h_lower],
            original_header=header,
            confidence=1.0,
            tier_used="exact",
        )

    # Tier 2 — single rapidfuzz C-call over the flat terms list
    try:
        from rapidfuzz import fuzz, process  # noqa: PLC0415

        match = process.extractOne(
            h_lower,
            all_terms,
            scorer=fuzz.token_set_ratio,
        )
        if match is not None and match[1] > 70:
            return ColumnMappingResult(
                canonical=inverse[match[0]],
                original_header=header,
                confidence=round(match[1] / 100.0, 3),
                tier_used="fuzzy",
            )
    except ImportError:
        pass

    # Tier 3 — spaCy vector similarity (semantic fallback)
    if _load_spacy_for_mapper():
        try:
            canonical_docs = _get_canonical_docs()
            header_doc = _spacy_nlp(header.strip())
            best_score, best_canonical = 0.0, None
            for canonical, cdoc in canonical_docs.items():
                score = header_doc.similarity(cdoc)
                if score > best_score:
                    best_score, best_canonical = score, canonical
            if best_canonical is not None and best_score > 0.65:
                return ColumnMappingResult(
                    canonical=best_canonical,
                    original_header=header,
                    confidence=round(best_score, 3),
                    tier_used="nlp",
                )
        except Exception:
            pass  # spaCy failure is never fatal — fall through to unmatched

    return ColumnMappingResult(
        canonical=None,
        original_header=header,
        confidence=0.0,
        tier_used="unmatched",
    )


# ---------------------------------------------------------------------------
# Table row resolution
# ---------------------------------------------------------------------------


def _map_table_rows_to_canonical(
    tables: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Resolve raw table column names to canonical fields.

    Drops the entire table (returns []) if no requirement_text column is found.
    Drops individual rows that have no requirement_text value after mapping.

    Multi-table support: collects headers from ALL rows (not just the first)
    so that documents with multiple tables having different schemas are handled
    correctly — each table's columns participate in the canonical mapping.
    """
    if not tables:
        return []

    # Collect headers from ALL rows — handles multi-table documents where
    # different pages have different column schemas in the same flat list.
    all_keys: list[str] = list({k for row in tables for k in row.keys()})

    column_map: dict[str, str] = {}  # canonical → original_key
    audit: dict[str, dict[str, Any]] = {}

    for original_key in all_keys:
        result = _map_column_to_canonical(original_key)
        audit[original_key] = {
            "canonical": result.canonical,
            "confidence": result.confidence,
            "tier": result.tier_used,
        }
        if result.canonical and result.canonical not in column_map:
            column_map[result.canonical] = original_key
            if result.tier_used != "exact" and result.confidence < 0.75:
                log.warning(
                    "column_mapping_low_confidence",
                    header=original_key,
                    canonical=result.canonical,
                    confidence=result.confidence,
                    tier=result.tier_used,
                )

    log.debug("column_mapping_audit", audit=audit)

    if "requirement_text" not in column_map:
        log.warning("ingestion_no_requirement_column", columns=all_keys)
        return []

    resolved: list[dict[str, str]] = []
    for row in tables:
        mapped = {
            canonical: row[orig_key]
            for canonical, orig_key in column_map.items()
            if orig_key in row and row[orig_key].strip()
        }
        if "requirement_text" in mapped:
            resolved.append(mapped)
    return resolved

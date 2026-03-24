"""Header column synonym resolution for Phase 1 ingestion.

Loads header_synonyms.yaml and maps raw table column headers to canonical
field names using exact match + optional rapidfuzz fallback.

Complexity of _map_column_to_canonical:
  Before: exact O(k_total) Python loop + fuzzy nested-loop O(C_canon × T_per_canon)
  After:  exact O(1) dict lookup  + fuzzy single rapidfuzz.process.extractOne C-call
where k_total ≈ 85 total synonym terms (constant).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

from platform.observability.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Header column synonym map  (header_synonyms.yaml, same directory as this pkg)
# ---------------------------------------------------------------------------

_SYNONYMS_PATH: Path = Path(__file__).parent.parent / "header_synonyms.yaml"

# {canonical: [terms]}  — forward map, same shape as before
_SYNONYMS_CACHE: dict[str, list[str]] | None = None
# {term: canonical}  — inverted map built once at load time for O(1) exact lookup
_INVERSE_LOOKUP: dict[str, str] | None = None
# Flat list of all terms — passed to rapidfuzz.process.extractOne (C implementation)
_ALL_TERMS: list[str] | None = None

_synonyms_lock = threading.Lock()


def _load_synonyms() -> tuple[dict[str, list[str]], dict[str, str], list[str]]:
    """Lazy-load header_synonyms.yaml.

    Returns (forward_map, inverse_lookup, all_terms).

    Three structures are built in one pass at first call and cached:
      forward_map:     {canonical: [terms]}  — original shape (kept for callers)
      inverse_lookup:  {term: canonical}     — O(1) exact match
      all_terms:       flat list of all terms — passed to rapidfuzz.process.extractOne
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
                                terms.extend(t.strip().lower() for t in term_list)
                    elif isinstance(lang_map, list):
                        terms.extend(t.strip().lower() for t in lang_map)

                    forward[canonical] = terms
                    for term in terms:
                        # First canonical wins on collision (deterministic YAML order)
                        inverse.setdefault(term, canonical)

                _SYNONYMS_CACHE = forward
                _INVERSE_LOOKUP = inverse
                _ALL_TERMS = list(inverse.keys())

    return _SYNONYMS_CACHE, _INVERSE_LOOKUP, _ALL_TERMS  # type: ignore[return-value]


def _map_column_to_canonical(header: str) -> tuple[str | None, float]:
    """Map one raw column header to a canonical field name.

    Returns (canonical_name, confidence) or (None, 0.0).

    Three-tier resolution (spec §Phase1 Sub-step D):
      1. Exact lowercase match  → O(1) dict lookup, confidence 1.0
      2. rapidfuzz.process.extractOne > 70 → single C-call, confidence proportional
      3. No match               → (None, 0.0)

    Complexity: O(1) for exact; O(k_total) in C for fuzzy (k_total ≈ 85, constant).
    Previously the fuzzy path ran a nested Python loop over all canonicals × terms.
    """
    _, inverse, all_terms = _load_synonyms()
    h_lower = header.strip().lower()

    # Tier 1 — O(1) dict lookup (replaces linear Python scan)
    if h_lower in inverse:
        return inverse[h_lower], 1.0

    # Tier 2 — single rapidfuzz C-call over the flat terms list
    try:
        from rapidfuzz import process, fuzz  # noqa: PLC0415

        match = process.extractOne(
            h_lower,
            all_terms,
            scorer=fuzz.token_set_ratio,
        )
        if match is not None and match[1] > 70:
            canonical = inverse[match[0]]
            return canonical, match[1] / 100.0
    except ImportError:
        pass

    return None, 0.0


def _map_table_rows_to_canonical(
    tables: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Resolve raw table column names to canonical fields.

    Drops the entire table (returns []) if no requirement_text column is found.
    Drops individual rows that have no requirement_text value after mapping.
    """
    if not tables:
        return []

    all_keys = list(tables[0].keys())
    column_map: dict[str, str] = {}  # canonical → original_key

    for original_key in all_keys:
        canonical, _ = _map_column_to_canonical(original_key)
        if canonical and canonical not in column_map:
            column_map[canonical] = original_key

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

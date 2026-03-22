"""Header column synonym resolution for Phase 1 ingestion.

Loads header_synonyms.yaml and maps raw table column headers to canonical
field names using exact match + optional rapidfuzz fallback.
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
_SYNONYMS_CACHE: dict[str, list[str]] | None = None
_synonyms_lock = threading.Lock()


def _load_synonyms() -> dict[str, list[str]]:
    """Lazy-load and flatten header_synonyms.yaml into {canonical: [terms]}."""
    global _SYNONYMS_CACHE
    if _SYNONYMS_CACHE is None:
        with _synonyms_lock:
            if _SYNONYMS_CACHE is None:
                with _SYNONYMS_PATH.open(encoding="utf-8") as fh:
                    raw: dict[str, Any] = yaml.safe_load(fh)
                cache: dict[str, list[str]] = {}
                for canonical, lang_map in raw.items():
                    terms: list[str] = []
                    if isinstance(lang_map, dict):
                        for term_list in lang_map.values():
                            if isinstance(term_list, list):
                                terms.extend(t.strip().lower() for t in term_list)
                    elif isinstance(lang_map, list):
                        terms.extend(t.strip().lower() for t in lang_map)
                    cache[canonical] = terms
                _SYNONYMS_CACHE = cache
    return _SYNONYMS_CACHE


def _map_column_to_canonical(header: str) -> tuple[str | None, float]:
    """Map one raw column header to a canonical field name.

    Returns (canonical_name, confidence) or (None, 0.0).

    Three-tier resolution (spec §Phase1 Sub-step D):
      1. Exact lowercase match  → confidence 1.0
      2. rapidfuzz token_set_ratio > 70 → confidence proportional
      3. No match               → (None, 0.0)
    """
    synonyms = _load_synonyms()
    h_lower = header.strip().lower()

    for canonical, terms in synonyms.items():
        if h_lower in terms:
            return canonical, 1.0

    try:
        from rapidfuzz.fuzz import token_set_ratio  # noqa: PLC0415

        best_canonical: str | None = None
        best_score: float = 0.0
        for canonical, terms in synonyms.items():
            for term in terms:
                score = token_set_ratio(h_lower, term) / 100.0
                if score > best_score:
                    best_score = score
                    best_canonical = canonical
        if best_score > 0.70:
            return best_canonical, best_score
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

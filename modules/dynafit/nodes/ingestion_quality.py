"""Quality scoring and gating for Phase 1 ingestion.

Contains:
- MoSCoW priority enrichment (keyword-based)
- Entity hint extraction (spaCy NER, best-effort)
- Specificity scoring (ambiguity detection)
- Completeness scoring (per-module keyword presence)
- Cross-field schema consistency checks
- Quality gate application (_apply_quality_gates)

Tokenization strategy
---------------------
Each atom previously triggered 4 independent re.findall / .lower() passes
(one per scoring function).  _apply_quality_gates now calls _tokenize_text()
once per atom and threads the resulting _TextTokens through all scorers,
reducing redundant work from O(4 × a × w) to O(a × w).

_score_specificity and _score_completeness keep their original public
signatures as thin wrappers so existing tests and callers are unaffected.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, Literal

from platform.schemas.requirement import FlaggedAtom, RawUpload, ValidatedAtom

from .ingestion_atomiser import _MODULE_SET, _ClassifiedRequirement

# ---------------------------------------------------------------------------
# Priority enrichment — keyword MoSCoW, no LLM needed
# ---------------------------------------------------------------------------

_MUST_RE = re.compile(r"\b(must|shall|required|mandatory|critical|compulsory)\b", re.IGNORECASE)
_COULD_RE = re.compile(r"\b(could|nice.to.have|optional|desirable|wish)\b", re.IGNORECASE)


def _infer_moscow_priority(text: str) -> Literal["MUST", "SHOULD", "COULD"]:
    if _MUST_RE.search(text):
        return "MUST"
    if _COULD_RE.search(text):
        return "COULD"
    return "SHOULD"


# ---------------------------------------------------------------------------
# Entity hint extraction — spaCy NER (best-effort, lazy load)
# ---------------------------------------------------------------------------

_spacy_nlp: Any = None
_spacy_unavailable: bool = False
_spacy_lock = threading.Lock()


def _load_spacy() -> bool:
    """Ensure spaCy model is loaded. Returns True if available."""
    global _spacy_nlp, _spacy_unavailable
    if _spacy_unavailable:
        return False
    if _spacy_nlp is None:
        with _spacy_lock:
            if _spacy_nlp is None and not _spacy_unavailable:
                try:
                    import spacy  # noqa: PLC0415

                    _spacy_nlp = spacy.load("en_core_web_lg")
                except Exception as exc:
                    from platform.observability.logger import get_logger  # noqa: PLC0415

                    get_logger(__name__).warning("spacy_load_failed", error=str(exc))
                    _spacy_unavailable = True
                    return False
    return not _spacy_unavailable


def _extract_entity_hints(text: str) -> list[str]:
    """Return NER entity strings from text. Returns [] if spaCy is not installed."""
    if not _load_spacy():
        return []
    try:
        doc = _spacy_nlp(text[:512])
        return list({ent.text.lower() for ent in doc.ents if len(ent.text) > 2})
    except Exception:
        return []


def _extract_entity_hints_batch(texts: list[str]) -> list[list[str]]:
    """Batch NER using spaCy pipe() — 3-5x faster than per-text calls.

    Returns a list of entity-hint lists, one per input text.
    Falls back to empty lists if spaCy is unavailable.
    """
    if not texts or not _load_spacy():
        return [[] for _ in texts]
    try:
        results: list[list[str]] = []
        for doc in _spacy_nlp.pipe([t[:512] for t in texts]):
            results.append(list({ent.text.lower() for ent in doc.ents if len(ent.text) > 2}))
        return results
    except Exception:
        return [[] for _ in texts]


# ---------------------------------------------------------------------------
# Token cache — computed once per atom, shared across all scorers
# ---------------------------------------------------------------------------

_TOKENIZE_RE = re.compile(r"\b\w+\b")


@dataclass(frozen=True, slots=True)
class _TextTokens:
    """Pre-computed token forms for a single requirement text.

    Built once per atom in _apply_quality_gates and passed to all scoring
    functions, eliminating 4 redundant re.findall / .lower() calls per atom.
    """

    text_lower: str
    words: list[str]           # individual word tokens (lowercase)
    word_set: frozenset[str]   # O(1) membership — used by completeness scorer
    bigrams: list[str]         # adjacent word pairs — used by specificity scorer


def _tokenize_text(text: str) -> _TextTokens:
    """Tokenize *text* into all forms needed by the quality scorers.

    O(w) — called once per atom, result threaded through all scorers.
    """
    text_lower = text.lower()
    words = _TOKENIZE_RE.findall(text_lower)
    bigrams = [f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1)]
    return _TextTokens(
        text_lower=text_lower,
        words=words,
        word_set=frozenset(words),
        bigrams=bigrams,
    )


# ---------------------------------------------------------------------------
# Specificity scoring — ambiguity detector (spec §Phase1 Step 4B)
# ---------------------------------------------------------------------------

_CONCRETE_NOUNS: frozenset[str] = frozenset(
    [
        "invoice",
        "invoices",
        "purchase order",
        "vendor",
        "customer",
        "journal",
        "payment",
        "account",
        "ledger",
        "budget",
        "asset",
        "currency",
        "tax",
        "matching",
        "approval",
        "workflow",
        "transaction",
        "report",
        "posting",
        "allocation",
        "reconciliation",
        "forecast",
        "warehouse",
        "inventory",
        "product",
        "order",
        "shipment",
        "receipt",
        "supplier",
        "bank",
        "voucher",
        "period",
        "dimension",
        "fiscal",
        "tolerance",
        "credit",
        "debit",
    ]
)

_SPECIFIC_VERBS: frozenset[str] = frozenset(
    [
        "create",
        "validate",
        "approve",
        "calculate",
        "post",
        "allocate",
        "reconcile",
        "generate",
        "export",
        "import",
        "submit",
        "match",
        "link",
        "block",
        "release",
        "reverse",
        "cancel",
        "archive",
        "integrate",
        "notify",
        "schedule",
        "configure",
        "assign",
        "reject",
        "enforce",
    ]
)

_VAGUE_TERMS: frozenset[str] = frozenset(
    [
        "handle",
        "manage",
        "support",
        "deal",
        "provide",
        "ensure",
        "allow",
        "enable",
        "facilitate",
        "address",
        "cover",
        "work",
    ]
)


def _score_specificity_from_tokens(tokens: _TextTokens) -> float:
    """Specificity score computed from pre-tokenized _TextTokens.

    All frozenset lookups are O(1).  No re.findall / .lower() — tokens
    were computed once by _tokenize_text() and are shared across scorers.
    """
    concrete = sum(1 for w in tokens.words if w in _CONCRETE_NOUNS) + sum(
        1 for bg in tokens.bigrams if bg in _CONCRETE_NOUNS
    )
    specific = sum(1 for w in tokens.words if w in _SPECIFIC_VERBS)
    vague = sum(1 for w in tokens.words if w in _VAGUE_TERMS)

    total = concrete + specific + vague
    if total == 0:
        return 0.4  # short / neutral text: no signal either way
    return (concrete + specific) / total


def _score_specificity(text: str) -> float:
    """Specificity score in [0, 1]: (concrete + specific_verbs) / total vocab.

    < 0.30 → TOO_VAGUE (spec threshold).

    Public wrapper — tokenizes internally.  _apply_quality_gates calls
    _score_specificity_from_tokens() directly to avoid re-tokenizing.
    """
    return _score_specificity_from_tokens(_tokenize_text(text))


# ---------------------------------------------------------------------------
# Completeness scoring — per-module expected keyword presence (spec §Phase1 Step 4C)
# ---------------------------------------------------------------------------

_MODULE_EXPECTED_PARAMS: dict[str, list[str]] = {
    "AccountsPayable": ["matching", "tolerance", "approval", "payment", "vendor"],
    "AccountsReceivable": ["invoice", "customer", "credit", "collection", "dunning"],
    "GeneralLedger": ["posting", "dimension", "period", "currency", "journal"],
    "FixedAssets": ["depreciation", "asset", "acquisition", "disposal"],
    "Budgeting": ["budget", "forecast", "allocation", "variance"],
    "CashAndBankManagement": ["bank", "reconciliation", "payment", "cash"],
    "ProcurementAndSourcing": ["purchase", "requisition", "order", "vendor"],
    "InventoryManagement": ["inventory", "stock", "warehouse", "batch"],
    "ProductionControl": ["production", "order", "routing", "bom"],
    "SalesAndMarketing": ["sales", "customer", "order", "quote"],
    "ProjectManagement": ["project", "resource", "time", "cost"],
    "HumanResources": ["employee", "payroll", "leave", "position"],
    "Warehouse": ["picking", "packing", "zone", "wave"],
    "Transportation": ["carrier", "load", "route", "shipment"],
    "MasterPlanning": ["planning", "forecast", "supply", "demand"],
    "OrganizationAdministration": ["organization", "legal entity", "hierarchy"],
    "SystemAdministration": ["security", "role", "permission", "user"],
}

# Pre-split each param into a frozenset of words, built once at import time.
# _score_completeness_from_tokens() uses word_set ⊇ param_words (subset check)
# which is O(|param_words|) per param — avoids O(w_chars × p_len) substring scan.
_MODULE_PARAM_WORDSETS: dict[str, list[frozenset[str]]] = {
    module: [frozenset(p.split()) for p in params]
    for module, params in _MODULE_EXPECTED_PARAMS.items()
}


def _score_completeness_from_tokens(tokens: _TextTokens, module: str) -> float:
    """Completeness score computed from pre-tokenized _TextTokens.

    Uses frozenset subset check (param_words ⊆ word_set) instead of
    str.__contains__ substring scan, changing per-atom cost from
    O(p × w_chars) to O(p × avg_param_words) ≈ O(p) — near-constant.
    """
    param_sets = _MODULE_PARAM_WORDSETS.get(module, [])
    if not param_sets:
        return 50.0
    found = sum(1 for ps in param_sets if ps <= tokens.word_set)
    return round(found / len(param_sets) * 100.0, 1)


def _score_completeness(text: str, module: str) -> float:
    """Completeness score in [0, 100]: % of expected module keywords present.

    Public wrapper — tokenizes internally.  _apply_quality_gates calls
    _score_completeness_from_tokens() directly to avoid re-tokenizing.
    """
    return _score_completeness_from_tokens(_tokenize_text(text), module)


# ---------------------------------------------------------------------------
# Cross-field schema consistency check (spec §Phase1 Step 4A)
# ---------------------------------------------------------------------------

_CUSTOMER_CONTEXT_RE = re.compile(r"\b(customer|sales order|revenue|receivable)\b", re.IGNORECASE)
_VENDOR_CONTEXT_RE = re.compile(r"\b(vendor|purchase order|payable|supplier)\b", re.IGNORECASE)
_GAAP_STANDARD_RE = re.compile(r"\bGAAP\b")


def _check_cross_field_consistency(text: str, module: str, country: str) -> str | None:
    """Return a human-readable flag string if a cross-field inconsistency is
    detected, otherwise None."""
    if module == "AccountsPayable" and _CUSTOMER_CONTEXT_RE.search(text):
        return "module_hint_mismatch: AP module but text implies customer/AR context"
    if module == "AccountsReceivable" and _VENDOR_CONTEXT_RE.search(text):
        return "module_hint_mismatch: AR module but text implies vendor/AP context"
    if country.upper() in ("DE", "AT", "CH") and _GAAP_STANDARD_RE.search(text):
        return (
            "country_standard_mismatch: GAAP referenced in German-speaking country "
            "(expected HGB/IFRS)"
        )
    return None


# ---------------------------------------------------------------------------
# Quality gates — produce ValidatedAtom / FlaggedAtom from classified reqs
# ---------------------------------------------------------------------------


def _apply_quality_gates(
    unique: list[_ClassifiedRequirement],
    potential_duplicates: list[_ClassifiedRequirement],
    upload: RawUpload,
    pii_entities_by_source_ref: dict[str, list[Any]] | None = None,
) -> tuple[list[ValidatedAtom], list[FlaggedAtom]]:
    """Apply all Phase 1 quality gates and produce validated / flagged atom lists.

    Gate order (spec §Phase1 Step 4):
      A. Schema cross-field consistency     — rejects on mismatch
      B. Specificity < 0.30 (too vague)     — rejects
      C. Completeness < 30 + specificity borderline — rejects as INCOMPLETE
      D. Text length 10–2000 chars          — rejects on violation
      Passed all → ValidatedAtom
    Potential duplicates are added to flagged_atoms without blocking the pass-through.

    Tokenization: each atom is tokenized exactly once via _tokenize_text().
    The resulting _TextTokens is shared across all four scorers, eliminating
    redundant re.findall / .lower() work from the hot per-atom loop.

    Args:
        unique: List of unique classified requirements
        potential_duplicates: List of potential duplicates
        upload: RawUpload metadata
        pii_entities_by_source_ref: Map of source_ref → list of PIIEntity detected in that text
    """
    validated: list[ValidatedAtom] = []
    flagged: list[FlaggedAtom] = []

    # Initialize PII entities map if not provided
    if pii_entities_by_source_ref is None:
        pii_entities_by_source_ref = {}

    # Pre-compute entity hints for all unique atoms in one batched spaCy pipe() call.
    _unique_texts = [req.atom.requirement_text for req in unique]
    _hints_batch = _extract_entity_hints_batch(_unique_texts)
    _entity_hints_map: dict[str, list[str]] = {
        req.atom.atom_id: hints for req, hints in zip(unique, _hints_batch)
    }

    duplicate_ids = {r.atom.atom_id for r in potential_duplicates}
    for dup in potential_duplicates:
        pii_entities = pii_entities_by_source_ref.get(dup.atom.source_ref, [])
        flagged.append(
            FlaggedAtom(
                atom_id=dup.atom.atom_id,
                upload_id=dup.atom.upload_id,
                requirement_text=dup.atom.requirement_text,
                flag_reason="POTENTIAL_DUPLICATE",
                flag_detail=(
                    "cosine similarity 0.80–0.92 with another atom; human review required"
                ),
                pii_entities=pii_entities,
            )
        )

    for req in unique:
        if req.atom.atom_id in duplicate_ids:
            continue

        text = req.atom.requirement_text
        module = req.module if req.module in _MODULE_SET else "OrganizationAdministration"
        pii_entities = pii_entities_by_source_ref.get(req.atom.source_ref, [])

        # Gate A — schema cross-field consistency (uses raw text, regex only)
        consistency_flag = _check_cross_field_consistency(text, module, upload.country)
        if consistency_flag:
            flagged.append(
                FlaggedAtom(
                    atom_id=req.atom.atom_id,
                    upload_id=req.atom.upload_id,
                    requirement_text=text,
                    flag_reason="SCHEMA_MISMATCH",
                    flag_detail=consistency_flag,
                    pii_entities=pii_entities,
                )
            )
            continue

        # Tokenize once — reused by Gate B, Gate C, and ValidatedAtom construction.
        tokens = _tokenize_text(text)

        # Gate B — specificity / ambiguity
        specificity = _score_specificity_from_tokens(tokens)
        if specificity < 0.30:
            flagged.append(
                FlaggedAtom(
                    atom_id=req.atom.atom_id,
                    upload_id=req.atom.upload_id,
                    requirement_text=text,
                    flag_reason="TOO_VAGUE",
                    flag_detail=(f"specificity_score={specificity:.2f} below 0.30 threshold"),
                    specificity_score=specificity,
                    pii_entities=pii_entities,
                )
            )
            continue

        # Gate C — completeness borderline
        completeness = _score_completeness_from_tokens(tokens, module)
        if completeness < 30.0 and specificity < 0.50:
            flagged.append(
                FlaggedAtom(
                    atom_id=req.atom.atom_id,
                    upload_id=req.atom.upload_id,
                    requirement_text=text,
                    flag_reason="INCOMPLETE",
                    flag_detail=(
                        f"completeness={completeness:.1f}% and "
                        f"specificity={specificity:.2f} both below threshold"
                    ),
                    specificity_score=specificity,
                    pii_entities=pii_entities,
                )
            )
            continue

        # Gate D — text length
        if not (10 <= len(text) <= 2000):
            flagged.append(
                FlaggedAtom(
                    atom_id=req.atom.atom_id,
                    upload_id=req.atom.upload_id,
                    requirement_text=text[:2000],
                    flag_reason="SCHEMA_MISMATCH",
                    flag_detail=(f"requirement_text length {len(text)} outside [10, 2000]"),
                    pii_entities=pii_entities,
                )
            )
            continue

        # All gates passed
        validated.append(
            ValidatedAtom(
                atom_id=req.atom.atom_id,
                upload_id=req.atom.upload_id,
                requirement_text=text,
                module=module,
                country=upload.country,
                wave=upload.wave,
                priority=_infer_moscow_priority(text),
                intent=req.intent,
                content_type=req.atom.content_type,
                entity_hints=_entity_hints_map.get(req.atom.atom_id, []),
                specificity_score=specificity,
                completeness_score=completeness,
                pii_entities=pii_entities,
                source_refs=[req.atom.source_ref] if req.atom.source_ref else [],
            )
        )

    return validated, flagged

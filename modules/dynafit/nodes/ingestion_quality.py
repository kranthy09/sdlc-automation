"""Quality scoring and gating for Phase 1 ingestion.

Contains:
- MoSCoW priority enrichment (keyword-based)
- Entity hint extraction (spaCy NER, best-effort)
- Specificity scoring (ambiguity detection)
- Completeness scoring (per-module keyword presence)
- Cross-field schema consistency checks
- Quality gate application (_apply_quality_gates)
"""

from __future__ import annotations

import re
import threading
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


def _extract_entity_hints(text: str) -> list[str]:
    """Return NER entity strings from text. Returns [] if spaCy is not installed."""
    global _spacy_nlp, _spacy_unavailable
    if _spacy_unavailable:
        return []
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
                    return []
    try:
        doc = _spacy_nlp(text[:512])
        return list({ent.text.lower() for ent in doc.ents if len(ent.text) > 2})
    except Exception:
        return []


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


def _score_specificity(text: str) -> float:
    """Specificity score in [0, 1]: (concrete + specific_verbs) / total vocab.

    < 0.30 → TOO_VAGUE (spec threshold)
    """
    words = re.findall(r"\b\w+\b", text.lower())
    bigrams = [f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1)]

    concrete = sum(1 for w in words if w in _CONCRETE_NOUNS) + sum(
        1 for bg in bigrams if bg in _CONCRETE_NOUNS
    )
    specific = sum(1 for w in words if w in _SPECIFIC_VERBS)
    vague = sum(1 for w in words if w in _VAGUE_TERMS)

    total = concrete + specific + vague
    if total == 0:
        return 0.4  # short / neutral text: no signal either way
    return (concrete + specific) / total


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


def _score_completeness(text: str, module: str) -> float:
    """Completeness score in [0, 100]: % of expected module keywords present."""
    params = _MODULE_EXPECTED_PARAMS.get(module, [])
    if not params:
        return 50.0
    text_lower = text.lower()
    found = sum(1 for p in params if p in text_lower)
    return round(found / len(params) * 100.0, 1)


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
) -> tuple[list[ValidatedAtom], list[FlaggedAtom]]:
    """Apply all Phase 1 quality gates and produce validated / flagged atom lists.

    Gate order (spec §Phase1 Step 4):
      A. Schema cross-field consistency     — rejects on mismatch
      B. Specificity < 0.30 (too vague)     — rejects
      C. Completeness < 30 + specificity borderline — rejects as INCOMPLETE
      D. Text length 10–2000 chars          — rejects on violation
      Passed all → ValidatedAtom
    Potential duplicates are added to flagged_atoms without blocking the pass-through.
    """
    validated: list[ValidatedAtom] = []
    flagged: list[FlaggedAtom] = []

    duplicate_ids = {r.atom.atom_id for r in potential_duplicates}
    for dup in potential_duplicates:
        flagged.append(
            FlaggedAtom(
                atom_id=dup.atom.atom_id,
                upload_id=dup.atom.upload_id,
                requirement_text=dup.atom.requirement_text,
                flag_reason="POTENTIAL_DUPLICATE",
                flag_detail=(
                    "cosine similarity 0.80–0.92 with another atom; human review required"
                ),
            )
        )

    for req in unique:
        if req.atom.atom_id in duplicate_ids:
            continue

        text = req.atom.requirement_text
        module = req.module if req.module in _MODULE_SET else "OrganizationAdministration"

        # Gate A — schema cross-field consistency
        consistency_flag = _check_cross_field_consistency(text, module, upload.country)
        if consistency_flag:
            flagged.append(
                FlaggedAtom(
                    atom_id=req.atom.atom_id,
                    upload_id=req.atom.upload_id,
                    requirement_text=text,
                    flag_reason="SCHEMA_MISMATCH",
                    flag_detail=consistency_flag,
                )
            )
            continue

        # Gate B — specificity / ambiguity
        specificity = _score_specificity(text)
        if specificity < 0.30:
            flagged.append(
                FlaggedAtom(
                    atom_id=req.atom.atom_id,
                    upload_id=req.atom.upload_id,
                    requirement_text=text,
                    flag_reason="TOO_VAGUE",
                    flag_detail=(f"specificity_score={specificity:.2f} below 0.30 threshold"),
                    specificity_score=specificity,
                )
            )
            continue

        # Gate C — completeness borderline
        completeness = _score_completeness(text, module)
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
                )
            )
            continue

        # All gates passed
        validated.append(
            ValidatedAtom(
                atom_id=req.atom.atom_id,
                upload_id=req.atom.upload_id,
                requirement_text=text,
                module=module,  # type: ignore[arg-type]
                country=upload.country,
                wave=upload.wave,
                priority=_infer_moscow_priority(text),
                intent=req.intent,
                content_type=req.atom.content_type,
                entity_hints=_extract_entity_hints(text),
                specificity_score=specificity,
                completeness_score=completeness,
                source_refs=[req.atom.source_ref] if req.atom.source_ref else [],
            )
        )

    return validated, flagged

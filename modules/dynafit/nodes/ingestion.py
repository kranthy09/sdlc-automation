"""
Ingestion node — Phase 1 of the DYNAFIT pipeline (Session C).

Responsibility: RawUpload → RequirementAtom[] + ValidatedAtom[] + FlaggedAtom[]

Pipeline steps:
  1.  G1-lite file validation   (platform/guardrails/file_validator.py)
  2.  Document parsing           → table rows + prose chunks (DoclingParser)
  3.  Header column mapping      → synonym resolution (header_synonyms.yaml)
  4.  G3-lite injection scan    (platform/guardrails/injection_scanner.py)
  5.  Atomization + classification → one combined LLM call per raw text
  6.  Deduplication              → cosine similarity (numpy; FAISS deferred)
  7.  Priority enrichment        → keyword-based MoSCoW
  8.  Entity hint extraction     → spaCy NER (best-effort, lazy load)
  9.  Quality gates              → schema consistency, ambiguity, completeness
  10. Phase event publish        → Redis PhaseStartEvent (best-effort)

Post-MVP deferred:
  - Image extraction (spec §Phase1 Sub-step E)
  - Cross-wave linker (historical fitments — handled in Phase 2 retrieval)
  - FAISS / MinHashLSH for batches > 5 K atoms
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from platform.guardrails.file_validator import validate_file
from platform.guardrails.injection_scanner import scan_for_injection
from platform.llm.client import LLMClient
from platform.observability.logger import get_logger
from platform.parsers.docling_parser import DoclingParser
from platform.schemas.events import PhaseStartEvent
from platform.schemas.product import ProductConfig
from platform.schemas.requirement import (
    FlaggedAtom,
    RawUpload,
    RequirementAtom,
    ValidatedAtom,
)
from platform.storage.redis_pub import RedisPubSub

from ..state import DynafitState

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# D365 module constrained vocabulary
# ---------------------------------------------------------------------------

_D365_MODULES: list[str] = [
    "AccountsPayable",
    "AccountsReceivable",
    "GeneralLedger",
    "FixedAssets",
    "Budgeting",
    "CashAndBankManagement",
    "ProcurementAndSourcing",
    "InventoryManagement",
    "ProductionControl",
    "SalesAndMarketing",
    "ProjectManagement",
    "HumanResources",
    "Warehouse",
    "Transportation",
    "MasterPlanning",
    "OrganizationAdministration",
    "SystemAdministration",
]
_MODULE_SET: frozenset[str] = frozenset(_D365_MODULES)
_MODULE_LIST_STR: str = ", ".join(_D365_MODULES)

# ---------------------------------------------------------------------------
# Default ProductConfig — MVP supports d365_fo only
# ---------------------------------------------------------------------------

_D365_FO_CONFIG: ProductConfig = ProductConfig(
    product_id="d365_fo",
    display_name="Dynamics 365 Finance & Operations",
    llm_model="claude-sonnet-4-6",
    embedding_model="BAAI/bge-large-en-v1.5",
    capability_kb_namespace="d365_fo_capabilities",
    doc_corpus_namespace="d365_fo_docs",
    historical_fitments_table="d365_fo_fitments",
    fit_confidence_threshold=0.85,
    review_confidence_threshold=0.60,
    auto_approve_with_history=True,
    country_rules_path="knowledge_bases/d365_fo/country_rules/",
    fdd_template_path="knowledge_bases/d365_fo/fdd_templates/fit_template.j2",
    code_language="xpp",
)


def _get_product_config(product_id: str) -> ProductConfig:
    """Return ProductConfig for the given product_id. MVP: d365_fo only."""
    if product_id == "d365_fo":
        return _D365_FO_CONFIG
    return _D365_FO_CONFIG.model_copy(update={"product_id": product_id})


# ---------------------------------------------------------------------------
# LLM response schemas (private — not part of module public API)
# ---------------------------------------------------------------------------

_IntentLiteral = Literal["FUNCTIONAL", "NON_FUNCTIONAL", "INTEGRATION", "REPORTING"]


class _ClassifiedAtom(BaseModel):
    """One atom with intent and module as produced by the LLM."""

    text: str
    intent: _IntentLiteral
    module: str  # validated against _MODULE_SET after parsing


class _AtomizationResult(BaseModel):
    """LLM tool-use output schema for the combined atomise + classify call."""

    atoms: list[_ClassifiedAtom]


# ---------------------------------------------------------------------------
# Internal pipeline record — carries LLM classification through deduplication
# ---------------------------------------------------------------------------


@dataclass
class _ClassifiedRequirement:
    """RequirementAtom plus its LLM-assigned intent and module.

    Exists only inside the ingestion pipeline.  Converted to
    ValidatedAtom / FlaggedAtom at the final quality-gate step.
    """

    atom: RequirementAtom
    intent: _IntentLiteral
    module: str  # validated D365 module string


# ---------------------------------------------------------------------------
# Header column synonym map  (header_synonyms.yaml, same directory as this pkg)
# ---------------------------------------------------------------------------

_SYNONYMS_PATH: Path = Path(__file__).parent.parent / "header_synonyms.yaml"
_SYNONYMS_CACHE: dict[str, list[str]] | None = None


def _load_synonyms() -> dict[str, list[str]]:
    """Lazy-load and flatten header_synonyms.yaml into {canonical: [terms]}."""
    global _SYNONYMS_CACHE
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


# ---------------------------------------------------------------------------
# LLM call: atomise + classify intent + tag module (one call per raw text)
# ---------------------------------------------------------------------------

_ATOMISATION_PROMPT = """\
You are a D365 F&O requirements analyst.

TASK 1 — SPLIT:
Decompose the requirement text below into atomic requirements.
Each atom describes exactly ONE functional need.
- Start each atom with "The system shall..." or "The system must..."
- Preserve all specific details (thresholds, field names, frequencies)
- If the text is already a single requirement, return it as a single atom

TASK 2 — CLASSIFY each atom:
  intent: exactly one of FUNCTIONAL, NON_FUNCTIONAL, INTEGRATION, REPORTING
  module: exactly one of: {module_list}

Requirement text:
{text}
"""


def _atomise_and_classify(
    text: str,
    llm: LLMClient,
    config: ProductConfig,
) -> list[_ClassifiedAtom]:
    """Split and classify one raw text via LLM. Fails safe to a single atom."""
    prompt = _ATOMISATION_PROMPT.format(
        module_list=_MODULE_LIST_STR,
        text=text[:3000],
    )
    _fallback = _ClassifiedAtom(
        text=text.strip(),
        intent="FUNCTIONAL",
        module="OrganizationAdministration",
    )
    try:
        result: _AtomizationResult = llm.complete(
            prompt, _AtomizationResult, config, temperature=0.0
        )
        items: list[_ClassifiedAtom] = []
        for item in result.atoms:
            module = (
                item.module if item.module in _MODULE_SET else "OrganizationAdministration"
            )
            trimmed = item.text.strip()
            if trimmed:
                items.append(_ClassifiedAtom(text=trimmed, intent=item.intent, module=module))
        return items or [_fallback]
    except Exception as exc:
        log.warning("atomise_llm_failed", error=str(exc), preview=text[:80])
        return [_fallback]


# ---------------------------------------------------------------------------
# Priority enrichment — keyword MoSCoW, no LLM needed
# ---------------------------------------------------------------------------

_MUST_RE = re.compile(
    r"\b(must|shall|required|mandatory|critical|compulsory)\b", re.IGNORECASE
)
_COULD_RE = re.compile(
    r"\b(could|nice.to.have|optional|desirable|wish)\b", re.IGNORECASE
)


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


def _extract_entity_hints(text: str) -> list[str]:
    """Return NER entity strings from text. Returns [] if spaCy is not installed."""
    global _spacy_nlp, _spacy_unavailable
    if _spacy_unavailable:
        return []
    if _spacy_nlp is None:
        try:
            import spacy  # noqa: PLC0415

            _spacy_nlp = spacy.load("en_core_web_lg")
        except Exception as exc:
            log.warning("spacy_load_failed", error=str(exc))
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

_CUSTOMER_CONTEXT_RE = re.compile(
    r"\b(customer|sales order|revenue|receivable)\b", re.IGNORECASE
)
_VENDOR_CONTEXT_RE = re.compile(
    r"\b(vendor|purchase order|payable|supplier)\b", re.IGNORECASE
)
_GAAP_STANDARD_RE = re.compile(r"\bGAAP\b")


def _check_cross_field_consistency(
    text: str, module: str, country: str
) -> str | None:
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
# Deduplication — cosine similarity via numpy (spec §Phase1 Step 3A)
# ---------------------------------------------------------------------------


def _deduplicate_requirements(
    requirements: list[_ClassifiedRequirement],
    embedder: Any,
) -> tuple[list[_ClassifiedRequirement], list[_ClassifiedRequirement]]:
    """Cosine-similarity deduplication.

    Returns (unique_requirements, potential_duplicates).

    - cosine > 0.92  → hard merge: remove j, append j.atom_id to i's source_ref
    - cosine 0.80–0.92 → soft flag: j stays in unique, also returned in duplicates
    """
    if len(requirements) <= 1:
        return requirements, []

    import numpy as np  # noqa: PLC0415

    texts = [r.atom.requirement_text for r in requirements]
    matrix = embedder.embed_batch(texts)
    vecs = np.array(matrix, dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    vecs = vecs / norms
    sim: Any = vecs @ vecs.T

    hard_merged: set[int] = set()
    soft_flagged: set[int] = set()

    for i in range(len(requirements)):
        if i in hard_merged:
            continue
        for j in range(i + 1, len(requirements)):
            if j in hard_merged:
                continue
            s = float(sim[i, j])
            if s > 0.92:
                hard_merged.add(j)
                existing_ref = (
                    requirements[i].atom.source_ref or requirements[i].atom.atom_id
                )
                requirements[i] = _ClassifiedRequirement(
                    atom=requirements[i].atom.model_copy(
                        update={
                            "source_ref": (
                                f"{existing_ref},{requirements[j].atom.atom_id}"
                            )
                        }
                    ),
                    intent=requirements[i].intent,
                    module=requirements[i].module,
                )
            elif s > 0.80:
                soft_flagged.add(j)

    unique = [r for idx, r in enumerate(requirements) if idx not in hard_merged]
    duplicates = [r for idx, r in enumerate(requirements) if idx in soft_flagged]
    return unique, duplicates


# ---------------------------------------------------------------------------
# Redis publish — best-effort sync wrapper around async publish
# ---------------------------------------------------------------------------


def _publish_phase_event(batch_id: str, redis: RedisPubSub | None) -> None:
    """Publish PhaseStartEvent for the ingestion phase. Non-fatal on failure."""
    if redis is None:
        return
    event = PhaseStartEvent(batch_id=batch_id, phase=1, phase_name="Ingestion")
    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(redis.publish(event))
        finally:
            loop.close()
    except Exception as exc:
        log.warning("ingestion_redis_publish_failed", batch_id=batch_id, error=str(exc))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_rejection_result(reason: str) -> dict[str, Any]:
    return {
        "atoms": [],
        "validated_atoms": [],
        "flagged_atoms": [],
        "errors": [reason],
    }


def _collect_requirement_texts(parse_result: Any) -> list[tuple[str, str]]:
    """Extract (requirement_text, source_ref) pairs from a ParseResult.

    Prefers resolved table rows; falls back to prose chunks when no
    requirement_text column is found in any table.
    """
    texts: list[tuple[str, str]] = []

    resolved = _map_table_rows_to_canonical(parse_result.tables)
    for i, row in enumerate(resolved):
        text = row.get("requirement_text", "").strip()
        if len(text) >= 10:
            texts.append((text, f"table_row_{i}"))

    if not texts:
        for chunk in parse_result.prose:
            text = chunk.text.strip()
            if len(text) >= 30:
                texts.append((text, f"page_{chunk.page}_prose"))

    return texts


def _build_classified_requirements(
    raw_texts: list[tuple[str, str]],
    upload: RawUpload,
    llm: LLMClient,
    config: ProductConfig,
) -> list[_ClassifiedRequirement]:
    """Run atomisation + classification on every raw text.

    Returns a flat list of _ClassifiedRequirement, one per atom produced.
    """
    results: list[_ClassifiedRequirement] = []
    counter = 0
    id_prefix = upload.upload_id[:8].upper()

    for text, source_ref in raw_texts:
        classified_atoms = _atomise_and_classify(text, llm, config)
        for atom in classified_atoms:
            if len(atom.text.strip()) < 10:
                continue
            atom_id = f"REQ-{id_prefix}-{counter:04d}"
            requirement = RequirementAtom(
                atom_id=atom_id,
                upload_id=upload.upload_id,
                requirement_text=atom.text.strip(),
                source_ref=source_ref,
                source_document=upload.filename,
                raw_module_hint=atom.module,
                content_type="text",
            )
            results.append(
                _ClassifiedRequirement(
                    atom=requirement,
                    intent=atom.intent,
                    module=atom.module,
                )
            )
            counter += 1

    return results


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
                    "cosine similarity 0.80–0.92 with another atom; "
                    "human review required"
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
                    flag_detail=(
                        f"specificity_score={specificity:.2f} below 0.30 threshold"
                    ),
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
                    flag_detail=(
                        f"requirement_text length {len(text)} outside [10, 2000]"
                    ),
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


# ---------------------------------------------------------------------------
# IngestionNode — injectable dependencies, callable as a LangGraph node
# ---------------------------------------------------------------------------


class IngestionNode:
    """Phase 1 ingestion pipeline with injectable dependencies.

    Instantiate directly in tests with mock infrastructure:

        node = IngestionNode(
            llm_client=make_llm_client(...),
            embedder=make_embedder(),
            redis=make_redis_pub_sub(),
        )
        result = node(state)

    Production code uses the module-level ``ingestion_node`` function which
    creates and caches a default instance.

    Args:
        llm_client: LLMClient for atomise/classify calls. Lazy-init if None.
        parser:     DoclingParser for document parsing. Lazy-init if None.
        embedder:   Embedder (sentence-transformers) for deduplication.
                    Lazy-init if None.
        redis:      RedisPubSub for PhaseStartEvent publish.
                    Skipped without error if None.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        parser: DoclingParser | None = None,
        embedder: Any | None = None,
        redis: RedisPubSub | None = None,
    ) -> None:
        self._llm = llm_client
        self._parser = parser
        self._embedder = embedder
        self._redis = redis

    # ------------------------------------------------------------------
    # Lazy infra
    # ------------------------------------------------------------------

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def _get_parser(self) -> DoclingParser:
        if self._parser is None:
            self._parser = DoclingParser()
        return self._parser

    def _get_embedder(self) -> Any:
        if self._embedder is None:
            from platform.retrieval.embedder import Embedder  # noqa: PLC0415

            self._embedder = Embedder("BAAI/bge-large-en-v1.5")
        return self._embedder

    # ------------------------------------------------------------------
    # LangGraph entry point
    # ------------------------------------------------------------------

    def __call__(self, state: DynafitState) -> dict[str, Any]:
        upload: RawUpload = state["upload"]
        batch_id: str = state["batch_id"]
        t0 = time.monotonic()

        log.info(
            "phase_start",
            phase=1,
            batch_id=batch_id,
            filename=upload.filename,
            input_hash=hashlib.sha256(upload.file_bytes).hexdigest()[:16],
        )

        config = _get_product_config(upload.product_id)

        # 1. G1-lite — file validation
        file_check = validate_file(upload.file_bytes, upload.filename)
        if not file_check.is_valid:
            log.error(
                "ingestion_file_rejected",
                batch_id=batch_id,
                reason=file_check.rejection_reason,
            )
            return _make_rejection_result(
                f"file_validation_failed: {file_check.rejection_reason}"
            )

        # 2. Document parsing
        parse_result = self._parse_document(upload, batch_id)
        if parse_result is None:
            return _make_rejection_result(f"parse_failed: {upload.filename}")

        # 3. Extract raw requirement texts
        raw_texts = _collect_requirement_texts(parse_result)
        if not raw_texts:
            log.warning("ingestion_no_text_found", batch_id=batch_id)
            return _make_rejection_result(
                "no_requirements_found: document produced no extractable text"
            )

        # 4. G3-lite — injection scan
        combined_text = "\n".join(t for t, _ in raw_texts)
        injection_scan = scan_for_injection(combined_text)
        if injection_scan.action == "BLOCK":
            log.error(
                "ingestion_injection_blocked",
                batch_id=batch_id,
                patterns=injection_scan.matched_patterns,
            )
            return _make_rejection_result(
                f"injection_blocked: patterns={injection_scan.matched_patterns}"
            )

        extra_errors: list[str] = (
            [f"injection_flagged:{p}" for p in injection_scan.matched_patterns]
            if injection_scan.action == "FLAG_FOR_REVIEW"
            else []
        )

        # 5. Atomise + classify (LLM)
        classified = _build_classified_requirements(
            raw_texts, upload, self._get_llm(), config
        )
        if not classified:
            return _make_rejection_result("atomisation_produced_no_atoms")

        # 6. Deduplicate
        unique, duplicates = _deduplicate_requirements(classified, self._get_embedder())

        # 7–9. Quality gates (priority / entity hints / validation baked in)
        validated, flagged = _apply_quality_gates(unique, duplicates, upload)

        # 10. Publish phase event (best-effort)
        _publish_phase_event(batch_id, self._redis)

        elapsed_ms = (time.monotonic() - t0) * 1000
        log.info(
            "phase_complete",
            phase=1,
            batch_id=batch_id,
            output_hash=hashlib.sha256(repr(validated).encode()).hexdigest()[:16],
            atoms_in=len(raw_texts),
            atoms_out=len(validated),
            flagged=len(flagged),
            guardrails_triggered=(
                ["G3_injection_flagged"] if extra_errors else []
            ),
            latency_ms=round(elapsed_ms, 1),
        )

        return {
            "atoms": [r.atom for r in unique],
            "validated_atoms": validated,
            "flagged_atoms": flagged,
            "errors": extra_errors,
        }

    # ------------------------------------------------------------------
    # Document parsing (writes bytes to a temp file for DoclingParser)
    # ------------------------------------------------------------------

    def _parse_document(self, upload: RawUpload, batch_id: str) -> Any | None:
        suffix = Path(upload.filename).suffix or ".bin"
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(upload.file_bytes)
                tmp_path = Path(tmp.name)
            return self._get_parser().parse(tmp_path)
        except Exception as exc:
            log.error("ingestion_parse_error", batch_id=batch_id, error=str(exc))
            return None
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Module-level singleton + LangGraph entry point
# ---------------------------------------------------------------------------

_node: IngestionNode | None = None


def ingestion_node(state: DynafitState) -> dict[str, Any]:
    """LangGraph Phase 1 node — delegates to the cached IngestionNode instance.

    Tests should instantiate IngestionNode directly with mock dependencies
    instead of calling this function.
    """
    global _node
    if _node is None:
        _node = IngestionNode()
    return _node(state)

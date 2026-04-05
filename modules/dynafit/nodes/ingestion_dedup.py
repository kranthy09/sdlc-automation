"""Cosine-similarity deduplication for Phase 1 ingestion.

Strategy by batch size:
  a ≤ 300  → numpy full-matrix path  (O(a²·d) BLAS + O(a²) numpy C)
  a > 300  → FAISS range_search path  (O(a·d) per query, exact inner-product)
             falls back to numpy if faiss-cpu is not installed.

The O(a²) Python nested loop that existed here has been replaced in both paths
by numpy/FAISS C operations.  The only Python loop that remains runs over the
result pairs (sparse when near-duplicates are rare, which is the typical case).
"""

from __future__ import annotations

from typing import Any

from .ingestion_atomiser import _ClassifiedRequirement

# Threshold: above this cosine → hard merge (j removed, id appended to i's source_ref)
_HARD_THRESH: float = 0.92
# Threshold: above this cosine (and ≤ _HARD_THRESH) → soft flag for human review
_SOFT_THRESH: float = 0.80
# Batch size above which FAISS is preferred over the full numpy matrix
_FAISS_THRESHOLD: int = 300


# ---------------------------------------------------------------------------
# Shared merge-application helper
# ---------------------------------------------------------------------------


def _apply_merges(
    requirements: list[_ClassifiedRequirement],
    merge_targets: dict[int, list[int]],
    hard_merged: set[int],
    soft_flagged: set[int],
) -> tuple[list[_ClassifiedRequirement], list[_ClassifiedRequirement]]:
    """Apply collected merge decisions to the requirements list.

    One model_copy per survivor atom (not one per absorbed atom).
    source_ref built with a single join — avoids O(k²) string growth.
    artifact_ids and citations are union-merged from absorbed atoms.
    """
    for i, js in merge_targets.items():
        merged_ids = [requirements[j].atom.atom_id for j in js]
        base_ref = (
            requirements[i].atom.source_ref
            or requirements[i].atom.atom_id
        )
        new_ref = ",".join([base_ref] + merged_ids)

        # Union-merge artifact_ids (preserve order, no duplicates)
        seen: set[str] = set(requirements[i].atom.artifact_ids)
        merged_art_ids = list(requirements[i].atom.artifact_ids)
        for j in js:
            for aid in requirements[j].atom.artifact_ids:
                if aid not in seen:
                    seen.add(aid)
                    merged_art_ids.append(aid)

        # Merge citations from absorbed atoms
        merged_citations = list(requirements[i].atom.citations)
        existing_refs = {c.source_ref for c in merged_citations}
        for j in js:
            for cit in requirements[j].atom.citations:
                if cit.source_ref not in existing_refs:
                    existing_refs.add(cit.source_ref)
                    merged_citations.append(cit)

        requirements[i] = _ClassifiedRequirement(
            atom=requirements[i].atom.model_copy(update={
                "source_ref": new_ref,
                "artifact_ids": merged_art_ids,
                "citations": merged_citations,
            }),
            intent=requirements[i].intent,
            module=requirements[i].module,
        )

    unique = [r for idx, r in enumerate(requirements) if idx not in hard_merged]
    duplicates = [r for idx, r in enumerate(requirements) if idx in soft_flagged]
    return unique, duplicates


# ---------------------------------------------------------------------------
# Path A: numpy full-matrix  (a ≤ _FAISS_THRESHOLD)
# ---------------------------------------------------------------------------


def _deduplicate_numpy(
    requirements: list[_ClassifiedRequirement],
    vecs: Any,  # np.ndarray, shape (a, d), already L2-normalised
) -> tuple[list[_ClassifiedRequirement], list[_ClassifiedRequirement]]:
    """Deduplicate using the full a×a cosine matrix via numpy BLAS.

    Complexity: O(a²·d) for the matmul (C/BLAS), O(a²) for argwhere (C).
    The old O(a²) Python bytecode loop is replaced by three numpy C calls.
    """
    import numpy as np  # noqa: PLC0415

    sim: Any = vecs @ vecs.T  # O(a²·d) BLAS

    # Extract all threshold-crossing index pairs from the upper triangle in one
    # numpy C pass — no Python loop over the a² matrix cells.
    upper = np.triu(sim, k=1)
    hard_ij = np.argwhere(upper > _HARD_THRESH)                      # shape (m_hard, 2)
    soft_ij = np.argwhere((upper > _SOFT_THRESH) & (upper <= _HARD_THRESH))  # shape (m_soft, 2)

    # Build merge map processing rows in order so later j's don't become survivors
    # after already being absorbed by an earlier i.
    hard_merged: set[int] = set()
    merge_targets: dict[int, list[int]] = {}
    for row in hard_ij:
        i, j = int(row[0]), int(row[1])
        if j in hard_merged:
            continue
        merge_targets.setdefault(i, []).append(j)
        hard_merged.add(j)

    soft_flagged = {int(row[1]) for row in soft_ij if int(row[1]) not in hard_merged}

    return _apply_merges(requirements, merge_targets, hard_merged, soft_flagged)


# ---------------------------------------------------------------------------
# Path B: FAISS range_search  (a > _FAISS_THRESHOLD)
# ---------------------------------------------------------------------------


def _deduplicate_faiss(
    requirements: list[_ClassifiedRequirement],
    vecs: Any,  # np.ndarray, shape (a, d), already L2-normalised, dtype float32
) -> tuple[list[_ClassifiedRequirement], list[_ClassifiedRequirement]]:
    """Deduplicate using FAISS IndexFlatIP range_search.

    For each atom, FAISS returns only the atoms whose cosine exceeds
    _SOFT_THRESH — the result set is sparse when near-duplicates are rare.

    Complexity:
      index.add + range_search: O(a·d) per query = O(a²·d) worst case, but
      implemented in AVX-accelerated C (2–5× faster than numpy for a > 300).
      Python loop: O(result_pairs) — typically << a² for real requirements docs.
    """
    import faiss  # noqa: PLC0415

    a, d = vecs.shape
    index = faiss.IndexFlatIP(d)
    index.add(vecs)  # O(a·d)

    # range_search returns all (query_i, db_j) pairs with inner-product > thresh.
    # With normalised vectors, inner-product == cosine similarity.
    lims, D_out, I_out = index.range_search(vecs, _SOFT_THRESH)  # O(a·d) amortised

    hard_merged: set[int] = set()
    merge_targets: dict[int, list[int]] = {}
    soft_flagged: set[int] = set()

    for i in range(a):
        if i in hard_merged:
            continue
        start, end = int(lims[i]), int(lims[i + 1])
        for k in range(start, end):
            j = int(I_out[k])
            if j <= i or j in hard_merged:  # skip self-match and already-absorbed
                continue
            s = float(D_out[k])
            if s > _HARD_THRESH:
                merge_targets.setdefault(i, []).append(j)
                hard_merged.add(j)
            else:
                soft_flagged.add(j)

    return _apply_merges(requirements, merge_targets, hard_merged, soft_flagged)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _deduplicate_requirements(
    requirements: list[_ClassifiedRequirement],
    embedder: Any,
) -> tuple[list[_ClassifiedRequirement], list[_ClassifiedRequirement]]:
    """Cosine-similarity deduplication.

    Returns (unique_requirements, potential_duplicates).

    - cosine > 0.92  → hard merge: remove j, append j.atom_id to i's source_ref
    - cosine 0.80–0.92 → soft flag: j stays in unique, also returned in duplicates

    Dispatch:
      a ≤ 300  → _deduplicate_numpy  (full matrix, numpy BLAS)
      a > 300  → _deduplicate_faiss  (range_search, falls back to numpy on ImportError)
    """
    if len(requirements) <= 1:
        return requirements, []

    import numpy as np  # noqa: PLC0415

    texts = [r.atom.requirement_text for r in requirements]
    matrix = embedder.embed_batch(texts)
    vecs = np.array(matrix, dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    vecs = (vecs / norms).astype(np.float32)

    a = len(requirements)
    if a > _FAISS_THRESHOLD:
        try:
            return _deduplicate_faiss(requirements, vecs)
        except ImportError:
            pass  # faiss-cpu not installed — fall through to numpy path

    return _deduplicate_numpy(requirements, vecs)

"""
Seed script — populate Qdrant with D365 F&O capability and docs embeddings.

Usage:
    uv run python -m infra.scripts.seed_knowledge_base --product d365_fo
    uv run python -m infra.scripts.seed_knowledge_base --product d365_fo --source lite --reset

Options:
    --product   Product ID (required). Used to locate knowledge_bases/{product}/ and name the collection.
    --source    'lite' (default) or 'full'. Determines which YAML file is loaded.
    --reset     Drop and recreate collections before seeding (full data wipe).
    --qdrant-url  Qdrant URL (default: http://localhost:6333, or QDRANT_URL env var).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

from platform.retrieval.bm25 import BM25Retriever
from platform.retrieval.embedder import Embedder
from platform.retrieval.vector_store import (
    CollectionConfig,
    Point,
    VectorStore,
)

# Default embedding model — matches ProductConfig for d365_fo
_DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
_DEFAULT_QDRANT_URL = "http://localhost:6333"

# Repo root — two levels up from infra/scripts/
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_capabilities(product: str, source: str) -> list[dict]:
    """Load capabilities from capabilities_{source}.yaml.

    Capabilities are curated D365 features (module-scoped, structured).
    Uses hybrid retrieval (dense embeddings + BM25 sparse keywords).
    Text field is mapped to 'description' in the capability collection payload.
    """
    yaml_path = (
        _REPO_ROOT / "knowledge_bases" / product / f"capabilities_{source}.yaml"
    )
    if not yaml_path.exists():
        print(f"ERROR: YAML not found: {yaml_path}", file=sys.stderr)
        sys.exit(1)
    with yaml_path.open() as f:
        data = yaml.safe_load(f)
    caps: list[dict] = data.get("capabilities", [])
    if not caps:
        print(f"ERROR: No capabilities found in {yaml_path}", file=sys.stderr)
        sys.exit(1)
    return caps


def _load_docs(product: str, source: str) -> list[dict]:
    """Load MS Learn documentation from docs_corpus_{source}.yaml.

    Docs corpus is raw Microsoft Learn documentation (broad scope, semantic search).
    Uses dense-only retrieval (no BM25 sparse, no module filter) for cross-module insights.
    Returns empty list if the file does not exist — docs are optional.
    """
    yaml_path = _REPO_ROOT / "knowledge_bases" / product / f"docs_corpus_{source}.yaml"
    if not yaml_path.exists():
        return []
    with yaml_path.open() as f:
        data = yaml.safe_load(f)
    return data.get("docs", [])


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Qdrant with capability and docs embeddings.")
    parser.add_argument("--product", required=True, help="Product ID (e.g. d365_fo)")
    parser.add_argument(
        "--source",
        default="lite",
        choices=["lite", "full"],
        help="YAML source variant",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate collections before seeding",
    )
    parser.add_argument(
        "--qdrant-url",
        default=os.environ.get("QDRANT_URL", _DEFAULT_QDRANT_URL),
        help="Qdrant server URL",
    )
    args = parser.parse_args()

    cap_collection = f"{args.product}_capabilities"
    doc_collection = f"{args.product}_docs"

    # 1. Load YAMLs (separated files: capabilities + docs_corpus)
    print(
        f"Loading knowledge_bases/{args.product}/"
        f"(capabilities_{args.source}.yaml + docs_corpus_{args.source}.yaml) ..."
    )
    caps = _load_capabilities(args.product, args.source)
    cap_descriptions = [c["text"] for c in caps]
    print(f"  {len(caps)} capabilities loaded")

    docs = _load_docs(args.product, args.source)
    doc_texts = [d["text"] for d in docs]
    print(f"  {len(docs)} docs loaded")

    # 2. BM25 indices — separate corpora for IDF weighting
    print("Building BM25 indices ...")
    cap_bm25 = BM25Retriever(corpus=cap_descriptions)
    doc_bm25 = BM25Retriever(corpus=doc_texts) if doc_texts else None

    # 3. Embedder — lazy-loads model on first encode call
    print(f"Loading embedder ({_DEFAULT_EMBEDDING_MODEL}) ...")
    embedder = Embedder(_DEFAULT_EMBEDDING_MODEL)

    # 4. VectorStore — connect to Qdrant
    print(f"Connecting to Qdrant at {args.qdrant_url} ...")
    store = VectorStore(args.qdrant_url)

    cfg = CollectionConfig(size=384, distance="cosine", sparse=True)

    # ── Capabilities ──────────────────────────────────────────────────────────
    if args.reset:
        print(f"  --reset: dropping collection '{cap_collection}' ...")
        store.recreate_collection(cap_collection, cfg)
        print(f"  Collection '{cap_collection}' recreated.")
    else:
        store.ensure_collection(cap_collection, cfg)
        print(f"  Collection '{cap_collection}' ensured.")

    print(f"Embedding {len(cap_descriptions)} capability descriptions ...")
    cap_vecs = embedder.embed_batch(cap_descriptions)

    cap_points: list[Point] = []
    for cap, vec, desc in zip(caps, cap_vecs, cap_descriptions, strict=True):
        si, sv = cap_bm25.encode(desc)
        cap_points.append(
            Point(
                id=cap["id"],
                dense_vector=vec,
                payload={
                    "module": cap["module"],
                    "feature": cap["feature"],
                    "description": desc,
                },
                sparse_indices=si,
                sparse_values=sv,
            )
        )

    print(f"Upserting {len(cap_points)} points into '{cap_collection}' ...")
    store.upsert(cap_collection, cap_points)
    print(f"  Seeded {len(cap_points)} capabilities.")

    # ── Docs ──────────────────────────────────────────────────────────────────
    if args.reset:
        print(f"  --reset: dropping collection '{doc_collection}' ...")
        store.recreate_collection(doc_collection, cfg)
        print(f"  Collection '{doc_collection}' recreated.")
    else:
        store.ensure_collection(doc_collection, cfg)
        print(f"  Collection '{doc_collection}' ensured.")

    if docs and doc_bm25:
        print(f"Embedding {len(doc_texts)} doc texts ...")
        doc_vecs = embedder.embed_batch(doc_texts)

        doc_points: list[Point] = []
        for doc, vec, text in zip(docs, doc_vecs, doc_texts, strict=True):
            si, sv = doc_bm25.encode(text)
            doc_points.append(
                Point(
                    id=doc["id"],
                    dense_vector=vec,
                    payload={
                        "module": doc.get("module", ""),
                        "feature": doc.get("feature", ""),
                        "title": doc["title"],
                        "url": doc["url"],
                        "text": text,
                    },
                    sparse_indices=si,
                    sparse_values=sv,
                )
            )

        print(f"Upserting {len(doc_points)} points into '{doc_collection}' ...")
        store.upsert(doc_collection, doc_points)
        print(f"  Seeded {len(doc_points)} docs.")
    elif docs:
        # docs exist but doc_bm25 is None (shouldn't happen)
        print(
            f"ERROR: docs loaded ({len(docs)}) but BM25 index creation failed",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        # No docs to seed (docs file empty)
        print(f"  No docs to seed — '{doc_collection}' collection created empty.")

    # ── Verification ──────────────────────────────────────────────────────────
    print("\nVerifying collections in Qdrant ...")
    try:
        cap_count = store.collection_point_count(cap_collection)
        doc_count = store.collection_point_count(doc_collection)
        print(f"  {cap_collection}: {cap_count} points")
        print(f"  {doc_collection}: {doc_count} points")

        if cap_count == 0:
            print(
                f"ERROR: {cap_collection} has 0 points — seeding failed",
                file=sys.stderr,
            )
            sys.exit(1)
        if len(docs) > 0 and doc_count == 0:
            print(
                f"ERROR: {doc_collection} has 0 points but docs exist in YAML"
                f" — seeding failed",
                file=sys.stderr,
            )
            sys.exit(1)
    except Exception as exc:
        print(
            f"ERROR: Failed to verify collections: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"\nDone: {len(cap_points)} capabilities + {len(docs)} docs "
        f"seeded to Qdrant at {args.qdrant_url}"
    )


if __name__ == "__main__":
    main()

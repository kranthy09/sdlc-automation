"""
Seed script — populate Qdrant with D365 F&O capability embeddings.

Usage:
    uv run python -m infra.scripts.seed_knowledge_base --product d365_fo
    uv run python -m infra.scripts.seed_knowledge_base --product d365_fo --source lite --reset

Options:
    --product   Product ID (required). Used to locate knowledge_bases/{product}/ and name the collection.
    --source    'lite' (default) or 'full'. Determines which YAML file is loaded.
    --reset     Drop and recreate the collection before seeding (full data wipe).
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
    """Load capability dicts from knowledge_bases/{product}/capabilities_{source}.yaml."""
    yaml_path = (
        _REPO_ROOT
        / "knowledge_bases"
        / product
        / f"capabilities_{source}.yaml"
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed Qdrant with capability embeddings."
    )
    parser.add_argument(
        "--product", required=True, help="Product ID (e.g. d365_fo)"
    )
    parser.add_argument(
        "--source",
        default="lite",
        choices=["lite", "full"],
        help="YAML source variant",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate collection before seeding",
    )
    parser.add_argument(
        "--qdrant-url",
        default=os.environ.get("QDRANT_URL", _DEFAULT_QDRANT_URL),
        help="Qdrant server URL",
    )
    args = parser.parse_args()

    collection = f"{args.product}_capabilities"

    # 1. Load YAML
    print(
        f"Loading knowledge_bases/{args.product}/capabilities_{args.source}.yaml ..."
    )
    caps = _load_capabilities(args.product, args.source)
    descriptions = [c["description"] for c in caps]
    print(f"  {len(caps)} capabilities loaded")

    # 2. BM25 — fit on all descriptions for IDF weighting
    print("Building BM25 index ...")
    bm25 = BM25Retriever(corpus=descriptions)

    # 3. Embedder — lazy-loads model on first encode call
    print(f"Loading embedder ({_DEFAULT_EMBEDDING_MODEL}) ...")
    embedder = Embedder(_DEFAULT_EMBEDDING_MODEL)

    # 4. VectorStore — connect to Qdrant
    print(f"Connecting to Qdrant at {args.qdrant_url} ...")
    store = VectorStore(args.qdrant_url)

    # 5. Create / recreate collection
    cfg = CollectionConfig(size=384, distance="cosine", sparse=True)
    if args.reset:
        print(f"  --reset: dropping collection '{collection}' ...")
        store.recreate_collection(collection, cfg)
        print(f"  Collection '{collection}' recreated.")
    else:
        store.ensure_collection(collection, cfg)
        print(f"  Collection '{collection}' ensured.")

    # 6. Batch-embed all descriptions
    print(
        f"Embedding {len(descriptions)} descriptions (this may take a minute on first run) ..."
    )
    dense_vectors = embedder.embed_batch(descriptions)

    # 7. Build Points
    points: list[Point] = []
    for cap, dense_vec, desc in zip(
        caps, dense_vectors, descriptions, strict=True
    ):
        sparse_indices, sparse_values = bm25.encode(desc)
        points.append(
            Point(
                id=cap["id"],
                dense_vector=dense_vec,
                payload={
                    "module": cap["module"],
                    "feature": cap["feature"],
                    "description": desc,
                },
                sparse_indices=sparse_indices,
                sparse_values=sparse_values,
            )
        )

    # 8. Upsert
    print(f"Upserting {len(points)} points into '{collection}' ...")
    store.upsert(collection, points)

    print(
        f"\nSeeded {len(points)} capabilities to '{collection}' in Qdrant at {args.qdrant_url}"
    )


if __name__ == "__main__":
    main()

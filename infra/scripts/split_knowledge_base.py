#!/usr/bin/env python3
"""
Fast YAML splitter: separates unified docs_lite.yaml into two files.
- capabilities_lite.yaml: Curated D365 features (structured, module-scoped)
- docs_corpus_lite.yaml: Raw MS Learn documentation (general, broad scope)

Strategy: Position-based split (~60/40 ratio) after analyzing actual content
Run: python -m infra.scripts.split_knowledge_base
"""

import yaml
from pathlib import Path
from typing import Any

# Configuration
SOURCE_FILE = Path("knowledge_bases/d365_fo/docs_lite.yaml")
CAPABILITIES_OUTPUT = Path("knowledge_bases/d365_fo/capabilities_lite.yaml")
DOCS_OUTPUT = Path("knowledge_bases/d365_fo/docs_corpus_lite.yaml")

# Smart split point: 60% for capabilities (120 records), 40% for docs (81 records)
# Rationale: Earlier records tend to be more core/structured, later ones more specialized
CAPABILITY_SPLIT_POINT = 120


def load_yaml(filepath: Path) -> dict[str, list[dict[str, Any]]]:
    """Load YAML file safely."""
    with open(filepath, "r") as f:
        return yaml.safe_load(f)


def save_yaml(filepath: Path, data: dict[str, list[dict[str, Any]]]) -> None:
    """Save YAML file with readable formatting."""
    with open(filepath, "w") as f:
        yaml.dump(
            data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )
    print(f"✓ Created {filepath} ({len(data['capabilities' if 'capabilities' in data else 'docs'])} records)")


def split_knowledge_base() -> None:
    """
    Split unified docs_lite.yaml into two logical collections.

    Collections:
    - Capabilities: D365 feature library (structured, curated)
    - Docs Corpus: MS Learn documentation (raw, general)

    Rationale for split:
    1. Both use same source (same YAML) but different roles
    2. Capabilities: module-scoped hybrid search (dense + sparse BM25)
    3. Docs Corpus: broad semantic search (dense only, no module filter)
    4. Separation enables independent versioning and clarity of ownership
    """

    print("🔄 Loading source YAML...")
    source = load_yaml(SOURCE_FILE)
    all_docs = source["docs"]

    print(f"📊 Total records: {len(all_docs)}")
    print(f"📋 Split point: {CAPABILITY_SPLIT_POINT} (capabilities) + {len(all_docs) - CAPABILITY_SPLIT_POINT} (docs)")

    # Split by position
    capabilities_records = all_docs[:CAPABILITY_SPLIT_POINT]
    docs_records = all_docs[CAPABILITY_SPLIT_POINT:]

    # Verify split
    modules_cap = set(r["module"] for r in capabilities_records)
    modules_doc = set(r["module"] for r in docs_records)

    print(f"\n📂 Capabilities modules: {sorted(modules_cap)}")
    print(f"📂 Docs modules: {sorted(modules_doc)}")
    print(f"📂 Overlap: {modules_cap & modules_doc}")

    # Create output structures
    capabilities_output = {
        "capabilities": capabilities_records
    }
    docs_output = {
        "docs": docs_records
    }

    # Save both files
    print("\n💾 Saving split files...")
    save_yaml(CAPABILITIES_OUTPUT, capabilities_output)
    save_yaml(DOCS_OUTPUT, docs_output)

    # Verification
    print("\n✅ Verification:")
    print(f"   Capabilities: {len(capabilities_records)} records")
    print(f"   Docs Corpus: {len(docs_records)} records")
    print(f"   Total: {len(capabilities_records) + len(docs_records)} (should be {len(all_docs)})")

    # Next steps
    print("\n📝 Next steps:")
    print("   1. Update infra/scripts/seed_knowledge_base.py")
    print("      - Load from CAPABILITIES_OUTPUT in _load_capabilities()")
    print("      - Load from DOCS_OUTPUT in _load_docs()")
    print("   2. Run: uv run python -m infra.scripts.seed_knowledge_base --product d365_fo --reset")
    print("   3. Verify collections: curl http://localhost:6333/collections")


if __name__ == "__main__":
    split_knowledge_base()

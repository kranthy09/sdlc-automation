from qdrant_client import QdrantClient

from platforms.retrieval.embedder import embed

COLLECTION = "demo_chunks"

query = "How do we do three-way invoice matching?"
client = QdrantClient(host="localhost", port=6333)

hits = client.search(
    collection_name=COLLECTION,
    query_vector=embed(query),
    limit=3,
    with_payload=True,
)

for h in hits:
    print("score:", h.score, "text:", (h.payload or {}).get("text"))

from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct

from platforms.retrieval.embedder import embed

COLLECTION = "demo_chunks"

texts = [
    "The system shall validate three-way matching for vendor invoices.",
    "The system shall allow posting journal entries to the general ledger.",
    "The system shall support vendor master data creation and updates.",
]

client = QdrantClient(host="localhost", port=6333)

points = []
for i, t in enumerate(texts, start=1):
    vec = embed(t)  # list[float], length should be 1024 for bge-large
    points.append(
        PointStruct(
            id=i,
            vector=vec,
            payload={"text": t},
        )
    )

client.upsert(collection_name=COLLECTION, points=points)
print(f"Upserted {len(points)} points into {COLLECTION}")

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

COLLECTION = "demo_chunks"
VECTOR_SIZE = 1024  # bge-large-en-v1.5

client = QdrantClient(host="localhost", port=6333)

if client.collection_exists(COLLECTION):
    print("Collection already exists:", COLLECTION)
else:
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )
    print("Created collection:", COLLECTION)

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

client = QdrantClient(host="localhost", port=6333)

VECTOR_SIZE = 384  # all-MiniLM-L6-v2

if not client.collection_exists("activity_chunks"):
    client.create_collection(
        collection_name="activity_chunks",
        vectors_config=VectorParams(
            size=VECTOR_SIZE,
            distance=Distance.COSINE
        )
    )
    print("Qdrant collection 'activity_chunks' created!")
else:
    print("Qdrant collection 'activity_chunks' already exists!")

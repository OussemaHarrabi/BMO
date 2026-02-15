from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

neo4j_driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", "password")
)
qdrant_client = QdrantClient(host="localhost", port=6333)
embedder = SentenceTransformer("all-MiniLM-L6-v2")

COLLECTION = "activity_chunks"

TEST_QUERIES = [
    "Where did I see that merge conflict?",
    "What file was I editing for the dashboard?",
    "Show me authentication related work",
    "What was I doing with the database?",
    "shopping cart bug fix",
]


def search_qdrant(query, top_k=3):
    query_vector = embedder.encode(query).tolist()
    results = qdrant_client.query_points(
        collection_name=COLLECTION,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    )
    return results.points


def get_neo4j_context(tx, activity_id):
    result = tx.run(
        """
        MATCH (a:UserActivity {id: $aid})
        OPTIONAL MATCH (a)-[:TOUCHED_FILE]->(f:File)
        OPTIONAL MATCH (a)-[:IN_FOLDER]->(fo:Folder)
        OPTIONAL MATCH (a)-[:HAS_CAPTURE]->(s:ScreenCapture)
        OPTIONAL MATCH (a)-[:HAS_SUMMARY]->(su:Summary)
        RETURN a.type AS type, a.timestamp AS timestamp, a.description AS description,
               f.name AS file_name, f.path AS file_path,
               fo.name AS folder_name, fo.path AS folder_path,
               s.ocr_text AS ocr_text,
               su.text AS summary_text
        """,
        aid=activity_id,
    )
    return result.single()


SEPARATOR = "=" * 70

print(f"\n{SEPARATOR}")
print("  ACTIVITY TRACKER - Semantic Search + Graph Lookup")
print(SEPARATOR)

for query in TEST_QUERIES:
    print(f"\n  QUERY: \"{query}\"")
    print(f"  {'-' * 60}")

    hits = search_qdrant(query)

    for rank, hit in enumerate(hits, 1):
        activity_id = hit.payload["activity_id"]
        score = hit.score

        with neo4j_driver.session() as session:
            ctx = session.execute_read(get_neo4j_context, activity_id)

        print(f"\n  #{rank} (score: {score:.4f}) [{ctx['type']}]")
        print(f"     {ctx['description']}")
        print(f"     Time: {ctx['timestamp']}")

        if ctx.get("file_name"):
            print(f"     File: {ctx['file_name']} -> {ctx['file_path']}")
        if ctx.get("folder_name"):
            print(f"     Folder: {ctx['folder_name']} ({ctx['folder_path']})")
        if ctx.get("ocr_text"):
            print(f"     OCR: {ctx['ocr_text']}")
        if ctx.get("summary_text"):
            print(f"     Summary: {ctx['summary_text']}")

    print()

print(SEPARATOR)
print("  All queries completed.")
print(SEPARATOR)

neo4j_driver.close()

import uuid
from datetime import datetime, timedelta

from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct
from sentence_transformers import SentenceTransformer

neo4j_driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", "password")
)
qdrant_client = QdrantClient(host="localhost", port=6333)
embedder = SentenceTransformer("all-MiniLM-L6-v2")

COLLECTION = "activity_chunks"

now = datetime.now()

MOCK_DATA = [
    {
        "activity_id": "act-001",
        "type": "file_edit",
        "timestamp": (now - timedelta(hours=2)).isoformat(),
        "description": "Edited the main dashboard component in React to add a new chart widget",
        "file": {"id": "file-001", "name": "Dashboard.tsx", "path": "/src/components/Dashboard.tsx"},
        "folder": {"id": "folder-001", "name": "components", "path": "/src/components"},
    },
    {
        "activity_id": "act-002",
        "type": "file_create",
        "timestamp": (now - timedelta(hours=1, minutes=45)).isoformat(),
        "description": "Created a new Python script for data preprocessing and CSV parsing",
        "file": {"id": "file-002", "name": "preprocess.py", "path": "/scripts/preprocess.py"},
        "folder": {"id": "folder-002", "name": "scripts", "path": "/scripts"},
    },
    {
        "activity_id": "act-003",
        "type": "screen_capture",
        "timestamp": (now - timedelta(hours=1, minutes=30)).isoformat(),
        "description": "Screenshot of VS Code showing a merge conflict in the authentication module",
        "screen_capture": {"id": "cap-001", "ocr_text": "git merge conflict auth.py line 42 def verify_token"},
    },
    {
        "activity_id": "act-004",
        "type": "file_edit",
        "timestamp": (now - timedelta(hours=1)).isoformat(),
        "description": "Updated the database migration script to add user preferences table",
        "file": {"id": "file-003", "name": "migration_025.sql", "path": "/db/migrations/migration_025.sql"},
        "folder": {"id": "folder-003", "name": "migrations", "path": "/db/migrations"},
    },
    {
        "activity_id": "act-005",
        "type": "screen_capture",
        "timestamp": (now - timedelta(minutes=45)).isoformat(),
        "description": "Browser tab showing Neo4j documentation about graph traversal queries",
        "screen_capture": {"id": "cap-002", "ocr_text": "Neo4j Cypher MATCH RETURN graph traversal pattern matching"},
    },
    {
        "activity_id": "act-006",
        "type": "file_edit",
        "timestamp": (now - timedelta(minutes=30)).isoformat(),
        "description": "Modified the API endpoint for user login to support OAuth2 flow",
        "file": {"id": "file-004", "name": "auth_routes.py", "path": "/api/routes/auth_routes.py"},
        "folder": {"id": "folder-004", "name": "routes", "path": "/api/routes"},
    },
    {
        "activity_id": "act-007",
        "type": "summary",
        "timestamp": (now - timedelta(minutes=15)).isoformat(),
        "description": "AI summary: User spent the last 2 hours working on frontend dashboard, data pipeline, and authentication improvements",
        "summary": {"id": "sum-001", "text": "Frontend dashboard chart widget, Python data preprocessing, OAuth2 login flow, database migration for user preferences"},
    },
    {
        "activity_id": "act-008",
        "type": "file_edit",
        "timestamp": (now - timedelta(minutes=10)).isoformat(),
        "description": "Fixed a bug in the shopping cart calculation where discount was applied twice",
        "file": {"id": "file-005", "name": "cart.js", "path": "/src/utils/cart.js"},
        "folder": {"id": "folder-005", "name": "utils", "path": "/src/utils"},
    },
]


def insert_neo4j(tx, record):
    tx.run(
        """
        MERGE (a:UserActivity {id: $act_id})
        SET a.type = $type, a.timestamp = $ts, a.description = $desc
        """,
        act_id=record["activity_id"],
        type=record["type"],
        ts=record["timestamp"],
        desc=record["description"],
    )

    if "file" in record:
        f = record["file"]
        tx.run(
            """
            MERGE (f:File {id: $fid})
            SET f.name = $name, f.path = $path
            WITH f
            MATCH (a:UserActivity {id: $act_id})
            MERGE (a)-[:TOUCHED_FILE]->(f)
            """,
            fid=f["id"], name=f["name"], path=f["path"], act_id=record["activity_id"],
        )

    if "folder" in record:
        fo = record["folder"]
        tx.run(
            """
            MERGE (fo:Folder {id: $foid})
            SET fo.name = $name, fo.path = $path
            WITH fo
            MATCH (a:UserActivity {id: $act_id})
            MERGE (a)-[:IN_FOLDER]->(fo)
            """,
            foid=fo["id"], name=fo["name"], path=fo["path"], act_id=record["activity_id"],
        )

    if "file" in record and "folder" in record:
        tx.run(
            """
            MATCH (f:File {id: $fid}), (fo:Folder {id: $foid})
            MERGE (f)-[:LOCATED_IN]->(fo)
            """,
            fid=record["file"]["id"], foid=record["folder"]["id"],
        )

    if "screen_capture" in record:
        sc = record["screen_capture"]
        tx.run(
            """
            MERGE (s:ScreenCapture {id: $sid})
            SET s.ocr_text = $ocr
            WITH s
            MATCH (a:UserActivity {id: $act_id})
            MERGE (a)-[:HAS_CAPTURE]->(s)
            """,
            sid=sc["id"], ocr=sc["ocr_text"], act_id=record["activity_id"],
        )

    if "summary" in record:
        su = record["summary"]
        tx.run(
            """
            MERGE (su:Summary {id: $suid})
            SET su.text = $text
            WITH su
            MATCH (a:UserActivity {id: $act_id})
            MERGE (a)-[:HAS_SUMMARY]->(su)
            """,
            suid=su["id"], text=su["text"], act_id=record["activity_id"],
        )


def build_embed_text(record):
    parts = [record["description"]]
    if "file" in record:
        parts.append(f"file: {record['file']['name']} at {record['file']['path']}")
    if "screen_capture" in record:
        parts.append(f"OCR: {record['screen_capture']['ocr_text']}")
    if "summary" in record:
        parts.append(f"summary: {record['summary']['text']}")
    return " | ".join(parts)


print("=== Ingesting mock data ===\n")

texts_to_embed = []
point_ids = []
payloads = []

for record in MOCK_DATA:
    text = build_embed_text(record)
    texts_to_embed.append(text)
    point_ids.append(record["activity_id"])
    payloads.append({
        "activity_id": record["activity_id"],
        "type": record["type"],
        "timestamp": record["timestamp"],
        "description": record["description"],
        "text": text,
    })

print(f"Generating embeddings for {len(texts_to_embed)} records...")
vectors = embedder.encode(texts_to_embed).tolist()
print("Embeddings generated.")

print("Inserting into Neo4j...")
with neo4j_driver.session() as session:
    for record in MOCK_DATA:
        session.execute_write(insert_neo4j, record)
print(f"Neo4j: {len(MOCK_DATA)} activities inserted with relationships.")

print("Inserting into Qdrant...")
points = [
    PointStruct(id=idx, vector=vec, payload=pay)
    for idx, (vec, pay) in enumerate(zip(vectors, payloads))
]
qdrant_client.upsert(collection_name=COLLECTION, points=points)
print(f"Qdrant: {len(points)} vectors inserted.")

print("\n=== Ingestion complete ===")
neo4j_driver.close()

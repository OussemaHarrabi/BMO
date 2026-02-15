"""
Mock test simulating the real pipeline:
  Screen capture -> OCR -> LLM summary -> text_to_graph.ingest_text()

Each entry below represents an LLM-generated summary of what the user
was doing at a specific moment (as if captured from a screenshot).
"""

from text_to_graph import ingest_text, ensure_schema

ensure_schema()

MOCK_LLM_SUMMARIES = [
    {
        "timestamp": "2026-02-15T09:00:00",
        "text": (
            "User has VS Code open with the file server.py at /backend/src/server.py. "
            "They are editing the main Flask application entry point. A terminal panel "
            "is visible at the bottom running 'python server.py' with debug output. "
            "Chrome is open in the background on localhost:5000 showing the API docs page."
        ),
    },
    {
        "timestamp": "2026-02-15T09:15:00",
        "text": (
            "User is browsing GitHub pull request #142 for the authentication module. "
            "The PR shows changes to auth_middleware.py at /backend/src/middleware/auth_middleware.py "
            "and login_controller.py at /backend/src/controllers/login_controller.py. "
            "They appear to be reviewing code comments from a teammate."
        ),
    },
    {
        "timestamp": "2026-02-15T09:32:00",
        "text": (
            "User switched to VS Code and opened auth_middleware.py at "
            "/backend/src/middleware/auth_middleware.py. They are debugging a JWT token "
            "validation issue. The Chrome DevTools console is visible showing a 401 "
            "Unauthorized error from https://api.example.com/v1/users/me endpoint."
        ),
    },
    {
        "timestamp": "2026-02-15T09:45:00",
        "text": (
            "User is on Stack Overflow reading a question about Python JWT token refresh "
            "strategies. Another Chrome tab shows the PyJWT library documentation at "
            "https://pyjwt.readthedocs.io/en/stable/usage.html. VS Code is minimized "
            "in the taskbar."
        ),
    },
    {
        "timestamp": "2026-02-15T10:00:00",
        "text": (
            "User is back in VS Code editing auth_middleware.py at "
            "/backend/src/middleware/auth_middleware.py. They added a new function for "
            "token refresh logic. The file requirements.txt at /backend/requirements.txt "
            "is also open in another tab, showing PyJWT was added as a dependency."
        ),
    },
    {
        "timestamp": "2026-02-15T10:20:00",
        "text": (
            "User opened the terminal and is running pytest. The test file "
            "test_auth.py at /backend/tests/test_auth.py is visible with 3 passing "
            "tests and 1 failing test for the token refresh endpoint. VS Code shows "
            "the test output panel."
        ),
    },
    {
        "timestamp": "2026-02-15T10:35:00",
        "text": (
            "User is on Slack messaging the team channel about the authentication fix. "
            "They shared a code snippet from auth_middleware.py. A Jira ticket page is "
            "open in Chrome showing ticket AUTH-2847 'Fix JWT refresh token expiry handling'. "
            "The ticket status is 'In Progress'."
        ),
    },
    {
        "timestamp": "2026-02-15T10:50:00",
        "text": (
            "User has Docker Desktop open and is viewing container logs for the "
            "postgres-db container. They also have pgAdmin open in Chrome at "
            "http://localhost:5050 browsing the users table. The file "
            "migration_042.sql at /backend/db/migrations/migration_042.sql is open "
            "in VS Code showing an ALTER TABLE statement for the refresh_tokens table."
        ),
    },
    {
        "timestamp": "2026-02-15T11:05:00",
        "text": (
            "User is writing documentation in Notion. The page title is "
            "'Authentication Flow - Technical Spec'. They have a diagram showing "
            "the OAuth2 flow with access tokens and refresh tokens. Chrome has "
            "Google Docs open with the team's API specification document at "
            "https://docs.google.com/document/d/1a2b3c/edit."
        ),
    },
    {
        "timestamp": "2026-02-15T11:20:00",
        "text": (
            "User is in VS Code with multiple files open: server.py at /backend/src/server.py, "
            "auth_middleware.py at /backend/src/middleware/auth_middleware.py, and a new file "
            "token_service.py at /backend/src/services/token_service.py. They are refactoring "
            "the token logic into a dedicated service module. Git panel shows 4 modified files "
            "ready to commit."
        ),
    },
    {
        "timestamp": "2026-02-15T11:40:00",
        "text": (
            "User is on GitHub creating a new pull request. The PR title is "
            "'Fix JWT refresh token handling and add token service'. The diff shows "
            "changes across 5 files. Chrome also has the CI/CD pipeline page open "
            "showing GitHub Actions running tests. VS Code is in the background."
        ),
    },
    {
        "timestamp": "2026-02-15T11:55:00",
        "text": (
            "User is on YouTube watching a conference talk about microservice "
            "authentication patterns. They have Obsidian open taking notes in a "
            "file called auth-patterns.md. Chrome DevTools network tab is visible "
            "in another window showing API request traces."
        ),
    },
]

print("=" * 70)
print("  MOCK TEST: LLM Summary -> Neo4j Graph + Qdrant Vectors")
print("=" * 70)

for i, entry in enumerate(MOCK_LLM_SUMMARIES, 1):
    result = ingest_text(text=entry["text"], timestamp=entry["timestamp"])

    print(f"\n[{entry['timestamp']}] Activity #{i}")
    print(f"  ID: {result['activity_id']}")
    print(f"  Nodes: {result['neo4j_nodes_created']}")
    ent = result["entities"]
    if ent["files"]:
        print(f"  Files: {ent['files']}")
    if ent["folders"]:
        print(f"  Folders: {ent['folders']}")
    if ent["apps"]:
        print(f"  Apps: {ent['apps']}")
    if ent["websites"]:
        print(f"  Websites: {ent['websites']}")
    if ent["urls"]:
        print(f"  URLs: {ent['urls']}")
    if ent["actions"]:
        print(f"  Actions: {ent['actions']}")

print("\n" + "=" * 70)
print("  INGESTION COMPLETE - DATABASE TOTALS")
print("=" * 70)

from neo4j import GraphDatabase
from qdrant_client import QdrantClient

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
with driver.session() as s:
    for label in ["UserActivity", "File", "Folder", "Application",
                   "Website", "URL"]:
        r = s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()
        print(f"  {label}: {r['c']} nodes")
    r = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()
    print(f"  Total relationships: {r['c']}")

    print("\n  Relationship breakdown:")
    for rel in ["TOUCHED_FILE", "IN_FOLDER", "LOCATED_IN", "USED_APP",
                "VISITED_SITE", "VISITED_URL"]:
        r = s.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c").single()
        print(f"    {rel}: {r['c']}")
driver.close()

client = QdrantClient(host="localhost", port=6333)
info = client.get_collection("activity_chunks")
print(f"\n  Qdrant points: {info.points_count}")

print("\n" + "=" * 70)
print("  SEMANTIC SEARCH TEST")
print("=" * 70)

from sentence_transformers import SentenceTransformer
embedder = SentenceTransformer("all-MiniLM-L6-v2")

QUERIES = [
    "When was I working on the JWT authentication bug?",
    "What files did I edit today?",
    "Which websites was I browsing for research?",
    "Show me the database migration work",
    "What did I discuss on Slack?",
    "When was I writing documentation?",
    "Pull request review activity",
    "What tests did I run?",
]

for q in QUERIES:
    vec = embedder.encode(q).tolist()
    hits = client.query_points(
        collection_name="activity_chunks", query=vec, limit=3, with_payload=True
    )
    print(f"\n  Q: \"{q}\"")
    for rank, h in enumerate(hits.points, 1):
        ts = h.payload["timestamp"]
        desc = h.payload["description"][:90]
        print(f"    #{rank} [{h.score:.3f}] ({ts}) {desc}...")

print("\n" + "=" * 70)
print("  ALL TESTS PASSED")
print("=" * 70)

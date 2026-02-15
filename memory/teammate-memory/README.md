# Activity Tracking Backend - Neo4j + Qdrant Module

## Overview

This module is the **storage and search backend** for the team's activity tracking platform. It receives LLM-generated text summaries (produced from OCR'd screen captures) and:

1. **Parses** entities from the text (files, apps, websites, URLs, actions)
2. **Creates a knowledge graph** in Neo4j (nodes + relationships)
3. **Stores semantic embeddings** in Qdrant (384-dim vectors for natural language search)

### Where This Fits in the Full Pipeline

```
 [Data Collection Team Member]         [This Module]                [Query Layer]
 +--------------------------+     +----------------------+     +------------------+
 | Screen Capture           |     | text_to_graph.py     |     | Semantic Search  |
 | --> OCR                  | --> | - Entity extraction   | --> | (Qdrant vectors) |
 | --> LLM Summary Text     |     | - Neo4j graph nodes  |     | Graph Traversal  |
 +--------------------------+     | - Qdrant embeddings  |     | (Neo4j Cypher)   |
                                  +----------------------+     +------------------+
```

- **Input**: Plain text string (LLM summary of a screen capture)
- **Output**: Structured graph in Neo4j + searchable vectors in Qdrant
- **Integration point**: `ingest_text()` function in `text_to_graph.py`

---

## Project Structure

```
sss/
|-- Neo4j/
|   +-- app.py                    # Neo4j schema setup (5 uniqueness constraints)
|-- AI_minds/
|   |-- main.py                   # Qdrant collection setup (384-dim, Cosine)
|   +-- qdrant_storage/           # Qdrant local data storage
|-- text_to_graph.py              # CORE MODULE - LLM text --> Neo4j + Qdrant
|-- test_mock_pipeline.py         # Full pipeline test (12 realistic activities)
|-- ingest_mock_data.py           # Initial mock data test (8 activities)
|-- query_test.py                 # Semantic search + graph lookup test
|-- neo4j-graph-view.png          # Screenshot: Neo4j graph visualization
|-- neo4j-connected.png           # Screenshot: Neo4j browser connection
+-- qdrant-dashboard.png          # Screenshot: Qdrant dashboard
```

---

## Infrastructure Requirements

### Docker Containers

| Service | Container Name     | Ports                          | Version    |
|---------|--------------------|--------------------------------|------------|
| Neo4j   | `nervous_blackburn`| 7474 (browser), 7687 (bolt)    | 2026.01.4  |
| Qdrant  | `nervous_blackwell`| 6333 (API + dashboard)         | latest     |

**Neo4j credentials**: `neo4j` / `password`

### Start Containers

```bash
docker start nervous_blackburn    # Neo4j
docker start nervous_blackwell    # Qdrant
```

### Browser Dashboards

- **Neo4j Browser**: http://localhost:7474
- **Qdrant Dashboard**: http://localhost:6333/dashboard

### Python Environment

- **Python 3.11** required (run with `py -3.11` on this machine)
- System `python` points to Python 3.12 (msys64) but packages are installed on 3.11

### Python Dependencies

```
neo4j
qdrant-client>=1.16.2
sentence-transformers
torch
```

Install with:
```bash
py -3.11 -m pip install neo4j qdrant-client sentence-transformers
```

---

## Core Module: text_to_graph.py

This is the main deliverable. It provides two public functions:

### `ensure_schema()`

Creates uniqueness constraints for `Application`, `Website`, and `URL` node types in Neo4j. Call once at startup.

```python
from text_to_graph import ensure_schema
ensure_schema()
```

### `ingest_text(text, timestamp=None, activity_id=None)`

Ingests a single LLM summary into both Neo4j and Qdrant.

**Parameters:**

| Parameter     | Type          | Required | Description                                   |
|---------------|---------------|----------|-----------------------------------------------|
| `text`        | `str`         | Yes      | The LLM-generated summary text                |
| `timestamp`   | `str or None` | No       | ISO 8601 timestamp (defaults to current time)  |
| `activity_id` | `str or None` | No       | Unique ID for this activity (auto-generated)   |

**Returns:**

```python
{
    "activity_id": "act-a1b2c3d4",
    "timestamp": "2026-02-15T09:00:00",
    "entities": {
        "files": ["auth_routes.py"],
        "folders": ["routes"],
        "apps": ["VS Code"],
        "websites": ["GitHub"],
        "urls": ["https://api.example.com/v1/users"],
        "actions": ["editing", "browsing"],
    },
    "neo4j_nodes_created": 6,
    "qdrant_point_id": 48372615940123,
}
```

**Usage:**

```python
from text_to_graph import ingest_text, ensure_schema

# Call once at startup
ensure_schema()

# Call for each LLM summary from the OCR pipeline
result = ingest_text(
    text="User is editing auth_routes.py in VS Code and browsing GitHub",
    timestamp="2026-02-15T09:00:00",
)

print(result["activity_id"])        # "act-a1b2c3d4"
print(result["entities"]["files"])  # ["auth_routes.py"]
print(result["neo4j_nodes_created"])# 5
```

---

## Entity Extraction

The module extracts entities from plain text using regex and heuristic matching. No external LLM calls are needed for extraction.

### What It Detects

| Entity Type | Method | Examples |
|------------|--------|---------|
| **Files** | Regex matching 50+ extensions | `auth_routes.py`, `Dashboard.tsx`, `migration_030.sql` |
| **Folders** | Extracted from file paths | `/api/routes/auth.py` --> folder `routes` |
| **Applications** | Keyword matching (50+ known apps) | VS Code, Chrome, Docker, Slack, Postman |
| **Websites** | Keyword matching (30+ known sites) + domain patterns | GitHub, Stack Overflow, Google Docs |
| **URLs** | Full URL regex | `https://docs.google.com/document/d/abc123` |
| **Actions** | Verb matching (40+ verbs) | editing, debugging, reviewing, deploying |

### Deduplication

- Each entity gets a **deterministic ID** via MD5 hash of its name: `_stable_id("file", "auth.py")` always produces the same ID
- Neo4j `MERGE` ensures the same entity mentioned across multiple activities creates only **one node**
- Multiple activities referencing the same file/app/website all connect to a single shared node

### Extending Entity Recognition

Edit these sections in `text_to_graph.py` to add more recognized entities:

| What to Add | Location in text_to_graph.py |
|------------|------------------------------|
| File extensions | `FILE_PATTERN` regex (line 59) |
| Applications | `KNOWN_APPS` list (line 81) |
| Websites | `KNOWN_WEBSITES` list (line 96) |
| Action verbs | `ACTION_VERBS` list (line 110) |

---

## Neo4j Graph Schema

### Node Labels

| Label | Properties | Description |
|-------|-----------|-------------|
| `UserActivity` | id, type, timestamp, description | A single captured user activity |
| `File` | id, name, path | A file the user interacted with |
| `Folder` | id, name, path | A directory containing files |
| `Application` | id, name | A desktop application used |
| `Website` | id, name | A website visited |
| `URL` | id, url, domain | A specific URL visited |
| `ScreenCapture` | id, ocr_text | OCR text from a screenshot |
| `Summary` | id, text | AI-generated summary text |

### Relationships

| Relationship | From --> To | Meaning |
|-------------|-------------|---------|
| `TOUCHED_FILE` | UserActivity --> File | User interacted with this file |
| `IN_FOLDER` | UserActivity --> Folder | Activity occurred in this directory |
| `LOCATED_IN` | File --> Folder | File lives inside this directory |
| `USED_APP` | UserActivity --> Application | User was using this application |
| `VISITED_SITE` | UserActivity --> Website | User visited this website |
| `VISITED_URL` | UserActivity --> URL | User visited this specific URL |
| `HAS_CAPTURE` | UserActivity --> ScreenCapture | Activity has an associated screenshot |
| `HAS_SUMMARY` | UserActivity --> Summary | Activity has an AI summary |

### Uniqueness Constraints (8 total)

| Created By | Constraints |
|-----------|-------------|
| `Neo4j/app.py` | UserActivity, File, Folder, ScreenCapture, Summary |
| `text_to_graph.ensure_schema()` | Application, Website, URL |

### Graph Visualization

The graph naturally reveals patterns like:
- Which files are always edited together
- Which applications are used for which types of work
- Which websites are visited during debugging vs. documentation
- Time-based activity sequences

---

## Qdrant Vector Store

### Collection: `activity_chunks`

| Property | Value |
|----------|-------|
| Dimensions | 384 |
| Distance metric | Cosine |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` (runs locally) |

### Point Payload Schema

Each Qdrant point stores this metadata alongside its vector:

```python
{
    "activity_id": "act-a1b2c3d4",   # Links to Neo4j UserActivity.id
    "type": "screen_activity",
    "timestamp": "2026-02-15T09:00:00",
    "description": "Full LLM summary text...",
    "files": ["auth_routes.py"],
    "apps": ["VS Code"],
    "websites": ["GitHub"],
    "actions": ["editing"],
}
```

### Cross-Linking with Neo4j

Every Qdrant point's `activity_id` matches a Neo4j `UserActivity` node's `id` property. This enables a two-step query pattern:

1. **Semantic search** in Qdrant: "When was I debugging authentication?" --> returns `activity_id`
2. **Graph traversal** in Neo4j using that `activity_id` --> returns all related files, apps, websites

---

## Querying the Data

### Semantic Search (Natural Language --> Qdrant)

```python
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient

embedder = SentenceTransformer("all-MiniLM-L6-v2")
client = QdrantClient(host="localhost", port=6333)

query_vector = embedder.encode("When was I debugging the auth bug?").tolist()
results = client.query_points(
    collection_name="activity_chunks",
    query=query_vector,
    limit=3,
    with_payload=True,
)

for hit in results.points:
    print(f"Score: {hit.score:.3f}")
    print(f"Activity: {hit.payload['description']}")
    print(f"Activity ID: {hit.payload['activity_id']}")
```

### Graph Traversal (Activity ID --> Neo4j)

```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))

with driver.session() as session:
    result = session.run("""
        MATCH (a:UserActivity {id: $aid})
        OPTIONAL MATCH (a)-[:TOUCHED_FILE]->(f:File)
        OPTIONAL MATCH (a)-[:USED_APP]->(app:Application)
        OPTIONAL MATCH (a)-[:VISITED_SITE]->(w:Website)
        RETURN a, collect(DISTINCT f) AS files,
               collect(DISTINCT app) AS apps,
               collect(DISTINCT w) AS websites
    """, aid="act-a1b2c3d4")
```

### Useful Cypher Queries

```cypher
-- All activities for a specific file
MATCH (a:UserActivity)-[:TOUCHED_FILE]->(f:File {name: "auth_middleware.py"})
RETURN a.timestamp, a.description
ORDER BY a.timestamp

-- All files touched while using a specific app
MATCH (a:UserActivity)-[:USED_APP]->(app:Application {name: "VS Code"})
MATCH (a)-[:TOUCHED_FILE]->(f:File)
RETURN DISTINCT f.name, f.path

-- Full activity context with all related entities
MATCH (a:UserActivity)
OPTIONAL MATCH (a)-[:TOUCHED_FILE]->(f:File)
OPTIONAL MATCH (a)-[:USED_APP]->(app:Application)
OPTIONAL MATCH (a)-[:VISITED_SITE]->(w:Website)
RETURN a.timestamp, a.description,
       collect(DISTINCT f.name) AS files,
       collect(DISTINCT app.name) AS apps,
       collect(DISTINCT w.name) AS websites
ORDER BY a.timestamp

-- Find related activities through shared files
MATCH (a1:UserActivity)-[:TOUCHED_FILE]->(f:File)<-[:TOUCHED_FILE]-(a2:UserActivity)
WHERE a1 <> a2
RETURN a1.description, f.name, a2.description

-- Activities within a time range
MATCH (a:UserActivity)
WHERE a.timestamp >= "2026-02-15T09:00:00"
  AND a.timestamp <= "2026-02-15T12:00:00"
RETURN a.timestamp, a.description
ORDER BY a.timestamp
```

---

## How to Run

### Step 1: Start Docker Containers

```bash
docker start nervous_blackburn    # Neo4j
docker start nervous_blackwell    # Qdrant
```

### Step 2: Initialize Schemas

```bash
py -3.11 Neo4j/app.py            # Creates 5 Neo4j uniqueness constraints
py -3.11 AI_minds/main.py        # Creates Qdrant collection (384-dim, Cosine)
```

### Step 3: Run the Mock Pipeline Test

```bash
py -3.11 test_mock_pipeline.py    # Ingests 12 activities + runs semantic search
```

### Step 4: Verify in Dashboards

- **Neo4j**: http://localhost:7474 -- run `MATCH (n) RETURN n LIMIT 50` to see the graph
- **Qdrant**: http://localhost:6333/dashboard -- check `activity_chunks` collection

---

## Test Results

### Mock Pipeline (test_mock_pipeline.py)

12 realistic LLM summaries simulating a developer's morning (9:00 AM - 11:55 AM) were ingested. The activities cover: code editing, PR reviews, debugging, Stack Overflow research, testing, Slack messaging, database migration, documentation, refactoring, creating PRs, and watching conference talks.

**Database totals after ingestion:**

| Entity | Count |
|--------|-------|
| UserActivity nodes | 12 |
| File nodes | 8 |
| Folder nodes | 7 |
| Application nodes | 9 |
| Website nodes | 5 |
| URL nodes | 4 |
| Total relationships | 65 |
| Qdrant vectors | 12 |

**Relationship breakdown:**

| Relationship | Count |
|-------------|-------|
| TOUCHED_FILE | 15 |
| IN_FOLDER | 15 |
| LOCATED_IN | 8 |
| USED_APP | 17 |
| VISITED_SITE | 7 |
| VISITED_URL | 3 |

### Semantic Search Results

All 8 test queries returned correct top results:

| Query | Top Result Score | Correct? |
|-------|-----------------|----------|
| "When was I working on the JWT authentication bug?" | 0.637 | Yes |
| "What files did I edit today?" | 0.520 | Yes |
| "Which websites was I browsing for research?" | 0.540 | Yes |
| "Show me the database migration work" | 0.605 | Yes |
| "What did I discuss on Slack?" | 0.567 | Yes |
| "When was I writing documentation?" | 0.571 | Yes |
| "Pull request review activity" | 0.582 | Yes |
| "What tests did I run?" | 0.556 | Yes |

---

## Integration Guide for Team Leader

### Minimal Integration

```python
from text_to_graph import ingest_text, ensure_schema

# One-time setup
ensure_schema()

# For each screen capture processed by the OCR + LLM pipeline:
llm_summary = "User is editing auth_routes.py in VS Code..."  # from LLM
capture_time = "2026-02-15T09:00:00"                           # from capture

result = ingest_text(text=llm_summary, timestamp=capture_time)

# result["activity_id"] can be stored for later lookups
# result["entities"] shows what was extracted
# result["neo4j_nodes_created"] confirms graph was updated
```

### Input Format

`ingest_text()` accepts **any plain text string**. It works best with descriptive LLM summaries like:

```
"User is editing auth_routes.py in VS Code and browsing GitHub"
"User has Docker Desktop running and is viewing container logs"
"User is on Stack Overflow reading about JWT token refresh strategies"
"User is on Slack messaging the team about the authentication fix"
```

### Configuration

Connection settings are defined at the top of `text_to_graph.py`:

```python
NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "password")
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION = "activity_chunks"
```

Update these if deploying to a different environment.

### Potential Next Steps

These are not yet implemented but can be added as needed:

1. **REST API wrapper** -- Wrap `ingest_text()` in a FastAPI/Flask endpoint for HTTP-based integration
2. **Query API** -- Expose semantic search + graph queries as HTTP endpoints
3. **Time-range filtering** -- Add Qdrant payload filters for time-based queries
4. **Web UI** -- Build a search interface for end users

---

## Technical Notes

| Topic | Detail |
|-------|--------|
| Neo4j constraint syntax | 2026.01.4 uses `FOR (n:Label) REQUIRE n.id IS UNIQUE` (old `ON/ASSERT` removed) |
| Neo4j transaction API | `session.write_transaction()` deprecated; uses `session.execute_write()` |
| qdrant-client 1.16.2 | Uses `create_collection`, `vectors_config=`, `Distance.COSINE` enum |
| Qdrant point IDs | Must be integers; activity_id strings hashed via `int(hashlib.md5(...).hexdigest()[:15], 16)` |
| Embedding model | `all-MiniLM-L6-v2` runs locally (first load downloads ~80MB model) |
| Windows console | Cannot print Unicode emojis; all output uses plain ASCII |
| Python version | Use `py -3.11` on this machine (system `python` points to 3.12/msys64) |

---

## Known Limitations

1. **Regex-based extraction** -- Entity detection uses pattern matching, not LLM-powered NER. Works well for structured summaries but may miss unusual entity names or formats.
2. **No REST API yet** -- Currently Python import only. Can be wrapped in FastAPI/Flask if the team leader needs HTTP endpoints.
3. **No time-range filtering** -- Semantic search returns results across all time. Can be added via Qdrant payload filters.
4. **First-load latency** -- The embedding model takes a few seconds to download on first run (~80MB).
5. **Single-user model** -- The current schema does not distinguish between different users. A `User` node can be added if multi-user support is needed.

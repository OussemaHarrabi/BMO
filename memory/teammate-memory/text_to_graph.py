"""
Text-to-Graph Ingestion Module
================================
Receives free-form LLM summary text (from OCR screen captures),
extracts entities, creates Neo4j graph nodes/relationships,
and stores embeddings in Qdrant for semantic search.

Usage:
    from text_to_graph import ingest_text
    result = ingest_text("User is editing auth_routes.py in VS Code and browsing GitHub")

    # Or run directly:
    # py -3.11 text_to_graph.py
"""

import re
import uuid
import hashlib
from datetime import datetime
from typing import Optional

from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct
from sentence_transformers import SentenceTransformer

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "password")
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION = "activity_chunks"

_neo4j_driver = None
_qdrant_client = None
_embedder = None


def _get_neo4j():
    global _neo4j_driver
    if _neo4j_driver is None:
        _neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    return _neo4j_driver


def _get_qdrant():
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    return _qdrant_client


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


FILE_PATTERN = re.compile(
    r'(?:^|[\s,;:(\["\'])('                            # boundary before match
    r'(?:[A-Za-z0-9_\-./\\]+\.(?:'                      # path chars + dot
    r'py|tsx|jsx|ts|js|html|css|scss|json|yaml|yml|'    # longer extensions first (tsx before ts)
    r'md|txt|sql|sh|bat|xml|csv|env|cfg|ini|toml|'
    r'java|cpp|h|go|rs|rb|php|vue|svelte|dart|'
    r'png|jpg|jpeg|gif|svg|pdf|docx|doc|xlsx|xls|pptx|ppt'
    r'))(?=[\s,;:)\]"\'.]|$)'                           # boundary after match (word-end)
    r')',
    re.IGNORECASE,
)

URL_PATTERN = re.compile(
    r'https?://[^\s,;)\]"\']+',
    re.IGNORECASE,
)

DOMAIN_PATTERN = re.compile(
    r'(?:^|[\s,;:(\["\'])((?:[a-zA-Z0-9-]+\.)+(?:com|org|net|io|dev|ai|co|app|edu|gov|me))',
    re.IGNORECASE,
)

KNOWN_APPS = [
    "VS Code", "VSCode", "Visual Studio Code", "Visual Studio",
    "Chrome", "Google Chrome", "Firefox", "Mozilla Firefox", "Safari",
    "Edge", "Microsoft Edge", "Brave",
    "Terminal", "PowerShell", "CMD", "Command Prompt", "Git Bash",
    "Notepad", "Notepad++", "Sublime Text", "Atom", "Vim", "Neovim",
    "IntelliJ", "PyCharm", "WebStorm", "Android Studio", "Xcode",
    "Slack", "Discord", "Teams", "Microsoft Teams", "Zoom",
    "Postman", "Insomnia", "Docker", "Docker Desktop",
    "Figma", "Photoshop", "Illustrator",
    "Word", "Excel", "PowerPoint", "Outlook",
    "Notion", "Obsidian", "Jira", "Confluence",
    "Spotify", "File Explorer", "Finder",
]

KNOWN_WEBSITES = [
    "GitHub", "GitLab", "Bitbucket",
    "Stack Overflow", "StackOverflow",
    "Google", "Google Docs", "Google Sheets", "Google Drive",
    "YouTube", "Reddit", "Twitter", "X.com",
    "ChatGPT", "Claude", "Copilot",
    "npm", "npmjs", "PyPI",
    "AWS", "Azure", "GCP", "Vercel", "Netlify", "Heroku",
    "MongoDB Atlas", "Neo4j Aura",
    "Wikipedia", "Medium", "Dev.to",
    "LinkedIn", "Facebook",
    "Trello", "Asana", "Monday",
]

ACTION_VERBS = [
    "editing", "edited", "edit",
    "creating", "created", "create",
    "opening", "opened", "open",
    "browsing", "browsed", "browse",
    "reading", "read",
    "writing", "wrote", "write",
    "debugging", "debugged", "debug",
    "searching", "searched", "search",
    "reviewing", "reviewed", "review",
    "committing", "committed", "commit",
    "pushing", "pushed", "push",
    "pulling", "pulled", "pull",
    "merging", "merged", "merge",
    "deploying", "deployed", "deploy",
    "testing", "tested", "test",
    "installing", "installed", "install",
    "downloading", "downloaded", "download",
    "uploading", "uploaded", "upload",
    "copying", "copied", "copy",
    "deleting", "deleted", "delete",
    "running", "ran", "run",
    "viewing", "viewed", "view",
    "watching", "watched", "watch",
    "chatting", "chatted", "chat",
    "messaging", "messaged", "message",
    "typing", "typed", "type",
    "scrolling", "scrolled", "scroll",
    "clicking", "clicked", "click",
    "navigating", "navigated", "navigate",
]


def _stable_id(prefix, value):
    """Generate a deterministic ID so repeated ingestion merges, not duplicates."""
    h = hashlib.md5(value.lower().strip().encode()).hexdigest()[:12]
    return f"{prefix}-{h}"


def extract_entities(text):
    """
    Parse free-form LLM summary text and extract structured entities.

    Returns dict with:
        files:    [{id, name, path}]
        folders:  [{id, name, path}]
        apps:     [{id, name}]
        websites: [{id, name, url}]
        urls:     [{id, url, domain}]
        actions:  [str]
    """
    entities = {
        "files": [],
        "folders": [],
        "apps": [],
        "websites": [],
        "urls": [],
        "actions": [],
    }

    seen_files = set()
    seen_folders = set()
    seen_apps = set()
    seen_websites = set()
    seen_urls = set()

    url_spans = set()
    for match in URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(".,;:)")
        for i in range(match.start(), match.start() + len(url)):
            url_spans.add(i)
        if url.lower() not in seen_urls:
            seen_urls.add(url.lower())
            domain_match = re.search(r'https?://([^/\s]+)', url)
            domain = domain_match.group(1) if domain_match else url
            entities["urls"].append({
                "id": _stable_id("url", url),
                "url": url,
                "domain": domain,
            })

    for match in FILE_PATTERN.finditer(text):
        if match.start(1) in url_spans:
            continue
        filepath = match.group(1).replace("\\", "/")
        filename = filepath.split("/")[-1]
        has_path = "/" in filepath

        if filename.lower() not in seen_files:
            seen_files.add(filename.lower())
            entities["files"].append({
                "id": _stable_id("file", filename),
                "name": filename,
                "path": filepath,
            })
        elif has_path:
            for f in entities["files"]:
                if f["name"].lower() == filename.lower() and "/" not in f["path"]:
                    f["path"] = filepath
                    break

        if has_path:
            folder_path = "/".join(filepath.split("/")[:-1])
            folder_name = folder_path.split("/")[-1] if folder_path else "root"
            if folder_path.lower() not in seen_folders:
                seen_folders.add(folder_path.lower())
                entities["folders"].append({
                    "id": _stable_id("folder", folder_path),
                    "name": folder_name,
                    "path": folder_path,
                })

    text_lower = text.lower()
    for app in KNOWN_APPS:
        if app.lower() in text_lower and app.lower() not in seen_apps:
            seen_apps.add(app.lower())
            entities["apps"].append({
                "id": _stable_id("app", app),
                "name": app,
            })

    for site in KNOWN_WEBSITES:
        if site.lower() in text_lower and site.lower() not in seen_websites:
            seen_websites.add(site.lower())
            entities["websites"].append({
                "id": _stable_id("website", site),
                "name": site,
            })

    for match in DOMAIN_PATTERN.finditer(text):
        domain = match.group(1).rstrip(".")
        if domain.lower() not in seen_websites and domain.lower() not in seen_urls:
            seen_websites.add(domain.lower())
            entities["websites"].append({
                "id": _stable_id("website", domain),
                "name": domain,
            })

    for verb in ACTION_VERBS:
        pattern = re.compile(r'\b' + re.escape(verb) + r'\b', re.IGNORECASE)
        if pattern.search(text):
            entities["actions"].append(verb)

    return entities


def _create_graph(tx, activity_id, text, timestamp, entities):
    tx.run(
        """
        MERGE (a:UserActivity {id: $aid})
        SET a.type = 'screen_activity',
            a.timestamp = $ts,
            a.description = $desc
        """,
        aid=activity_id, ts=timestamp, desc=text,
    )

    for f in entities["files"]:
        tx.run(
            """
            MERGE (f:File {id: $fid})
            SET f.name = $name, f.path = $path
            WITH f
            MATCH (a:UserActivity {id: $aid})
            MERGE (a)-[:TOUCHED_FILE]->(f)
            """,
            fid=f["id"], name=f["name"], path=f["path"], aid=activity_id,
        )

    for fo in entities["folders"]:
        tx.run(
            """
            MERGE (fo:Folder {id: $foid})
            SET fo.name = $name, fo.path = $path
            WITH fo
            MATCH (a:UserActivity {id: $aid})
            MERGE (a)-[:IN_FOLDER]->(fo)
            """,
            foid=fo["id"], name=fo["name"], path=fo["path"], aid=activity_id,
        )

    for f in entities["files"]:
        if "/" in f["path"]:
            folder_path = "/".join(f["path"].split("/")[:-1])
            folder_id = _stable_id("folder", folder_path)
            tx.run(
                """
                MATCH (f:File {id: $fid}), (fo:Folder {id: $foid})
                MERGE (f)-[:LOCATED_IN]->(fo)
                """,
                fid=f["id"], foid=folder_id,
            )

    for app in entities["apps"]:
        tx.run(
            """
            MERGE (ap:Application {id: $apid})
            SET ap.name = $name
            WITH ap
            MATCH (a:UserActivity {id: $aid})
            MERGE (a)-[:USED_APP]->(ap)
            """,
            apid=app["id"], name=app["name"], aid=activity_id,
        )

    for site in entities["websites"]:
        tx.run(
            """
            MERGE (w:Website {id: $wid})
            SET w.name = $name
            WITH w
            MATCH (a:UserActivity {id: $aid})
            MERGE (a)-[:VISITED_SITE]->(w)
            """,
            wid=site["id"], name=site["name"], aid=activity_id,
        )

    for url_info in entities["urls"]:
        tx.run(
            """
            MERGE (u:URL {id: $uid})
            SET u.url = $url, u.domain = $domain
            WITH u
            MATCH (a:UserActivity {id: $aid})
            MERGE (a)-[:VISITED_URL]->(u)
            """,
            uid=url_info["id"], url=url_info["url"],
            domain=url_info["domain"], aid=activity_id,
        )


def _store_vector(activity_id, text, timestamp, entities):
    embedder = _get_embedder()
    client = _get_qdrant()

    vector = embedder.encode(text).tolist()

    payload = {
        "activity_id": activity_id,
        "type": "screen_activity",
        "timestamp": timestamp,
        "description": text,
        "files": [f["name"] for f in entities["files"]],
        "apps": [a["name"] for a in entities["apps"]],
        "websites": [w["name"] for w in entities["websites"]],
        "actions": entities["actions"],
    }

    # hash-based integer ID required by Qdrant
    point_id = int(hashlib.md5(activity_id.encode()).hexdigest()[:15], 16)

    client.upsert(
        collection_name=COLLECTION,
        points=[PointStruct(id=point_id, vector=vector, payload=payload)],
    )

    return point_id


def ingest_text(
    text: str,
    timestamp: Optional[str] = None,
    activity_id: Optional[str] = None,
) -> dict:
    """
    Ingest a free-form LLM summary text into Neo4j + Qdrant.

    Args:
        text:        The LLM-generated summary of a screen capture / activity.
        timestamp:   ISO timestamp (defaults to now).
        activity_id: Unique ID for this activity (auto-generated if not provided).

    Returns:
        dict with activity_id, entities found, neo4j node count, qdrant point id.
    """
    if not text or not text.strip():
        return {"error": "Empty text provided"}

    if timestamp is None:
        timestamp = datetime.now().isoformat()
    if activity_id is None:
        activity_id = f"act-{uuid.uuid4().hex[:8]}"

    entities = extract_entities(text)

    driver = _get_neo4j()
    with driver.session() as session:
        session.execute_write(_create_graph, activity_id, text, timestamp, entities)

    qdrant_point_id = _store_vector(activity_id, text, timestamp, entities)

    node_count = (
        1
        + len(entities["files"])
        + len(entities["folders"])
        + len(entities["apps"])
        + len(entities["websites"])
        + len(entities["urls"])
    )

    return {
        "activity_id": activity_id,
        "timestamp": timestamp,
        "entities": {
            "files": [f["name"] for f in entities["files"]],
            "folders": [f["name"] for f in entities["folders"]],
            "apps": [a["name"] for a in entities["apps"]],
            "websites": [w["name"] for w in entities["websites"]],
            "urls": [u["url"] for u in entities["urls"]],
            "actions": entities["actions"],
        },
        "neo4j_nodes_created": node_count,
        "qdrant_point_id": qdrant_point_id,
    }


def ensure_schema():
    """Create uniqueness constraints for Application, Website, URL node types."""
    driver = _get_neo4j()
    with driver.session() as session:
        for label in ["Application", "Website", "URL"]:
            session.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
            )
    print("Schema updated: Application, Website, URL constraints created.")


if __name__ == "__main__":

    ensure_schema()

    SAMPLE_TEXTS = [
        (
            "User is editing auth_routes.py in VS Code. Chrome browser is open "
            "with a Stack Overflow page about OAuth2 refresh token implementation. "
            "The file is located at /api/routes/auth_routes.py."
        ),
        (
            "User has Docker Desktop running and is viewing the terminal output. "
            "They are running database migration scripts. The file migration_030.sql "
            "is open in the editor at /db/migrations/migration_030.sql."
        ),
        (
            "User is browsing GitHub repository page for the project. They have "
            "multiple tabs open: one showing the README.md, another showing "
            "the pull request review page. VS Code has main.py open at /src/main.py."
        ),
        (
            "User is on Google Docs writing project documentation. Slack is open "
            "in the background with team chat. Chrome tab shows "
            "https://docs.google.com/document/d/abc123/edit"
        ),
        (
            "User is debugging a React component in Chrome DevTools. The file "
            "Dashboard.tsx at /src/components/Dashboard.tsx is open in VS Code "
            "with breakpoints set. They are also reading the React documentation."
        ),
    ]

    print("=" * 70)
    print("  TEXT-TO-GRAPH INGESTION TEST")
    print("=" * 70)

    for i, text in enumerate(SAMPLE_TEXTS, 1):
        print(f"\n--- Sample {i} ---")
        print(f"Input: {text[:100]}...")
        result = ingest_text(text)
        print(f"Activity ID: {result['activity_id']}")
        print(f"Nodes created: {result['neo4j_nodes_created']}")
        print(f"Entities found:")
        for key, vals in result["entities"].items():
            if vals:
                print(f"  {key}: {vals}")
        print(f"Qdrant point: {result['qdrant_point_id']}")

    print("\n" + "=" * 70)
    print("  INGESTION COMPLETE")
    print("=" * 70)

    driver = _get_neo4j()
    with driver.session() as s:
        for label in ["UserActivity", "File", "Folder", "Application",
                       "Website", "URL", "ScreenCapture", "Summary"]:
            r = s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()
            print(f"  {label}: {r['c']} nodes")
        r = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()
        print(f"  Total relationships: {r['c']}")

    print()
    client = _get_qdrant()
    info = client.get_collection(COLLECTION)
    print(f"  Qdrant points: {info.points_count}")

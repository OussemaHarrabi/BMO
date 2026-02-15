"""
Neo4j Knowledge Graph - Entity relationships and graph queries.

Includes entity extraction from free-form text (integrated from teammate's text_to_graph.py).
"""

import logging
import os
import re
import json
import hashlib
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

VALID_RELATIONSHIP_TYPES = frozenset([
    "RELATED_TO", "MENTIONS", "TOUCHED_FILE", "IN_FOLDER", 
    "USED_APP", "VISITED_SITE", "VISITED_URL", "INSPIRED_BY",
    "CONTAINS", "PARENT_OF", "CHILD_OF", "DEPENDS_ON"
])


# ══════════════════════════════════════════════════════════════════════════════
#  ENTITY EXTRACTION PATTERNS (from teammate text_to_graph.py)
# ══════════════════════════════════════════════════════════════════════════════

FILE_PATTERN = re.compile(
    r'(?:^|[\s,;:(\["\'])('                            # boundary before match
    r'(?:[A-Za-z0-9_\-./\\]+\.(?:'                      # path chars + dot
    r'py|tsx|jsx|ts|js|html|css|scss|json|yaml|yml|'    # longer extensions first
    r'md|txt|sql|sh|bat|xml|csv|env|cfg|ini|toml|'
    r'java|cpp|h|go|rs|rb|php|vue|svelte|dart|'
    r'png|jpg|jpeg|gif|svg|pdf|docx|doc|xlsx|xls|pptx|ppt'
    r'))(?=[\s,;:)\]"\'.]|$)'                           # boundary after match
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


def _stable_id(prefix: str, value: str) -> str:
    """Generate a deterministic ID so repeated ingestion merges, not duplicates."""
    h = hashlib.md5(value.lower().strip().encode()).hexdigest()[:12]
    return f"{prefix}-{h}"


@dataclass
class EntityResult:
    """Entity node from graph."""
    entity_id: str
    name: str
    entity_type: str
    properties: Dict[str, Any]
    mention_count: int


@dataclass
class ExtractedEntities:
    """Entities extracted from free-form text."""
    files: List[Dict[str, str]]
    folders: List[Dict[str, str]]
    apps: List[Dict[str, str]]
    websites: List[Dict[str, str]]
    urls: List[Dict[str, str]]
    actions: List[str]


@dataclass
class RelationshipResult:
    """Relationship between entities."""
    from_entity: str
    to_entity: str
    relationship_type: str
    properties: Dict[str, Any]


@dataclass
class TraversalResult:
    """Result of graph traversal."""
    entities: List[EntityResult]
    relationships: List[RelationshipResult]
    paths: List[List[str]]


def extract_entities_from_text(text: str) -> ExtractedEntities:
    """
    Extract structured entities from free-form LLM summary text.
    
    Parses text for:
    - Files (by extension patterns)
    - Folders (from file paths)
    - Apps (from known app list)
    - Websites (from known sites + domain patterns)
    - URLs (full URLs)
    - Actions (from verb patterns)
    
    Returns:
        ExtractedEntities with all found entities.
    """
    entities = ExtractedEntities(
        files=[], folders=[], apps=[], websites=[], urls=[], actions=[]
    )
    
    seen_files = set()
    seen_folders = set()
    seen_apps = set()
    seen_websites = set()
    seen_urls = set()
    
    # Track URL spans to avoid extracting filenames from within URLs
    url_spans = set()
    for match in URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(".,;:)")
        for i in range(match.start(), match.start() + len(url)):
            url_spans.add(i)
        if url.lower() not in seen_urls:
            seen_urls.add(url.lower())
            domain_match = re.search(r'https?://([^/\s]+)', url)
            domain = domain_match.group(1) if domain_match else url
            entities.urls.append({
                "id": _stable_id("url", url),
                "url": url,
                "domain": domain,
            })
    
    # Extract files
    for match in FILE_PATTERN.finditer(text):
        if match.start(1) in url_spans:
            continue
        filepath = match.group(1).replace("\\", "/")
        filename = filepath.split("/")[-1]
        has_path = "/" in filepath
        
        if filename.lower() not in seen_files:
            seen_files.add(filename.lower())
            entities.files.append({
                "id": _stable_id("file", filename),
                "name": filename,
                "path": filepath,
            })
        elif has_path:
            # Update path if we find a more complete one
            for f in entities.files:
                if f["name"].lower() == filename.lower() and "/" not in f["path"]:
                    f["path"] = filepath
                    break
        
        # Extract folder from path
        if has_path:
            folder_path = "/".join(filepath.split("/")[:-1])
            folder_name = folder_path.split("/")[-1] if folder_path else "root"
            if folder_path.lower() not in seen_folders:
                seen_folders.add(folder_path.lower())
                entities.folders.append({
                    "id": _stable_id("folder", folder_path),
                    "name": folder_name,
                    "path": folder_path,
                })
    
    # Extract known apps
    text_lower = text.lower()
    for app in KNOWN_APPS:
        if app.lower() in text_lower and app.lower() not in seen_apps:
            seen_apps.add(app.lower())
            entities.apps.append({
                "id": _stable_id("app", app),
                "name": app,
            })
    
    # Extract known websites
    for site in KNOWN_WEBSITES:
        if site.lower() in text_lower and site.lower() not in seen_websites:
            seen_websites.add(site.lower())
            entities.websites.append({
                "id": _stable_id("website", site),
                "name": site,
            })
    
    # Extract domains
    for match in DOMAIN_PATTERN.finditer(text):
        domain = match.group(1).rstrip(".")
        if domain.lower() not in seen_websites and domain.lower() not in seen_urls:
            seen_websites.add(domain.lower())
            entities.websites.append({
                "id": _stable_id("website", domain),
                "name": domain,
            })
    
    # Extract actions
    for verb in ACTION_VERBS:
        pattern = re.compile(r'\b' + re.escape(verb) + r'\b', re.IGNORECASE)
        if pattern.search(text):
            entities.actions.append(verb)
    
    return entities


class KnowledgeGraph:
    """Neo4j knowledge graph operations for BMO."""
    
    def __init__(self):
        """Initialize Neo4j driver."""
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD")
        
        if not password:
            raise ValueError("NEO4J_PASSWORD environment variable must be set")
        
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._ensure_schema()
    
    def _ensure_schema(self):
        """Create constraints and indexes if they don't exist."""
        with self.driver.session() as session:
            for label in ["Memory", "Entity", "UserActivity", "File", "Folder", 
                          "Application", "Website", "URL"]:
                try:
                    id_field = "memory_id" if label == "Memory" else "id" if label != "Entity" else "entity_id"
                    session.run(f"""
                        CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS
                        FOR (n:{label}) REQUIRE n.{id_field} IS UNIQUE
                    """)
                except Exception as e:
                    logger.debug("Constraint %s may already exist: %s", label, e)
            
            try:
                session.run("""
                    CREATE INDEX entity_type_idx IF NOT EXISTS
                    FOR (e:Entity) ON (e.entity_type)
                """)
            except Exception as e:
                logger.debug("Index entity_type_idx may already exist: %s", e)
            
            try:
                session.run("""
                    CREATE INDEX entity_name_idx IF NOT EXISTS
                    FOR (e:Entity) ON (e.name)
                """)
            except Exception as e:
                logger.debug("Index entity_name_idx may already exist: %s", e)
    
    def close(self):
        """Close the driver connection."""
        self.driver.close()
    
    def add_memory(
        self,
        memory_id: str,
        summary: str,
        category: str,
        source: str
    ):
        """Add a memory node to the graph."""
        with self.driver.session() as session:
            session.run("""
                MERGE (m:Memory {memory_id: $memory_id})
                ON CREATE SET
                    m.summary = $summary,
                    m.category = $category,
                    m.source = $source,
                    m.created_at = datetime()
                ON MATCH SET
                    m.summary = $summary,
                    m.updated_at = datetime()
            """, {
                "memory_id": memory_id,
                "summary": summary,
                "category": category,
                "source": source
            })
    
    def add_entity(
        self,
        entity_id: str,
        name: str,
        entity_type: str,
        properties: Optional[Dict[str, Any]] = None
    ):
        """Add or update an entity node."""
        props_json = json.dumps(properties or {})
        
        with self.driver.session() as session:
            session.run("""
                MERGE (e:Entity {entity_id: $entity_id})
                ON CREATE SET
                    e.name = $name,
                    e.entity_type = $entity_type,
                    e.properties = $properties,
                    e.first_seen = datetime(),
                    e.last_seen = datetime(),
                    e.mention_count = 1
                ON MATCH SET
                    e.last_seen = datetime(),
                    e.mention_count = e.mention_count + 1
            """, {
                "entity_id": entity_id,
                "name": name,
                "entity_type": entity_type,
                "properties": props_json
            })
    
    def add_mention(
        self,
        memory_id: str,
        entity_id: str,
        context: str,
        confidence: float
    ):
        """Create MENTIONS relationship between memory and entity."""
        with self.driver.session() as session:
            session.run("""
                MATCH (m:Memory {memory_id: $memory_id})
                MATCH (e:Entity {entity_id: $entity_id})
                MERGE (m)-[r:MENTIONS]->(e)
                ON CREATE SET
                    r.context = $context,
                    r.confidence = $confidence,
                    r.created_at = datetime()
            """, {
                "memory_id": memory_id,
                "entity_id": entity_id,
                "context": context,
                "confidence": confidence
            })
    
    def add_inspired_by(
        self,
        from_entity: str,
        to_entity: str,
        evidence: str,
        strength: float
    ):
        """Create INSPIRED_BY relationship between entities."""
        with self.driver.session() as session:
            session.run("""
                MATCH (a:Entity {entity_id: $from_entity})
                MATCH (b:Entity {entity_id: $to_entity})
                MERGE (a)-[r:INSPIRED_BY]->(b)
                ON CREATE SET
                    r.evidence = $evidence,
                    r.strength = $strength,
                    r.created_at = datetime()
            """, {
                "from_entity": from_entity,
                "to_entity": to_entity,
                "evidence": evidence,
                "strength": strength
            })
    
    def add_related_to(
        self,
        from_entity: str,
        to_entity: str,
        relationship_type: str,
        strength: float = 0.5
    ):
        """Create RELATED_TO relationship between entities."""
        with self.driver.session() as session:
            session.run("""
                MATCH (a:Entity {entity_id: $from_entity})
                MATCH (b:Entity {entity_id: $to_entity})
                MERGE (a)-[r:RELATED_TO]->(b)
                ON CREATE SET
                    r.relationship_type = $relationship_type,
                    r.strength = $strength,
                    r.created_at = datetime()
            """, {
                "from_entity": from_entity,
                "to_entity": to_entity,
                "relationship_type": relationship_type,
                "strength": strength
            })
    
    def get_entity(self, entity_name: str) -> Optional[EntityResult]:
        """Get entity by name."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (e:Entity {name: $name})
                RETURN e.entity_id, e.name, e.entity_type, e.properties, e.mention_count
            """, {"name": entity_name})
            
            record = result.single()
            if not record:
                return None
            
            return EntityResult(
                entity_id=record[0],
                name=record[1],
                entity_type=record[2] or "unknown",
                properties=json.loads(record[3]) if record[3] else {},
                mention_count=record[4] or 1
            )
    
    def get_entity_by_id(self, entity_id: str) -> Optional[EntityResult]:
        """Get entity by ID."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (e:Entity {entity_id: $entity_id})
                RETURN e.entity_id, e.name, e.entity_type, e.properties, e.mention_count
            """, {"entity_id": entity_id})
            
            record = result.single()
            if not record:
                return None
            
            return EntityResult(
                entity_id=record[0],
                name=record[1],
                entity_type=record[2] or "unknown",
                properties=json.loads(record[3]) if record[3] else {},
                mention_count=record[4] or 1
            )
    
    def traverse(
        self,
        start_entity: str,
        relationship_type: Optional[str] = None,
        direction: str = "both",
        depth: int = 2
    ) -> TraversalResult:
        """Traverse graph from starting entity."""
        if relationship_type and relationship_type not in VALID_RELATIONSHIP_TYPES:
            raise ValueError(f"Invalid relationship_type: {relationship_type}")
        
        if not isinstance(depth, int) or depth < 1 or depth > 5:
            raise ValueError("depth must be an integer between 1 and 5")
        
        if direction not in ("outgoing", "incoming", "both"):
            raise ValueError("direction must be 'outgoing', 'incoming', or 'both'")
        
        rel_pattern = f":{relationship_type}" if relationship_type else ""
        
        if direction == "outgoing":
            query = f"""
                MATCH path = (start:Entity {{name: $start_entity}})-[r{rel_pattern}*1..{depth}]->(end:Entity)
                RETURN nodes(path) as nodes, relationships(path) as rels
                LIMIT 100
            """
        elif direction == "incoming":
            query = f"""
                MATCH path = (start:Entity {{name: $start_entity}})<-[r{rel_pattern}*1..{depth}]-(end:Entity)
                RETURN nodes(path) as nodes, relationships(path) as rels
                LIMIT 100
            """
        else:
            query = f"""
                MATCH path = (start:Entity {{name: $start_entity}})-[r{rel_pattern}*1..{depth}]-(end:Entity)
                RETURN nodes(path) as nodes, relationships(path) as rels
                LIMIT 100
            """
        
        entities_dict = {}
        relationships = []
        paths = []
        
        with self.driver.session() as session:
            result = session.run(query, {"start_entity": start_entity})
            
            for record in result:
                nodes = record["nodes"]
                rels = record["rels"]
                
                path_names = []
                for node in nodes:
                    entity_id = node.get("entity_id", "")
                    if entity_id and entity_id not in entities_dict:
                        entities_dict[entity_id] = EntityResult(
                            entity_id=entity_id,
                            name=node.get("name", ""),
                            entity_type=node.get("entity_type", "unknown"),
                            properties=json.loads(node.get("properties", "{}")) if node.get("properties") else {},
                            mention_count=node.get("mention_count", 1)
                        )
                    path_names.append(node.get("name", ""))
                
                for rel in rels:
                    relationships.append(RelationshipResult(
                        from_entity=rel.start_node.get("entity_id", ""),
                        to_entity=rel.end_node.get("entity_id", ""),
                        relationship_type=rel.type,
                        properties=dict(rel)
                    ))
                
                paths.append(path_names)
        
        return TraversalResult(
            entities=list(entities_dict.values()),
            relationships=relationships,
            paths=paths
        )
    
    def get_entities_for_memory(self, memory_id: str) -> List[EntityResult]:
        """Get all entities mentioned in a memory."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (m:Memory {memory_id: $memory_id})-[:MENTIONS]->(e:Entity)
                RETURN e.entity_id, e.name, e.entity_type, e.properties, e.mention_count
            """, {"memory_id": memory_id})
            
            entities = []
            for record in result:
                entities.append(EntityResult(
                    entity_id=record[0],
                    name=record[1],
                    entity_type=record[2] or "unknown",
                    properties=json.loads(record[3]) if record[3] else {},
                    mention_count=record[4] or 1
                ))
            
            return entities
    
    def get_related_memories(self, entity_id: str, depth: int = 1) -> List[str]:
        """Get memory IDs related to an entity."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (e:Entity {entity_id: $entity_id})<-[:MENTIONS]-(m:Memory)
                RETURN DISTINCT m.memory_id
                UNION
                MATCH (e:Entity {entity_id: $entity_id})-[:RELATED_TO*1..2]-(e2:Entity)<-[:MENTIONS]-(m:Memory)
                RETURN DISTINCT m.memory_id
            """, {"entity_id": entity_id})
            
            return [record[0] for record in result]
    
    def delete_memory_references(self, memory_id: str):
        """Delete memory node and its relationships."""
        with self.driver.session() as session:
            session.run("""
                MATCH (m:Memory {memory_id: $memory_id})
                DETACH DELETE m
            """, {"memory_id": memory_id})
    
    def infer_inspiration(self, project_entity: str, time_window_hours: int = 24):
        """
        Infer INSPIRED_BY relationships based on temporal patterns.
        
        If user viewed a repo, then created a project within time_window,
        create an INSPIRED_BY relationship.
        """
        with self.driver.session() as session:
            session.run("""
                MATCH (m1:Memory)-[:MENTIONS]->(repo:Entity {entity_type: 'repo'})
                MATCH (m2:Memory)-[:MENTIONS]->(proj:Entity {entity_type: 'project'})
                WHERE proj.entity_id = $project_entity
                  AND m1.created_at < m2.created_at
                  AND duration.between(m1.created_at, m2.created_at).hours < $hours
                MERGE (proj)-[:INSPIRED_BY {
                    evidence: 'Temporal proximity: viewed repo before creating project',
                    strength: 0.7,
                    created_at: datetime()
                }]->(repo)
            """, {
                "project_entity": project_entity,
                "hours": time_window_hours
            })
    
    def find_connections(
        self,
        entity_a: str,
        entity_b: str,
        max_depth: int = 3
    ) -> List[List[str]]:
        """Find all paths between two entities."""
        if not isinstance(max_depth, int) or max_depth < 1 or max_depth > 5:
            raise ValueError("max_depth must be an integer between 1 and 5")
        
        with self.driver.session() as session:
            result = session.run(f"""
                MATCH path = shortestPath(
                    (a:Entity {{name: $entity_a}})-[*..{max_depth}]-(b:Entity {{name: $entity_b}})
                )
                RETURN [n in nodes(path) | n.name] as path_names
                LIMIT 10
            """, {
                "entity_a": entity_a,
                "entity_b": entity_b
            })
            
            return [record["path_names"] for record in result]
    
    def get_top_entities(self, entity_type: Optional[str] = None, limit: int = 10) -> List[EntityResult]:
        """Get most mentioned entities."""
        if entity_type:
            query = """
                MATCH (e:Entity {entity_type: $entity_type})
                RETURN e.entity_id, e.name, e.entity_type, e.properties, e.mention_count
                ORDER BY e.mention_count DESC
                LIMIT $limit
            """
            params = {"entity_type": entity_type, "limit": limit}
        else:
            query = """
                MATCH (e:Entity)
                RETURN e.entity_id, e.name, e.entity_type, e.properties, e.mention_count
                ORDER BY e.mention_count DESC
                LIMIT $limit
            """
            params = {"limit": limit}
        
        with self.driver.session() as session:
            result = session.run(query, params)
            
            return [
                EntityResult(
                    entity_id=record[0],
                    name=record[1],
                    entity_type=record[2] or "unknown",
                    properties=json.loads(record[3]) if record[3] else {},
                    mention_count=record[4] or 1
                )
                for record in result
            ]
    
    def get_entity_stats(self) -> Dict[str, int]:
        """Get entity count by type."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (e:Entity)
                RETURN e.entity_type, count(*) as count
                ORDER BY count DESC
            """)
            
            return {record[0]: record[1] for record in result}
    
    def ingest_activity(
        self,
        text: str,
        activity_id: Optional[str] = None,
        timestamp: Optional[str] = None,
        activity_type: str = "screen_activity"
    ) -> Dict[str, Any]:
        """
        Ingest a free-form LLM summary text into the knowledge graph.
        
        Creates a UserActivity node and links it to extracted entities
        (files, apps, websites, URLs) via relationships:
        - TOUCHED_FILE
        - IN_FOLDER
        - USED_APP
        - VISITED_SITE
        - VISITED_URL
        
        Args:
            text: The LLM-generated summary of activity.
            activity_id: Unique ID (auto-generated if not provided).
            timestamp: ISO timestamp (defaults to now).
            activity_type: Type of activity (default: screen_activity).
            
        Returns:
            Dict with activity_id, entities found, and node count.
        """
        import uuid
        
        if not text or not text.strip():
            return {"error": "Empty text provided"}
        
        if timestamp is None:
            timestamp = datetime.now().isoformat()
        if activity_id is None:
            activity_id = f"act-{uuid.uuid4().hex[:8]}"
        
        # Extract entities from text
        entities = extract_entities_from_text(text)
        
        with self.driver.session() as session:
            # Create UserActivity node
            session.run("""
                MERGE (a:UserActivity {id: $aid})
                SET a.type = $atype,
                    a.timestamp = $ts,
                    a.description = $desc
            """, {
                "aid": activity_id,
                "atype": activity_type,
                "ts": timestamp,
                "desc": text
            })
            
            # Create File nodes and relationships
            for f in entities.files:
                session.run("""
                    MERGE (f:File {id: $fid})
                    SET f.name = $name, f.path = $path
                    WITH f
                    MATCH (a:UserActivity {id: $aid})
                    MERGE (a)-[:TOUCHED_FILE]->(f)
                """, {
                    "fid": f["id"],
                    "name": f["name"],
                    "path": f["path"],
                    "aid": activity_id
                })
            
            # Create Folder nodes and relationships
            for fo in entities.folders:
                session.run("""
                    MERGE (fo:Folder {id: $foid})
                    SET fo.name = $name, fo.path = $path
                    WITH fo
                    MATCH (a:UserActivity {id: $aid})
                    MERGE (a)-[:IN_FOLDER]->(fo)
                """, {
                    "foid": fo["id"],
                    "name": fo["name"],
                    "path": fo["path"],
                    "aid": activity_id
                })
            
            # Link files to their folders
            for f in entities.files:
                if "/" in f["path"]:
                    folder_path = "/".join(f["path"].split("/")[:-1])
                    folder_id = _stable_id("folder", folder_path)
                    session.run("""
                        MATCH (f:File {id: $fid}), (fo:Folder {id: $foid})
                        MERGE (f)-[:LOCATED_IN]->(fo)
                    """, {
                        "fid": f["id"],
                        "foid": folder_id
                    })
            
            # Create Application nodes and relationships
            for app in entities.apps:
                session.run("""
                    MERGE (ap:Application {id: $apid})
                    SET ap.name = $name
                    WITH ap
                    MATCH (a:UserActivity {id: $aid})
                    MERGE (a)-[:USED_APP]->(ap)
                """, {
                    "apid": app["id"],
                    "name": app["name"],
                    "aid": activity_id
                })
            
            # Create Website nodes and relationships
            for site in entities.websites:
                session.run("""
                    MERGE (w:Website {id: $wid})
                    SET w.name = $name
                    WITH w
                    MATCH (a:UserActivity {id: $aid})
                    MERGE (a)-[:VISITED_SITE]->(w)
                """, {
                    "wid": site["id"],
                    "name": site["name"],
                    "aid": activity_id
                })
            
            # Create URL nodes and relationships
            for url_info in entities.urls:
                session.run("""
                    MERGE (u:URL {id: $uid})
                    SET u.url = $url, u.domain = $domain
                    WITH u
                    MATCH (a:UserActivity {id: $aid})
                    MERGE (a)-[:VISITED_URL]->(u)
                """, {
                    "uid": url_info["id"],
                    "url": url_info["url"],
                    "domain": url_info["domain"],
                    "aid": activity_id
                })
        
        node_count = (
            1  # UserActivity
            + len(entities.files)
            + len(entities.folders)
            + len(entities.apps)
            + len(entities.websites)
            + len(entities.urls)
        )
        
        return {
            "activity_id": activity_id,
            "timestamp": timestamp,
            "entities": {
                "files": [f["name"] for f in entities.files],
                "folders": [f["name"] for f in entities.folders],
                "apps": [a["name"] for a in entities.apps],
                "websites": [w["name"] for w in entities.websites],
                "urls": [u["url"] for u in entities.urls],
                "actions": entities.actions,
            },
            "neo4j_nodes_created": node_count,
        }

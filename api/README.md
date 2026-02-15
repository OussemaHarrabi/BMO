# 🔧 BMO Backend API

FastAPI-powered backend that handles memory storage, retrieval, and AI-powered query processing.

## Architecture

```
api/
├── main.py              # FastAPI app setup, CORS, routers
├── routes/
│   ├── chat.py          # Chat query processing + sessions
│   ├── memory.py        # Memory CRUD operations
│   ├── capture.py       # Screenshot capture management
│   └── system.py        # System health & status
└── memory/
    └── chat_sessions.py # File-based chat session storage
```

## API Endpoints

### Chat (`/api/chat`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/query` | POST | Process natural language query through agent pipeline |
| `/ws` | WebSocket | Real-time streaming chat with progress updates |
| `/sessions` | GET | List all chat sessions |
| `/sessions` | POST | Create new chat session |
| `/sessions/{id}` | GET | Get session with all messages |
| `/sessions/{id}` | PUT | Update session title |
| `/sessions/{id}` | DELETE | Delete session |
| `/sessions/{id}/messages` | POST | Add message to session |

**Query Request:**
```json
{
  "query": "What code was I writing yesterday?",
  "categories": ["code", "work"],
  "time_range_days": 7,
  "fast_mode": true
}
```

**Query Response:**
```json
{
  "answer": "Yesterday you were working on...",
  "confidence": 0.85,
  "sources": [...],
  "screenshots": [{"memory_id": "...", "image_base64": "..."}],
  "processing_time_ms": 1250,
  "intent_detected": "MEMORY_SEARCH",
  "uncertain": false
}
```

### Memory (`/api/memory`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | List memories with filters |
| `/` | POST | Create new memory |
| `/{memory_id}` | GET | Get specific memory |
| `/{memory_id}` | DELETE | Delete memory |
| `/search` | POST | Semantic search |
| `/graph/query` | POST | Query knowledge graph |
| `/stats/categories` | GET | Memory count by category |
| `/stats/timeline` | GET | Memory count over time |

**Search Request:**
```json
{
  "query": "machine learning tutorials",
  "category": "research",
  "limit": 20
}
```

### Capture (`/api/capture`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/folder/status` | GET | Get watcher status |
| `/folder/ingest` | POST | Trigger manual ingestion |

### System (`/api/system`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | System health check |

---

## Multi-Agent System

The backend uses a sophisticated multi-agent pipeline for query processing:

```
User Query → Router → Retriever → Reasoner → Verifier → Response
```

### Agent Components (`agents/`)

#### 1. Router Agent (`router.py`)
Classifies user intent using phi3.5:

| Intent | Description | Example |
|--------|-------------|---------|
| `MEMORY_SEARCH` | Find past activities | "What was I reading yesterday?" |
| `KNOWLEDGE_GRAPH` | Explore connections | "How is X related to Y?" |
| `CLARIFICATION` | Query too vague | "Find that thing" |
| `GENERAL_CHAT` | Greetings/help | "Hello", "What can you do?" |

Also extracts filters:
- `category_filter`: code, finance, personal, research, work, entertainment
- `time_filter`: today, yesterday, this_week, this_month
- `entity_focus`: Specific topics mentioned

#### 2. Reasoner Agent (`reasoner.py`)
Generates answers using RAG:
- Retrieves relevant memories from Qdrant
- Synthesizes answer from context
- Cites source memories
- Handles no-results gracefully

#### 3. Verifier Agent (`verifier.py`)
Validates responses:
- Fact-checks claims against sources
- Adjusts confidence scores
- Filters invalid source citations
- Ensures answer accuracy

#### 4. Orchestrator (`orchestrator.py`)
Coordinates the full pipeline:
- Manages agent execution order
- Handles special cases (general chat, clarification)
- Builds source references
- Extracts screenshots for response

---

## Memory Storage

### Vector Store (`memory/vector_store.py`)
Qdrant-powered semantic search:

- **Collection**: `bmo_memories`
- **Vector Size**: 768 dimensions (nomic-embed-text)
- **Distance Metric**: Cosine similarity

**Features:**
- Semantic similarity search
- Category/source filtering
- Date range queries
- Deduplication via content hash
- Timeline statistics

**Indexed Fields:**
- `category` (keyword)
- `source` (keyword)
- `created_at` (datetime)

### Knowledge Graph (`memory/knowledge_graph.py`)
Neo4j-powered relationship storage:

- Entity nodes (topics, projects, people)
- Relationship edges (related_to, inspired_by, etc.)
- Graph traversal queries
- Memory-entity linking

---

## Content Processing (`processing/`)

### Classifier (`classifier.py`)
Categorizes content into:
- work, code, research, studying
- meetings, entertainment, shopping
- health, travel, finance, social
- creative, personal, uncategorized

### Entity Extractor (`entity_extractor.py`)
Extracts named entities:
- Projects, repositories
- Technologies, frameworks
- People, organizations
- Topics, concepts

### Summarizer (`summarizer.py`)
Generates concise summaries for:
- Long-form content
- Screenshot descriptions
- Memory indexing

---

## Screenshot Pipeline (`capture/`)

### Screenshot Watcher (`screenshot_watcher.py`)
Monitors folder for new screenshots:

```python
# Pipeline stages
1. Detect new file (watchdog)
2. Validate image format
3. Extract text (OCR via phi3.5 vision)
4. Classify content category
5. Generate summary
6. Create embeddings (nomic-embed-text)
7. Store in Qdrant + Neo4j
```

### Vision Service (`os_monitor/vision_service.py`)
phi3.5 vision analysis:
- Text extraction from images
- Content understanding
- Activity classification
- Context generation

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API URL |
| `QDRANT_HOST` | `localhost` | Qdrant host |
| `QDRANT_PORT` | `6333` | Qdrant port |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `password` | Neo4j password |
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `FRONTEND_URL` | `http://localhost:3000` | CORS allowed origin |

### Config Files (`config/`)

- `app.yaml` - Application settings
- `models.yaml` - LLM model configurations
- `storage.yaml` - Database settings
- `triggers.yaml` - Capture trigger rules

---

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Start the API server
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Or via Docker
docker-compose up bmo-backend
```

**API Documentation**: http://localhost:8000/docs

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | FastAPI |
| LLM Client | Ollama (phi3.5, nomic-embed-text) |
| Vector DB | Qdrant |
| Graph DB | Neo4j |
| Cache | Redis |
| Async | httpx, asyncio |

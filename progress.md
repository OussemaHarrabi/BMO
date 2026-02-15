# BMO Capture Pipeline - Progress Report

**Last Updated**: 2025-02-15

## Overview

BMO is a personal AI memory system that captures, processes, and stores user activities from multiple sources. This document tracks the current implementation status against the original design.

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CAPTURE LAYER                                   │
├─────────────────────────────────────────────────────────────────────────┤
│  OS Listener          │  Email Processor       │  Browser Extension    │
│  (Desktop/Docs/DL)    │  (IMAP/Gmail)          │  (Coming Soon)        │
└──────────┬────────────┴──────────┬─────────────┴──────────┬────────────┘
           │                       │                        │
           ▼                       ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        PROCESSING LAYER                                 │
├─────────────────────────────────────────────────────────────────────────┤
│  Text Extraction  │  Vision Service   │  Text Chunking   │  Summarization │
│  (PDF, TXT, etc)  │  (Images → Desc)  │  (Large Docs)    │  (LLM Summary)  │
└──────────┬────────┴────────┬──────────┴────────┬─────────┴───────┬──────┘
           │                 │                   │                 │
           ▼                 ▼                   ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         STORAGE LAYER                                   │
├─────────────────────────────────────────────────────────────────────────┤
│           Qdrant (Vector Store)        │       Neo4j (Knowledge Graph)  │
│  - Embeddings for semantic search      │  - Entity relationships        │
│  - Raw text + summaries                │  - Files, Apps, Websites       │
│  - Image base64 for retrieval          │  - Activity timeline           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## New Implementations (vs. Previous Version)

### 1. OS Listener (`capture/os_monitor/os_listener.py`)

**NEW** - Complete reactive filesystem monitoring system.

| Feature | Status | Description |
|---------|--------|-------------|
| Multi-directory watch | ✅ | Desktop, Documents, Downloads |
| Windows path resolution | ✅ | Registry-based folder lookup |
| Noise filtering | ✅ | Ignores .tmp, .part, system files |
| Event dispatch | ✅ | CREATE, MODIFY, DELETE, RENAME, MOVE |
| Dual storage | ✅ | Qdrant + Neo4j integration |
| Graceful shutdown | ✅ | SIGINT/SIGTERM handling |

**Usage**:
```bash
cd D:\oussema\HACKATHONS\SMU\Hackathon
PYTHONPATH=. python -m bmo.capture.os_monitor.os_listener --log-level INFO
```

### 2. Text Chunking (`capture/os_monitor/text_chunker.py`)

**NEW** - Recursive text chunking for large documents.

| Feature | Status | Description |
|---------|--------|-------------|
| Recursive splitting | ✅ | Hierarchical separators (paragraphs → sentences → words) |
| Overlap preservation | ✅ | 200-char overlap for context |
| Configurable sizes | ✅ | 1500 chars default, min 100 |
| Smart merging | ✅ | Merges tiny chunks back |

**Algorithm**:
1. Try paragraph splits (`\n\n\n`, `\n\n`)
2. Fall back to sentence splits (`. `, `? `, `! `)
3. Fall back to word splits (`, `, ` `)
4. Final fallback: character-level split

### 3. Enhanced Document Processor (`capture/os_monitor/document_processor.py`)

**ENHANCED** - Added chunking and dual-storage workflows.

| Feature | Status | Description |
|---------|--------|-------------|
| Small doc workflow | ✅ | Extract → Summarize → Embed → Store (Qdrant + Neo4j) |
| Large doc workflow | ✅ | Extract → Chunk → Per-chunk summary → Store each chunk |
| Image workflow | ✅ | Vision → Describe → Summarize → Store with base64 |
| Threshold detection | ✅ | Auto-detect docs > 3000 chars |

### 4. Knowledge Graph Integration (`memory/knowledge_graph.py`)

**ENHANCED** - Full entity extraction and graph ingestion.

| Feature | Status | Description |
|---------|--------|-------------|
| Entity extraction | ✅ | Files, folders, apps, websites, URLs |
| Pattern matching | ✅ | Regex for file extensions, domains, URLs |
| Known entity lists | ✅ | 50+ apps, 30+ websites recognized |
| `ingest_activity()` | ✅ | Creates UserActivity nodes with relationships |
| TOUCHED_FILE relationship | ✅ | Activity → File |
| USED_APP relationship | ✅ | Activity → Application |
| VISITED_SITE relationship | ✅ | Activity → Website |
| IN_FOLDER relationship | ✅ | Activity → Folder |
| LOCATED_IN relationship | ✅ | File → Folder |

### 5. Vector Store Enhancements (`memory/vector_store.py`)

**ENHANCED** - Added image storage and sync methods.

| Feature | Status | Description |
|---------|--------|-------------|
| `image_base64` field | ✅ | Store original images for retrieval |
| `add_sync()` method | ✅ | Synchronous add for OS listener |
| `search_sync()` method | ✅ | Synchronous search |
| Image in search results | ✅ | Returns base64 with search hits |

### 6. Vision Service (`capture/os_monitor/vision_service.py`)

**ENHANCED** - Returns base64 alongside description.

| Feature | Status | Description |
|---------|--------|-------------|
| `describe_image_with_base64()` | ✅ | Returns (description, base64) tuple |
| OllamaClient integration | ✅ | Uses unified client for inference |
| Fallback stub | ✅ | Returns basic file info if model fails |

---

## Model Configuration

All models are locally hosted with <4B parameters (hackathon requirement).

| Role | Model | Parameters | Purpose |
|------|-------|------------|---------|
| ROUTER | phi3.5:latest | 3.8B | Intent classification |
| REASONER | qwen3:4b | 4.0B | Complex reasoning |
| CLASSIFIER | phi3.5:latest | 3.8B | Content categorization |
| ENTITY_EXTRACTOR | qwen3:4b | 4.0B | Named entity extraction |
| VERIFIER | phi3.5:latest | 3.8B | Verification tasks |
| VISION | gemma3:4b | 4.0B | Image description |
| EMBEDDINGS | nomic-embed-text | 137M | Vector embeddings (768-dim) |

**Note**: Vision model `gemma3:4b` is currently downloading (~3.3GB).

---

## Infrastructure Status

### Docker Services

| Service | Container | Port | Status |
|---------|-----------|------|--------|
| Vector DB | bmo-qdrant | 6333, 6334 | ✅ Running |
| Graph DB | bmo-neo4j | 7474, 7687 | ✅ Running |
| Cache | bmo-redis | 6379 | ✅ Running |
| API | bmo-backend | 8000 | ✅ Running |
| UI | bmo-frontend | 3000 | ✅ Running |

### Environment Configuration (`.env`)

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=bmo_password
QDRANT_HOST=localhost
QDRANT_PORT=6333
OLLAMA_HOST=http://localhost:11434
```

---

## Data Flow Examples

### Example 1: Text File Created

```
User creates document.txt in Downloads
    ↓
OS Listener detects FILE_CREATED event
    ↓
DocumentProcessor._on_create() called
    ↓
TextExtractor.extract() → raw text
    ↓
if len(text) > 3000:
    RecursiveTextChunker.chunk() → [chunk1, chunk2, ...]
    for each chunk:
        SummarizationService.summarize() → chunk_summary
        VectorStore.add_sync(chunk, summary, category="document_chunk")
    KnowledgeGraph.ingest_activity(combined_summary)
else:
    SummarizationService.summarize() → summary
    VectorStore.add_sync(text, summary, category="document")
    KnowledgeGraph.ingest_activity(summary)
```

### Example 2: Image File Created

```
User saves screenshot.png to Desktop
    ↓
OS Listener detects FILE_CREATED event
    ↓
VisionService.can_process() → True
    ↓
VisionService.describe_image_with_base64() 
    → (description, base64_data)
    ↓
SummarizationService.summarize(description) → summary
    ↓
VectorStore.add_sync(
    description, summary, 
    category="image",
    image_base64=base64_data  # ← Store original for retrieval
)
    ↓
KnowledgeGraph.ingest_activity(summary, activity_type="image_capture")
```

### Example 3: Retrieval Query

```
User asks: "What images did I save yesterday?"
    ↓
VectorStore.search("images saved yesterday")
    → Returns memories with image_base64 field populated
    ↓
KnowledgeGraph.traverse("user activity images")
    → Returns related files, apps, timestamps
    ↓
Combined result with:
    - Vector similarity matches
    - Graph relationship context
    - Original image data (base64)
```

---

## Pending Tasks

| Task | Priority | Status |
|------|----------|--------|
| Complete gemma3:4b download | High | In Progress (~32%) |
| End-to-end pipeline test | High | Pending |
| Browser extension capture | Medium | Not Started |
| Email capture integration | Medium | Implemented, untested |
| Real-time activity streaming | Low | Not Started |

---

## File Structure

```
bmo/
├── capture/
│   ├── os_monitor/
│   │   ├── os_listener.py       # NEW: Main entry point
│   │   ├── document_processor.py # ENHANCED: Chunking + dual storage
│   │   ├── text_chunker.py      # NEW: Recursive chunking
│   │   ├── vision_service.py    # ENHANCED: Base64 return
│   │   ├── text_extractor.py    # Existing
│   │   ├── embedding_service.py # Existing
│   │   ├── summarization_service.py # Existing
│   │   ├── identity_service.py  # Existing
│   │   ├── event_queue.py       # Existing
│   │   ├── watcher.py           # Existing
│   │   └── models.py            # Existing
│   └── email/
│       ├── email_processor.py   # Existing
│       └── imap_client.py       # Existing
├── memory/
│   ├── vector_store.py          # ENHANCED: image_base64 + sync methods
│   └── knowledge_graph.py       # ENHANCED: ingest_activity()
├── core/
│   └── ollama_client.py         # FIXED: gemma3:4b model name
├── agents/
│   ├── orchestrator.py          # Existing
│   ├── router.py                # Existing
│   ├── reasoner.py              # Existing
│   └── verifier.py              # Existing
├── api/
│   └── routes/
│       ├── memory.py            # Existing
│       └── capture.py           # Existing
├── docker-compose.yml           # Existing
├── .env                         # Configuration
└── progress.md                  # This file
```

---

## Testing Commands

```bash
# Start OS Listener
cd D:\oussema\HACKATHONS\SMU\Hackathon
PYTHONPATH=. python -m bmo.capture.os_monitor.os_listener --log-level INFO

# Test imports
PYTHONPATH=. python -c "
from bmo.capture.os_monitor.os_listener import start_listener
from bmo.capture.os_monitor.text_chunker import RecursiveTextChunker
from bmo.memory.knowledge_graph import KnowledgeGraph, extract_entities_from_text
print('All imports OK')
"

# Test chunker
PYTHONPATH=. python -c "
from bmo.capture.os_monitor.text_chunker import RecursiveTextChunker
chunker = RecursiveTextChunker(chunk_size=500)
text = 'Hello world. ' * 200
chunks = chunker.chunk(text)
print(f'Text length: {len(text)}, Chunks: {len(chunks)}')
"

# Test entity extraction
PYTHONPATH=. python -c "
from bmo.memory.knowledge_graph import extract_entities_from_text
result = extract_entities_from_text('Editing main.py in VS Code while browsing GitHub')
print(f'Files: {result.files}')
print(f'Apps: {result.apps}')
print(f'Websites: {result.websites}')
"
```

---

## Compliance Notes

- **No external APIs**: All models run locally via Ollama
- **Parameter limit**: All models <4B parameters
- **Privacy**: No data leaves the local machine
- **Open source**: All components are open source (Qdrant, Neo4j, Ollama)

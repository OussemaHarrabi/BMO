# File Intelligence Pipeline — Architecture & Logic Reference

## Overview

A local file monitoring pipeline that watches OS filesystem events, maintains stable file identity, tracks state transitions, and synchronizes everything to **Qdrant** (vector database) as the single source of truth for both metadata and embeddings.

---

## Project Structure

```
os_events_detecter/
├── main.py                  # Entry point — wires all components, runs pipeline
├── watcher.py               # OS filesystem event monitoring (watchdog)
├── event_queue.py           # Thread-safe sequential event processing
├── models.py                # Data models: FSEvent, FileIdentity, enums
├── identity_service.py      # Stable file identity tracking (UUID, hash, path)
├── state_machine.py         # Explicit file lifecycle state transitions
├── document_processor.py    # Event router — orchestrates identity + qdrant
├── qdrant_client.py         # Qdrant REST API client (vectors + metadata)
├── embedding_service.py     # Embedding stub (replace with real LLM)
├── reconciliation.py        # Startup disk-vs-state sync scanner
├── test_sequence_cases.py   # Unit + integration tests
└── watched_folder/          # Default monitored directory
```

---

## Data Flow (Sequence)

```
Filesystem Event (OS)
    │
    ▼
FileWatcher (watchdog)
    │  normalize path
    │  deduplicate (time-window)
    │  infer moves on Windows (delete+create → move)
    ▼
FSEvent (structured object)
    │
    ▼
EventQueue (thread-safe, sequential)
    │
    ▼
DocumentProcessor
    │
    ├──▶ FileIdentityService
    │       • register / modify / delete / rename
    │       • SHA256 content hashing
    │       • UUID identity preservation
    │       • hash-based identity restoration
    │
    ├──▶ StateMachine
    │       • validates state transition
    │       • updates FileIdentity.state
    │
    ├──▶ EmbeddingService (for .txt files)
    │       • text → vector embedding
    │
    └──▶ QdrantClient
            • upsert_vector (embeddable files)
            • upsert_metadata (non-embeddable files)
            • update_payload (renames/moves)
            • delete_vector (deletions)
```

---

## Components in Detail

### 1. FileWatcher (`watcher.py`)

Uses the `watchdog` library for recursive OS event monitoring.

**Capabilities:**
- Watches one or more directories recursively
- Normalizes all paths to absolute form
- Deduplicates rapid-fire duplicate events (150ms window)
- **Windows move inference**: Windows does not emit native `move` events — it emits `delete` + `create`. The watcher correlates these within a 350ms window by filename to synthesize move events.

**Events emitted (as `FSEvent`):**

| Event Type | Trigger |
|---|---|
| `file_created` | New file appears |
| `file_modified` | File content changes |
| `file_deleted` | File removed from disk |
| `file_renamed` | File name changes (same directory) |
| `file_moved` | File moves to different directory |
| `directory_created` | New folder appears |
| `directory_deleted` | Folder removed |
| `directory_renamed` | Folder name changes (same parent) |
| `directory_moved` | Folder moves to different parent |

**Rename vs Move distinction:** If `dirname(src) == dirname(dest)` → rename. Otherwise → move.

---

### 2. EventQueue (`event_queue.py`)

- Thread-safe `queue.Queue` with a dedicated worker thread
- Guarantees **sequential processing** — events are handled one at a time in order
- Supports `drain()` to block until all queued events are processed
- Graceful shutdown with sentinel `None` value

---

### 3. FSEvent (`models.py`)

Every internal event follows this structure:

```python
{
    "event_type": str,       # e.g. "file_created", "file_moved"
    "src_path": str | None,  # original path (for rename/move/delete)
    "dest_path": str | None, # destination path (for rename/move)
    "path": str | None,      # canonical path (for create/modify/delete)
    "timestamp": str,        # ISO 8601 UTC
    "is_directory": bool
}
```

---

### 4. FileIdentityService (`identity_service.py`)

Maintains **stable file identity independent of path**. A file's UUID persists through renames, moves, and even delete+recreate cycles.

**Identity record (`FileIdentity`):**

| Field | Type | Purpose |
|---|---|---|
| `file_id` | UUID (str) | Permanent unique identifier |
| `content_hash` | SHA256 (str) | Content fingerprint |
| `original_created_at` | ISO timestamp | When first seen |
| `current_path` | str | Current absolute path |
| `status` | `active` / `deleted` / `trashed` | Lifecycle status |
| `state` | `NEW` / `ACTIVE` / `MODIFIED` / ... | State machine position |

**Rules:**

| Scenario | Action |
|---|---|
| Path changes (rename/move) | Update `current_path` only — same `file_id` |
| Content changes (modify) | Recompute SHA256, update `content_hash` |
| File deleted | Set `status=deleted`, remove from path index, **keep identity** |
| File re-created with same SHA256 | **Restore original identity** (same `file_id`) |
| Purge requested | Only allowed from `DELETED` state — removes identity permanently |

**Thread safety:** All operations are protected by a `threading.Lock`.

**Indexes maintained:**
- `_by_path` — fast lookup by current absolute path
- `_by_hash` — reverse lookup by content hash (for restoration)
- `_by_id` — lookup by UUID

---

### 5. StateMachine (`state_machine.py`)

Explicit state transitions — invalid transitions return `None` and log a warning.

```
         ┌──────────┐
         │   NEW    │
         └────┬─────┘
              │ file_created / directory_created
              ▼
         ┌──────────┐
    ┌───▶│  ACTIVE  │◀──────────────────────┐
    │    └──┬─┬─┬───┘                       │
    │       │ │ │                            │
    │       │ │ │ file_modified              │
    │       │ │ ▼                            │
    │       │ │ ┌──────────┐                │
    │       │ │ │ MODIFIED │──(any event)──▶│
    │       │ │ └──────────┘                │
    │       │ │                              │
    │       │ │ file_renamed                 │
    │       │ ▼                              │
    │       │ ┌──────────┐                  │
    │       │ │ RENAMED  │──(any event)───▶ │
    │       │ └──────────┘                  │
    │       │                                │
    │       │ file_moved                     │
    │       ▼                                │
    │    ┌──────────┐                       │
    │    │  MOVED   │──(any event)────────▶ │
    │    └──────────┘                       │
    │                                        │
    │    file_deleted (from any active state) │
    │       │                                │
    │       ▼                                │
    │    ┌──────────┐    file_created        │
    │    │ DELETED  │───────────────────────┘
    │    └────┬─────┘
    │         │ purge (manual)
    │         ▼
    │    ┌──────────┐
    │    │  PURGED  │  (terminal — no transitions out)
    │    └──────────┘
```

**Allowed transitions table:**

| From State | Event | To State |
|---|---|---|
| NEW | file_created, directory_created | ACTIVE |
| ACTIVE | file_modified | MODIFIED |
| ACTIVE | file_renamed, directory_renamed | RENAMED |
| ACTIVE | file_moved, directory_moved | MOVED |
| ACTIVE | file_deleted, directory_deleted | DELETED |
| MODIFIED | file_modified | MODIFIED |
| MODIFIED | file_renamed | RENAMED |
| MODIFIED | file_moved | MOVED |
| MODIFIED | file_deleted | DELETED |
| MOVED | file_modified | MODIFIED |
| MOVED | file_renamed, directory_renamed | RENAMED |
| MOVED | file_moved, directory_moved | MOVED |
| MOVED | file_deleted, directory_deleted | DELETED |
| RENAMED | file_modified | MODIFIED |
| RENAMED | file_renamed, directory_renamed | RENAMED |
| RENAMED | file_moved, directory_moved | MOVED |
| RENAMED | file_deleted, directory_deleted | DELETED |
| DELETED | file_created, directory_created | ACTIVE |
| PURGED | *(none)* | *(terminal)* |

---

### 6. DocumentProcessor (`document_processor.py`)

Central event router. Receives each `FSEvent` and orchestrates identity + Qdrant operations.

**Event → Action mapping:**

| Event | Identity Action | Qdrant Action |
|---|---|---|
| `file_created` | `register(path)` | `upsert_vector` (if .txt) or `upsert_metadata` |
| `file_modified` | `handle_modify(path)` | `upsert_vector` (if .txt) or `upsert_metadata` |
| `file_deleted` | `handle_delete(path)` | `delete_vector(file_id)` |
| `file_renamed` | `handle_rename(src, dest)` | `update_payload(file_id, identity)` |
| `file_moved` | `handle_rename(src, dest)` | `update_payload(file_id, identity)` |
| `directory_created` | `register(path, is_directory=True)` | *(no vector)* |
| `directory_deleted` | `handle_delete(path)` | `delete_vector(file_id)` |
| `directory_renamed` | `handle_rename(src, dest)` | `update_payload(file_id, identity)` |
| `directory_moved` | `handle_rename(src, dest)` | `update_payload(file_id, identity)` |

**Embedding logic:**
- Only `.txt` files are embedded (extensible via `_SUPPORTED_TEXT_EXTENSIONS`)
- Text is read → passed to `EmbeddingService.embed()` → stored as vector in Qdrant
- Non-embeddable files are stored as **metadata-only points** (zero vector) so every file is tracked in Qdrant

---

### 7. QdrantClient (`qdrant_client.py`)

Real REST API client using `urllib.request`. Single storage backend for everything.

**Methods:**

| Method | Qdrant API | Purpose |
|---|---|---|
| `ensure_collection()` | `GET/PUT /collections/{name}` | Auto-create collection on startup |
| `upsert_vector(id, vector, payload)` | `PUT /collections/{name}/points?wait=true` | Store file with embedding vector |
| `upsert_metadata(id, payload)` | Same as above, zero vector | Store file without embedding |
| `update_payload(id, payload)` | `POST /collections/{name}/points/payload` | Update metadata (rename/move) |
| `delete_vector(id)` | `POST /collections/{name}/points/delete?wait=true` | Remove point completely |
| `search(vector, limit)` | `POST /collections/{name}/points/search` | Semantic search |
| `get_point(id)` | `GET /collections/{name}/points/{id}` | Retrieve single point |
| `scroll(limit, filter)` | `POST /collections/{name}/points/scroll` | List/paginate points |

**Payload stored per point:**

```json
{
    "file_id": "uuid",
    "content_hash": "sha256hex",
    "original_created_at": "2026-02-14T...",
    "current_path": "C:\\...\\file.txt",
    "status": "active",
    "state": "ACTIVE"
}
```

**Offline resilience:** All API calls catch `URLError` and log errors without crashing the pipeline.

**Configuration:**
```python
QdrantClient(
    url="http://localhost:6333",    # Your Qdrant instance
    collection="documents",          # Collection name
    api_key="your-api-key",          # Optional, for Qdrant Cloud
    vector_size=384                   # Must match embedding dimension
)
```

---

### 8. EmbeddingService (`embedding_service.py`)

**Currently a stub.** Returns `[0.0] * 384`.

**To replace with real LLM:**
```python
class EmbeddingService:
    def __init__(self, model_path: str) -> None:
        self._model = load_your_model(model_path)
    
    def embed(self, text: str) -> list[float]:
        return self._model.encode(text).tolist()
```

The rest of the pipeline requires no changes — it only calls `embed(text) -> list[float]`.

---

### 9. ReconciliationScanner (`reconciliation.py`)

Runs **once at startup** before the watcher begins.

**Logic:**
1. Walk all watched directories recursively
2. For each file on disk not in identity service → register it + upsert metadata to Qdrant
3. For each identity marked `ACTIVE` whose path no longer exists on disk → mark `DELETED` + delete from Qdrant

This ensures the system recovers from crashes or offline periods.

---

## Event Reaction Reference

### File is created
```
OS → file_created event
→ EventQueue (sequential)
→ DocumentProcessor._on_create()
   → IdentityService.register(path)
      → compute SHA256
      → check for deleted identity with same hash → restore if found
      → otherwise create new UUID identity
   → if .txt: EmbeddingService.embed(text) → QdrantClient.upsert_vector()
   → if other: QdrantClient.upsert_metadata()
```

### File is modified
```
OS → file_modified event
→ DocumentProcessor._on_modify()
   → IdentityService.handle_modify(path)
      → recompute SHA256
      → state: * → MODIFIED
   → if .txt: re-embed → QdrantClient.upsert_vector() (overwrites old vector)
   → if other: QdrantClient.upsert_metadata()
```

### File is deleted
```
OS → file_deleted event
→ DocumentProcessor._on_delete()
   → IdentityService.handle_delete(path)
      → status: active → deleted
      → state: * → DELETED
      → remove from path index (identity preserved in _by_id and _by_hash)
   → QdrantClient.delete_vector(file_id)
```

### File is renamed (same directory)
```
OS → file_renamed event (or inferred on Windows)
→ DocumentProcessor._on_rename()
   → IdentityService.handle_rename(src, dest)
      → same UUID, update current_path
      → state: * → RENAMED
   → QdrantClient.update_payload(file_id, updated_identity)
```

### File is moved (different directory)
```
OS → file_moved event (or inferred on Windows from delete+create)
→ DocumentProcessor._on_move()
   → IdentityService.handle_rename(src, dest)  [same logic]
      → same UUID, update current_path
      → state: * → MOVED
   → QdrantClient.update_payload(file_id, updated_identity)
```

### File is deleted then re-created with same content
```
1. OS → file_deleted → identity marked DELETED, vector removed from Qdrant
2. OS → file_created → IdentityService.register()
   → SHA256 matches a DELETED identity → RESTORE original UUID
   → status: deleted → active
   → state: DELETED → ACTIVE
   → re-embed and upsert to Qdrant with original file_id
```

### Directory events
- `directory_created` → identity registered (no embedding, no vector)
- `directory_deleted` → identity marked deleted, point removed from Qdrant
- `directory_renamed/moved` → identity path updated, payload updated in Qdrant

---

## Windows Move Inference

Windows `watchdog` does not emit `FileMovedEvent`. Instead it fires:
1. `FileDeletedEvent` at old path
2. `FileCreatedEvent` at new path

The `_MoveTracker` in `watcher.py` correlates these:
- Buffers deletes and creates for 350ms
- Matches by filename
- If `dirname(old) != dirname(new)` → synthesize `file_moved`
- Unmatched events flush as regular create/delete after the window expires

---

## What Needs Replacement for Production

| Component | Current State | Replace With |
|---|---|---|
| `EmbeddingService` | Returns `[0.0]*384` | Local LLM (e.g. sentence-transformers, 4B model) |
| `QdrantClient` | Real REST client, ready | Just provide URL + API key |
| `SIGTERM` on Windows | `signal.SIGTERM` may not work | Use `ctrl_c` or Windows service wrapper |

**Everything else is production-ready.**

---

## Configuration

All in `main.py`:

```python
# Watch path
DEFAULT_WATCH = "path/to/your/folder"

# Qdrant
qdrant = QdrantClient(
    url="http://localhost:6333",
    collection="documents",
    api_key=None,           # set for Qdrant Cloud
    vector_size=384,        # match your embedding model
)

# Embedding
embedding = EmbeddingService(dimension=384)
```

---

## Thread Safety Model

- `FileIdentityService`: All public methods acquire `threading.Lock`
- `EventQueue`: `queue.Queue` is inherently thread-safe; single worker guarantees serial processing
- `_MoveTracker` / `_DedupTracker`: Each has its own `threading.Lock`
- `QdrantClient`: Stateless HTTP calls, safe for concurrent use
- The watcher callback runs on watchdog's thread → events are immediately enqueued → processed on the worker thread

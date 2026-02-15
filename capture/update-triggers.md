# OS Triggers Saving Vision — Full System Reference

> **Generated**: February 2026
>
> This document catalogues **every file** in the project so any new contributor
> can understand the current state of the system without reading each source.
>
> Format per file: **name** · **what it does** · **full current content**.

---

## Table of Contents

| # | File | Role |
|---|------|------|
| 1 | `main.py` | Entry point (CLI) |
| 2 | `os_listener.py` | Reactive OS filesystem listener |
| 3 | `document_processor.py` | Event router & processing pipeline |
| 4 | `vision_service.py` | Image description via multimodal LLM |
| 5 | `text_extractor.py` | Text extraction (txt, md, pdf, docx…) |
| 6 | `summarization_service.py` | LLM summarization + categorization |
| 7 | `embedding_service.py` | Text → vector embedding (Ollama) |
| 8 | `qdrant_client.py` | Qdrant vector DB REST client |
| 9 | `identity_service.py` | File identity tracking (hash + UUID) |
| 10 | `state_machine.py` | File lifecycle state transitions |
| 11 | `event_queue.py` | Thread-safe FIFO event queue |
| 12 | `watcher.py` | Watchdog wrapper (dedup, move inference) |
| 13 | `models.py` | Data models & enums |
| 14 | `reconciliation.py` | Disk-scan reconciliation (used in normal mode only) |
| 15 | `reset_qdrant.py` | Utility — wipe & recreate Qdrant collection |
| 16 | `ollamatest.py` | Quick manual test script for Ollama |
| 17 | `requirements.txt` | Python dependencies |

---

## 1 · `main.py`

**Description:**
Entry point of the application. Parses CLI arguments (`--listen`, `--extra`, `--log-level`).
In `--listen` mode it delegates to `os_listener.start_listener()` for reactive filesystem monitoring.
In normal mode it watches a local `watched_folder/`, runs reconciliation on startup, and processes events through the full pipeline (identity → text/vision → summarize → embed → Qdrant).

**Content:**
```python
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

from document_processor import DocumentProcessor
from embedding_service import EmbeddingService
from event_queue import EventQueue
from identity_service import FileIdentityService
from models import FSEvent
from qdrant_client import QdrantClient
from reconciliation import ReconciliationScanner
from summarization_service import SummarizationService
from text_extractor import TextExtractor
from vision_service import VisionService
from watcher import FileWatcher

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_WATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watched_folder")


def _setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT, stream=sys.stdout)


def main() -> None:
    # ---- CLI argument parsing ----
    parser = argparse.ArgumentParser(description="File Intelligence Pipeline")
    parser.add_argument(
        "--listen",
        action="store_true",
        help="Start in OS listener mode (watch Documents, Desktop, Downloads).",
    )
    parser.add_argument(
        "--extra",
        nargs="*",
        default=[],
        help="Extra directories to watch in --listen mode.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging verbosity (default: INFO).",
    )
    args = parser.parse_args()

    _setup_logging(getattr(logging, args.log_level))

    # ---- OS Listener mode ----
    if args.listen:
        from os_listener import start_listener
        start_listener(
            extra_paths=args.extra or None,
            log_level=getattr(logging, args.log_level),
        )
        return

    # ---- Normal watched_folder mode ----
    logger = logging.getLogger("main")

    watch_paths = [DEFAULT_WATCH]
    for wp in watch_paths:
        os.makedirs(wp, exist_ok=True)

    # Initialize all services
    identity_service = FileIdentityService()
    qdrant = QdrantClient(vector_size=768)  # Match nomic-embed-text dimension
    
    # Text extraction for multiple formats
    text_extractor = TextExtractor()
    
    # Gemma3 4B for both vision and summarization (multimodal model)
    vision = VisionService(model_name="gemma3:4b")
    
    # Same Gemma3 4B model for summarization + categorization
    categories = [
        "Technology",
        "Science",
        "Business",
        "Health",
        "Education",
        "Legal",
        "Finance",
        "Personal",
        "Creative",
        "Other",
    ]
    summarization = SummarizationService(
        model_name="gemma3:4b",
        max_tokens=150,
        categories=categories,
    )
    
    # Embedding service (Ollama nomic-embed-text, 768 dims)
    embedding = EmbeddingService(model_name="nomic-embed-text", dimension=768)

    processor = DocumentProcessor(
        identity_service=identity_service,
        qdrant=qdrant,
        embedding=embedding,
        summarization=summarization,
        text_extractor=text_extractor,
        vision=vision,
    )

    def _handle_event(event: FSEvent) -> None:
        logger.info("Processing event: %s", event.to_dict())
        processor.process(event)

    event_queue = EventQueue(handler=_handle_event)
    event_queue.start()

    scanner = ReconciliationScanner(
        watch_paths=watch_paths,
        identity_service=identity_service,
        qdrant=qdrant,
    )
    scanner.run()

    watcher = FileWatcher(paths=watch_paths, emit=event_queue.enqueue)
    watcher.start()

    shutdown = False

    def _signal_handler(sig: int, frame: object) -> None:
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info("Pipeline running. Watching: %s  (Ctrl+C to stop)", watch_paths)

    try:
        while not shutdown:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Shutting down...")
        watcher.stop()
        event_queue.drain()
        event_queue.stop()
        logger.info("Pipeline stopped.")


if __name__ == "__main__":
    main()
```

---

## 2 · `os_listener.py`

**Description:**
Reactive real-time filesystem listener. Watches Desktop, Documents, and Downloads (auto-resolved via Windows registry). Purely event-driven — no scanning of existing files, no reconciliation. Filters out OS noise (temp files, hidden files, system dirs). Each new filesystem event is printed as a clean one-liner and processed through the full pipeline. Supports `--extra` paths and `--log-level`. All internal module loggers are silenced to CRITICAL to keep terminal output clean.

**Content:**
```python
"""
OS Listener — Reactive real-time filesystem monitoring.

Watches Desktop, Documents, Downloads for NEW events only.
No scanning, no reconciliation, no checking existing files.
Pure event-driven: when you create/download/modify/delete a file → it reacts.

Usage:
    python os_listener.py
    python os_listener.py --extra "C:\\Projects"
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import signal
import sys
import time
from pathlib import Path
from typing import List, Optional

# ── Silence ALL internal module loggers BEFORE importing them ──────────
# CRITICAL = only show if the whole system is crashing, nothing else
_INTERNAL_LOGGERS = (
    "identity_service", "state_machine", "qdrant_client",
    "document_processor", "event_queue", "watcher",
    "embedding_service", "summarization_service",
    "vision_service", "text_extractor", "reconciliation",
    "watchdog", "watchdog.observers", "watchdog.observers.inotify_buffer",
    "urllib3", "httpx",
)
for _mod in _INTERNAL_LOGGERS:
    logging.getLogger(_mod).setLevel(logging.CRITICAL)

from document_processor import DocumentProcessor
from embedding_service import EmbeddingService
from event_queue import EventQueue
from identity_service import FileIdentityService
from models import EventType, FSEvent
from qdrant_client import QdrantClient
from summarization_service import SummarizationService
from text_extractor import TextExtractor
from vision_service import VisionService
from watcher import FileWatcher

# ── Logger for this module only ───────────────────────────────────────
LOG_FORMAT = "%(asctime)s  %(message)s"
logger = logging.getLogger("os_listener")


# ======================================================================
# Noise filter — skip temp/system/hidden files
# ======================================================================

_NOISE_EXT = frozenset({
    ".tmp", ".temp", ".part", ".crdownload", ".partial", ".download",
    ".opdownload", ".swp", ".swo", ".swx", ".bak", ".orig",
    ".ds_store", ".db-journal", ".lock", ".lck", ".lockfile",
})

_NOISE_PREFIXES = ("~$", ".~", "._", ".goutputstream-")

_NOISE_NAMES = frozenset({
    "thumbs.db", "desktop.ini", ".ds_store",
    "ntuser.dat", "ntuser.dat.log1", "ntuser.dat.log2",
    "iconcache.db",
})

_NOISE_DIRS = frozenset({
    "__pycache__", ".git", ".svn", ".hg", "node_modules",
    ".vscode", ".idea", "$recycle.bin",
    "system volume information", ".cache", ".thumbnails",
})


def _is_noise(path: str | None) -> bool:
    if not path:
        return True
    base = os.path.basename(path).lower()
    _, ext = os.path.splitext(base)
    if base in _NOISE_NAMES:
        return True
    if ext in _NOISE_EXT:
        return True
    for pfx in _NOISE_PREFIXES:
        if base.startswith(pfx):
            return True
    if base.startswith(".") and base not in (".", ".."):
        return True
    parts = {p.lower() for p in Path(path).parts}
    if parts & _NOISE_DIRS:
        return True
    return False


# ======================================================================
# Resolve OS user directories
# ======================================================================

def _resolve_win_folder(name: str) -> Optional[str]:
    try:
        import winreg
        sub_key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        reg_map = {"Desktop": "Desktop", "Documents": "Personal",
                   "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}"}
        reg_name = reg_map.get(name)
        if not reg_name:
            return None
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
            val, _ = winreg.QueryValueEx(key, reg_name)
            expanded = os.path.expandvars(val)
            return os.path.normpath(expanded) if os.path.isdir(expanded) else None
    except Exception:
        return None


def get_watch_dirs() -> List[str]:
    home = str(Path.home())
    is_win = platform.system() == "Windows"
    dirs: List[str] = []
    for name in ("Desktop", "Documents", "Downloads"):
        resolved = _resolve_win_folder(name) if is_win else None
        if not resolved:
            resolved = os.path.join(home, name)
        if os.path.isdir(resolved):
            dirs.append(os.path.normpath(resolved))
    return dirs


# ======================================================================
# Main listener
# ======================================================================

def start_listener(
    extra_paths: Optional[List[str]] = None,
    log_level: int = logging.INFO,
) -> None:
    """
    Start reactive OS listener. Only responds to NEW events.
    No scanning of existing files. No reconciliation.
    """
    logging.basicConfig(level=log_level, format=LOG_FORMAT, stream=sys.stdout)

    # Keep internal loggers silent regardless of global level
    for _mod in _INTERNAL_LOGGERS:
        logging.getLogger(_mod).setLevel(logging.CRITICAL)

    # Resolve directories
    watch_paths = get_watch_dirs()
    if extra_paths:
        for p in extra_paths:
            norm = os.path.normpath(os.path.abspath(p))
            if os.path.isdir(norm):
                watch_paths.append(norm)

    if not watch_paths:
        logger.error("No directories to watch.")
        sys.exit(1)

    # ── Print banner ──────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  OS LISTENER — Reactive mode (new events only)")
    print("=" * 60)
    for wp in watch_paths:
        print(f"  ► {wp}")
    print("=" * 60)
    print()

    # ── Build pipeline ────────────────────────────────────────────────
    identity_svc = FileIdentityService()
    qdrant = QdrantClient(vector_size=768)
    text_ext = TextExtractor()
    vision = VisionService(model_name="gemma3:4b")
    summarization = SummarizationService(
        model_name="gemma3:4b", max_tokens=150,
        categories=["Technology", "Science", "Business", "Health",
                     "Education", "Legal", "Finance", "Personal",
                     "Creative", "Other"],
    )
    embedding = EmbeddingService(model_name="nomic-embed-text", dimension=768)

    processor = DocumentProcessor(
        identity_service=identity_svc,
        qdrant=qdrant,
        embedding=embedding,
        summarization=summarization,
        text_extractor=text_ext,
        vision=vision,
    )

    # ── Event handler — only real user files ──────────────────────────
    count = 0

    def _on_event(event: FSEvent) -> None:
        nonlocal count
        path = event.dest_path or event.path or event.src_path
        if _is_noise(path):
            return

        count += 1
        etype = event.event_type.value
        fname = os.path.basename(path or "?")

        # Print a clean one-liner
        print(f"  [{count}] {etype:20s}  {fname}")

        try:
            processor.process(event)
            # Confirm for create/modify — the ones that write to Qdrant
            if event.event_type in (
                EventType.FILE_CREATED, EventType.FILE_MODIFIED,
            ):
                print(f"       → done")
        except Exception as e:
            print(f"       ✗ {e}")

    # ── Start event queue + watcher ───────────────────────────────────
    eq = EventQueue(handler=_on_event)
    eq.start()

    watcher = FileWatcher(paths=watch_paths, emit=eq.enqueue)
    watcher.start()

    # ── Graceful shutdown ─────────────────────────────────────────────
    shutdown = False

    def _sig(sig: int, frame: object) -> None:
        nonlocal shutdown
        shutdown = True

    import threading
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _sig)
        signal.signal(signal.SIGTERM, _sig)

    print("  Listening... (Ctrl+C to stop)\n")

    try:
        while not shutdown:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n  Shutting down...")
        watcher.stop()
        eq.drain()
        eq.stop()
        print(f"  Done. Processed {count} events.\n")


# ======================================================================
# CLI
# ======================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OS Listener — reactive filesystem monitoring")
    parser.add_argument("--extra", nargs="*", default=[], help="Extra directories to watch")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="WARNING",
                        help="Log level (default: WARNING — minimal output)")
    args = parser.parse_args()
    start_listener(
        extra_paths=args.extra or None,
        log_level=getattr(logging, args.log_level),
    )
```

---

## 3 · `document_processor.py`

**Description:**
Central event router. Receives `FSEvent` objects and dispatches them to create/modify/delete/rename/move handlers. For create & modify, runs the content pipeline: tries image description first (via VisionService — describe only, NOT stored in Qdrant), then text extraction → summarization → embedding → Qdrant upsert. Falls back to metadata-only storage for unsupported formats. Images are described by the vision LLM but their descriptions are deliberately not persisted to the vector database.

**Content:**
```python
from __future__ import annotations

import logging
import os
from typing import Optional

from embedding_service import EmbeddingService
from identity_service import FileIdentityService
from models import EventType, FileIdentity, FSEvent
from qdrant_client import QdrantClient
from summarization_service import SummarizationService
from text_extractor import TextExtractor
from vision_service import VisionService

logger = logging.getLogger(__name__)


class DocumentProcessor:

    def __init__(
        self,
        identity_service: FileIdentityService,
        qdrant: QdrantClient,
        embedding: EmbeddingService,
        summarization: SummarizationService,
        text_extractor: TextExtractor,
        vision: VisionService,
    ) -> None:
        self._identity = identity_service
        self._qdrant = qdrant
        self._embedding = embedding
        self._summarization = summarization
        self._text_extractor = text_extractor
        self._vision = vision

    _DISPATCH: dict[EventType, str] = {
        EventType.FILE_CREATED: "_on_create",
        EventType.FILE_MODIFIED: "_on_modify",
        EventType.FILE_DELETED: "_on_delete",
        EventType.FILE_RENAMED: "_on_rename",
        EventType.FILE_MOVED: "_on_move",
        EventType.DIRECTORY_CREATED: "_on_create",
        EventType.DIRECTORY_DELETED: "_on_delete",
        EventType.DIRECTORY_RENAMED: "_on_rename",
        EventType.DIRECTORY_MOVED: "_on_move",
    }

    def process(self, event: FSEvent) -> None:
        method_name = self._DISPATCH.get(event.event_type)
        if method_name:
            getattr(self, method_name)(event)
        else:
            logger.debug("DocumentProcessor: no handler for %s", event.event_type.value)

    def _on_create(self, event: FSEvent) -> None:
        path = event.dest_path or event.path or event.src_path
        if not path or event.is_directory:
            if path:
                self._identity.register(path, is_directory=True)
            return
        identity = self._identity.register(path)
        self._sync_to_qdrant(path, identity)

    def _on_modify(self, event: FSEvent) -> None:
        path = event.path or event.src_path
        if not path or event.is_directory:
            return
        identity = self._identity.handle_modify(path)
        if not identity:
            identity = self._identity.register(path)
        self._sync_to_qdrant(path, identity)

    def _on_delete(self, event: FSEvent) -> None:
        path = event.path or event.src_path
        if not path:
            return
        identity = self._identity.handle_delete(path)
        if not identity:
            return
        self._qdrant.delete_vector(identity.file_id)

    def _on_rename(self, event: FSEvent) -> None:
        src = event.src_path
        dest = event.dest_path
        if not src or not dest:
            return
        identity = self._identity.handle_rename(src, dest)
        if not identity:
            return
        self._qdrant.update_payload(identity.file_id, identity.to_dict())

    def _on_move(self, event: FSEvent) -> None:
        self._on_rename(event)

    def _sync_to_qdrant(self, path: str, identity: FileIdentity) -> None:
        """Enhanced RAG workflow: text/image → process → summarize → embed → store."""
        
        # Try image processing first
        if self._vision.can_process(path):
            self._process_image(path, identity)
            return
        
        # Try text extraction
        if self._text_extractor.can_extract(path):
            self._process_text(path, identity)
            return
        
        # Fallback: store metadata only
        logger.debug("[DocumentProcessor] Unsupported format, storing metadata only: %s", path)
        self._qdrant.upsert_metadata(point_id=identity.file_id, payload=identity.to_dict())

    def _process_text(self, path: str, identity: FileIdentity) -> None:
        """
        Text workflow: extract → summarize → embed → store
        """
        logger.debug("[DocumentProcessor] Processing text file: %s", path)
        
        # Step 1: Extract text
        text = self._text_extractor.extract(path)
        if not text or not text.strip():
            logger.warning("[DocumentProcessor] No text extracted from %s", path)
            self._qdrant.upsert_metadata(point_id=identity.file_id, payload=identity.to_dict())
            return
        
        # Step 2: Summarize with LLM
        result = self._summarization.summarize(text, max_length=5000)
        summary = result["summary"]
        category = result["category"]
        if not summary:
            logger.warning("[DocumentProcessor] Summarization failed for %s", path)
            summary = text[:500]  # Fallback to truncated original
            category = "Other"
        
        # Step 3: Embed the summary
        vector = self._embedding.embed(summary)
        
        # Step 4: Store in Qdrant with enriched payload
        payload = identity.to_dict()
        payload.update({
            "content_type": "text",
            "summary": summary,
            "category": category,
            "original_length": len(text),
            "summary_length": len(summary),
        })
        
        self._qdrant.upsert_vector(
            point_id=identity.file_id,
            vector=vector,
            payload=payload,
        )
        logger.info(
            "[DocumentProcessor] Text processed: %s (original=%d, summary=%d)",
            os.path.basename(path), len(text), len(summary)
        )

    def _process_image(self, path: str, identity: FileIdentity) -> None:
        """
        Image workflow: describe only (NO Qdrant storage).
        The description is generated and logged but images are not stored
        in the vector database.
        """
        logger.debug("[DocumentProcessor] Processing image file: %s", path)

        description = self._vision.describe_image(path)
        if not description or not description.strip():
            logger.warning("[DocumentProcessor] No description generated for %s", path)
            return

        logger.info(
            "[DocumentProcessor] Image described (not stored in Qdrant): %s (%d chars)",
            os.path.basename(path), len(description),
        )
```

---

## 4 · `vision_service.py`

**Description:**
Multimodal image description service using Ollama's gemma3:4b. Reads images from disk via Pillow, resizes large images to max 1280px, converts to RGB, encodes as base64 PNG, and sends directly to the LLM so it truly sees the pixels. Waits up to 3 seconds for files to be fully written (handles in-progress downloads/screenshots). Falls back to raw byte reading if Pillow is unavailable. Uses a detailed 6-step analysis prompt (objects, text, layout, context, colors, details). Image descriptions are NOT stored in Qdrant — only generated and logged.

**Content:**
```python
from __future__ import annotations

import base64
import io
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Max image dimension (width or height) to send to the LLM.
# Larger images get resized — keeps VRAM usage sane and speeds up inference.
_MAX_IMAGE_DIM = 1280


def _read_image_as_base64(path: str, max_dim: int = _MAX_IMAGE_DIM) -> Optional[str]:
    """Read an image, resize if needed, return as base64 PNG string.

    This guarantees the LLM actually receives pixel data — no ambiguity
    about file paths, partial writes, or encoding issues.
    """
    try:
        from PIL import Image as PILImage

        img = PILImage.open(path)
        img.load()  # force full read from disk

        # Convert palette / RGBA to RGB so the LLM gets clean data
        if img.mode in ("P", "LA"):
            img = img.convert("RGBA")
        if img.mode == "RGBA":
            bg = PILImage.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize large images to keep things fast
        w, h = img.size
        if max(w, h) > max_dim:
            ratio = max_dim / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), PILImage.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    except ImportError:
        # Pillow not installed — fall back to raw file read
        logger.debug("[VisionService] Pillow not available, reading raw file bytes")
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
        except Exception as e:
            logger.error("[VisionService] Failed to read image %s: %s", path, e)
            return None
    except Exception as e:
        logger.error("[VisionService] Failed to process image %s: %s", path, e)
        return None


class VisionService:
    """Vision language model for image description (gemma3:4b multimodal)."""

    _PROMPT = (
        "You are an expert image analyst. Examine this image carefully and "
        "produce a thorough, precise description.\n\n"
        "1. **What is shown** — Identify every distinct object, person, icon, "
        "UI element, or region visible. Name applications, websites, brands, "
        "or tools if recognizable.\n\n"
        "2. **Text & labels** — Transcribe ALL readable text exactly as it "
        "appears: titles, buttons, menus, URLs, filenames, code snippets, "
        "error messages, timestamps, watermarks. Quote them verbatim.\n\n"
        "3. **Layout & structure** — Describe the arrangement: columns, panels, "
        "tabs, overlapping windows, split screens, sidebars.\n\n"
        "4. **Context & meaning** — What activity or task does this image "
        "represent? Is it a screenshot, a photo, artwork, a diagram, a chat? "
        "State clearly.\n\n"
        "5. **Colors & visual style** — Color scheme, dark/light mode, "
        "highlighted or selected elements.\n\n"
        "6. **Key details** — Error states, progress bars, notifications, "
        "selected items, cursor position, timestamps.\n\n"
        "Be factual and exhaustive. Do NOT guess or invent content that is not "
        "visible. Write in plain English paragraphs."
    )

    def __init__(self, model_name: str = "gemma3:4b") -> None:
        self._model_name = model_name
        self._ollama_available = self._check_ollama()
        logger.info(
            "[VisionService] Initialized model=%s (available=%s)",
            model_name, self._ollama_available,
        )

    def _check_ollama(self) -> bool:
        try:
            import ollama
            ollama.list()
            return True
        except ImportError:
            logger.warning("[VisionService] ollama not installed — stub mode")
            return False
        except Exception as e:
            logger.warning("[VisionService] ollama unavailable: %s — stub mode", e)
            return False

    def can_process(self, path: str) -> bool:
        ext = os.path.splitext(path)[1].lower()
        return ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}

    # ------------------------------------------------------------------

    def describe_image(self, path: str) -> Optional[str]:
        """Describe the image at *path* using the vision LLM.

        The image is read from disk, optionally resized, converted to base64
        PNG, and sent directly to Ollama so the model truly *sees* the pixels.
        """
        if not os.path.exists(path):
            logger.warning("[VisionService] Image not found: %s", path)
            return None
        if not self.can_process(path):
            logger.warning("[VisionService] Unsupported format: %s", path)
            return None

        # Wait briefly for the file to be fully written (downloads / screenshots)
        self._wait_for_stable(path, timeout=3.0)

        if not self._ollama_available:
            return self._stub_describe(path)

        # Read + resize + base64 encode
        b64_data = _read_image_as_base64(path)
        if not b64_data:
            return self._stub_describe(path)

        try:
            import ollama

            response = ollama.chat(
                model=self._model_name,
                messages=[{
                    "role": "user",
                    "content": self._PROMPT,
                    "images": [b64_data],  # base64 string — Ollama accepts this directly
                }],
                options={"temperature": 0.3},
            )

            description = response["message"]["content"].strip()
            logger.info(
                "[VisionService] Described %s (%d chars)",
                os.path.basename(path), len(description),
            )
            return description

        except Exception as e:
            logger.error("[VisionService] describe failed for %s: %s", path, e)
            return self._stub_describe(path)

    # ------------------------------------------------------------------

    @staticmethod
    def _wait_for_stable(path: str, timeout: float = 3.0) -> None:
        """Wait until the file size stops changing (file fully written)."""
        deadline = time.monotonic() + timeout
        prev_size = -1
        while time.monotonic() < deadline:
            try:
                cur = os.path.getsize(path)
            except OSError:
                break
            if cur == prev_size and cur > 0:
                return
            prev_size = cur
            time.sleep(0.3)

    def _stub_describe(self, path: str) -> str:
        try:
            size = os.path.getsize(path)
            ext = os.path.splitext(path)[1]
            return f"Image file: {os.path.basename(path)} ({ext} format, {size} bytes)"
        except Exception:
            return f"Image file: {os.path.basename(path)}"
```

---

## 5 · `text_extractor.py`

**Description:**
Multi-format text extraction service. Supports plain text files (.txt, .md, .log, .json, .xml, .csv, .py, .js, .java, .cpp, .c, .h), Microsoft Word (.docx via python-docx), and PDF (.pdf via PyPDF2). Gracefully degrades if optional libraries are missing.

**Content:**
```python
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class TextExtractor:
    """Extracts text from various file formats."""

    def __init__(self) -> None:
        logger.info("[TextExtractor] Initialized")
        self._docx_available = self._check_docx()
        self._pdf_available = self._check_pdf()

    def _check_docx(self) -> bool:
        try:
            import docx
            return True
        except ImportError:
            logger.warning("[TextExtractor] python-docx not installed - .docx support disabled")
            return False

    def _check_pdf(self) -> bool:
        try:
            import PyPDF2
            return True
        except ImportError:
            logger.warning("[TextExtractor] PyPDF2 not installed - .pdf support disabled")
            return False

    def can_extract(self, path: str) -> bool:
        """Check if file type is supported for text extraction."""
        ext = os.path.splitext(path)[1].lower()
        if ext in {".txt", ".md", ".log", ".json", ".xml", ".csv", ".py", ".js", ".java", ".cpp", ".c", ".h"}:
            return True
        if ext == ".docx" and self._docx_available:
            return True
        if ext == ".pdf" and self._pdf_available:
            return True
        return False

    def extract(self, path: str) -> Optional[str]:
        """Extract text content from file."""
        if not os.path.exists(path):
            logger.warning("[TextExtractor] File not found: %s", path)
            return None

        ext = os.path.splitext(path)[1].lower()

        try:
            if ext in {".txt", ".md", ".log", ".json", ".xml", ".csv", ".py", ".js", ".java", ".cpp", ".c", ".h"}:
                return self._extract_plain_text(path)
            elif ext == ".docx" and self._docx_available:
                return self._extract_docx(path)
            elif ext == ".pdf" and self._pdf_available:
                return self._extract_pdf(path)
            else:
                logger.debug("[TextExtractor] Unsupported file type: %s", ext)
                return None
        except Exception as e:
            logger.error("[TextExtractor] Failed to extract from %s: %s", path, e)
            return None

    def _extract_plain_text(self, path: str) -> Optional[str]:
        """Extract plain text files."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
                logger.info("[TextExtractor] Extracted plain text from %s (%d chars)", path, len(text))
                return text
        except Exception as e:
            logger.error("[TextExtractor] Plain text extraction failed: %s", e)
            return None

    def _extract_docx(self, path: str) -> Optional[str]:
        """Extract text from .docx files."""
        try:
            import docx
            doc = docx.Document(path)
            text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
            logger.info("[TextExtractor] Extracted .docx from %s (%d chars)", path, len(text))
            return text
        except Exception as e:
            logger.error("[TextExtractor] .docx extraction failed: %s", e)
            return None

    def _extract_pdf(self, path: str) -> Optional[str]:
        """Extract text from .pdf files."""
        try:
            import PyPDF2
            with open(path, "rb") as fh:
                reader = PyPDF2.PdfReader(fh)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                logger.info("[TextExtractor] Extracted .pdf from %s (%d chars)", path, len(text))
                return text.strip()
        except Exception as e:
            logger.error("[TextExtractor] .pdf extraction failed: %s", e)
            return None
```

---

## 6 · `summarization_service.py`

**Description:**
LLM-based text summarization and categorization using Ollama gemma3:4b. Takes raw text, truncates to max length, asks the LLM to produce JSON with `summary` and `category` fields. Categories are configurable (default: Technology, Science, Business, Health, Education, Legal, Finance, Personal, Creative, Other). Has robust JSON parsing with fallbacks for markdown-wrapped responses and malformed output. Includes fuzzy category matching.

**Content:**
```python
from __future__ import annotations

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES: list[str] = [
    "Technology",
    "Science",
    "Business",
    "Health",
    "Education",
    "Legal",
    "Finance",
    "Personal",
    "Creative",
    "Other",
]


class SummarizationService:
    """LLM service for text summarization (max 4B parameters)."""

    def __init__(
        self,
        model_name: str = "gemma3:4b",
        max_tokens: int = 150,
        categories: Optional[list[str]] = None,
    ) -> None:
        """
        Initialize summarization service.
        
        Args:
            model_name: Ollama model name (e.g., "gemma3:4b", "llama3.2:3b", "phi3:3.8b")
            max_tokens: Maximum tokens in summary
            categories: Fixed list of allowed categories. Defaults to DEFAULT_CATEGORIES.
        """
        self._model_name = model_name
        self._max_tokens = max_tokens
        self._categories = categories if categories is not None else list(DEFAULT_CATEGORIES)
        self._ollama_available = self._check_ollama()
        logger.info(
            "[SummarizationService] Initialized with model=%s, categories=%s (available=%s)",
            model_name,
            self._categories,
            self._ollama_available,
        )

    def _check_ollama(self) -> bool:
        """Check if ollama is available."""
        try:
            import ollama
            # Test connection
            ollama.list()
            return True
        except ImportError:
            logger.warning("[SummarizationService] ollama not installed - using stub mode")
            return False
        except Exception as e:
            logger.warning("[SummarizationService] ollama not available: %s - using stub mode", e)
            return False

    def summarize(self, text: str, max_length: int = 500) -> dict[str, str]:
        """
        Generate a summary and a category for the text using local LLM.
        
        Args:
            text: Input text to summarize
            max_length: Maximum characters to process (truncate if longer)
        
        Returns:
            Dict with keys "summary" and "category"
        """
        if not text or not text.strip():
            logger.warning("[SummarizationService] Empty text provided")
            return {"summary": "", "category": "Other"}

        # Truncate very long texts to avoid context overflow
        if len(text) > max_length:
            text_to_summarize = text[:max_length] + "..."
            logger.info("[SummarizationService] Truncated text from %d to %d chars", len(text), max_length)
        else:
            text_to_summarize = text

        if not self._ollama_available:
            return self._stub_summarize(text_to_summarize)

        try:
            import ollama

            categories_str = ", ".join(self._categories)
            prompt = f"""Analyze the following text. You must respond with ONLY valid JSON, no other text.

The JSON must have exactly two keys:
- "summary": a concise 2-3 sentence summary of the main topics and key information
- "category": exactly one category from this list: [{categories_str}]

Text:
{text_to_summarize}

Respond with ONLY the JSON object:"""

            response = ollama.chat(
                model=self._model_name,
                messages=[{
                    'role': 'user',
                    'content': prompt,
                }],
                options={
                    "num_predict": self._max_tokens,
                    "temperature": 0.3,
                }
            )

            raw = response['message']['content'].strip()
            result = self._parse_response(raw)
            logger.info(
                "[SummarizationService] Generated summary (input=%d chars, summary=%d chars, category=%s)",
                len(text_to_summarize),
                len(result["summary"]),
                result["category"],
            )
            return result

        except Exception as e:
            logger.error("[SummarizationService] Summarization failed: %s", e)
            return self._stub_summarize(text_to_summarize)

    def _parse_response(self, raw: str) -> dict[str, str]:
        """Parse the LLM JSON response, extracting summary and category."""
        # Try direct JSON parse
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "summary" in data and "category" in data:
                return {
                    "summary": str(data["summary"]).strip(),
                    "category": self._validate_category(str(data["category"]).strip()),
                }
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code block
        json_match = re.search(r'```(?:json)?\s*({.*?})\s*```', raw, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if isinstance(data, dict) and "summary" in data and "category" in data:
                    return {
                        "summary": str(data["summary"]).strip(),
                        "category": self._validate_category(str(data["category"]).strip()),
                    }
            except json.JSONDecodeError:
                pass

        # Try extracting JSON from anywhere in the text
        json_match = re.search(r'({[^{}]*"summary"[^{}]*"category"[^{}]*})', raw, re.DOTALL)
        if not json_match:
            json_match = re.search(r'({[^{}]*"category"[^{}]*"summary"[^{}]*})', raw, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return {
                    "summary": str(data.get("summary", raw)).strip(),
                    "category": self._validate_category(str(data.get("category", "Other")).strip()),
                }
            except json.JSONDecodeError:
                pass

        # Last resort: use raw text as summary
        logger.warning("[SummarizationService] Could not parse JSON from response, using raw text")
        return {"summary": raw, "category": "Other"}

    def _validate_category(self, category: str) -> str:
        """Ensure the category is one of the allowed values."""
        # Exact match
        for c in self._categories:
            if c.lower() == category.lower():
                return c
        # Partial / fuzzy match
        for c in self._categories:
            if c.lower() in category.lower() or category.lower() in c.lower():
                return c
        logger.warning(
            "[SummarizationService] Unknown category '%s', defaulting to 'Other'",
            category,
        )
        return "Other"

    def _stub_summarize(self, text: str) -> dict[str, str]:
        """Fallback stub - returns truncated original text with 'Other' category."""
        max_stub_length = 200
        if len(text) <= max_stub_length:
            logger.info("[SummarizationService] STUB - returning original text (%d chars)", len(text))
            return {"summary": text, "category": "Other"}
        
        truncated = text[:max_stub_length] + "..."
        logger.info(
            "[SummarizationService] STUB - returning truncated text (%d chars)",
            len(truncated),
        )
        return {"summary": truncated, "category": "Other"}
```

---

## 7 · `embedding_service.py`

**Description:**
Text-to-vector embedding service using Ollama's `nomic-embed-text` model (768 dimensions). Wraps `ollama.embed()` with error handling and a zero-vector fallback stub when Ollama is unavailable.

**Content:**
```python
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding service using Ollama nomic-embed-text."""

    def __init__(self, model_name: str = "nomic-embed-text", dimension: int = 768) -> None:
        """
        Initialize embedding service.
        
        Args:
            model_name: Ollama embedding model name (default: "nomic-embed-text" = 768 dims)
            dimension: Expected embedding dimension (must match model)
        """
        self._model_name = model_name
        self._dimension = dimension
        self._ollama_available = self._check_ollama()
        
        logger.info(
            "[EmbeddingService] Initialized with model=%s, dim=%d (available=%s)",
            model_name,
            dimension,
            self._ollama_available,
        )

    def _check_ollama(self) -> bool:
        """Check if ollama is available."""
        try:
            import ollama
            ollama.list()
            return True
        except ImportError:
            logger.warning("[EmbeddingService] ollama not installed - using stub mode")
            return False
        except Exception as e:
            logger.warning("[EmbeddingService] ollama not available: %s - using stub mode", e)
            return False

    def embed(self, text: str) -> list[float]:
        """
        Generate embedding vector from text using Ollama.
        
        Args:
            text: Input text to embed
        
        Returns:
            Embedding vector (list of floats)
        """
        if not text or not text.strip():
            logger.warning("[EmbeddingService] Empty text provided, returning zero vector")
            return [0.0] * self._dimension

        if self._ollama_available:
            try:
                import ollama
                response = ollama.embed(model=self._model_name, input=text)
                vector = response["embeddings"][0]
                logger.info(
                    "[EmbeddingService] Generated embedding (text=%d chars, dim=%d)",
                    len(text),
                    len(vector),
                )
                return vector
            except Exception as e:
                logger.error("[EmbeddingService] Embedding generation failed: %s", e)
                return self._stub_embed(text)
        else:
            return self._stub_embed(text)

    def _stub_embed(self, text: str) -> list[float]:
        """Fallback stub - returns zero vector."""
        logger.info(
            "[EmbeddingService] STUB - returning zero vector (text=%d chars, dim=%d)",
            len(text),
            self._dimension,
        )
        return [0.0] * self._dimension
```

---

## 8 · `qdrant_client.py`

**Description:**
Lightweight Qdrant vector database REST client using only stdlib `urllib`. Manages a single collection (`documents`, 768-dim, Cosine distance). Provides: `ensure_collection`, `upsert_vector`, `delete_vector`, `search`, `upsert_metadata` (zero-vector for non-embeddable files), `update_payload`, `get_point`, `scroll`. Operates in offline mode if Qdrant is unreachable.

**Content:**
```python
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Optional

logger = logging.getLogger(__name__)


class QdrantClient:

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection: str = "documents",
        api_key: Optional[str] = None,
        vector_size: int = 768,
    ) -> None:
        self._url = url.rstrip("/")
        self._collection = collection
        self._api_key = api_key
        self._vector_size = vector_size
        self.ensure_collection()

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            h["api-key"] = self._api_key
        return h

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict | list] = None,
    ) -> dict[str, Any]:
        url = f"{self._url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            logger.error(
                "[QdrantClient] HTTP %s %s -> %d: %s",
                method, url, exc.code, error_body,
            )
            raise
        except urllib.error.URLError as exc:
            logger.error("[QdrantClient] Connection error %s %s: %s", method, url, exc.reason)
            raise

    # ── collection management ──────────────────────────────────────────

    def ensure_collection(self) -> None:
        try:
            self._request("GET", f"/collections/{self._collection}")
            logger.info("[QdrantClient] Collection '%s' already exists", self._collection)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                logger.info("[QdrantClient] Creating collection '%s'", self._collection)
                self._request("PUT", f"/collections/{self._collection}", {
                    "vectors": {
                        "size": self._vector_size,
                        "distance": "Cosine",
                    }
                })
                logger.info("[QdrantClient] Collection '%s' created", self._collection)
            else:
                raise
        except urllib.error.URLError:
            logger.warning(
                "[QdrantClient] Cannot reach Qdrant at %s — operating in offline mode",
                self._url,
            )

    # ── upsert (create or update) ──────────────────────────────────────

    def upsert_vector(
        self,
        point_id: str,
        vector: list[float],
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        body = {
            "points": [
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": payload or {},
                }
            ]
        }
        try:
            result = self._request(
                "PUT",
                f"/collections/{self._collection}/points?wait=true",
                body,
            )
            logger.info(
                "[QdrantClient] Upserted point id=%s dim=%d into '%s'",
                point_id, len(vector), self._collection,
            )
            return result
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            logger.error("[QdrantClient] Failed to upsert point %s: %s", point_id, exc)
            return {"status": "error", "point_id": point_id}

    # ── delete ─────────────────────────────────────────────────────────

    def delete_vector(self, point_id: str) -> dict[str, Any]:
        body = {
            "points": [point_id],
        }
        try:
            result = self._request(
                "POST",
                f"/collections/{self._collection}/points/delete?wait=true",
                body,
            )
            logger.info(
                "[QdrantClient] Deleted point id=%s from '%s'",
                point_id, self._collection,
            )
            return result
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            logger.error("[QdrantClient] Failed to delete point %s: %s", point_id, exc)
            return {"status": "error", "point_id": point_id}

    # ── search ─────────────────────────────────────────────────────────

    def search(
        self,
        vector: list[float],
        limit: int = 5,
        score_threshold: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "vector": vector,
            "limit": limit,
            "with_payload": True,
        }
        if score_threshold is not None:
            body["score_threshold"] = score_threshold
        try:
            result = self._request(
                "POST",
                f"/collections/{self._collection}/points/search",
                body,
            )
            return result.get("result", [])
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            logger.error("[QdrantClient] Search failed: %s", exc)
            return []

    # ── upsert metadata-only (zero vector for non-embeddable files) ───

    def upsert_metadata(
        self,
        point_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        zero_vector = [0.0] * self._vector_size
        return self.upsert_vector(point_id=point_id, vector=zero_vector, payload=payload)

    # ── update payload on existing point ───────────────────────────────

    def update_payload(
        self,
        point_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        body = {
            "points": [point_id],
            "payload": payload,
        }
        try:
            result = self._request(
                "POST",
                f"/collections/{self._collection}/points/payload",
                body,
            )
            logger.info("[QdrantClient] Updated payload for point id=%s", point_id)
            return result
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            logger.error("[QdrantClient] Failed to update payload %s: %s", point_id, exc)
            return {"status": "error", "point_id": point_id}

    # ── get single point ───────────────────────────────────────────────

    def get_point(self, point_id: str) -> Optional[dict[str, Any]]:
        try:
            result = self._request(
                "GET",
                f"/collections/{self._collection}/points/{point_id}",
            )
            return result.get("result")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        except urllib.error.URLError as exc:
            logger.error("[QdrantClient] Failed to get point %s: %s", point_id, exc)
            return None

    # ── scroll / list all points ───────────────────────────────────────

    def scroll(
        self,
        limit: int = 100,
        offset: Optional[str] = None,
        filter_payload: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        if offset:
            body["offset"] = offset
        if filter_payload:
            body["filter"] = filter_payload
        try:
            result = self._request(
                "POST",
                f"/collections/{self._collection}/points/scroll",
                body,
            )
            return result.get("result", {}).get("points", [])
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            logger.error("[QdrantClient] Scroll failed: %s", exc)
            return []
```

---

## 9 · `identity_service.py`

**Description:**
Thread-safe file identity tracker. Assigns a UUID to each file and tracks it by path, content hash (SHA-256), and ID. Supports register, modify (rehash), delete, rename/move, and purge. When a deleted file reappears with the same hash, it restores the original identity (hash-based resurrection). Uses `StateMachine` for lifecycle state transitions.

**Content:**
```python
from __future__ import annotations

import hashlib
import logging
import os
import threading
from typing import Optional

from models import EventType, FileIdentity, FileState, FileStatus
from state_machine import StateMachine

logger = logging.getLogger(__name__)

_BUFFER_SIZE = 65536


def _compute_hash(path: str) -> Optional[str]:
    try:
        sha = hashlib.sha256()
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(_BUFFER_SIZE)
                if not chunk:
                    break
                sha.update(chunk)
        return sha.hexdigest()
    except (OSError, IOError):
        return None


class FileIdentityService:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_path: dict[str, FileIdentity] = {}
        self._by_hash: dict[str, list[FileIdentity]] = {}
        self._by_id: dict[str, FileIdentity] = {}
        self._state_machine = StateMachine()

    def _normalize(self, path: str) -> str:
        return os.path.normpath(os.path.abspath(path))

    def _index_hash(self, identity: FileIdentity) -> None:
        if identity.content_hash:
            self._by_hash.setdefault(identity.content_hash, [])
            if identity not in self._by_hash[identity.content_hash]:
                self._by_hash[identity.content_hash].append(identity)

    def _unindex_hash(self, identity: FileIdentity) -> None:
        if identity.content_hash and identity.content_hash in self._by_hash:
            entries = self._by_hash[identity.content_hash]
            self._by_hash[identity.content_hash] = [e for e in entries if e.file_id != identity.file_id]
            if not self._by_hash[identity.content_hash]:
                del self._by_hash[identity.content_hash]

    def get_by_path(self, path: str) -> Optional[FileIdentity]:
        with self._lock:
            return self._by_path.get(self._normalize(path))

    def get_by_id(self, file_id: str) -> Optional[FileIdentity]:
        with self._lock:
            return self._by_id.get(file_id)

    def get_all(self) -> list[FileIdentity]:
        with self._lock:
            return list(self._by_id.values())

    def register(self, path: str, is_directory: bool = False) -> FileIdentity:
        norm = self._normalize(path)
        with self._lock:
            existing = self._by_path.get(norm)
            if existing and existing.status == FileStatus.ACTIVE:
                return existing

            content_hash = None if is_directory else _compute_hash(norm)

            if content_hash:
                candidates = self._by_hash.get(content_hash, [])
                for candidate in candidates:
                    if candidate.status == FileStatus.DELETED:
                        logger.info(
                            "Restoring identity %s (hash match) at %s",
                            candidate.file_id,
                            norm,
                        )
                        old_path = candidate.current_path
                        if old_path in self._by_path and self._by_path[old_path].file_id == candidate.file_id:
                            del self._by_path[old_path]
                        candidate.current_path = norm
                        candidate.status = FileStatus.ACTIVE
                        candidate.state = FileState.ACTIVE
                        self._by_path[norm] = candidate
                        return candidate

            identity = FileIdentity(
                current_path=norm,
                content_hash=content_hash,
                status=FileStatus.ACTIVE,
                state=FileState.NEW,
            )
            ns = self._state_machine.transition(identity.state, EventType.FILE_CREATED)
            if ns:
                identity.state = ns
            self._by_path[norm] = identity
            self._by_id[identity.file_id] = identity
            self._index_hash(identity)
            logger.info("Registered new identity %s for %s", identity.file_id, norm)
            return identity

    def handle_modify(self, path: str) -> Optional[FileIdentity]:
        norm = self._normalize(path)
        with self._lock:
            identity = self._by_path.get(norm)
            if not identity:
                return None
            self._unindex_hash(identity)
            identity.content_hash = _compute_hash(norm)
            self._index_hash(identity)
            ns = self._state_machine.transition(identity.state, EventType.FILE_MODIFIED)
            if ns:
                identity.state = ns
            logger.info("Modified identity %s hash=%s", identity.file_id, identity.content_hash)
            return identity

    def handle_delete(self, path: str) -> Optional[FileIdentity]:
        norm = self._normalize(path)
        with self._lock:
            identity = self._by_path.get(norm)
            if not identity:
                return None
            identity.status = FileStatus.DELETED
            ns = self._state_machine.transition(identity.state, EventType.FILE_DELETED)
            if ns:
                identity.state = ns
            del self._by_path[norm]
            logger.info("Marked deleted identity %s at %s", identity.file_id, norm)
            return identity

    def handle_rename(self, src: str, dest: str) -> Optional[FileIdentity]:
        src_n = self._normalize(src)
        dest_n = self._normalize(dest)
        with self._lock:
            identity = self._by_path.get(src_n)
            if not identity:
                return None
            del self._by_path[src_n]
            identity.current_path = dest_n
            self._by_path[dest_n] = identity

            src_dir = os.path.dirname(src_n)
            dest_dir = os.path.dirname(dest_n)
            if src_dir == dest_dir:
                event = EventType.FILE_RENAMED
            else:
                event = EventType.FILE_MOVED

            ns = self._state_machine.transition(identity.state, event)
            if ns:
                identity.state = ns
            logger.info(
                "Rename/move identity %s: %s -> %s (event=%s)",
                identity.file_id,
                src_n,
                dest_n,
                event.value,
            )
            return identity

    def handle_move(self, src: str, dest: str) -> Optional[FileIdentity]:
        return self.handle_rename(src, dest)

    def purge(self, file_id: str) -> bool:
        with self._lock:
            identity = self._by_id.get(file_id)
            if not identity:
                return False
            if not StateMachine.can_purge(identity.state):
                logger.warning("Cannot purge identity %s in state %s", file_id, identity.state.value)
                return False
            identity.state = FileState.PURGED
            identity.status = FileStatus.DELETED
            self._unindex_hash(identity)
            if identity.current_path in self._by_path:
                del self._by_path[identity.current_path]
            del self._by_id[file_id]
            logger.info("Purged identity %s", file_id)
            return True
```

---

## 10 · `state_machine.py`

**Description:**
Deterministic finite state machine for file lifecycle transitions. States: NEW → ACTIVE → MODIFIED / RENAMED / MOVED / DELETED → PURGED. Defines which events are valid from each state. Only DELETED files can be purged.

**Content:**
```python
from __future__ import annotations

import logging
from typing import Optional

from models import EventType, FileState

logger = logging.getLogger(__name__)

_TRANSITIONS: dict[FileState, dict[EventType, FileState]] = {
    FileState.NEW: {
        EventType.FILE_CREATED: FileState.ACTIVE,
        EventType.DIRECTORY_CREATED: FileState.ACTIVE,
    },
    FileState.ACTIVE: {
        EventType.FILE_MODIFIED: FileState.MODIFIED,
        EventType.FILE_RENAMED: FileState.RENAMED,
        EventType.FILE_MOVED: FileState.MOVED,
        EventType.FILE_DELETED: FileState.DELETED,
        EventType.DIRECTORY_RENAMED: FileState.RENAMED,
        EventType.DIRECTORY_MOVED: FileState.MOVED,
        EventType.DIRECTORY_DELETED: FileState.DELETED,
    },
    FileState.MODIFIED: {
        EventType.FILE_MODIFIED: FileState.MODIFIED,
        EventType.FILE_RENAMED: FileState.RENAMED,
        EventType.FILE_MOVED: FileState.MOVED,
        EventType.FILE_DELETED: FileState.DELETED,
    },
    FileState.MOVED: {
        EventType.FILE_MODIFIED: FileState.MODIFIED,
        EventType.FILE_RENAMED: FileState.RENAMED,
        EventType.FILE_MOVED: FileState.MOVED,
        EventType.FILE_DELETED: FileState.DELETED,
        EventType.DIRECTORY_RENAMED: FileState.RENAMED,
        EventType.DIRECTORY_MOVED: FileState.MOVED,
        EventType.DIRECTORY_DELETED: FileState.DELETED,
    },
    FileState.RENAMED: {
        EventType.FILE_MODIFIED: FileState.MODIFIED,
        EventType.FILE_RENAMED: FileState.RENAMED,
        EventType.FILE_MOVED: FileState.MOVED,
        EventType.FILE_DELETED: FileState.DELETED,
        EventType.DIRECTORY_RENAMED: FileState.RENAMED,
        EventType.DIRECTORY_MOVED: FileState.MOVED,
        EventType.DIRECTORY_DELETED: FileState.DELETED,
    },
    FileState.DELETED: {
        EventType.FILE_CREATED: FileState.ACTIVE,
        EventType.DIRECTORY_CREATED: FileState.ACTIVE,
    },
    FileState.PURGED: {},
}


class StateMachine:

    def transition(self, current_state: FileState, event_type: EventType) -> Optional[FileState]:
        allowed = _TRANSITIONS.get(current_state, {})
        next_state = allowed.get(event_type)
        if next_state is None:
            logger.warning(
                "No valid transition from state=%s on event=%s",
                current_state.value,
                event_type.value,
            )
            return None
        logger.info(
            "State transition: %s -[%s]-> %s",
            current_state.value,
            event_type.value,
            next_state.value,
        )
        return next_state

    @staticmethod
    def can_purge(current_state: FileState) -> bool:
        return current_state == FileState.DELETED
```

---

## 11 · `event_queue.py`

**Description:**
Thread-safe FIFO event queue. A background worker thread dequeues `FSEvent` objects and passes them to a configurable handler callback. Supports start/stop/drain (wait for empty).

**Content:**
```python
from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, Optional

from models import FSEvent

logger = logging.getLogger(__name__)


class EventQueue:

    def __init__(self, handler: Callable[[FSEvent], None], max_size: int = 0) -> None:
        self._queue: queue.Queue[Optional[FSEvent]] = queue.Queue(maxsize=max_size)
        self._handler = handler
        self._worker_thread: Optional[threading.Thread] = None
        self._running = threading.Event()

    def start(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._running.set()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="EventQueueWorker")
        self._worker_thread.start()
        logger.info("EventQueue worker started")

    def stop(self) -> None:
        self._running.clear()
        self._queue.put(None)
        if self._worker_thread:
            self._worker_thread.join(timeout=10)
        logger.info("EventQueue worker stopped")

    def enqueue(self, event: FSEvent) -> None:
        self._queue.put(event)
        logger.debug("Enqueued event: %s", event.event_type.value)

    def _worker_loop(self) -> None:
        while self._running.is_set():
            try:
                event = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if event is None:
                break
            try:
                self._handler(event)
            except Exception:
                logger.exception("Error processing event %s", event.event_type.value)
            finally:
                self._queue.task_done()

    def drain(self) -> None:
        self._queue.join()
```

---

## 12 · `watcher.py`

**Description:**
Wrapper around the `watchdog` library. Translates raw watchdog events into `FSEvent` model objects. Includes deduplication (150ms window) and Windows move inference (350ms window — pairs a delete + create of the same filename from different directories into a single MOVED event). Flushes expired pending events in a background thread.

**Content:**
```python
from __future__ import annotations

import logging
import os
import platform
import threading
import time
from typing import Callable, Optional

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from models import EventType, FSEvent

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"
_MOVE_WINDOW_SEC = 0.35
_DEDUP_WINDOW_SEC = 0.15


class _MoveTracker:

    def __init__(self, window: float = _MOVE_WINDOW_SEC) -> None:
        self._window = window
        self._lock = threading.Lock()
        self._pending_deletes: dict[str, tuple[FSEvent, float]] = {}
        self._pending_creates: dict[str, tuple[FSEvent, float]] = {}

    def add_delete(self, event: FSEvent) -> None:
        key = os.path.basename(event.path or event.src_path or "")
        with self._lock:
            self._pending_deletes[key] = (event, time.monotonic())

    def add_create(self, event: FSEvent) -> None:
        key = os.path.basename(event.path or event.dest_path or event.src_path or "")
        with self._lock:
            self._pending_creates[key] = (event, time.monotonic())

    def try_match_move(self, event: FSEvent, is_create: bool) -> Optional[FSEvent]:
        if not _IS_WINDOWS:
            return None
        key = os.path.basename(
            event.path or event.dest_path or event.src_path or ""
        )
        now = time.monotonic()
        with self._lock:
            if is_create:
                if key in self._pending_deletes:
                    del_event, ts = self._pending_deletes[key]
                    if now - ts <= self._window:
                        del self._pending_deletes[key]
                        src = del_event.path or del_event.src_path
                        dest = event.path or event.dest_path or event.src_path
                        if src and dest and os.path.dirname(os.path.normpath(src)) != os.path.dirname(os.path.normpath(dest)):
                            return FSEvent(
                                event_type=EventType.FILE_MOVED if not event.is_directory else EventType.DIRECTORY_MOVED,
                                src_path=src,
                                dest_path=dest,
                                is_directory=event.is_directory,
                            )
            else:
                if key in self._pending_creates:
                    cr_event, ts = self._pending_creates[key]
                    if now - ts <= self._window:
                        del self._pending_creates[key]
                        src = event.path or event.src_path
                        dest = cr_event.path or cr_event.dest_path or cr_event.src_path
                        if src and dest and os.path.dirname(os.path.normpath(src)) != os.path.dirname(os.path.normpath(dest)):
                            return FSEvent(
                                event_type=EventType.FILE_MOVED if not event.is_directory else EventType.DIRECTORY_MOVED,
                                src_path=src,
                                dest_path=dest,
                                is_directory=event.is_directory,
                            )
        return None

    def flush_expired(self) -> list[FSEvent]:
        now = time.monotonic()
        expired: list[FSEvent] = []
        with self._lock:
            for key in list(self._pending_deletes):
                ev, ts = self._pending_deletes[key]
                if now - ts > self._window:
                    expired.append(ev)
                    del self._pending_deletes[key]
            for key in list(self._pending_creates):
                ev, ts = self._pending_creates[key]
                if now - ts > self._window:
                    expired.append(ev)
                    del self._pending_creates[key]
        return expired


class _DedupTracker:

    def __init__(self, window: float = _DEDUP_WINDOW_SEC) -> None:
        self._window = window
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}

    def _make_key(self, event: FSEvent) -> str:
        parts = [
            event.event_type.value,
            event.src_path or "",
            event.dest_path or "",
            event.path or "",
            str(event.is_directory),
        ]
        return "|".join(parts)

    def is_duplicate(self, event: FSEvent) -> bool:
        key = self._make_key(event)
        now = time.monotonic()
        with self._lock:
            self._cleanup(now)
            if key in self._seen and now - self._seen[key] < self._window:
                return True
            self._seen[key] = now
            return False

    def _cleanup(self, now: float) -> None:
        expired = [k for k, t in self._seen.items() if now - t > self._window * 3]
        for k in expired:
            del self._seen[k]


class _WatchdogHandler(FileSystemEventHandler):

    def __init__(self, emit: Callable[[FSEvent], None]) -> None:
        super().__init__()
        self._emit = emit
        self._move_tracker = _MoveTracker()
        self._dedup = _DedupTracker()
        self._flush_thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._running.set()
        self._start_flusher()

    def stop(self) -> None:
        self._running.clear()
        if self._flush_thread:
            self._flush_thread.join(timeout=5)

    def _start_flusher(self) -> None:
        def _loop() -> None:
            while self._running.is_set():
                expired = self._move_tracker.flush_expired()
                for ev in expired:
                    if not self._dedup.is_duplicate(ev):
                        self._emit(ev)
                time.sleep(_MOVE_WINDOW_SEC / 2)
        self._flush_thread = threading.Thread(target=_loop, daemon=True, name="MoveFlushThread")
        self._flush_thread.start()

    def _normalize(self, path: str) -> str:
        return os.path.normpath(os.path.abspath(path))

    def on_created(self, event: FileSystemEvent) -> None:
        is_dir = isinstance(event, DirCreatedEvent)
        et = EventType.DIRECTORY_CREATED if is_dir else EventType.FILE_CREATED
        fs_ev = FSEvent(
            event_type=et,
            path=self._normalize(event.src_path),
            src_path=self._normalize(event.src_path),
            is_directory=is_dir,
        )
        if _IS_WINDOWS:
            move = self._move_tracker.try_match_move(fs_ev, is_create=True)
            if move:
                if not self._dedup.is_duplicate(move):
                    self._emit(move)
                return
            self._move_tracker.add_create(fs_ev)
            return
        if not self._dedup.is_duplicate(fs_ev):
            self._emit(fs_ev)

    def on_deleted(self, event: FileSystemEvent) -> None:
        is_dir = isinstance(event, DirDeletedEvent)
        et = EventType.DIRECTORY_DELETED if is_dir else EventType.FILE_DELETED
        fs_ev = FSEvent(
            event_type=et,
            path=self._normalize(event.src_path),
            src_path=self._normalize(event.src_path),
            is_directory=is_dir,
        )
        if _IS_WINDOWS:
            move = self._move_tracker.try_match_move(fs_ev, is_create=False)
            if move:
                if not self._dedup.is_duplicate(move):
                    self._emit(move)
                return
            self._move_tracker.add_delete(fs_ev)
            return
        if not self._dedup.is_duplicate(fs_ev):
            self._emit(fs_ev)

    def on_modified(self, event: FileSystemEvent) -> None:
        if isinstance(event, (DirCreatedEvent, DirDeletedEvent)):
            return
        is_dir = not isinstance(event, FileModifiedEvent)
        if is_dir:
            return
        fs_ev = FSEvent(
            event_type=EventType.FILE_MODIFIED,
            path=self._normalize(event.src_path),
            src_path=self._normalize(event.src_path),
            is_directory=False,
        )
        if not self._dedup.is_duplicate(fs_ev):
            self._emit(fs_ev)

    def on_moved(self, event: FileSystemEvent) -> None:
        is_dir = isinstance(event, DirMovedEvent)
        src = self._normalize(event.src_path)
        dest = self._normalize(event.dest_path)
        src_dir = os.path.dirname(src)
        dest_dir = os.path.dirname(dest)
        if src_dir == dest_dir:
            et = EventType.DIRECTORY_RENAMED if is_dir else EventType.FILE_RENAMED
        else:
            et = EventType.DIRECTORY_MOVED if is_dir else EventType.FILE_MOVED
        fs_ev = FSEvent(
            event_type=et,
            src_path=src,
            dest_path=dest,
            is_directory=is_dir,
        )
        if not self._dedup.is_duplicate(fs_ev):
            self._emit(fs_ev)


class FileWatcher:

    def __init__(self, paths: list[str], emit: Callable[[FSEvent], None], recursive: bool = True) -> None:
        self._paths = [os.path.normpath(os.path.abspath(p)) for p in paths]
        self._recursive = recursive
        self._handler = _WatchdogHandler(emit)
        self._observer = Observer()

    def start(self) -> None:
        for p in self._paths:
            if not os.path.isdir(p):
                os.makedirs(p, exist_ok=True)
            self._observer.schedule(self._handler, p, recursive=self._recursive)
            logger.info("Watching: %s (recursive=%s)", p, self._recursive)
        self._observer.start()

    def stop(self) -> None:
        self._handler.stop()
        self._observer.stop()
        self._observer.join(timeout=10)
        logger.info("FileWatcher stopped")
```

---

## 13 · `models.py`

**Description:**
Core data models and enums. Defines `EventType` (9 filesystem events), `FileStatus` (active/deleted/trashed), `FileState` (lifecycle states for the state machine), `FSEvent` (timestamped event dataclass), and `FileIdentity` (UUID + hash + path + status tracking).

**Content:**
```python
from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class EventType(str, enum.Enum):
    FILE_CREATED = "file_created"
    FILE_MODIFIED = "file_modified"
    FILE_DELETED = "file_deleted"
    FILE_RENAMED = "file_renamed"
    FILE_MOVED = "file_moved"
    DIRECTORY_CREATED = "directory_created"
    DIRECTORY_DELETED = "directory_deleted"
    DIRECTORY_RENAMED = "directory_renamed"
    DIRECTORY_MOVED = "directory_moved"


class FileStatus(str, enum.Enum):
    ACTIVE = "active"
    DELETED = "deleted"
    TRASHED = "trashed"


class FileState(str, enum.Enum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    MOVED = "MOVED"
    RENAMED = "RENAMED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    PURGED = "PURGED"


@dataclass
class FSEvent:
    event_type: EventType
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    src_path: Optional[str] = None
    dest_path: Optional[str] = None
    path: Optional[str] = None
    is_directory: bool = False

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "src_path": self.src_path,
            "dest_path": self.dest_path,
            "path": self.path,
            "timestamp": self.timestamp,
            "is_directory": self.is_directory,
        }


@dataclass
class FileIdentity:
    file_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content_hash: Optional[str] = None
    original_created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    current_path: str = ""
    status: FileStatus = FileStatus.ACTIVE
    state: FileState = FileState.NEW

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "content_hash": self.content_hash,
            "original_created_at": self.original_created_at,
            "current_path": self.current_path,
            "status": self.status.value,
            "state": self.state.value,
        }
```

---

## 14 · `reconciliation.py`

**Description:**
Startup disk-scan reconciliation. Walks all watched directories, registers any files not yet tracked by the identity service, and marks tracked files that no longer exist on disk as deleted. **Only used in normal `watched_folder` mode** — the reactive OS listener (`--listen`) does NOT use reconciliation.

**Content:**
```python
from __future__ import annotations

import logging
import os
from typing import Set

from identity_service import FileIdentityService
from models import FileStatus
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)


class ReconciliationScanner:

    def __init__(
        self,
        watch_paths: list[str],
        identity_service: FileIdentityService,
        qdrant: QdrantClient,
    ) -> None:
        self._watch_paths = watch_paths
        self._identity = identity_service
        self._qdrant = qdrant

    def run(self) -> None:
        logger.info("=== Reconciliation scan started ===")
        disk_paths = self._scan_disk()
        self._sync_new_files(disk_paths)
        self._mark_missing(disk_paths)
        logger.info("=== Reconciliation scan completed (%d files on disk) ===", len(disk_paths))

    def _scan_disk(self) -> Set[str]:
        found: Set[str] = set()
        for root_path in self._watch_paths:
            norm_root = os.path.normpath(os.path.abspath(root_path))
            if not os.path.isdir(norm_root):
                continue
            for dirpath, _dirnames, filenames in os.walk(norm_root):
                for fn in filenames:
                    full = os.path.normpath(os.path.join(dirpath, fn))
                    found.add(full)
        return found

    def _sync_new_files(self, disk_paths: Set[str]) -> None:
        registered = 0
        for path in disk_paths:
            existing = self._identity.get_by_path(path)
            if existing is None:
                identity = self._identity.register(path)
                self._qdrant.upsert_metadata(identity.file_id, identity.to_dict())
                registered += 1
                logger.debug("Reconciliation: registered %s -> %s", path, identity.file_id)
        if registered:
            logger.info("Reconciliation: registered %d new files", registered)

    def _mark_missing(self, disk_paths: Set[str]) -> None:
        marked = 0
        for identity in self._identity.get_all():
            if identity.status != FileStatus.ACTIVE:
                continue
            if identity.current_path not in disk_paths:
                self._identity.handle_delete(identity.current_path)
                self._qdrant.delete_vector(identity.file_id)
                marked += 1
                logger.debug(
                    "Reconciliation: marked missing %s (%s)",
                    identity.current_path,
                    identity.file_id,
                )
        if marked:
            logger.info("Reconciliation: marked %d files as missing", marked)
```

---

## 15 · `reset_qdrant.py`

**Description:**
Standalone utility script to wipe and recreate the Qdrant `documents` collection. Deletes the collection, waits 2 seconds, recreates with 768-dim Cosine vectors and 32MB WAL, then verifies 0 points. Run with `python reset_qdrant.py`.

**Content:**
```python
"""
Reset Qdrant — Delete and recreate the 'documents' collection.

Usage:
    python reset_qdrant.py
"""

import json
import sys
import time
import urllib.request
import urllib.error

QDRANT_URL = "http://localhost:6333"
COLLECTION = "documents"
VECTOR_SIZE = 768


def reset():
    # 1) Delete
    print(f"Deleting collection '{COLLECTION}'...", end=" ")
    try:
        req = urllib.request.Request(
            f"{QDRANT_URL}/collections/{COLLECTION}",
            method="DELETE",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        print("OK")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("(didn't exist)")
        else:
            print(f"ERROR {e.code}")
            sys.exit(1)
    except urllib.error.URLError as e:
        print(f"\nCannot reach Qdrant at {QDRANT_URL}: {e.reason}")
        sys.exit(1)

    # 2) Wait for cleanup
    time.sleep(2)

    # 3) Recreate empty
    print(f"Creating empty collection '{COLLECTION}' (dim={VECTOR_SIZE}, cosine)...", end=" ")
    body = json.dumps({
        "vectors": {"size": VECTOR_SIZE, "distance": "Cosine"},
        "wal_config": {"wal_capacity_mb": 32},
    }).encode()
    req = urllib.request.Request(
        f"{QDRANT_URL}/collections/{COLLECTION}",
        data=body,
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()
    print("OK")

    # 4) Verify
    req = urllib.request.Request(f"{QDRANT_URL}/collections/{COLLECTION}")
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
        pts = d["result"]["points_count"]
    print(f"Done. Collection '{COLLECTION}' ready — {pts} points.\n")


if __name__ == "__main__":
    reset()
```

---

## 16 · `ollamatest.py`

**Description:**
Quick manual test script for verifying Ollama image description works. Sends a local `photo.jpg` to gemma3:4b with a simple prompt. Not part of the main pipeline — just a scratch/debug file.

**Content:**
```python
import ollama
 response = ollama.chat(
    model='gemma3:4b',
    messages=[{
        'role': 'user',
        'content': 'What is in this image?',
        'images': ['./photo.jpg']  # Just pass the path string here
    }]
)
print(response['message']['content'])
```

---

## 17 · `requirements.txt`

**Description:**
Python package dependencies for the project. Core: watchdog, ollama, Pillow. Text extraction: python-docx, PyPDF2. Embedding (optional/legacy): sentence-transformers, torch, transformers, accelerate, huggingface_hub.

**Content:**
```
# Core dependencies
watchdog>=3.0.0

# Embedding generation (sentence-transformers)
sentence-transformers>=2.2.0
torch>=2.0.0
transformers>=4.30.0
accelerate>=0.20.0

# LLM integration (Ollama - optional, can use transformers instead)
ollama>=0.1.0

# Document processing
python-docx>=0.8.11
PyPDF2>=3.0.0

# HuggingFace Hub (for model downloads)
huggingface_hub>=0.16.0

# Image processing (resize / convert before feeding to vision LLM)
Pillow>=10.0.0
```

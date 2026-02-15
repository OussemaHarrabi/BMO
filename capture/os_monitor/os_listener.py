"""
OS Listener — Reactive real-time filesystem monitoring for BMO.

Watches Desktop, Documents, Downloads for NEW events only.
Pure event-driven: when you create/download/modify/delete a file → it reacts.

Usage:
    python -m bmo.capture.os_monitor.os_listener
    python -m bmo.capture.os_monitor.os_listener --extra "C:\\Projects"
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

_INTERNAL_LOGGERS = (
    "identity_service", "state_machine", "qdrant_client",
    "document_processor", "event_queue", "watcher",
    "embedding_service", "summarization_service",
    "vision_service", "text_extractor", "reconciliation",
    "watchdog", "watchdog.observers", "watchdog.observers.inotify_buffer",
    "urllib3", "httpx", "neo4j", "bmo",
)
for _mod in _INTERNAL_LOGGERS:
    logging.getLogger(_mod).setLevel(logging.CRITICAL)

from bmo.capture.os_monitor.document_processor import DocumentProcessor
from bmo.capture.os_monitor.embedding_service import EmbeddingService
from bmo.capture.os_monitor.event_queue import EventQueue
from bmo.capture.os_monitor.identity_service import FileIdentityService
from bmo.capture.os_monitor.models import EventType, FSEvent
from bmo.capture.os_monitor.summarization_service import SummarizationService
from bmo.capture.os_monitor.text_extractor import TextExtractor
from bmo.capture.os_monitor.vision_service import VisionService
from bmo.capture.os_monitor.watcher import FileWatcher
from bmo.memory.vector_store import VectorStore
from bmo.memory.knowledge_graph import KnowledgeGraph

LOG_FORMAT = "%(asctime)s  %(message)s"
logger = logging.getLogger("os_listener")


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


def _resolve_win_folder(name: str) -> Optional[str]:
    try:
        import winreg
        sub_key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        reg_map = {
            "Desktop": "Desktop",
            "Documents": "Personal",
            "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}"
        }
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


def start_listener(
    extra_paths: Optional[List[str]] = None,
    log_level: int = logging.INFO,
) -> None:
    """Start reactive OS listener with BMO integration."""
    logging.basicConfig(level=log_level, format=LOG_FORMAT, stream=sys.stdout)

    for _mod in _INTERNAL_LOGGERS:
        logging.getLogger(_mod).setLevel(logging.CRITICAL)

    watch_paths = get_watch_dirs()
    if extra_paths:
        for p in extra_paths:
            norm = os.path.normpath(os.path.abspath(p))
            if os.path.isdir(norm):
                watch_paths.append(norm)

    if not watch_paths:
        logger.error("No directories to watch.")
        sys.exit(1)

    print()
    print("=" * 60)
    print("  BMO OS LISTENER — Reactive mode (Qdrant + Neo4j)")
    print("=" * 60)
    for wp in watch_paths:
        print(f"  ► {wp}")
    print("=" * 60)
    print()

    identity_svc = FileIdentityService()
    vector_store = VectorStore()
    text_ext = TextExtractor()
    vision = VisionService()
    summarization = SummarizationService()
    embedding = EmbeddingService()
    
    try:
        knowledge_graph = KnowledgeGraph()
        print("  ✓ Neo4j connected")
    except Exception as e:
        print(f"  ⚠ Neo4j unavailable: {e}")
        knowledge_graph = None

    processor = DocumentProcessor(
        identity_service=identity_svc,
        vector_store=vector_store,
        embedding=embedding,
        summarization=summarization,
        text_extractor=text_ext,
        vision=vision,
        knowledge_graph=knowledge_graph,
    )

    count = 0

    def _on_event(event: FSEvent) -> None:
        nonlocal count
        path = event.dest_path or event.path or event.src_path
        if _is_noise(path):
            return

        count += 1
        etype = event.event_type.value
        fname = os.path.basename(path or "?")

        print(f"  [{count}] {etype:20s}  {fname}")

        try:
            processor.process(event)
            if event.event_type in (EventType.FILE_CREATED, EventType.FILE_MODIFIED):
                print(f"       → stored in Qdrant + Neo4j")
        except Exception as e:
            print(f"       ✗ {e}")

    eq = EventQueue(handler=_on_event)
    eq.start()

    watcher = FileWatcher(paths=watch_paths, emit=eq.enqueue)
    watcher.start()

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
        if knowledge_graph:
            knowledge_graph.close()
        print(f"  Done. Processed {count} events.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BMO OS Listener — reactive filesystem monitoring")
    parser.add_argument("--extra", nargs="*", default=[], help="Extra directories to watch")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="WARNING",
        help="Log level (default: WARNING)"
    )
    args = parser.parse_args()
    start_listener(
        extra_paths=args.extra or None,
        log_level=getattr(logging, args.log_level),
    )

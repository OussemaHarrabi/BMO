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

from bmo.capture.os_monitor.models import EventType, FSEvent

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

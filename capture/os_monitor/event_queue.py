from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, Optional

from bmo.capture.os_monitor.models import FSEvent

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

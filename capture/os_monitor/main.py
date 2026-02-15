from __future__ import annotations

import logging
import os
import signal
import sys
import time

from bmo.capture.os_monitor.document_processor import DocumentProcessor
from bmo.capture.os_monitor.embedding_service import EmbeddingService
from bmo.capture.os_monitor.event_queue import EventQueue
from bmo.capture.os_monitor.identity_service import FileIdentityService
from bmo.capture.os_monitor.models import FSEvent
from bmo.capture.os_monitor.reconciliation import ReconciliationScanner
from bmo.capture.os_monitor.summarization_service import SummarizationService
from bmo.capture.os_monitor.text_extractor import TextExtractor
from bmo.capture.os_monitor.vision_service import VisionService
from bmo.capture.os_monitor.watcher import FileWatcher
from bmo.core.ollama_client import OllamaClient
from bmo.memory.vector_store import VectorStore

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT, stream=sys.stdout)


def main() -> None:
    _setup_logging()
    logger = logging.getLogger("os_monitor")

    # Read WATCH_PATHS from environment (comma-separated)
    watch_paths_str = os.getenv("WATCH_PATHS", "")
    if watch_paths_str:
        watch_paths = [p.strip() for p in watch_paths_str.split(",") if p.strip()]
    else:
        # Default fallback
        default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watched_folder")
        watch_paths = [default_path]
        logger.warning("WATCH_PATHS not set in environment, using default: %s", default_path)

    # Ensure watch directories exist
    for wp in watch_paths:
        os.makedirs(wp, exist_ok=True)
        logger.info("Watching path: %s", wp)

    # Initialize BMO core services
    ollama_client = OllamaClient()
    
    # Check Ollama is running
    if not ollama_client.health_check_sync():
        logger.error("Ollama is not running! Please start Ollama first.")
        sys.exit(1)
    
    # Initialize vector store (uses bmo_memories collection, 768 dimensions)
    vector_store = VectorStore()
    
    # Initialize identity service
    identity_service = FileIdentityService()
    
    # Initialize processing services with shared OllamaClient
    text_extractor = TextExtractor()
    vision = VisionService(ollama_client=ollama_client)
    summarization = SummarizationService(ollama_client=ollama_client, max_tokens=150)
    embedding = EmbeddingService(ollama_client=ollama_client, dimension=768)

    # Initialize document processor
    processor = DocumentProcessor(
        identity_service=identity_service,
        vector_store=vector_store,
        embedding=embedding,
        summarization=summarization,
        text_extractor=text_extractor,
        vision=vision,
    )

    def _handle_event(event: FSEvent) -> None:
        logger.info("Processing event: %s", event.to_dict())
        processor.process(event)

    # Initialize event queue
    event_queue = EventQueue(handler=_handle_event)
    event_queue.start()

    # Run reconciliation scan to sync existing files
    scanner = ReconciliationScanner(
        watch_paths=watch_paths,
        identity_service=identity_service,
        vector_store=vector_store,
    )
    scanner.run()

    # Start file watcher
    watcher = FileWatcher(paths=watch_paths, emit=event_queue.enqueue)
    watcher.start()

    shutdown = False

    def _signal_handler(sig: int, frame: object) -> None:
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info("OS Monitor running. Watching: %s  (Ctrl+C to stop)", watch_paths)

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
        logger.info("OS Monitor stopped.")


if __name__ == "__main__":
    main()

from __future__ import annotations

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
    _setup_logging()
    logger = logging.getLogger("main")

    watch_paths = [DEFAULT_WATCH]
    for wp in watch_paths:
        os.makedirs(wp, exist_ok=True)

    # Initialize all services
    identity_service = FileIdentityService()
    qdrant = QdrantClient(vector_size=384)  # Match embedding dimension
    
    # Text extraction for multiple formats
    text_extractor = TextExtractor()
    
    # Vision model for image description (max 4B)
    vision = VisionService(model_name="llava-phi3:3.8b")  # or "llava:7b"
    
    # LLM for summarization (max 4B)
    summarization = SummarizationService(model_name="llama3.2:3b", max_tokens=150)
    
    # Embedding service (sentence-transformers recommended)
    embedding = EmbeddingService(dimension=384)

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

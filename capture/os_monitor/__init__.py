"""
OS Monitor Module - File system monitoring and document processing.

Integrates file watching, text/image processing, and vector storage.
"""

from bmo.capture.os_monitor.document_processor import DocumentProcessor
from bmo.capture.os_monitor.embedding_service import EmbeddingService
from bmo.capture.os_monitor.event_queue import EventQueue
from bmo.capture.os_monitor.identity_service import FileIdentityService
from bmo.capture.os_monitor.models import (
    EventType,
    FileIdentity,
    FileState,
    FileStatus,
    FSEvent,
)
from bmo.capture.os_monitor.reconciliation import ReconciliationScanner
from bmo.capture.os_monitor.state_machine import StateMachine
from bmo.capture.os_monitor.summarization_service import SummarizationService
from bmo.capture.os_monitor.text_extractor import TextExtractor
from bmo.capture.os_monitor.vision_service import VisionService
from bmo.capture.os_monitor.watcher import FileWatcher

__all__ = [
    "DocumentProcessor",
    "EmbeddingService",
    "EventQueue",
    "EventType",
    "FileIdentity",
    "FileIdentityService",
    "FileState",
    "FileStatus",
    "FileWatcher",
    "FSEvent",
    "ReconciliationScanner",
    "StateMachine",
    "SummarizationService",
    "TextExtractor",
    "VisionService",
]

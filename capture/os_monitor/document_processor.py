from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional, List

from bmo.capture.os_monitor.embedding_service import EmbeddingService
from bmo.capture.os_monitor.identity_service import FileIdentityService
from bmo.capture.os_monitor.models import EventType, FileIdentity, FSEvent
from bmo.capture.os_monitor.summarization_service import SummarizationService
from bmo.capture.os_monitor.text_extractor import TextExtractor
from bmo.capture.os_monitor.text_chunker import RecursiveTextChunker
from bmo.capture.os_monitor.vision_service import VisionService
from bmo.memory.vector_store import VectorStore
from bmo.memory.knowledge_graph import KnowledgeGraph, extract_entities_from_text

logger = logging.getLogger(__name__)

LARGE_DOCUMENT_THRESHOLD = 3000


class DocumentProcessor:

    def __init__(
        self,
        identity_service: FileIdentityService,
        vector_store: VectorStore,
        embedding: EmbeddingService,
        summarization: SummarizationService,
        text_extractor: TextExtractor,
        vision: VisionService,
        knowledge_graph: Optional[KnowledgeGraph] = None,
    ) -> None:
        self._identity = identity_service
        self._vector_store = vector_store
        self._embedding = embedding
        self._summarization = summarization
        self._text_extractor = text_extractor
        self._vision = vision
        self._knowledge_graph = knowledge_graph or self._init_knowledge_graph()
        self._chunker = RecursiveTextChunker(chunk_size=1500, chunk_overlap=200)

    def _init_knowledge_graph(self) -> Optional[KnowledgeGraph]:
        """Initialize KnowledgeGraph, return None if connection fails."""
        try:
            return KnowledgeGraph()
        except Exception as e:
            logger.warning("[DocumentProcessor] Neo4j unavailable, skipping graph: %s", e)
            return None

    def _extract_entity_names(self, text: str) -> List[str]:
        """Extract entity names from text for storage in Qdrant."""
        try:
            extracted = extract_entities_from_text(text)
            entity_names = []
            entity_names.extend(f["name"] for f in extracted.files)
            entity_names.extend(f["name"] for f in extracted.folders)
            entity_names.extend(a["name"] for a in extracted.apps)
            entity_names.extend(w["name"] for w in extracted.websites)
            entity_names.extend(u["domain"] for u in extracted.urls)
            return entity_names
        except Exception as e:
            logger.warning("[DocumentProcessor] Entity extraction failed: %s", e)
            return []

    @staticmethod
    def _parse_timestamp(timestamp_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO timestamp string to datetime."""
        if not timestamp_str:
            return None
        try:
            # Handle ISO format with timezone
            if timestamp_str.endswith('Z'):
                timestamp_str = timestamp_str[:-1] + '+00:00'
            return datetime.fromisoformat(timestamp_str)
        except (ValueError, TypeError) as e:
            logger.debug("[DocumentProcessor] Could not parse timestamp %s: %s", timestamp_str, e)
            return None

    def process(self, event: FSEvent) -> None:
        handler = _DISPATCH.get(event.event_type)
        if handler:
            handler(self, event)
        else:
            logger.debug("DocumentProcessor: no handler for %s", event.event_type.value)

    def _on_create(self, event: FSEvent) -> None:
        path = event.dest_path or event.path or event.src_path
        if not path or event.is_directory:
            if path:
                self._identity.register(path, is_directory=True)
            return
        identity = self._identity.register(path)
        self._sync_to_vector_store(path, identity, event.timestamp)

    def _on_modify(self, event: FSEvent) -> None:
        path = event.path or event.src_path
        if not path or event.is_directory:
            return
        identity = self._identity.handle_modify(path)
        if not identity:
            identity = self._identity.register(path)
        self._sync_to_vector_store(path, identity, event.timestamp)

    def _on_delete(self, event: FSEvent) -> None:
        path = event.path or event.src_path
        if not path:
            return
        identity = self._identity.handle_delete(path)
        if not identity:
            return
        self._vector_store.delete_by_source_path(identity.current_path)

    def _on_rename(self, event: FSEvent) -> None:
        src = event.src_path
        dest = event.dest_path
        if not src or not dest:
            return
        identity = self._identity.handle_rename(src, dest)
        if not identity:
            return
        # Update path in vector store by re-syncing
        self._sync_to_vector_store(dest, identity, event.timestamp)

    def _on_move(self, event: FSEvent) -> None:
        self._on_rename(event)

    def _sync_to_vector_store(self, path: str, identity: FileIdentity, timestamp: Optional[str] = None) -> None:
        """Enhanced RAG workflow: text/image → process → summarize → embed → store."""
        created_at = self._parse_timestamp(timestamp)
        
        # Try image processing first
        if self._vision.can_process(path):
            self._process_image(path, identity, created_at)
            return
        
        # Try text extraction
        if self._text_extractor.can_extract(path):
            self._process_text(path, identity, created_at)
            return
        
        # Fallback: store metadata only (no embedding)
        logger.info("[DocumentProcessor] Unsupported format, skipping: %s", path)

    def _process_text(self, path: str, identity: FileIdentity, created_at: Optional[datetime] = None) -> None:
        """Text workflow: extract → chunk (if large) → summarize → embed → store → graph"""
        logger.info("[DocumentProcessor] Processing text file: %s", path)
        
        text = self._text_extractor.extract(path)
        if not text or not text.strip():
            logger.warning("[DocumentProcessor] No text extracted from %s", path)
            return
        
        if len(text) > LARGE_DOCUMENT_THRESHOLD:
            self._process_large_text(path, text, identity, created_at)
        else:
            self._process_small_text(path, text, identity, created_at)

    def _process_small_text(self, path: str, text: str, identity: FileIdentity, created_at: Optional[datetime] = None) -> None:
        """Process small documents as single unit."""
        summary = self._summarization.summarize(text, max_length=5000)
        if not summary:
            summary = text[:500]
        
        # Extract entities from the summary
        entities = self._extract_entity_names(summary)
        
        memory = self._vector_store.add_sync(
            raw_text=text,
            summary=summary,
            category="document",
            source="os_monitor",
            source_path=path,
            tags=[os.path.splitext(path)[1].lower().lstrip(".")],
            entities=entities,
            created_at=created_at
        )
        
        self._ingest_to_graph(summary, memory.memory_id, "file_document")
        
        logger.info(
            "[DocumentProcessor] Text processed: %s (original=%d, summary=%d, entities=%d, memory_id=%s)",
            os.path.basename(path), len(text), len(summary), len(entities), memory.memory_id
        )

    def _process_large_text(self, path: str, text: str, identity: FileIdentity, created_at: Optional[datetime] = None) -> None:
        """Process large documents with recursive chunking."""
        chunks = self._chunker.chunk(text)
        logger.info("[DocumentProcessor] Split large document into %d chunks: %s", len(chunks), path)
        
        all_summaries = []
        
        for i, chunk in enumerate(chunks):
            summary = self._summarization.summarize(chunk, max_length=2000)
            if not summary:
                summary = chunk[:300]
            
            all_summaries.append(summary)
            
            # Extract entities from the chunk summary
            entities = self._extract_entity_names(summary)
            
            memory = self._vector_store.add_sync(
                raw_text=chunk,
                summary=summary,
                category="document_chunk",
                source="os_monitor",
                source_path=path,
                tags=[
                    os.path.splitext(path)[1].lower().lstrip("."),
                    f"chunk_{i+1}_of_{len(chunks)}"
                ],
                entities=entities,
                created_at=created_at
            )
            
            logger.debug(
                "[DocumentProcessor] Chunk %d/%d stored: memory_id=%s, entities=%d",
                i + 1, len(chunks), memory.memory_id, len(entities)
            )
        
        combined_summary = " ".join(all_summaries)
        self._ingest_to_graph(combined_summary, identity.file_id, "file_document_chunked")
        
        logger.info(
            "[DocumentProcessor] Large text processed: %s (%d chunks, total=%d chars)",
            os.path.basename(path), len(chunks), len(text)
        )

    def _ingest_to_graph(self, summary: str, activity_id: str, activity_type: str) -> None:
        """Ingest summary to Neo4j knowledge graph."""
        if not self._knowledge_graph:
            return
        try:
            self._knowledge_graph.ingest_activity(
                text=summary,
                activity_id=activity_id,
                activity_type=activity_type
            )
            logger.debug("[DocumentProcessor] Graph updated: %s", activity_id)
        except Exception as e:
            logger.warning("[DocumentProcessor] Graph ingest failed: %s", e)

    def _process_image(self, path: str, identity: FileIdentity, created_at: Optional[datetime] = None) -> None:
        """Image workflow: vision model → describe → summarize → embed → store → graph"""
        logger.info("[DocumentProcessor] Processing image file: %s", path)
        
        description, image_base64 = self._vision.describe_image_with_base64(path)
        if not description or not description.strip():
            logger.warning("[DocumentProcessor] No description generated for %s", path)
            return
        
        summary = self._summarization.summarize(description, max_length=2000)
        if not summary:
            summary = description[:500]
        
        # Extract entities from the summary
        entities = self._extract_entity_names(summary)
        
        memory = self._vector_store.add_sync(
            raw_text=description,
            summary=summary,
            category="image",
            source="os_monitor",
            source_path=path,
            tags=["image", os.path.splitext(path)[1].lower().lstrip(".")],
            entities=entities,
            image_base64=image_base64,
            created_at=created_at
        )
        
        self._ingest_to_graph(summary, memory.memory_id, "image_capture")
        
        logger.info(
            "[DocumentProcessor] Image processed: %s (description=%d, summary=%d, entities=%d, memory_id=%s)",
            os.path.basename(path), len(description), len(summary), len(entities), memory.memory_id
        )


_DISPATCH = {
    EventType.FILE_CREATED: DocumentProcessor._on_create,
    EventType.FILE_MODIFIED: DocumentProcessor._on_modify,
    EventType.FILE_DELETED: DocumentProcessor._on_delete,
    EventType.FILE_RENAMED: DocumentProcessor._on_rename,
    EventType.FILE_MOVED: DocumentProcessor._on_move,
    EventType.DIRECTORY_CREATED: DocumentProcessor._on_create,
    EventType.DIRECTORY_DELETED: DocumentProcessor._on_delete,
    EventType.DIRECTORY_RENAMED: DocumentProcessor._on_rename,
    EventType.DIRECTORY_MOVED: DocumentProcessor._on_move,
}

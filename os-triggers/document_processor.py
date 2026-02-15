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
        logger.info("[DocumentProcessor] Unsupported format, storing metadata only: %s", path)
        self._qdrant.upsert_metadata(point_id=identity.file_id, payload=identity.to_dict())

    def _process_text(self, path: str, identity: FileIdentity) -> None:
        """
        Text workflow: extract → summarize → embed → store
        """
        logger.info("[DocumentProcessor] Processing text file: %s", path)
        
        # Step 1: Extract text
        text = self._text_extractor.extract(path)
        if not text or not text.strip():
            logger.warning("[DocumentProcessor] No text extracted from %s", path)
            self._qdrant.upsert_metadata(point_id=identity.file_id, payload=identity.to_dict())
            return
        
        # Step 2: Summarize with LLM
        summary = self._summarization.summarize(text, max_length=5000)
        if not summary:
            logger.warning("[DocumentProcessor] Summarization failed for %s", path)
            summary = text[:500]  # Fallback to truncated original
        
        # Step 3: Embed the summary
        vector = self._embedding.embed(summary)
        
        # Step 4: Store in Qdrant with enriched payload
        payload = identity.to_dict()
        payload.update({
            "content_type": "text",
            "summary": summary,
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
        Image workflow: vision model → describe → summarize → embed → store
        """
        logger.info("[DocumentProcessor] Processing image file: %s", path)
        
        # Step 1: Generate description with vision model
        description = self._vision.describe_image(path)
        if not description or not description.strip():
            logger.warning("[DocumentProcessor] No description generated for %s", path)
            self._qdrant.upsert_metadata(point_id=identity.file_id, payload=identity.to_dict())
            return
        
        # Step 2: Summarize the description
        summary = self._summarization.summarize(description, max_length=2000)
        if not summary:
            logger.warning("[DocumentProcessor] Summarization failed for image %s", path)
            summary = description[:500]  # Fallback
        
        # Step 3: Embed the summary
        vector = self._embedding.embed(summary)
        
        # Step 4: Store in Qdrant with enriched payload
        payload = identity.to_dict()
        payload.update({
            "content_type": "image",
            "description": description,
            "summary": summary,
            "description_length": len(description),
        })
        
        self._qdrant.upsert_vector(
            point_id=identity.file_id,
            vector=vector,
            payload=payload,
        )
        logger.info(
            "[DocumentProcessor] Image processed: %s (description=%d, summary=%d)",
            os.path.basename(path), len(description), len(summary)
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

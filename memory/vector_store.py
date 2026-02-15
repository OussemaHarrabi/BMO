"""
Qdrant Vector Store - Memory storage and retrieval using vector similarity.
"""

import logging
import os
import uuid
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams,
    Distance,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    Range,
    DatetimeRange,
    PayloadSchemaType,
)
import httpx


COLLECTION_NAME = "bmo_memories"
VECTOR_SIZE = 768


@dataclass
class Memory:
    """Memory object representation."""
    memory_id: str
    raw_text: str
    summary: Optional[str]
    category: str
    source: str
    source_url: Optional[str]
    source_path: Optional[str]
    created_at: datetime
    updated_at: datetime
    tags: List[str]
    embedding_id: Optional[str] = None
    image_base64: Optional[str] = None  # Store original image for retrieval


@dataclass
class SearchResult:
    """Search result with score."""
    memory: Memory
    score: float


class VectorStore:
    """Qdrant vector store operations for BMO memories."""
    
    def __init__(self):
        """Initialize Qdrant client."""
        host = os.getenv("QDRANT_HOST", "localhost")
        port = int(os.getenv("QDRANT_PORT", "6333"))
        
        self.client = QdrantClient(host=host, port=port)
        # Support both OLLAMA_HOST (docker) and OLLAMA_URL env vars
        self.ollama_url = os.getenv("OLLAMA_HOST", os.getenv("OLLAMA_URL", "http://localhost:11434"))
        self._ensure_collection()
    
    def _ensure_collection(self):
        """Create collection if it doesn't exist."""
        collections = self.client.get_collections().collections
        exists = any(c.name == COLLECTION_NAME for c in collections)
        
        if not exists:
            self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=VECTOR_SIZE,
                    distance=Distance.COSINE
                )
            )
            # Create payload indexes for filtering
            self.client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="category",
                field_schema=PayloadSchemaType.KEYWORD
            )
            self.client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="source",
                field_schema=PayloadSchemaType.KEYWORD
            )
            self.client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="created_at",
                field_schema=PayloadSchemaType.DATETIME
            )
    
    async def _get_embedding(self, text: str) -> List[float]:
        """Get embedding from Ollama."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.ollama_url}/api/embeddings",
                    json={
                        "model": "nomic-embed-text",
                        "prompt": text
                    },
                    timeout=60.0
                )
                response.raise_for_status()
                return response.json()["embedding"]
        except httpx.ConnectError as e:
            logger.error("Ollama connection failed: %s", e)
            raise RuntimeError(f"Cannot connect to Ollama at {self.ollama_url}") from e
        except httpx.HTTPStatusError as e:
            logger.error("Ollama embedding request failed: %s", e)
            raise RuntimeError(f"Ollama embedding failed: {e.response.status_code}") from e
    
    def _get_embedding_sync(self, text: str) -> List[float]:
        """Get embedding from Ollama (sync version)."""
        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{self.ollama_url}/api/embeddings",
                    json={
                        "model": "nomic-embed-text",
                        "prompt": text
                    },
                    timeout=60.0
                )
                response.raise_for_status()
                return response.json()["embedding"]
        except httpx.ConnectError as e:
            logger.error("Ollama connection failed: %s", e)
            raise RuntimeError(f"Cannot connect to Ollama at {self.ollama_url}") from e
        except httpx.HTTPStatusError as e:
            logger.error("Ollama embedding request failed: %s", e)
            raise RuntimeError(f"Ollama embedding failed: {e.response.status_code}") from e
    
    def _generate_memory_id(self) -> str:
        """Generate unique memory ID as full UUID (Qdrant requirement)."""
        return str(uuid.uuid4())
    
    def _generate_content_hash(self, text: str) -> str:
        """Generate hash for deduplication."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]
    
    async def add(
        self,
        raw_text: str,
        summary: Optional[str] = None,
        category: str = "uncategorized",
        source: str = "manual",
        source_url: Optional[str] = None,
        source_path: Optional[str] = None,
        tags: Optional[List[str]] = None,
        entities: Optional[List[str]] = None
    ) -> Memory:
        """Add a new memory to the store."""
        memory_id = self._generate_memory_id()
        now = datetime.utcnow()
        content_hash = self._generate_content_hash(raw_text)
        
        # Get embedding from text to embed
        text_to_embed = summary if summary else raw_text[:1000]
        embedding = await self._get_embedding(text_to_embed)
        
        # Create point
        point = PointStruct(
            id=memory_id,
            vector=embedding,
            payload={
                "memory_id": memory_id,
                "raw_text": raw_text,
                "summary": summary,
                "category": category,
                "source": source,
                "source_url": source_url,
                "source_path": source_path,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "tags": tags or [],
                "entities": entities or [],
                "hash": content_hash
            }
        )
        
        # Upsert to collection
        self.client.upsert(
            collection_name=COLLECTION_NAME,
            points=[point]
        )
        
        return Memory(
            memory_id=memory_id,
            raw_text=raw_text,
            summary=summary,
            category=category,
            source=source,
            source_url=source_url,
            source_path=source_path,
            created_at=now,
            updated_at=now,
            tags=tags or [],
            embedding_id=memory_id
        )
    
    def add_sync(
        self,
        raw_text: str,
        summary: Optional[str] = None,
        category: str = "uncategorized",
        source: str = "manual",
        source_url: Optional[str] = None,
        source_path: Optional[str] = None,
        tags: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        image_base64: Optional[str] = None,
        created_at: Optional[datetime] = None
    ) -> Memory:
        """Add a new memory to the store (sync version)."""
        memory_id = self._generate_memory_id()
        now = datetime.utcnow()
        actual_created_at = created_at or now
        content_hash = self._generate_content_hash(raw_text)
        
        text_to_embed = summary if summary else raw_text[:1000]
        embedding = self._get_embedding_sync(text_to_embed)
        
        point = PointStruct(
            id=memory_id,
            vector=embedding,
            payload={
                "memory_id": memory_id,
                "raw_text": raw_text,
                "summary": summary,
                "category": category,
                "source": source,
                "source_url": source_url,
                "source_path": source_path,
                "created_at": actual_created_at.isoformat(),
                "updated_at": now.isoformat(),
                "tags": tags or [],
                "entities": entities or [],
                "hash": content_hash,
                "image_base64": image_base64
            }
        )
        
        self.client.upsert(
            collection_name=COLLECTION_NAME,
            points=[point]
        )
        
        return Memory(
            memory_id=memory_id,
            raw_text=raw_text,
            summary=summary,
            category=category,
            source=source,
            source_url=source_url,
            source_path=source_path,
            created_at=actual_created_at,
            updated_at=now,
            tags=tags or [],
            embedding_id=memory_id,
            image_base64=image_base64
        )
    
    def get_by_id(self, memory_id: str) -> Optional[Memory]:
        """Get memory by ID."""
        results = self.client.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[memory_id],
            with_payload=True
        )
        
        if not results:
            return None
        
        point = results[0]
        payload = point.payload or {}
        
        return Memory(
            memory_id=payload.get("memory_id", memory_id),
            raw_text=payload.get("raw_text", ""),
            summary=payload.get("summary"),
            category=payload.get("category", "uncategorized"),
            source=payload.get("source", "unknown"),
            source_url=payload.get("source_url"),
            source_path=payload.get("source_path"),
            created_at=datetime.fromisoformat(payload.get("created_at", datetime.utcnow().isoformat())),
            updated_at=datetime.fromisoformat(payload.get("updated_at", datetime.utcnow().isoformat())),
            tags=payload.get("tags", []),
            embedding_id=memory_id,
            image_base64=payload.get("image_base64")
        )
    
    async def search(
        self,
        query: str,
        category: Optional[str] = None,
        source: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """Search memories by semantic similarity."""
        # Get query embedding
        query_embedding = await self._get_embedding(query)
        
        # Build filters
        conditions = []
        
        if category:
            conditions.append(
                FieldCondition(
                    key="category",
                    match=MatchValue(value=category)
                )
            )
        
        if source:
            conditions.append(
                FieldCondition(
                    key="source",
                    match=MatchValue(value=source)
                )
            )
        
        if start_date or end_date:
            conditions.append(
                FieldCondition(
                    key="created_at",
                    range=DatetimeRange(
                        gte=start_date,
                        lte=end_date
                    )
                )
            )
        
        query_filter = Filter(must=conditions) if conditions else None
        
        response = self.client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_embedding,
            query_filter=query_filter,
            limit=limit,
            with_payload=True
        )
        
        search_results = []
        for point in response.points:
            payload = point.payload or {}
            memory = Memory(
                memory_id=payload.get("memory_id", ""),
                raw_text=payload.get("raw_text", ""),
                summary=payload.get("summary"),
                category=payload.get("category", "uncategorized"),
                source=payload.get("source", "unknown"),
                source_url=payload.get("source_url"),
                source_path=payload.get("source_path"),
                created_at=datetime.fromisoformat(payload.get("created_at", datetime.utcnow().isoformat())),
                updated_at=datetime.fromisoformat(payload.get("updated_at", datetime.utcnow().isoformat())),
                tags=payload.get("tags", []),
                embedding_id=payload.get("memory_id", ""),
                image_base64=payload.get("image_base64")
            )
            search_results.append(SearchResult(memory=memory, score=point.score))
        
        return search_results
    
    def search_sync(
        self,
        query: str,
        category: Optional[str] = None,
        source: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """Search memories by semantic similarity (sync version)."""
        query_embedding = self._get_embedding_sync(query)
        
        conditions = []
        
        if category:
            conditions.append(
                FieldCondition(
                    key="category",
                    match=MatchValue(value=category)
                )
            )
        
        if source:
            conditions.append(
                FieldCondition(
                    key="source",
                    match=MatchValue(value=source)
                )
            )
        
        if start_date or end_date:
            conditions.append(
                FieldCondition(
                    key="created_at",
                    range=DatetimeRange(
                        gte=start_date,
                        lte=end_date
                    )
                )
            )
        
        query_filter = Filter(must=conditions) if conditions else None
        
        response = self.client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_embedding,
            query_filter=query_filter,
            limit=limit,
            with_payload=True
        )
        
        search_results = []
        for point in response.points:
            payload = point.payload or {}
            memory = Memory(
                memory_id=payload.get("memory_id", ""),
                raw_text=payload.get("raw_text", ""),
                summary=payload.get("summary"),
                category=payload.get("category", "uncategorized"),
                source=payload.get("source", "unknown"),
                source_url=payload.get("source_url"),
                source_path=payload.get("source_path"),
                created_at=datetime.fromisoformat(payload.get("created_at", datetime.utcnow().isoformat())),
                updated_at=datetime.fromisoformat(payload.get("updated_at", datetime.utcnow().isoformat())),
                tags=payload.get("tags", []),
                embedding_id=payload.get("memory_id", ""),
                image_base64=payload.get("image_base64")
            )
            search_results.append(SearchResult(memory=memory, score=point.score))
        
        return search_results
    
    def list(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> List[Memory]:
        """List memories with optional filters."""
        conditions = []
        
        if filters:
            for key, value in filters.items():
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                )
        
        query_filter = Filter(must=conditions) if conditions else None
        
        # Scroll through results
        results, _ = self.client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=query_filter,
            limit=limit,
            offset=offset,
            with_payload=True
        )
        
        memories = []
        for point in results:
            payload = point.payload or {}
            memories.append(Memory(
                memory_id=payload.get("memory_id", ""),
                raw_text=payload.get("raw_text", ""),
                summary=payload.get("summary"),
                category=payload.get("category", "uncategorized"),
                source=payload.get("source", "unknown"),
                source_url=payload.get("source_url"),
                source_path=payload.get("source_path"),
                created_at=datetime.fromisoformat(payload.get("created_at", datetime.utcnow().isoformat())),
                updated_at=datetime.fromisoformat(payload.get("updated_at", datetime.utcnow().isoformat())),
                tags=payload.get("tags", []),
                embedding_id=payload.get("memory_id", ""),
                image_base64=payload.get("image_base64")
            ))
        
        return memories
    
    def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        try:
            self.client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=[memory_id]
            )
            return True
        except Exception as e:
            logger.warning("Failed to delete memory %s: %s", memory_id, e)
            return False
    
    def delete_by_source_path(self, source_path: str) -> int:
        """Delete all memories matching a source path. Returns count deleted."""
        try:
            results, _ = self.client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="source_path",
                            match=MatchValue(value=source_path)
                        )
                    ]
                ),
                limit=1000,
                with_payload=True
            )
            
            if not results:
                logger.debug("No memories found for source_path: %s", source_path)
                return 0
            
            memory_ids = [point.payload.get("memory_id") for point in results if point.payload]
            memory_ids = [mid for mid in memory_ids if mid]
            
            if memory_ids:
                self.client.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=memory_ids
                )
                logger.info("Deleted %d memories for source_path: %s", len(memory_ids), source_path)
            
            return len(memory_ids)
        except Exception as e:
            logger.error("Failed to delete by source_path %s: %s", source_path, e)
            return 0
    
    def check_duplicate(self, text: str) -> Optional[str]:
        """Check if similar content already exists."""
        content_hash = self._generate_content_hash(text)
        
        results, _ = self.client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="hash",
                        match=MatchValue(value=content_hash)
                    )
                ]
            ),
            limit=1,
            with_payload=True
        )
        
        if results:
            payload = results[0].payload or {}
            return payload.get("memory_id")
        return None
    
    def get_category_stats(self) -> Dict[str, int]:
        """Get memory count by category."""
        # Get all unique categories
        categories = ["code", "finance", "personal", "research", "work", "entertainment", "uncategorized"]
        stats = {}
        
        for category in categories:
            count = self.client.count(
                collection_name=COLLECTION_NAME,
                count_filter=Filter(
                    must=[
                        FieldCondition(
                            key="category",
                            match=MatchValue(value=category)
                        )
                    ]
                )
            ).count
            stats[category] = count
        
        return stats
    
    def get_timeline_stats(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get memory count over time."""
        from datetime import timedelta
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # This is a simplified implementation
        # In production, you'd want to aggregate by day
        results, _ = self.client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="created_at",
                        range=DatetimeRange(
                            gte=start_date,
                            lte=end_date
                        )
                    )
                ]
            ),
            limit=10000,
            with_payload=True
        )
        
        # Group by date
        date_counts: Dict[str, int] = {}
        for point in results:
            payload = point.payload or {}
            created_at = payload.get("created_at", "")
            if created_at:
                date_str = created_at[:10]  # YYYY-MM-DD
                date_counts[date_str] = date_counts.get(date_str, 0) + 1
        
        return [{"date": k, "count": v} for k, v in sorted(date_counts.items())]

"""
Agent Orchestrator - Coordinates the full agent pipeline.

Pipeline: Router -> Retriever -> Reasoner -> Verifier
"""

import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from core.ollama_client import OllamaClient
from agents.router import QueryRouter, RouterResult, Intent
from agents.reasoner import Reasoner, ReasonerResult
from agents.verifier import Verifier, VerificationResult

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Final result from the agent pipeline."""
    answer: str
    confidence: float
    sources: List[Dict[str, Any]]
    processing_time_ms: int
    intent_detected: str
    uncertain: bool = False
    screenshots: List[Dict[str, Any]] = field(default_factory=list)
    
    # Debug info
    router_result: Optional[RouterResult] = None
    reasoner_result: Optional[ReasonerResult] = None
    verification_result: Optional[VerificationResult] = None


@dataclass 
class PipelineState:
    """State tracking for pipeline recovery."""
    query_id: str
    query: str
    timestamp: datetime = field(default_factory=datetime.now)
    status: str = "pending"
    router_result: Optional[RouterResult] = None
    retrieval_result: Optional[List[Dict[str, Any]]] = None
    reasoner_result: Optional[ReasonerResult] = None
    verification_result: Optional[VerificationResult] = None
    error: Optional[str] = None


class AgentOrchestrator:
    """Orchestrates the full query processing pipeline."""
    
    def __init__(self, client: Optional[OllamaClient] = None):
        """Initialize orchestrator.
        
        Args:
            client: Optional shared OllamaClient instance.
        """
        self.client = client or OllamaClient()
        self.router = QueryRouter(self.client)
        self.reasoner = Reasoner(self.client)
        self.verifier = Verifier(self.client)
        
        # Optional components - lazy loaded
        self._vector_store = None
        self._knowledge_graph = None
    
    @property
    def vector_store(self):
        """Lazy load vector store."""
        if self._vector_store is None:
            try:
                from memory.vector_store import VectorStore
                self._vector_store = VectorStore()
            except ImportError:
                logger.warning("VectorStore not available")
        return self._vector_store
    
    @property
    def knowledge_graph(self):
        """Lazy load knowledge graph."""
        if self._knowledge_graph is None:
            try:
                from memory.knowledge_graph import KnowledgeGraph
                self._knowledge_graph = KnowledgeGraph()
            except ImportError:
                logger.warning("KnowledgeGraph not available")
        return self._knowledge_graph
    
    async def process_query(
        self,
        query: str,
        category_filter: Optional[str] = None,
        category_filters: Optional[List[str]] = None,
        time_range_days: Optional[int] = None,
        skip_verification: bool = False
    ) -> QueryResult:
        """Process a user query through the full pipeline.
        
        Pipeline stages:
        1. Router - Classify intent
        2. Retriever - Get relevant memories
        3. Reasoner - Generate answer
        4. Verifier - Fact-check response
        
        Args:
            query: User's query string.
            category_filter: Optional category to filter by.
            time_range_days: Optional time range in days.
            
        Returns:
            QueryResult with answer and metadata.
        """
        start_time = time.time()
        
        # Stage 1: Route query
        logger.info(f"Routing query: {query[:50]}...")
        router_result = await self.router.route(query)
        logger.info(f"Intent: {router_result.intent}, confidence: {router_result.confidence}")
        
        # Handle special intents
        if router_result.intent == Intent.GENERAL_CHAT:
            return self._handle_general_chat(query, router_result, start_time)
        
        if router_result.intent == Intent.CLARIFICATION:
            return await self._handle_clarification(query, router_result, start_time)
        
        # Use router's extracted filters if not overridden
        if not category_filter and not category_filters and router_result.category_filter:
            category_filter = router_result.category_filter
        
        # Stage 2: Retrieve memories
        logger.info("Retrieving memories...")
        memories = await self._retrieve_memories(
            query=query,
            intent=router_result.intent,
            category_filter=category_filter,
            category_filters=category_filters,
            time_range_days=time_range_days,
            entity_focus=router_result.entity_focus
        )
        
        if not memories:
            return await self._handle_no_results(query, router_result, start_time)
        
        logger.info(f"Retrieved {len(memories)} memories")
        
        # Stage 3: Generate answer
        logger.info("Generating answer...")
        reasoner_result = await self.reasoner.reason(query, memories)
        
        # Stage 4: Verify response (skip in fast mode)
        if skip_verification:
            logger.info("Skipping verification (fast mode)")
            processing_time = int((time.time() - start_time) * 1000)
            sources = self._build_source_references(memories, reasoner_result.cited_memories)
            screenshots = self._extract_screenshots(memories)
            
            return QueryResult(
                answer=reasoner_result.answer,
                confidence=0.7,
                sources=sources,
                processing_time_ms=processing_time,
                intent_detected=router_result.intent.value,
                uncertain=False,
                screenshots=screenshots,
                router_result=router_result,
                reasoner_result=reasoner_result,
                verification_result=None
            )
        
        logger.info("Verifying response...")
        verification_result = await self.verifier.verify(
            query=query,
            draft_answer=reasoner_result.answer,
            cited_sources=reasoner_result.cited_memories,
            source_memories=memories
        )
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # Build source references
        sources = self._build_source_references(memories, verification_result.valid_sources)
        screenshots = self._extract_screenshots(memories)
        
        return QueryResult(
            answer=verification_result.verified_answer,
            confidence=verification_result.confidence,
            sources=sources,
            processing_time_ms=processing_time,
            intent_detected=router_result.intent.value,
            uncertain=verification_result.confidence < 0.7,
            screenshots=screenshots,
            router_result=router_result,
            reasoner_result=reasoner_result,
            verification_result=verification_result
        )
    
    async def _retrieve_memories(
        self,
        query: str,
        intent: Intent,
        category_filter: Optional[str] = None,
        category_filters: Optional[List[str]] = None,
        time_range_days: Optional[int] = None,
        entity_focus: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant memories based on query and intent."""
        memories = []
        
        if self.vector_store:
            try:
                start_date = None
                if time_range_days:
                    start_date = datetime.now() - timedelta(days=time_range_days)
                
                if category_filters and len(category_filters) > 0:
                    for cat in category_filters:
                        cat_results = await self._search_vector_store(
                            query=query,
                            category=cat,
                            start_date=start_date,
                            limit=5
                        )
                        memories.extend(cat_results)
                else:
                    vector_results = await self._search_vector_store(
                        query=query,
                        category=category_filter,
                        start_date=start_date,
                        limit=10
                    )
                    memories.extend(vector_results)
            except Exception as e:
                logger.error(f"Vector search failed: {e}")
        
        # For knowledge graph intent, also query graph
        if intent == Intent.KNOWLEDGE_GRAPH and self.knowledge_graph and entity_focus:
            try:
                graph_results = await self._search_knowledge_graph(entity_focus)
                # Add unique memories from graph
                existing_ids = {m.get("memory_id") for m in memories}
                for mem in graph_results:
                    if mem.get("memory_id") not in existing_ids:
                        memories.append(mem)
            except Exception as e:
                logger.error(f"Graph search failed: {e}")
        
        return memories
    
    async def _search_vector_store(
        self,
        query: str,
        category: Optional[str] = None,
        start_date: Optional[datetime] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search vector store for relevant memories.
        
        Args:
            query: Search query.
            category: Optional category filter.
            start_date: Optional start date filter.
            limit: Maximum results.
            
        Returns:
            List of memory dicts.
        """
        if not self.vector_store:
            return []
        
        try:
            # Search vector store (it handles embedding internally)
            search_results = await self.vector_store.search(
                query=query,
                category=category,
                start_date=start_date,
                limit=limit
            )
            
            # Convert SearchResult objects to dicts
            return [
                {
                    "memory_id": r.memory.memory_id,
                    "raw_text": r.memory.raw_text,
                    "summary": r.memory.summary,
                    "category": r.memory.category,
                    "source": r.memory.source,
                    "created_at": r.memory.created_at.isoformat(),
                    "timestamp": r.memory.created_at.isoformat(),
                    "score": r.score,
                    "image_base64": getattr(r.memory, 'image_base64', None)
                }
                for r in search_results
            ]
        except Exception as e:
            logger.error(f"Vector store search error: {e}")
            return []
    
    async def _search_knowledge_graph(self, entity_name: str) -> List[Dict[str, Any]]:
        """Search knowledge graph for related memories.
        
        Args:
            entity_name: Entity to search for.
            
        Returns:
            List of memory dicts.
        """
        if not self.knowledge_graph:
            return []
        
        try:
            # Get related memory IDs from graph
            memory_ids = self.knowledge_graph.get_related_memories(entity_name, depth=2)
            
            # Fetch full memory objects from vector store
            if self.vector_store and memory_ids:
                memories = []
                for mid in memory_ids[:10]:  # Limit to 10
                    mem = self.vector_store.get_by_id(mid)
                    if mem:
                        memories.append(mem)
                return memories
            
            return []
        except Exception as e:
            logger.error(f"Knowledge graph search error: {e}")
            return []
    
    def _handle_general_chat(
        self,
        query: str,
        router_result: RouterResult,
        start_time: float
    ) -> QueryResult:
        """Handle general chat queries that don't need memory access.
        
        Args:
            query: User's query.
            router_result: Router classification result.
            start_time: Pipeline start time.
            
        Returns:
            QueryResult with chat response.
        """
        # Simple responses for common queries
        query_lower = query.lower()
        
        if any(g in query_lower for g in ["hello", "hi", "hey"]):
            answer = "Hello! I'm BMO, your personal memory assistant. I can help you find and recall things from your past activities. What would you like to know?"
        elif "what can you do" in query_lower or "help" in query_lower:
            answer = """I can help you with:
• Finding memories from your browsing history, files, and activities
• Discovering connections between topics and projects
• Recalling when you worked on something specific
• Searching by category (code, work, research, etc.)

Just ask me something like "What was I reading about yesterday?" or "Find my notes on machine learning"."""
        else:
            answer = "I'm here to help you recall your past activities. Try asking me about something you've seen, read, or worked on!"
        
        processing_time = int((time.time() - start_time) * 1000)
        
        return QueryResult(
            answer=answer,
            confidence=1.0,
            sources=[],
            processing_time_ms=processing_time,
            intent_detected=router_result.intent.value,
            uncertain=False,
            router_result=router_result
        )
    
    async def _handle_clarification(
        self,
        query: str,
        router_result: RouterResult,
        start_time: float
    ) -> QueryResult:
        """Handle vague queries that need clarification.
        
        Args:
            query: User's query.
            router_result: Router classification result.
            start_time: Pipeline start time.
            
        Returns:
            QueryResult with clarification request.
        """
        clarification = await self.reasoner.generate_clarification(query)
        processing_time = int((time.time() - start_time) * 1000)
        
        return QueryResult(
            answer=clarification,
            confidence=0.3,
            sources=[],
            processing_time_ms=processing_time,
            intent_detected=router_result.intent.value,
            uncertain=True,
            router_result=router_result
        )
    
    async def _handle_no_results(
        self,
        query: str,
        router_result: RouterResult,
        start_time: float
    ) -> QueryResult:
        """Handle case when no memories are found.
        
        Args:
            query: User's query.
            router_result: Router classification result.
            start_time: Pipeline start time.
            
        Returns:
            QueryResult with no-results response.
        """
        response = await self.reasoner.generate_no_results_response(query)
        processing_time = int((time.time() - start_time) * 1000)
        
        return QueryResult(
            answer=response,
            confidence=0.0,
            sources=[],
            processing_time_ms=processing_time,
            intent_detected=router_result.intent.value,
            uncertain=True,
            router_result=router_result
        )
    
    def _build_source_references(
        self,
        memories: List[Dict[str, Any]],
        valid_sources: List[str]
    ) -> List[Dict[str, Any]]:
        """Build source reference objects for response.
        
        Args:
            memories: All retrieved memories.
            valid_sources: List of valid source IDs.
            
        Returns:
            List of source reference dicts.
        """
        sources = []
        memory_map = {m.get("memory_id"): m for m in memories}
        
        for source_id in valid_sources:
            if source_id in memory_map:
                mem = memory_map[source_id]
                summary = mem.get("summary") or mem.get("raw_text") or ""
                sources.append({
                    "memory_id": source_id,
                    "summary": summary[:200] if summary else "",
                    "timestamp": mem.get("created_at", mem.get("timestamp")),
                    "source": mem.get("source", "unknown"),
                    "category": mem.get("category", "unknown"),
                    "relevance_score": mem.get("score", 0.0)
                })
        
        return sources
    
    def _extract_screenshots(
        self,
        memories: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        screenshots = []
        for mem in memories:
            if mem.get("image_base64"):
                screenshots.append({
                    "memory_id": mem.get("memory_id"),
                    "image_base64": mem.get("image_base64"),
                    "timestamp": mem.get("created_at", mem.get("timestamp")),
                    "source_url": mem.get("source_url"),
                    "category": mem.get("category")
                })
        return screenshots


async def process_query(
    query: str,
    category_filter: Optional[str] = None,
    category_filters: Optional[List[str]] = None,
    time_range_days: Optional[int] = None
) -> QueryResult:
    """Convenience function to process a query."""
    orchestrator = AgentOrchestrator()
    return await orchestrator.process_query(query, category_filter, category_filters, time_range_days)

"""
Query Router - Classifies query intent using Phi-3.5.
"""

import json
from typing import Optional
from dataclasses import dataclass
from enum import Enum
import logging

from core.ollama_client import OllamaClient, ModelRole

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """Query intent types."""
    MEMORY_SEARCH = "MEMORY_SEARCH"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    CLARIFICATION = "CLARIFICATION"
    GENERAL_CHAT = "GENERAL_CHAT"


ROUTER_SYSTEM_PROMPT = """You are a query router for a personal memory system.
Classify the user's intent into exactly one category.

MEMORY_SEARCH: User wants to find something from their past activities
- "What was I reading about yesterday?"
- "Find my notes on machine learning"
- "What code did I write last week?"
- "What have I been looking at?"
- "What was I doing recently?"
- "Show me my recent screenshots"
- "What applications did I use?"
- "What websites did I visit?"

KNOWLEDGE_GRAPH: User wants to understand connections/relationships
- "What projects did I start from that GitHub repo?"
- "How is X related to Y?"
- "What inspired my project?"

CLARIFICATION: Query is too vague to search effectively
- "Find that thing" (what thing?)
- "The project" (which project?)

GENERAL_CHAT: Doesn't need memory access - ONLY use for greetings or questions about the system itself
- "Hello"
- "What can you do?"
- "Hi there"

IMPORTANT: Any query about past activities, screenshots, websites, applications, or what the user did should be MEMORY_SEARCH.

Also extract filters if mentioned:
- category_filter: code, finance, personal, research, work, entertainment
- time_filter: today, yesterday, this_week, this_month
- entity_focus: specific project/repo/topic mentioned

Respond in JSON format ONLY."""


@dataclass
class RouterResult:
    """Result of query routing."""
    intent: Intent
    confidence: float
    category_filter: Optional[str] = None
    time_filter: Optional[str] = None
    entity_focus: Optional[str] = None
    latency_ms: int = 0
    model: str = ""


class QueryRouter:
    """Routes queries to appropriate handlers based on intent."""
    
    def __init__(self, client: Optional[OllamaClient] = None):
        """Initialize router.
        
        Args:
            client: Optional OllamaClient instance. Creates one if not provided.
        """
        self.client = client or OllamaClient()
    
    async def route(self, query: str) -> RouterResult:
        """Classify query intent and extract filters.
        
        Args:
            query: User's query string.
            
        Returns:
            RouterResult with intent and extracted filters.
        """
        prompt = f"""Classify this query:

"{query}"

JSON response:"""
        
        try:
            result = await self.client.generate(
                role=ModelRole.ROUTER,
                prompt=prompt,
                system_prompt=ROUTER_SYSTEM_PROMPT,
                format_json=True,
                temperature=0.3,
                max_tokens=150
            )
            
            return self._parse_result(result.content, result.latency_ms, result.model)
            
        except Exception as e:
            logger.error(f"Routing failed: {e}")
            # Fallback to keyword-based routing
            return self._fallback_route(query)
    
    def route_sync(self, query: str) -> RouterResult:
        """Classify query intent (synchronous version).
        
        Args:
            query: User's query string.
            
        Returns:
            RouterResult with intent and extracted filters.
        """
        prompt = f"""Classify this query:

"{query}"

JSON response:"""
        
        try:
            result = self.client.generate_sync(
                role=ModelRole.ROUTER,
                prompt=prompt,
                system_prompt=ROUTER_SYSTEM_PROMPT,
                format_json=True,
                temperature=0.3,
                max_tokens=150
            )
            
            return self._parse_result(result.content, result.latency_ms, result.model)
            
        except Exception as e:
            logger.error(f"Routing failed: {e}")
            return self._fallback_route(query)
    
    def _parse_result(self, json_str: str, latency_ms: int, model: str) -> RouterResult:
        """Parse JSON response into RouterResult.
        
        Args:
            json_str: JSON string from LLM.
            latency_ms: Response latency.
            model: Model used.
            
        Returns:
            RouterResult object.
        """
        try:
            json_str = json_str.strip()
            
            # Handle markdown code blocks
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]
            
            data = json.loads(json_str)
            
            # Parse intent
            intent_str = data.get("intent", "MEMORY_SEARCH").upper()
            try:
                intent = Intent(intent_str)
            except ValueError:
                intent = Intent.MEMORY_SEARCH
            
            return RouterResult(
                intent=intent,
                confidence=float(data.get("confidence", 0.7)),
                category_filter=data.get("category_filter"),
                time_filter=data.get("time_filter"),
                entity_focus=data.get("entity_focus"),
                latency_ms=latency_ms,
                model=model
            )
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to parse router JSON: {e}")
            return RouterResult(
                intent=Intent.MEMORY_SEARCH,
                confidence=0.5,
                latency_ms=latency_ms,
                model=model
            )
    
    def _fallback_route(self, query: str) -> RouterResult:
        """Fallback keyword-based routing.
        
        Args:
            query: User's query.
            
        Returns:
            RouterResult based on keywords.
        """
        query_lower = query.lower()
        
        # Check for general chat
        greetings = ["hello", "hi", "hey", "what can you do", "help"]
        if any(g in query_lower for g in greetings):
            return RouterResult(
                intent=Intent.GENERAL_CHAT,
                confidence=0.9,
                model="fallback"
            )
        
        # Check for knowledge graph queries
        graph_keywords = ["related", "connection", "inspired", "linked", "relationship"]
        if any(kw in query_lower for kw in graph_keywords):
            return RouterResult(
                intent=Intent.KNOWLEDGE_GRAPH,
                confidence=0.7,
                model="fallback"
            )
        
        # Check for vague queries needing clarification
        vague_patterns = ["that thing", "the project", "the file", "that one"]
        if any(p in query_lower for p in vague_patterns) and len(query.split()) < 5:
            return RouterResult(
                intent=Intent.CLARIFICATION,
                confidence=0.6,
                model="fallback"
            )
        
        # Extract time filters
        time_filter = None
        if "today" in query_lower:
            time_filter = "today"
        elif "yesterday" in query_lower:
            time_filter = "yesterday"
        elif "this week" in query_lower or "last week" in query_lower:
            time_filter = "this_week"
        elif "this month" in query_lower or "last month" in query_lower:
            time_filter = "this_month"
        
        # Extract category filters
        category_filter = None
        categories = ["code", "finance", "personal", "research", "work", "entertainment"]
        for cat in categories:
            if cat in query_lower:
                category_filter = cat
                break
        
        # Default to memory search
        return RouterResult(
            intent=Intent.MEMORY_SEARCH,
            confidence=0.6,
            category_filter=category_filter,
            time_filter=time_filter,
            model="fallback"
        )


async def route_query(query: str, client: Optional[OllamaClient] = None) -> RouterResult:
    """Convenience function to route a query.
    
    Args:
        query: User's query string.
        client: Optional OllamaClient instance.
        
    Returns:
        RouterResult with intent and filters.
    """
    router = QueryRouter(client)
    return await router.route(query)

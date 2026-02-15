"""
Reasoner Agent - Generates answers with citations using Qwen3-4B.
"""

import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import logging

from core.ollama_client import OllamaClient, ModelRole

logger = logging.getLogger(__name__)


REASONER_SYSTEM_PROMPT = """You are a personal memory assistant. Answer questions based ONLY on provided memories.

Rules:
1. ONLY use information from the provided memories
2. Cite sources using [Memory: <id>] format
3. If memories don't contain enough information, say so honestly
4. Be concise but complete
5. Synthesize information from multiple memories when relevant
6. Never make up information not in the memories"""


@dataclass
class ReasonerResult:
    """Result of reasoning."""
    answer: str
    cited_memories: List[str]
    latency_ms: int
    model: str
    tokens_used: int


class Reasoner:
    """Generates answers based on retrieved memories."""
    
    def __init__(self, client: Optional[OllamaClient] = None):
        """Initialize reasoner.
        
        Args:
            client: Optional OllamaClient instance. Creates one if not provided.
        """
        self.client = client or OllamaClient()
    
    async def reason(
        self,
        query: str,
        memories: List[Dict[str, Any]],
        max_memories: int = 8
    ) -> ReasonerResult:
        """Generate an answer based on retrieved memories.
        
        Args:
            query: User's query.
            memories: List of retrieved memory dicts.
            max_memories: Maximum number of memories to include.
            
        Returns:
            ReasonerResult with answer and citations.
        """
        formatted_memories = self._format_memories(memories[:max_memories])
        
        prompt = f"""Answer based on these memories:

USER QUESTION: {query}

RETRIEVED MEMORIES:
{formatted_memories}

---
Provide a helpful answer with citations:"""
        
        try:
            result = await self.client.generate(
                role=ModelRole.REASONER,
                prompt=prompt,
                system_prompt=REASONER_SYSTEM_PROMPT,
                temperature=0.7
            )
            
            logger.debug(f"Reasoner raw response: {result.raw_response}")
            answer = result.content.strip()
            cited_memories = self._extract_citations(answer)
            
            logger.info(f"Reasoner generated answer ({len(answer)} chars): {answer[:100]}...")
            
            # Ensure we never return empty answer
            if not answer:
                logger.warning("Reasoner returned empty answer, using fallback")
                answer = "I found some relevant memories but couldn't generate a clear answer. Please try rephrasing your question."
            
            return ReasonerResult(
                answer=answer,
                cited_memories=cited_memories,
                latency_ms=result.latency_ms,
                model=result.model,
                tokens_used=result.tokens_used
            )
            
        except Exception as e:
            logger.error(f"Reasoning failed: {e}")
            return ReasonerResult(
                answer="I encountered an error while processing your query. Please try again.",
                cited_memories=[],
                latency_ms=0,
                model="error",
                tokens_used=0
            )
    
    def reason_sync(
        self,
        query: str,
        memories: List[Dict[str, Any]],
        max_memories: int = 8
    ) -> ReasonerResult:
        """Generate answer (synchronous version).
        
        Args:
            query: User's query.
            memories: List of retrieved memory dicts.
            max_memories: Maximum number of memories to include.
            
        Returns:
            ReasonerResult with answer and citations.
        """
        formatted_memories = self._format_memories(memories[:max_memories])
        
        prompt = f"""Answer based on these memories:

USER QUESTION: {query}

RETRIEVED MEMORIES:
{formatted_memories}

---
Provide a helpful answer with citations:"""
        
        try:
            result = self.client.generate_sync(
                role=ModelRole.REASONER,
                prompt=prompt,
                system_prompt=REASONER_SYSTEM_PROMPT,
                temperature=0.7
            )
            
            answer = result.content.strip()
            cited_memories = self._extract_citations(answer)
            
            logger.info(f"Reasoner sync generated answer ({len(answer)} chars): {answer[:100]}...")
            
            if not answer:
                logger.warning("Reasoner sync returned empty answer, using fallback")
                answer = "I found some relevant memories but couldn't generate a clear answer. Please try rephrasing your question."
            
            return ReasonerResult(
                answer=answer,
                cited_memories=cited_memories,
                latency_ms=result.latency_ms,
                model=result.model,
                tokens_used=result.tokens_used
            )
            
        except Exception as e:
            logger.error(f"Reasoning failed: {e}")
            return ReasonerResult(
                answer="I encountered an error while processing your query. Please try again.",
                cited_memories=[],
                latency_ms=0,
                model="error",
                tokens_used=0
            )
    
    def _format_memories(self, memories: List[Dict[str, Any]]) -> str:
        """Format memories for inclusion in prompt.
        
        Args:
            memories: List of memory dicts.
            
        Returns:
            Formatted string of memories.
        """
        formatted = []
        for i, mem in enumerate(memories):
            memory_id = mem.get("memory_id", f"mem_{i+1}")
            category = mem.get("category", "unknown")
            source = mem.get("source", "unknown")
            timestamp = mem.get("timestamp", mem.get("created_at", "unknown"))
            content = mem.get("summary") or mem.get("raw_text") or mem.get("content") or ""
            
            if content and len(content) > 400:
                content = content[:400] + "..."
            
            formatted.append(f"""
[Memory {i+1}] ID: {memory_id}
Category: {category} | Source: {source}
Time: {timestamp}
Content: {content}
---""")
        
        return "\n".join(formatted)
    
    def _extract_citations(self, answer: str) -> List[str]:
        """Extract cited memory IDs from answer.
        
        Args:
            answer: Generated answer text.
            
        Returns:
            List of cited memory IDs.
        """
        # Pattern: [Memory: mem_xxx] or [Memory: xxx]
        pattern = r'\[Memory:\s*([^\]]+)\]'
        matches = re.findall(pattern, answer)
        
        # Also check for [Memory X] format
        pattern2 = r'\[Memory\s+(\d+)\]'
        matches2 = re.findall(pattern2, answer)
        
        citations = []
        for m in matches:
            citations.append(m.strip())
        for m in matches2:
            citations.append(f"mem_{m}")
        
        return list(set(citations))
    
    async def generate_clarification(self, query: str) -> str:
        """Generate a clarification request for vague queries.
        
        Args:
            query: The vague user query.
            
        Returns:
            Clarification question.
        """
        prompt = f"""The user asked: "{query}"

This query is too vague to search effectively. Generate a brief, helpful clarification question.
Ask for specific details that would help narrow down the search.

Clarification question:"""
        
        try:
            result = await self.client.generate(
                role=ModelRole.REASONER,
                prompt=prompt,
                temperature=0.7,
                max_tokens=100
            )
            return result.content.strip()
        except Exception:
            return "Could you please provide more details? What specifically are you looking for?"
    
    async def generate_no_results_response(self, query: str) -> str:
        """Generate a helpful response when no memories match.
        
        Args:
            query: User's query.
            
        Returns:
            Helpful response.
        """
        prompt = f"""The user asked: "{query}"

No relevant memories were found. Generate a brief, helpful response that:
1. Acknowledges the search was performed
2. Suggests possible reasons (maybe it happened before BMO was installed, or under a different context)
3. Offers to help if they can provide more details

Response:"""
        
        try:
            result = await self.client.generate(
                role=ModelRole.REASONER,
                prompt=prompt,
                temperature=0.7,
                max_tokens=150
            )
            return result.content.strip()
        except Exception:
            return "I couldn't find any memories matching your query. This might be from before I started recording, or it could be stored under different keywords. Could you provide more details or try different search terms?"


async def generate_answer(
    query: str,
    memories: List[Dict[str, Any]],
    client: Optional[OllamaClient] = None
) -> ReasonerResult:
    """Convenience function to generate an answer.
    
    Args:
        query: User's query.
        memories: Retrieved memories.
        client: Optional OllamaClient instance.
        
    Returns:
        ReasonerResult with answer and citations.
    """
    reasoner = Reasoner(client)
    return await reasoner.reason(query, memories)

"""
Content Summarizer - Generates concise summaries using Qwen3-4B.
"""

from typing import Optional
from dataclasses import dataclass
import logging

from core.ollama_client import OllamaClient, ModelRole

logger = logging.getLogger(__name__)


SUMMARIZER_SYSTEM_PROMPT = """You are a concise summarizer for a personal memory system.
Create brief, information-dense summaries that capture the key points.

Rules:
1. Maximum 2-3 sentences
2. Include specific names, numbers, and key terms
3. Focus on WHAT and WHY, not HOW
4. Use active voice
5. No filler words or preamble"""


@dataclass
class SummaryResult:
    """Result of content summarization."""
    summary: str
    latency_ms: int
    model: str
    tokens_used: int


class ContentSummarizer:
    """Generates concise summaries of content."""
    
    def __init__(self, client: Optional[OllamaClient] = None):
        """Initialize summarizer.
        
        Args:
            client: Optional OllamaClient instance. Creates one if not provided.
        """
        self.client = client or OllamaClient()
    
    async def summarize(
        self,
        text: str,
        source: str = "unknown",
        category: str = "uncategorized",
        max_chars: int = 2000
    ) -> SummaryResult:
        """Generate a concise summary of the text.
        
        Args:
            text: The text content to summarize.
            source: Source of the content (e.g., "browser", "file_system").
            category: Category of the content.
            max_chars: Maximum characters to use from text.
            
        Returns:
            SummaryResult with summary and metadata.
        """
        # Truncate text if needed
        truncated = text[:max_chars] if len(text) > max_chars else text
        
        prompt = f"""Summarize this content for future recall:

Source: {source}
Category: {category}

Content:
{truncated}

Summary:"""
        
        try:
            result = await self.client.generate(
                role=ModelRole.REASONER,
                prompt=prompt,
                system_prompt=SUMMARIZER_SYSTEM_PROMPT,
                temperature=0.7,
                max_tokens=200
            )
            
            summary = result.content.strip()
            
            # Clean up summary - remove any preamble
            if summary.startswith("Summary:"):
                summary = summary[8:].strip()
            
            return SummaryResult(
                summary=summary,
                latency_ms=result.latency_ms,
                model=result.model,
                tokens_used=result.tokens_used
            )
            
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            # Return truncated original as fallback
            fallback = text[:200] + "..." if len(text) > 200 else text
            return SummaryResult(
                summary=fallback,
                latency_ms=0,
                model="fallback",
                tokens_used=0
            )
    
    def summarize_sync(
        self,
        text: str,
        source: str = "unknown",
        category: str = "uncategorized",
        max_chars: int = 2000
    ) -> SummaryResult:
        """Generate a summary (synchronous version).
        
        Args:
            text: The text content to summarize.
            source: Source of the content.
            category: Category of the content.
            max_chars: Maximum characters to use from text.
            
        Returns:
            SummaryResult with summary and metadata.
        """
        truncated = text[:max_chars] if len(text) > max_chars else text
        
        prompt = f"""Summarize this content for future recall:

Source: {source}
Category: {category}

Content:
{truncated}

Summary:"""
        
        try:
            result = self.client.generate_sync(
                role=ModelRole.REASONER,
                prompt=prompt,
                system_prompt=SUMMARIZER_SYSTEM_PROMPT,
                temperature=0.7,
                max_tokens=200
            )
            
            summary = result.content.strip()
            if summary.startswith("Summary:"):
                summary = summary[8:].strip()
            
            return SummaryResult(
                summary=summary,
                latency_ms=result.latency_ms,
                model=result.model,
                tokens_used=result.tokens_used
            )
            
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            fallback = text[:200] + "..." if len(text) > 200 else text
            return SummaryResult(
                summary=fallback,
                latency_ms=0,
                model="fallback",
                tokens_used=0
            )
    
    @staticmethod
    def extract_key_sentences(text: str, max_sentences: int = 3) -> str:
        """Extract key sentences as a simple summary (no LLM).
        
        Uses basic heuristics to extract important sentences.
        Can be used as a fast fallback.
        
        Args:
            text: Text to extract from.
            max_sentences: Maximum number of sentences to extract.
            
        Returns:
            Extracted sentences joined.
        """
        import re
        
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        
        if not sentences:
            return text[:200]
        
        # Score sentences by importance heuristics
        scored = []
        for i, sent in enumerate(sentences):
            score = 0
            
            # First sentence often contains key info
            if i == 0:
                score += 2
            
            # Sentences with numbers are often important
            if re.search(r'\d+', sent):
                score += 1
            
            # Sentences with proper nouns (capitalized words)
            capitals = len(re.findall(r'\b[A-Z][a-z]+\b', sent))
            score += min(capitals, 2)
            
            # Avoid very short sentences
            if len(sent) < 20:
                score -= 2
            
            # Avoid very long sentences
            if len(sent) > 300:
                score -= 1
            
            scored.append((score, i, sent))
        
        # Sort by score, take top sentences, maintain original order
        scored.sort(key=lambda x: x[0], reverse=True)
        top = sorted(scored[:max_sentences], key=lambda x: x[1])
        
        return " ".join(s[2] for s in top)


async def summarize_content(
    text: str,
    source: str = "unknown",
    category: str = "uncategorized",
    client: Optional[OllamaClient] = None
) -> str:
    """Convenience function to summarize content.
    
    Args:
        text: Text to summarize.
        source: Source of the content.
        category: Category of the content.
        client: Optional OllamaClient instance.
        
    Returns:
        Summary string.
    """
    summarizer = ContentSummarizer(client)
    result = await summarizer.summarize(text, source, category)
    return result.summary

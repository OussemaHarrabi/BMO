from __future__ import annotations

import logging
from typing import Optional

from bmo.core.ollama_client import OllamaClient, ModelRole

logger = logging.getLogger(__name__)


class SummarizationService:
    """LLM service for text summarization using BMO's OllamaClient."""

    def __init__(self, ollama_client: Optional[OllamaClient] = None, max_tokens: int = 150) -> None:
        """
        Initialize summarization service.
        
        Args:
            ollama_client: OllamaClient instance (creates new if None)
            max_tokens: Maximum tokens in summary
        """
        self._client = ollama_client or OllamaClient()
        self._max_tokens = max_tokens
        logger.info("[SummarizationService] Initialized with model=%s", "qwen3:4b")

    def summarize(self, text: str, max_length: int = 500) -> str:
        """
        Generate a summary of the text using local LLM.
        
        Args:
            text: Input text to summarize
            max_length: Maximum characters to process (truncate if longer)
        
        Returns:
            Summary text
        """
        if not text or not text.strip():
            logger.warning("[SummarizationService] Empty text provided")
            return ""

        # Truncate very long texts to avoid context overflow
        if len(text) > max_length:
            text_to_summarize = text[:max_length] + "..."
            logger.info("[SummarizationService] Truncated text from %d to %d chars", len(text), max_length)
        else:
            text_to_summarize = text

        try:
            prompt = f"""Summarize the following text concisely in 2-3 sentences. Focus on the main topics and key information.

Text:
{text_to_summarize}

Summary:"""

            # Use OllamaClient with reasoner model
            result = self._client.generate_sync(
                role=ModelRole.REASONER,
                prompt=prompt,
                temperature=0.3,
                max_tokens=self._max_tokens
            )
            
            summary = result.content.strip()
            logger.info(
                "[SummarizationService] Generated summary (input=%d chars, output=%d chars)",
                len(text_to_summarize),
                len(summary),
            )
            return summary

        except Exception as e:
            logger.error("[SummarizationService] Summarization failed: %s", e)
            return self._stub_summarize(text_to_summarize)

    def _stub_summarize(self, text: str) -> str:
        """Fallback stub - returns truncated original text."""
        max_stub_length = 200
        if len(text) <= max_stub_length:
            logger.info("[SummarizationService] STUB - returning original text (%d chars)", len(text))
            return text
        
        truncated = text[:max_stub_length] + "..."
        logger.info("[SummarizationService] STUB - returning truncated text (%d chars)", len(truncated))
        return truncated

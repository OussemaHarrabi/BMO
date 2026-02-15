from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SummarizationService:
    """LLM service for text summarization (max 4B parameters)."""

    def __init__(self, model_name: str = "llama3.2:3b", max_tokens: int = 150) -> None:
        """
        Initialize summarization service.
        
        Args:
            model_name: Ollama model name (e.g., "llama3.2:3b", "phi3:3.8b", "gemma2:2b")
            max_tokens: Maximum tokens in summary
        """
        self._model_name = model_name
        self._max_tokens = max_tokens
        self._ollama_available = self._check_ollama()
        logger.info(
            "[SummarizationService] Initialized with model=%s (available=%s)",
            model_name,
            self._ollama_available,
        )

    def _check_ollama(self) -> bool:
        """Check if ollama is available."""
        try:
            import ollama
            # Test connection
            ollama.list()
            return True
        except ImportError:
            logger.warning("[SummarizationService] ollama not installed - using stub mode")
            return False
        except Exception as e:
            logger.warning("[SummarizationService] ollama not available: %s - using stub mode", e)
            return False

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

        if not self._ollama_available:
            return self._stub_summarize(text_to_summarize)

        try:
            import ollama
            
            prompt = f"""Summarize the following text concisely in 2-3 sentences. Focus on the main topics and key information.

Text:
{text_to_summarize}

Summary:"""

            response = ollama.generate(
                model=self._model_name,
                prompt=prompt,
                options={
                    "num_predict": self._max_tokens,
                    "temperature": 0.3,
                }
            )
            
            summary = response['response'].strip()
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

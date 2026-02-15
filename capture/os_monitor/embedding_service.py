from __future__ import annotations

import logging
from typing import Optional

from bmo.core.ollama_client import OllamaClient, ModelRole

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding service using BMO's OllamaClient with nomic-embed-text (768 dimensions)."""

    def __init__(self, ollama_client: Optional[OllamaClient] = None, dimension: int = 768) -> None:
        """
        Initialize embedding service.
        
        Args:
            ollama_client: OllamaClient instance (creates new if None)
            dimension: Expected embedding dimension (must be 768 for nomic-embed-text)
        """
        self._client = ollama_client or OllamaClient()
        self._dimension = dimension
        
        if dimension != 768:
            logger.warning(
                "[EmbeddingService] Dimension %d does not match nomic-embed-text (768), using 768",
                dimension
            )
            self._dimension = 768
        
        logger.info(
            "[EmbeddingService] Initialized with model=%s, dim=%d",
            "nomic-embed-text",
            self._dimension,
        )

    def embed(self, text: str) -> list[float]:
        """
        Generate embedding vector from text.
        
        Args:
            text: Input text to embed
        
        Returns:
            Embedding vector (list of floats, 768 dimensions)
        """
        if not text or not text.strip():
            logger.warning("[EmbeddingService] Empty text provided, returning zero vector")
            return [0.0] * self._dimension

        try:
            # Use OllamaClient with embeddings model
            result = self._client.embed_sync(text)
            vector = result.embedding
            
            logger.info(
                "[EmbeddingService] Generated embedding (text=%d chars, dim=%d)",
                len(text),
                len(vector),
            )
            return vector
            
        except Exception as e:
            logger.error("[EmbeddingService] Embedding generation failed: %s", e)
            return self._stub_embed(text)

    def _stub_embed(self, text: str) -> list[float]:
        """Fallback stub - returns zero vector."""
        logger.info(
            "[EmbeddingService] STUB - returning zero vector (text=%d chars, dim=%d)",
            len(text),
            self._dimension,
        )
        return [0.0] * self._dimension

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding service with sentence-transformers support."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", dimension: int = 384) -> None:
        """
        Initialize embedding service.
        
        Args:
            model_name: Model name for sentence-transformers (default: "all-MiniLM-L6-v2" = 384 dims)
                        Other options: "all-mpnet-base-v2" (768 dims), "paraphrase-MiniLM-L3-v2" (384 dims)
            dimension: Expected embedding dimension (must match model)
        """
        self._model_name = model_name
        self._dimension = dimension
        self._model: Optional[object] = None
        self._transformers_available = self._initialize_model()
        
        logger.info(
            "[EmbeddingService] Initialized with model=%s, dim=%d (available=%s)",
            model_name,
            dimension,
            self._transformers_available,
        )

    def _initialize_model(self) -> bool:
        """Try to load sentence-transformers model."""
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            logger.info("[EmbeddingService] Loaded model: %s", self._model_name)
            return True
        except ImportError:
            logger.warning("[EmbeddingService] sentence-transformers not installed - using stub mode")
            return False
        except Exception as e:
            logger.warning("[EmbeddingService] Failed to load model: %s - using stub mode", e)
            return False

    def embed(self, text: str) -> list[float]:
        """
        Generate embedding vector from text.
        
        Args:
            text: Input text to embed
        
        Returns:
            Embedding vector (list of floats)
        """
        if not text or not text.strip():
            logger.warning("[EmbeddingService] Empty text provided, returning zero vector")
            return [0.0] * self._dimension

        if self._transformers_available and self._model:
            try:
                # Generate real embedding
                embedding = self._model.encode(text, convert_to_numpy=True)
                vector = embedding.tolist()
                logger.info(
                    "[EmbeddingService] Generated embedding (text=%d chars, dim=%d)",
                    len(text),
                    len(vector),
                )
                return vector
            except Exception as e:
                logger.error("[EmbeddingService] Embedding generation failed: %s", e)
                return self._stub_embed(text)
        else:
            return self._stub_embed(text)

    def _stub_embed(self, text: str) -> list[float]:
        """Fallback stub - returns zero vector."""
        logger.info(
            "[EmbeddingService] STUB - returning zero vector (text=%d chars, dim=%d)",
            len(text),
            self._dimension,
        )
        return [0.0] * self._dimension

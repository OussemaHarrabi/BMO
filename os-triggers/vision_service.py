from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class VisionService:
    """Vision language model for image description (max 4B parameters)."""

    def __init__(self, model_name: str = "llava:7b") -> None:
        """
        Initialize vision service.
        
        Args:
            model_name: Ollama vision model name (e.g., "llava:7b", "bakllava:7b", "llava-phi3:3.8b")
        """
        self._model_name = model_name
        self._ollama_available = self._check_ollama()
        logger.info(
            "[VisionService] Initialized with model=%s (available=%s)",
            model_name,
            self._ollama_available,
        )

    def _check_ollama(self) -> bool:
        """Check if ollama is available."""
        try:
            import ollama
            ollama.list()
            return True
        except ImportError:
            logger.warning("[VisionService] ollama not installed - using stub mode")
            return False
        except Exception as e:
            logger.warning("[VisionService] ollama not available: %s - using stub mode", e)
            return False

    def can_process(self, path: str) -> bool:
        """Check if file is a supported image format."""
        ext = os.path.splitext(path)[1].lower()
        return ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}

    def describe_image(self, path: str) -> Optional[str]:
        """
        Generate a text description of the image using vision LLM.
        
        Args:
            path: Path to image file
        
        Returns:
            Text description of the image
        """
        if not os.path.exists(path):
            logger.warning("[VisionService] Image not found: %s", path)
            return None

        if not self.can_process(path):
            logger.warning("[VisionService] Unsupported image format: %s", path)
            return None

        if not self._ollama_available:
            return self._stub_describe(path)

        try:
            import ollama

            prompt = """Describe this image in detail. Include:
1. Main subjects or objects
2. Visual elements (colors, composition, style)
3. Context or setting
4. Any text visible in the image
5. Overall purpose or message

Keep the description factual and comprehensive."""

            response = ollama.generate(
                model=self._model_name,
                prompt=prompt,
                images=[path],
                options={
                    "temperature": 0.3,
                }
            )

            description = response['response'].strip()
            logger.info(
                "[VisionService] Generated description for %s (%d chars)",
                os.path.basename(path),
                len(description),
            )
            return description

        except Exception as e:
            logger.error("[VisionService] Image description failed for %s: %s", path, e)
            return self._stub_describe(path)

    def _stub_describe(self, path: str) -> str:
        """Fallback stub - returns basic file information."""
        try:
            size = os.path.getsize(path)
            ext = os.path.splitext(path)[1]
            description = f"Image file: {os.path.basename(path)} ({ext} format, {size} bytes)"
            logger.info("[VisionService] STUB - returning basic info: %s", description)
            return description
        except Exception as e:
            logger.error("[VisionService] STUB failed: %s", e)
            return f"Image file: {os.path.basename(path)}"

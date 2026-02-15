from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from bmo.core.ollama_client import OllamaClient, ModelRole

logger = logging.getLogger(__name__)


class VisionService:
    """Vision language model for image description using BMO's OllamaClient."""

    def __init__(self, ollama_client: Optional[OllamaClient] = None) -> None:
        """
        Initialize vision service.
        
        Args:
            ollama_client: OllamaClient instance (creates new if None)
        """
        self._client = ollama_client or OllamaClient()
        logger.info("[VisionService] Initialized with model=%s", "gemma3:4b-it")

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

        try:
            # Read image as base64
            with open(path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            prompt = """Describe this image in detail. Include:
1. Main subjects or objects
2. Visual elements (colors, composition, style)
3. Context or setting
4. Any text visible in the image
5. Overall purpose or message

Keep the description factual and comprehensive."""

            # Use OllamaClient with vision model - pass image_base64
            result = self._client.generate_with_image_sync(
                prompt=prompt,
                image_base64=image_data,
                role=ModelRole.VISION,
                temperature=0.3,
                max_tokens=300
            )

            description = result.content.strip()
            logger.info(
                "[VisionService] Generated description for %s (%d chars)",
                os.path.basename(path),
                len(description),
            )
            return description

        except Exception as e:
            logger.error("[VisionService] Image description failed for %s: %s", path, e)
            return self._stub_describe(path)

    def describe_image_with_base64(self, path: str) -> tuple[Optional[str], Optional[str]]:
        """
        Generate a text description of the image and return with base64 data.
        
        Args:
            path: Path to image file
        
        Returns:
            Tuple of (description, base64_data) - both None if failed
        """
        if not os.path.exists(path):
            logger.warning("[VisionService] Image not found: %s", path)
            return None, None

        if not self.can_process(path):
            logger.warning("[VisionService] Unsupported image format: %s", path)
            return None, None

        try:
            # Read image as base64
            with open(path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            prompt = """Describe this image in detail. Include:
1. Main subjects or objects
2. Visual elements (colors, composition, style)
3. Context or setting
4. Any text visible in the image
5. Overall purpose or message

Keep the description factual and comprehensive."""

            # Use OllamaClient with vision model - pass image_base64
            result = self._client.generate_with_image_sync(
                prompt=prompt,
                image_base64=image_data,
                role=ModelRole.VISION,
                temperature=0.3,
                max_tokens=300
            )

            description = result.content.strip()
            logger.info(
                "[VisionService] Generated description for %s (%d chars)",
                os.path.basename(path),
                len(description),
            )
            return description, image_data

        except Exception as e:
            logger.error("[VisionService] Image description failed for %s: %s", path, e)
            return self._stub_describe(path), None

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

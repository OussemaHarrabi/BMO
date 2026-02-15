from __future__ import annotations

import logging
import re
from typing import List

logger = logging.getLogger(__name__)


class RecursiveTextChunker:
    """Recursive text chunking for large documents."""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        min_chunk_size: int = 100,
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._min_chunk_size = min_chunk_size
        self._separators = [
            "\n\n\n",
            "\n\n",
            "\n",
            ". ",
            "? ",
            "! ",
            "; ",
            ", ",
            " ",
            "",
        ]
        logger.info(
            "[RecursiveTextChunker] Initialized (chunk_size=%d, overlap=%d)",
            chunk_size,
            chunk_overlap,
        )

    def chunk(self, text: str) -> List[str]:
        """Split text into overlapping chunks using recursive splitting."""
        if not text or len(text) <= self._chunk_size:
            return [text] if text else []

        return self._recursive_split(text, self._separators)

    def _recursive_split(self, text: str, separators: List[str]) -> List[str]:
        """Recursively split text using hierarchical separators."""
        if not separators:
            return self._split_by_chars(text)

        sep = separators[0]
        remaining_seps = separators[1:]

        if sep == "":
            return self._split_by_chars(text)

        parts = text.split(sep) if sep else [text]

        chunks = []
        current_chunk = ""

        for part in parts:
            test_chunk = current_chunk + sep + part if current_chunk else part

            if len(test_chunk) <= self._chunk_size:
                current_chunk = test_chunk
            else:
                if current_chunk:
                    if len(current_chunk) > self._chunk_size:
                        chunks.extend(self._recursive_split(current_chunk, remaining_seps))
                    else:
                        chunks.append(current_chunk)

                if len(part) > self._chunk_size:
                    chunks.extend(self._recursive_split(part, remaining_seps))
                    current_chunk = ""
                else:
                    current_chunk = part

        if current_chunk:
            if len(current_chunk) > self._chunk_size:
                chunks.extend(self._recursive_split(current_chunk, remaining_seps))
            else:
                chunks.append(current_chunk)

        return self._merge_with_overlap(chunks)

    def _split_by_chars(self, text: str) -> List[str]:
        """Split by character count as final fallback."""
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + self._chunk_size, len(text))
            chunks.append(text[start:end])
            start = end - self._chunk_overlap if end < len(text) else end
        return chunks

    def _merge_with_overlap(self, chunks: List[str]) -> List[str]:
        """Merge chunks with overlap for context preservation."""
        if len(chunks) <= 1:
            return chunks

        result = []
        for i, chunk in enumerate(chunks):
            if len(chunk) < self._min_chunk_size and i > 0 and result:
                result[-1] = result[-1] + " " + chunk
            else:
                result.append(chunk)

        return result

    def needs_chunking(self, text: str) -> bool:
        """Check if text exceeds chunk size threshold."""
        return len(text) > self._chunk_size

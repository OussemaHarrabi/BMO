from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class TextExtractor:
    """Extracts text from various file formats."""

    def __init__(self) -> None:
        logger.info("[TextExtractor] Initialized")
        self._docx_available = self._check_docx()
        self._pdf_available = self._check_pdf()

    def _check_docx(self) -> bool:
        try:
            import docx
            return True
        except ImportError:
            logger.warning("[TextExtractor] python-docx not installed - .docx support disabled")
            return False

    def _check_pdf(self) -> bool:
        try:
            import PyPDF2
            return True
        except ImportError:
            logger.warning("[TextExtractor] PyPDF2 not installed - .pdf support disabled")
            return False

    def can_extract(self, path: str) -> bool:
        """Check if file type is supported for text extraction."""
        ext = os.path.splitext(path)[1].lower()
        if ext in {".txt", ".md", ".log", ".json", ".xml", ".csv", ".py", ".js", ".java", ".cpp", ".c", ".h"}:
            return True
        if ext == ".docx" and self._docx_available:
            return True
        if ext == ".pdf" and self._pdf_available:
            return True
        return False

    def extract(self, path: str) -> Optional[str]:
        """Extract text content from file."""
        if not os.path.exists(path):
            logger.warning("[TextExtractor] File not found: %s", path)
            return None

        ext = os.path.splitext(path)[1].lower()

        try:
            if ext in {".txt", ".md", ".log", ".json", ".xml", ".csv", ".py", ".js", ".java", ".cpp", ".c", ".h"}:
                return self._extract_plain_text(path)
            elif ext == ".docx" and self._docx_available:
                return self._extract_docx(path)
            elif ext == ".pdf" and self._pdf_available:
                return self._extract_pdf(path)
            else:
                logger.debug("[TextExtractor] Unsupported file type: %s", ext)
                return None
        except Exception as e:
            logger.error("[TextExtractor] Failed to extract from %s: %s", path, e)
            return None

    def _extract_plain_text(self, path: str) -> Optional[str]:
        """Extract plain text files."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
                logger.info("[TextExtractor] Extracted plain text from %s (%d chars)", path, len(text))
                return text
        except Exception as e:
            logger.error("[TextExtractor] Plain text extraction failed: %s", e)
            return None

    def _extract_docx(self, path: str) -> Optional[str]:
        """Extract text from .docx files."""
        try:
            import docx
            doc = docx.Document(path)
            text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
            logger.info("[TextExtractor] Extracted .docx from %s (%d chars)", path, len(text))
            return text
        except Exception as e:
            logger.error("[TextExtractor] .docx extraction failed: %s", e)
            return None

    def _extract_pdf(self, path: str) -> Optional[str]:
        """Extract text from .pdf files."""
        try:
            import PyPDF2
            with open(path, "rb") as fh:
                reader = PyPDF2.PdfReader(fh)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                logger.info("[TextExtractor] Extracted .pdf from %s (%d chars)", path, len(text))
                return text.strip()
        except Exception as e:
            logger.error("[TextExtractor] .pdf extraction failed: %s", e)
            return None

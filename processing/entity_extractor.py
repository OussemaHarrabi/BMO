"""
Entity Extractor - Extracts named entities for knowledge graph using Qwen3-4B.
"""

import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import logging
import re

from core.ollama_client import OllamaClient, ModelRole

logger = logging.getLogger(__name__)


# Valid entity types
ENTITY_TYPES = [
    "person",
    "project",
    "repo",
    "topic",
    "technology",
    "website",
    "organization"
]


ENTITY_EXTRACTOR_SYSTEM_PROMPT = """You are an entity extractor for a personal knowledge graph.
Extract named entities and their types from the given text.

Entity types:
- person: Names of people
- project: Software projects, personal projects, work projects
- repo: GitHub/GitLab repositories (format: owner/name)
- topic: Technical topics, subjects, concepts
- technology: Programming languages, frameworks, tools
- website: Specific websites or web services
- organization: Companies, teams, groups

Rules:
1. Only extract entities explicitly mentioned
2. Normalize names (consistent casing)
3. For repos, extract full path if visible (e.g., "vercel/ai" not just "ai")
4. Include confidence score (0.0-1.0) based on how clearly it's mentioned

Respond in JSON format ONLY."""


@dataclass
class Entity:
    """Extracted entity."""
    name: str
    entity_type: str
    confidence: float
    context: Optional[str] = None


@dataclass
class ExtractionResult:
    """Result of entity extraction."""
    entities: List[Entity]
    latency_ms: int
    model: str
    tokens_used: int


class EntityExtractor:
    """Extracts named entities from text for knowledge graph."""
    
    def __init__(self, client: Optional[OllamaClient] = None):
        """Initialize extractor.
        
        Args:
            client: Optional OllamaClient instance. Creates one if not provided.
        """
        self.client = client or OllamaClient()
    
    async def extract(
        self,
        text: str,
        max_chars: int = 1500,
        min_confidence: float = 0.5
    ) -> ExtractionResult:
        """Extract named entities from text.
        
        Args:
            text: The text content to extract entities from.
            max_chars: Maximum characters to use from text.
            min_confidence: Minimum confidence threshold for entities.
            
        Returns:
            ExtractionResult with entities and metadata.
        """
        truncated = text[:max_chars] if len(text) > max_chars else text
        
        prompt = f"""Extract entities from this content:

{truncated}

Return JSON:
{{"entities": [{{"name": "...", "type": "...", "confidence": 0.0-1.0, "context": "snippet where found"}}]}}"""
        
        try:
            result = await self.client.generate(
                role=ModelRole.ENTITY_EXTRACTOR,
                prompt=prompt,
                system_prompt=ENTITY_EXTRACTOR_SYSTEM_PROMPT,
                format_json=True,
                temperature=0.3,
                max_tokens=500
            )
            
            entities = self._parse_entities(result.content, min_confidence)
            
            return ExtractionResult(
                entities=entities,
                latency_ms=result.latency_ms,
                model=result.model,
                tokens_used=result.tokens_used
            )
            
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            # Try regex fallback
            entities = self._extract_with_regex(text)
            return ExtractionResult(
                entities=entities,
                latency_ms=0,
                model="regex_fallback",
                tokens_used=0
            )
    
    def extract_sync(
        self,
        text: str,
        max_chars: int = 1500,
        min_confidence: float = 0.5
    ) -> ExtractionResult:
        """Extract entities (synchronous version).
        
        Args:
            text: The text content to extract entities from.
            max_chars: Maximum characters to use from text.
            min_confidence: Minimum confidence threshold.
            
        Returns:
            ExtractionResult with entities and metadata.
        """
        truncated = text[:max_chars] if len(text) > max_chars else text
        
        prompt = f"""Extract entities from this content:

{truncated}

Return JSON:
{{"entities": [{{"name": "...", "type": "...", "confidence": 0.0-1.0, "context": "snippet where found"}}]}}"""
        
        try:
            result = self.client.generate_sync(
                role=ModelRole.ENTITY_EXTRACTOR,
                prompt=prompt,
                system_prompt=ENTITY_EXTRACTOR_SYSTEM_PROMPT,
                format_json=True,
                temperature=0.3,
                max_tokens=500
            )
            
            entities = self._parse_entities(result.content, min_confidence)
            
            return ExtractionResult(
                entities=entities,
                latency_ms=result.latency_ms,
                model=result.model,
                tokens_used=result.tokens_used
            )
            
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            entities = self._extract_with_regex(text)
            return ExtractionResult(
                entities=entities,
                latency_ms=0,
                model="regex_fallback",
                tokens_used=0
            )
    
    def _parse_entities(self, json_str: str, min_confidence: float) -> List[Entity]:
        """Parse entities from JSON response.
        
        Args:
            json_str: JSON string from LLM.
            min_confidence: Minimum confidence threshold.
            
        Returns:
            List of Entity objects.
        """
        try:
            # Try to extract JSON from response
            json_str = json_str.strip()
            
            # Handle markdown code blocks
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]
            
            data = json.loads(json_str)
            raw_entities = data.get("entities", [])
            
            entities = []
            for e in raw_entities:
                entity_type = e.get("type", "").lower()
                confidence = float(e.get("confidence", 0.5))
                
                # Validate entity type
                if entity_type not in ENTITY_TYPES:
                    continue
                
                # Filter by confidence
                if confidence < min_confidence:
                    continue
                
                entities.append(Entity(
                    name=e.get("name", "").strip(),
                    entity_type=entity_type,
                    confidence=confidence,
                    context=e.get("context")
                ))
            
            return entities
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to parse entity JSON: {e}")
            return []
    
    def _extract_with_regex(self, text: str) -> List[Entity]:
        """Fallback regex-based entity extraction.
        
        Args:
            text: Text to extract from.
            
        Returns:
            List of Entity objects.
        """
        entities = []
        
        # GitHub repos (owner/repo pattern)
        repo_pattern = r'\b([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)\b'
        for match in re.finditer(repo_pattern, text):
            repo = match.group(1)
            # Filter out common false positives
            if "/" in repo and not repo.startswith("http"):
                entities.append(Entity(
                    name=repo,
                    entity_type="repo",
                    confidence=0.7,
                    context=text[max(0, match.start()-20):match.end()+20]
                ))
        
        # URLs for websites
        url_pattern = r'https?://([a-zA-Z0-9.-]+)'
        for match in re.finditer(url_pattern, text):
            domain = match.group(1)
            entities.append(Entity(
                name=domain,
                entity_type="website",
                confidence=0.8,
                context=match.group(0)
            ))
        
        # Technology keywords
        tech_keywords = [
            "Python", "JavaScript", "TypeScript", "React", "Vue", "Angular",
            "Node.js", "FastAPI", "Django", "Flask", "Docker", "Kubernetes",
            "PostgreSQL", "MongoDB", "Redis", "Neo4j", "AWS", "GCP", "Azure"
        ]
        text_lower = text.lower()
        for tech in tech_keywords:
            if tech.lower() in text_lower:
                entities.append(Entity(
                    name=tech,
                    entity_type="technology",
                    confidence=0.9
                ))
        
        # Deduplicate by name
        seen = set()
        unique_entities = []
        for e in entities:
            if e.name.lower() not in seen:
                seen.add(e.name.lower())
                unique_entities.append(e)
        
        return unique_entities


async def extract_entities(
    text: str,
    client: Optional[OllamaClient] = None,
    min_confidence: float = 0.5
) -> List[Dict[str, Any]]:
    """Convenience function to extract entities.
    
    Args:
        text: Text to extract entities from.
        client: Optional OllamaClient instance.
        min_confidence: Minimum confidence threshold.
        
    Returns:
        List of entity dicts with name, type, confidence.
    """
    extractor = EntityExtractor(client)
    result = await extractor.extract(text, min_confidence=min_confidence)
    
    return [
        {
            "name": e.name,
            "type": e.entity_type,
            "confidence": e.confidence,
            "context": e.context
        }
        for e in result.entities
    ]

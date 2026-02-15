"""
Ollama Client - Unified interface for local LLM inference.
"""

import os
import json
import time
from typing import Optional, Dict, Any, List, AsyncIterator
from dataclasses import dataclass
from enum import Enum

import httpx


class ModelRole(str, Enum):
    """Model roles in BMO system."""
    ROUTER = "router"
    REASONER = "reasoner"
    CLASSIFIER = "classifier"
    ENTITY_EXTRACTOR = "entity_extractor"
    VERIFIER = "verifier"
    VISION = "vision"
    EMBEDDINGS = "embeddings"


# Model configuration - all <4B parameters
MODEL_CONFIG = {
    ModelRole.ROUTER: {
        "name": "phi3.5:latest",
        "temperature": 0.3,
        "max_tokens": 150,
        "format": "json"
    },
    ModelRole.REASONER: {
        "name": "qwen3:4b",
        "temperature": 0.7,
        "max_tokens": 2000
    },
    ModelRole.CLASSIFIER: {
        "name": "phi3.5:latest",
        "temperature": 0.1,
        "max_tokens": 50
    },
    ModelRole.ENTITY_EXTRACTOR: {
        "name": "qwen3:4b",
        "temperature": 0.3,
        "max_tokens": 1000,
        "format": "json"
    },
    ModelRole.VERIFIER: {
        "name": "phi3.5:latest",
        "temperature": 0.2,
        "max_tokens": 1000,
        "format": "json"
    },
    ModelRole.VISION: {
        "name": "gemma3:4b",
        "temperature": 0.5,
        "max_tokens": 800
    },
    ModelRole.EMBEDDINGS: {
        "name": "nomic-embed-text",
        "dimension": 768
    }
}


@dataclass
class GenerationResult:
    """Result from model generation."""
    content: str
    model: str
    role: ModelRole
    tokens_used: int
    latency_ms: int
    raw_response: Dict[str, Any]


@dataclass
class EmbeddingResult:
    """Result from embedding generation."""
    embedding: List[float]
    model: str
    latency_ms: int


class OllamaClient:
    """Unified Ollama client for all BMO model interactions."""
    
    def __init__(self):
        """Initialize Ollama client."""
        self.base_url = os.getenv("OLLAMA_HOST", os.getenv("OLLAMA_URL", "http://localhost:11434"))
        self.timeout = float(os.getenv("OLLAMA_TIMEOUT", "120"))
        self._loaded_models: Dict[str, bool] = {}
    
    async def _ensure_model_loaded(self, model_name: str) -> bool:
        """Check if model is loaded, try to load if not."""
        if model_name in self._loaded_models:
            return self._loaded_models[model_name]
        
        async with httpx.AsyncClient() as client:
            try:
                # Check if model exists
                response = await client.get(
                    f"{self.base_url}/api/tags",
                    timeout=10.0
                )
                response.raise_for_status()
                
                models = response.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                
                # Check if our model is in the list
                loaded = any(model_name in name for name in model_names)
                self._loaded_models[model_name] = loaded
                
                return loaded
            except Exception:
                return False
    
    async def generate(
        self,
        role: ModelRole,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        format_json: bool = False
    ) -> GenerationResult:
        """Generate text using specified model role."""
        config = MODEL_CONFIG.get(role, MODEL_CONFIG[ModelRole.REASONER])
        model_name = config["name"]
        
        # Disable thinking mode for qwen3 models to ensure response fits in token limit
        # qwen3 uses /no_think suffix to disable chain-of-thought reasoning
        actual_prompt = prompt
        if "qwen3" in model_name.lower():
            actual_prompt = prompt + " /no_think"
        
        request_data = {
            "model": model_name,
            "prompt": actual_prompt,
            "stream": False,
            "options": {
                "temperature": temperature or config.get("temperature", 0.7),
                "num_predict": max_tokens or config.get("max_tokens", 2000)
            }
        }
        
        if system_prompt:
            request_data["system"] = system_prompt
        
        if format_json or config.get("format") == "json":
            request_data["format"] = "json"
        
        start_time = time.time()
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json=request_data,
                timeout=self.timeout
            )
            response.raise_for_status()
        
        latency_ms = int((time.time() - start_time) * 1000)
        result = response.json()
        
        content = result.get("response", "")
        
        return GenerationResult(
            content=content,
            model=model_name,
            role=role,
            tokens_used=result.get("eval_count", 0),
            latency_ms=latency_ms,
            raw_response=result
        )
    
    def generate_sync(
        self,
        role: ModelRole,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        format_json: bool = False
    ) -> GenerationResult:
        """Generate text using specified model role (sync version)."""
        config = MODEL_CONFIG.get(role, MODEL_CONFIG[ModelRole.REASONER])
        model_name = config["name"]
        
        actual_prompt = prompt
        if "qwen3" in model_name.lower():
            actual_prompt = prompt + " /no_think"
        
        request_data = {
            "model": model_name,
            "prompt": actual_prompt,
            "stream": False,
            "options": {
                "temperature": temperature or config.get("temperature", 0.7),
                "num_predict": max_tokens or config.get("max_tokens", 2000)
            }
        }
        
        if system_prompt:
            request_data["system"] = system_prompt
        
        if format_json or config.get("format") == "json":
            request_data["format"] = "json"
        
        start_time = time.time()
        
        with httpx.Client() as client:
            response = client.post(
                f"{self.base_url}/api/generate",
                json=request_data,
                timeout=self.timeout
            )
            response.raise_for_status()
        
        latency_ms = int((time.time() - start_time) * 1000)
        result = response.json()
        
        content = result.get("response", "")
        
        return GenerationResult(
            content=content,
            model=model_name,
            role=role,
            tokens_used=result.get("eval_count", 0),
            latency_ms=latency_ms,
            raw_response=result
        )
    
    async def chat(
        self,
        role: ModelRole,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        format_json: bool = False
    ) -> GenerationResult:
        """Chat completion using specified model role."""
        config = MODEL_CONFIG.get(role, MODEL_CONFIG[ModelRole.REASONER])
        model_name = config["name"]
        
        request_data = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature or config.get("temperature", 0.7),
                "num_predict": max_tokens or config.get("max_tokens", 500)
            }
        }
        
        if format_json or config.get("format") == "json":
            request_data["format"] = "json"
        
        start_time = time.time()
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json=request_data,
                timeout=self.timeout
            )
            response.raise_for_status()
        
        latency_ms = int((time.time() - start_time) * 1000)
        result = response.json()
        
        return GenerationResult(
            content=result.get("message", {}).get("content", ""),
            model=model_name,
            role=role,
            tokens_used=result.get("eval_count", 0),
            latency_ms=latency_ms,
            raw_response=result
        )
    
    async def embed(self, text: str) -> EmbeddingResult:
        """Generate embedding for text."""
        model_name = MODEL_CONFIG[ModelRole.EMBEDDINGS]["name"]
        
        start_time = time.time()
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={
                    "model": model_name,
                    "prompt": text
                },
                timeout=30.0
            )
            response.raise_for_status()
        
        latency_ms = int((time.time() - start_time) * 1000)
        result = response.json()
        
        return EmbeddingResult(
            embedding=result.get("embedding", []),
            model=model_name,
            latency_ms=latency_ms
        )
    
    def embed_sync(self, text: str) -> EmbeddingResult:
        """Generate embedding for text (sync version)."""
        model_name = MODEL_CONFIG[ModelRole.EMBEDDINGS]["name"]
        
        start_time = time.time()
        
        with httpx.Client() as client:
            response = client.post(
                f"{self.base_url}/api/embeddings",
                json={
                    "model": model_name,
                    "prompt": text
                },
                timeout=30.0
            )
            response.raise_for_status()
        
        latency_ms = int((time.time() - start_time) * 1000)
        result = response.json()
        
        return EmbeddingResult(
            embedding=result.get("embedding", []),
            model=model_name,
            latency_ms=latency_ms
        )
    
    async def generate_with_image(
        self,
        prompt: str,
        image_base64: str,
        role: ModelRole = ModelRole.VISION,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> GenerationResult:
        """Generate text from image using vision model."""
        config = MODEL_CONFIG.get(role, MODEL_CONFIG[ModelRole.VISION])
        model_name = config["name"]
        
        request_data = {
            "model": model_name,
            "prompt": prompt,
            "images": [image_base64],
            "stream": False,
            "options": {
                "temperature": temperature or config.get("temperature", 0.5),
                "num_predict": max_tokens or config.get("max_tokens", 300)
            }
        }
        
        if system_prompt:
            request_data["system"] = system_prompt
        
        start_time = time.time()
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json=request_data,
                timeout=self.timeout
            )
            response.raise_for_status()
        
        latency_ms = int((time.time() - start_time) * 1000)
        result = response.json()
        
        return GenerationResult(
            content=result.get("response", ""),
            model=model_name,
            role=role,
            tokens_used=result.get("eval_count", 0),
            latency_ms=latency_ms,
            raw_response=result
        )
    
    def generate_with_image_sync(
        self,
        prompt: str,
        image_base64: str,
        role: ModelRole = ModelRole.VISION,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> GenerationResult:
        """Generate text from image using vision model (sync version)."""
        config = MODEL_CONFIG.get(role, MODEL_CONFIG[ModelRole.VISION])
        model_name = config["name"]
        
        request_data = {
            "model": model_name,
            "prompt": prompt,
            "images": [image_base64],
            "stream": False,
            "options": {
                "temperature": temperature or config.get("temperature", 0.5),
                "num_predict": max_tokens or config.get("max_tokens", 300)
            }
        }
        
        if system_prompt:
            request_data["system"] = system_prompt
        
        start_time = time.time()
        
        with httpx.Client() as client:
            response = client.post(
                f"{self.base_url}/api/generate",
                json=request_data,
                timeout=self.timeout
            )
            response.raise_for_status()
        
        latency_ms = int((time.time() - start_time) * 1000)
        result = response.json()
        
        return GenerationResult(
            content=result.get("response", ""),
            model=model_name,
            role=role,
            tokens_used=result.get("eval_count", 0),
            latency_ms=latency_ms,
            raw_response=result
        )
    
    async def stream_generate(
        self,
        role: ModelRole,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> AsyncIterator[str]:
        """Stream text generation for real-time output."""
        config = MODEL_CONFIG.get(role, MODEL_CONFIG[ModelRole.REASONER])
        model_name = config["name"]
        
        request_data = {
            "model": model_name,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature or config.get("temperature", 0.7),
                "num_predict": max_tokens or config.get("max_tokens", 500)
            }
        }
        
        if system_prompt:
            request_data["system"] = system_prompt
        
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json=request_data,
                timeout=self.timeout
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        if "response" in data:
                            yield data["response"]
                        if data.get("done"):
                            break
    
    async def list_models(self) -> List[Dict[str, Any]]:
        """List available models."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/tags",
                timeout=10.0
            )
            response.raise_for_status()
        
        return response.json().get("models", [])
    
    async def pull_model(self, model_name: str) -> bool:
        """Pull a model from Ollama library."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/pull",
                    json={"name": model_name},
                    timeout=600.0  # Long timeout for downloads
                )
                response.raise_for_status()
                return True
            except Exception:
                return False
    
    async def health_check(self) -> bool:
        """Check if Ollama is running."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/tags",
                    timeout=5.0
                )
                return response.status_code == 200
        except Exception:
            return False
    
    def health_check_sync(self) -> bool:
        """Check if Ollama is running (sync version)."""
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{self.base_url}/api/tags",
                    timeout=5.0
                )
                return response.status_code == 200
        except Exception:
            return False


# Convenience functions for common operations
async def classify_content(text: str, client: Optional[OllamaClient] = None) -> str:
    """Classify content into a category."""
    if client is None:
        client = OllamaClient()
    
    system = """You are a content classifier. Classify the given text into exactly ONE category.
Categories: code, finance, personal, research, work, entertainment
Respond with ONLY the category name in lowercase, nothing else."""
    
    result = await client.generate(
        role=ModelRole.CLASSIFIER,
        prompt=f"Classify this content:\n\n{text[:1000]}\n\nCategory:",
        system_prompt=system
    )
    
    # Extract category from response
    category = result.content.strip().lower()
    valid_categories = ["code", "finance", "personal", "research", "work", "entertainment"]
    
    return category if category in valid_categories else "uncategorized"


async def summarize_content(text: str, source: str, category: str, client: Optional[OllamaClient] = None) -> str:
    """Summarize content for memory storage."""
    if client is None:
        client = OllamaClient()
    
    system = """You are a concise summarizer. Create brief, information-dense summaries.
Rules:
1. Maximum 2-3 sentences
2. Include specific names, numbers, and key terms
3. Focus on WHAT and WHY, not HOW
4. Use active voice
5. No filler words or preamble"""
    
    result = await client.generate(
        role=ModelRole.REASONER,
        prompt=f"Source: {source}\nCategory: {category}\n\nContent:\n{text[:2000]}\n\nSummary:",
        system_prompt=system
    )
    
    return result.content.strip()


async def extract_entities(text: str, client: Optional[OllamaClient] = None) -> List[Dict[str, Any]]:
    """Extract named entities from text."""
    if client is None:
        client = OllamaClient()
    
    system = """You are an entity extractor. Extract named entities and their types.
Entity types: person, project, repo, topic, technology, website, organization
Respond in JSON format ONLY: {"entities": [{"name": "...", "type": "...", "confidence": 0.0-1.0}]}"""
    
    result = await client.generate(
        role=ModelRole.ENTITY_EXTRACTOR,
        prompt=f"Extract entities from:\n\n{text[:1500]}\n\nJSON:",
        system_prompt=system,
        format_json=True
    )
    
    try:
        data = json.loads(result.content)
        return data.get("entities", [])
    except json.JSONDecodeError:
        return []

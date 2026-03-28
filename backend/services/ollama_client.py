"""
LAKO — Ollama Client Service
Handles all communication with the local Ollama server.
Ollama URL: http://localhost:11434
Session 1: Stub — wired in Session 3.
"""

import httpx
from typing import AsyncGenerator, List, Optional
from config import get_config


class OllamaClient:
    """Client for the local Ollama API."""

    def __init__(self):
        config = get_config()
        self.base_url = config["ollama_url"]
        self.primary_model = config["primary_model"]
        self.vision_model = config["vision_model"]
        self.embedding_model = config["embedding_model"]

    async def list_models(self) -> List[dict]:
        """
        GET /api/tags — Returns all installed Ollama models.
        Used by GET /api/models to auto-populate frontend dropdowns.
        TODO (Session 3): implement live call.
        """
        raise NotImplementedError("OllamaClient.list_models() — Session 3")

    async def stream_chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        POST /api/generate with stream=True.
        Yields tokens as they arrive for streaming response.
        TODO (Session 8): implement streaming.
        """
        raise NotImplementedError("OllamaClient.stream_chat() — Session 8")

    async def chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
    ) -> str:
        """
        POST /api/generate with stream=False.
        Returns full response as string.
        TODO (Session 8): implement.
        """
        raise NotImplementedError("OllamaClient.chat() — Session 8")

    async def embed(self, text: str) -> List[float]:
        """
        POST /api/embeddings — Generate embedding vector for text.
        Uses embedding_model (nomic-embed-text).
        TODO (Session 4): implement.
        """
        raise NotImplementedError("OllamaClient.embed() — Session 4")

    async def describe_image(self, image_base64: str, prompt: str = "Describe this image in detail.") -> str:
        """
        POST /api/generate with images field — Vision model call.
        Uses vision_model (llava:13b).
        TODO (Session 7): implement.
        """
        raise NotImplementedError("OllamaClient.describe_image() — Session 7")

    async def health_check(self) -> bool:
        """
        GET / on Ollama server — returns True if reachable.
        """
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(self.base_url)
                return r.status_code == 200
        except Exception:
            return False


# Singleton instance
ollama_client = OllamaClient()

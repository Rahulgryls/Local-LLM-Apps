"""
LAKO — Ollama Client Service
Handles all communication with the local Ollama server.
Session 3: list_models() and health_check() implemented.
Sessions 4, 7, 8: embed(), describe_image(), stream_chat() wired later.
"""

import json

import httpx
from typing import AsyncGenerator, List, Optional
from config import get_config


class OllamaClient:
    """Client for the local Ollama API. Reads config fresh on each call
    so that config changes (via POST /api/config) take effect immediately."""

    def _base_url(self) -> str:
        return get_config()["ollama_url"]

    def _embedding_model(self) -> str:
        return get_config()["embedding_model"]

    def _vision_model(self) -> str:
        return get_config()["vision_model"]

    def _primary_model(self) -> str:
        return get_config()["primary_model"]

    async def list_models(self) -> List[dict]:
        """
        GET /api/tags — Returns all installed Ollama models.
        Each entry: { name, size, modified }
        """
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{self._base_url()}/api/tags")
            r.raise_for_status()
            data = r.json()

        result = []
        for m in data.get("models", []):
            size_bytes = m.get("size", 0)
            size_gb = size_bytes / (1024 ** 3)
            size_str = f"~{size_gb:.1f} GB" if size_gb >= 0.05 else f"~{size_bytes // (1024 ** 2)} MB"
            result.append({
                "name": m["name"],
                "size": size_str,
                "modified": m.get("modified_at", ""),
            })
        return result

    async def health_check(self) -> bool:
        """GET / on Ollama server — returns True if reachable."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(self._base_url())
                return r.status_code == 200
        except Exception:
            return False

    async def stream_chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        POST /api/generate with stream=True.
        Yields tokens as they arrive — one JSON line per token from Ollama.
        Stops when Ollama sends {"done": true}.
        """
        effective_model = model or self._primary_model()
        body: dict = {"model": effective_model, "prompt": prompt, "stream": True}
        if system:
            body["system"] = system

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", f"{self._base_url()}/api/generate", json=body
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("response", "")
                        if token:
                            yield token
                        if chunk.get("done", False):
                            return
                    except json.JSONDecodeError:
                        continue

    async def chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
    ) -> str:
        """
        POST /api/generate with stream=False.
        Returns full response as a single string.
        """
        effective_model = model or self._primary_model()
        body: dict = {"model": effective_model, "prompt": prompt, "stream": False}
        if system:
            body["system"] = system

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{self._base_url()}/api/generate", json=body)
            r.raise_for_status()
            data = r.json()
            return data.get("response", "")

    async def embed(self, text: str) -> List[float]:
        """
        POST /api/embed — Generate a single embedding vector for text.
        Uses embedding_model from config (nomic-embed-text).
        Returns a flat list of floats (768 dims for nomic-embed-text).
        """
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self._base_url()}/api/embed",
                json={"model": self._embedding_model(), "input": text},
            )
            r.raise_for_status()
            data = r.json()
            return data["embeddings"][0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        POST /api/embed with a list of inputs — batch embedding.
        More efficient than calling embed() in a loop.
        Returns list of float vectors, one per input text.
        """
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{self._base_url()}/api/embed",
                json={"model": self._embedding_model(), "input": texts},
            )
            r.raise_for_status()
            data = r.json()
            return data["embeddings"]

    async def describe_image(
        self,
        image_base64: str,
        prompt: str = "Describe this image in detail.",
    ) -> str:
        """
        POST /api/generate with images field — Vision model call.
        Uses vision_model from config (llava:13b).
        stream=False — returns full response as a single string.
        """
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{self._base_url()}/api/generate",
                json={
                    "model": self._vision_model(),
                    "prompt": prompt,
                    "images": [image_base64],
                    "stream": False,
                },
            )
            r.raise_for_status()
            data = r.json()
            return data.get("response", "")


# Singleton instance
ollama_client = OllamaClient()

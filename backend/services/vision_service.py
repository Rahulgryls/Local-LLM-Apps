"""
LAKO — Vision Service
Processes images and diagrams extracted from documents.
Sends image to llava:13b via Ollama → returns text description.
Session 1: Stub — wired in Session 7.
"""

import base64
from pathlib import Path
from typing import Optional
from services.ollama_client import ollama_client


VISION_PROMPT = (
    "You are analyzing a document image for a bank knowledge system. "
    "Describe this image in detail: identify charts, diagrams, tables, flowcharts, "
    "process flows, or any structured content. Be precise and factual."
)


class VisionService:
    """Describes images and diagrams using the local vision model (llava:13b)."""

    async def describe_image_bytes(self, image_bytes: bytes, prompt: Optional[str] = None) -> str:
        """
        Convert raw image bytes to base64, then call llava:13b for description.
        TODO (Session 7): call ollama_client.describe_image()
        """
        raise NotImplementedError("VisionService.describe_image_bytes() — Session 7")

    async def describe_image_file(self, image_path: Path, prompt: Optional[str] = None) -> str:
        """
        Read image from disk and describe it.
        TODO (Session 7): read file → describe_image_bytes()
        """
        raise NotImplementedError("VisionService.describe_image_file() — Session 7")

    async def describe_image_base64(self, image_b64: str, prompt: Optional[str] = None) -> str:
        """
        Describe an already base64-encoded image.
        This is the core call to ollama_client.describe_image().
        TODO (Session 7): implement.
        """
        effective_prompt = prompt or VISION_PROMPT
        raise NotImplementedError("VisionService.describe_image_base64() — Session 7")


# Singleton instance
vision_service = VisionService()

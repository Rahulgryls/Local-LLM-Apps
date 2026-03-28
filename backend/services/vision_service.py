"""
LAKO — Vision Service
Processes images and diagrams extracted from documents.
Sends image to llava:13b via Ollama → returns text description.
Session 1: Stub — wired in Session 7.
"""

import base64
import io
from pathlib import Path
from typing import Optional

from PIL import Image as PILImage
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
        Raises ValueError if the image is smaller than 100x100 px.
        """
        img = PILImage.open(io.BytesIO(image_bytes))
        w, h = img.size
        if w < 100 or h < 100:
            raise ValueError(f"Image too small to describe: {w}x{h} px")
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        return await self.describe_image_base64(image_b64, prompt)

    async def describe_image_file(self, image_path: Path, prompt: Optional[str] = None) -> str:
        """Read image from disk and describe it."""
        image_bytes = Path(image_path).read_bytes()
        return await self.describe_image_bytes(image_bytes, prompt)

    async def describe_image_base64(self, image_b64: str, prompt: Optional[str] = None) -> str:
        """
        Describe an already base64-encoded image.
        This is the core call to ollama_client.describe_image().
        """
        effective_prompt = prompt or VISION_PROMPT
        return await ollama_client.describe_image(image_b64, effective_prompt)


# Singleton instance
vision_service = VisionService()

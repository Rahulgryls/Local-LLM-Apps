"""
LAKO — Vision Service
Processes images and diagrams extracted from documents.
Sends image to vision model (config: vision_model) via Ollama → returns text description.
Session 1:  Stub — wired in Session 7. Session 13: model reference updated to config-driven.
Session 16: Data-extraction vision prompt — extracts all numerical values with labels from
            charts/figures instead of generic descriptions, preventing RAG false negatives
            on figure-only statistical data.
"""

import base64
import io
from pathlib import Path
from typing import Optional

from PIL import Image as PILImage
from services.ollama_client import ollama_client


VISION_PROMPT = (
    "You are a data extraction assistant processing a document image for a knowledge system. "
    "Your primary goal is to extract ALL numerical values and their exact labels — do NOT give "
    "a generic description.\n\n"
    "If the image contains a chart, graph, or figure with data:\n"
    "  Chart title: <title as written>\n"
    "  Chart type: <bar / line / pie / grouped bar / etc.>\n"
    "  X-axis label: <label if present>\n"
    "  Y-axis label: <label if present>\n"
    "  Data points (list every value):\n"
    "    - <category / series label>: <exact numeric value> <unit or %>\n"
    "    (continue for every bar, line point, or segment — do not skip any)\n"
    "  Notes: <footnotes, asterisks, or statistical significance markers visible>\n\n"
    "If the image contains a table: reproduce every cell as plain text rows.\n"
    "If the image contains a flowchart or diagram: describe every node and arrow precisely.\n"
    "If the image contains document text: transcribe it exactly.\n\n"
    "Do not summarise. Do not skip values. If a value is illegible, write 'illegible'."
)


class VisionService:
    """Describes images and diagrams using the local vision model (config: vision_model)."""

    async def describe_image_bytes(self, image_bytes: bytes, prompt: Optional[str] = None) -> str:
        """
        Convert raw image bytes to base64, then call vision model for description.
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

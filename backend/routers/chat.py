"""
LAKO — Chat Router
POST /api/chat
Direct LLM query — model, prompt, streaming on/off.
Session 8: Fully implemented.
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from config import get_config
from services.ollama_client import ollama_client

router = APIRouter()


class ChatRequest(BaseModel):
    prompt: str
    model: Optional[str] = None  # Override primary model if provided
    stream: bool = True


class ChatResponse(BaseModel):
    answer: str
    model: str


@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Direct LLM query via Ollama — no document retrieval.
    stream=True (default): returns a StreamingResponse that yields tokens as plain text.
    stream=False: returns a JSON ChatResponse with the full answer.
    """
    effective_model = request.model or get_config()["primary_model"]

    if request.stream:
        async def generate():
            async for token in ollama_client.stream_chat(
                request.prompt,
                model=effective_model,
            ):
                yield token

        return StreamingResponse(generate(), media_type="text/plain")

    answer = await ollama_client.chat(request.prompt, model=effective_model)
    return ChatResponse(answer=answer, model=effective_model)

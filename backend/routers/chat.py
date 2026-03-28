"""
LAKO — Chat Router
POST /api/chat
Direct LLM query — model, prompt, streaming on/off.
Session 1: Stub — full implementation in Session 8.
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

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
    Direct LLM query via Ollama.
    Returns streaming response word-by-word when stream=True.
    STUB — wired to Ollama in Session 8.
    """
    # TODO (Session 8): call ollama_client.stream_chat()
    return ChatResponse(
        answer="[STUB] Chat endpoint is not yet implemented. Session 8 will wire this to Ollama.",
        model=request.model or "qwen3.5:9b",
    )

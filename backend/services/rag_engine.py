"""
LAKO — RAG Engine Service
Retrieval-Augmented Generation pipeline.
Query → embed → ChromaDB search → inject chunks → LLM → answer + citations.
Session 1: Stub — wired in Session 8.
"""

from typing import List, Optional
from services.embedder import embedder
from services.chroma_client import chroma_client
from services.ollama_client import ollama_client
from config import get_config


SYSTEM_PROMPT = """You are LAKO, an AI assistant for bank staff.
Answer questions based strictly on the provided document excerpts.
If the answer is not in the provided context, say: 'This information was not found in the knowledge base.'
Always answer in the same language as the question (EN or NL).
Cite the source document and page number for each key claim."""


class RAGEngine:
    """Orchestrates the full RAG pipeline for LAKO."""

    async def query(
        self,
        question: str,
        model: Optional[str] = None,
        top_k: Optional[int] = None,
        use_rag: bool = True,
    ) -> dict:
        """
        Full RAG pipeline:
        1. Embed the user question
        2. Similarity search in ChromaDB (top_k chunks)
        3. Filter by similarity_threshold
        4. Build augmented prompt: system + chunks + question
        5. Call LLM (streaming or non-streaming)
        6. Return answer + source citations

        Returns dict: {answer, sources, model, rag_used}
        TODO (Session 8): implement full pipeline.
        """
        config = get_config()
        effective_model = model or config["primary_model"]
        effective_top_k = top_k or config["top_k"]

        if not use_rag:
            # Direct LLM call — no retrieval
            raise NotImplementedError("RAGEngine.query(use_rag=False) — Session 8")

        # Step 1: embed question
        # query_embedding = await embedder.embed_query(question)

        # Step 2: search ChromaDB
        # chunks = chroma_client.similarity_search(query_embedding, top_k=effective_top_k, ...)

        # Step 3: filter by threshold
        # filtered = [c for c in chunks if c["score"] >= config["similarity_threshold"]]

        # Step 4: build prompt
        # prompt = self._build_prompt(question, filtered)

        # Step 5: call LLM
        # answer = await ollama_client.chat(prompt, model=effective_model, system=SYSTEM_PROMPT)

        # Step 6: return
        raise NotImplementedError("RAGEngine.query() — Session 8")

    def _build_prompt(self, question: str, chunks: List[dict]) -> str:
        """
        Assemble the augmented prompt:
        [CONTEXT]\n<chunks>\n[QUESTION]\n<question>
        TODO (Session 8): implement.
        """
        raise NotImplementedError("RAGEngine._build_prompt() — Session 8")


# Singleton instance
rag_engine = RAGEngine()

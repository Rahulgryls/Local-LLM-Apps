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
        2. Similarity search in ChromaDB (top_k chunks, filtered by threshold)
        3. Build augmented prompt: system + chunks + question
        4. Call LLM (non-streaming)
        5. Return answer + source citations

        Returns dict: {answer, sources, model, rag_used}
        """
        config = get_config()
        effective_model = model or config["primary_model"]
        effective_top_k = top_k or config["top_k"]

        if not use_rag:
            answer = await ollama_client.chat(
                question, model=effective_model, system=SYSTEM_PROMPT
            )
            return {
                "answer": answer,
                "sources": [],
                "model": effective_model,
                "rag_used": False,
            }

        # Step 1: embed question
        query_embedding = await embedder.embed_query(question)

        # Step 2: search ChromaDB (similarity_search already filters by threshold)
        chunks = chroma_client.similarity_search(
            query_embedding,
            top_k=effective_top_k,
            threshold=config["similarity_threshold"],
        )

        # Step 3: no relevant chunks found
        if not chunks:
            return {
                "answer": "This information was not found in the knowledge base.",
                "sources": [],
                "model": effective_model,
                "rag_used": True,
            }

        # Step 4: build augmented prompt
        prompt = self._build_prompt(question, chunks)

        # Step 5: call LLM
        answer = await ollama_client.chat(
            prompt, model=effective_model, system=SYSTEM_PROMPT
        )

        # Step 6: format sources
        sources = [
            {
                "filename":   c["metadata"]["filename"],
                "page":       c["metadata"]["page"],
                "chunk_type": c["metadata"]["chunk_type"],
                "score":      c["score"],
                "content":    c["document"],
            }
            for c in chunks
        ]

        return {
            "answer":   answer,
            "sources":  sources,
            "model":    effective_model,
            "rag_used": True,
        }

    def _build_prompt(self, question: str, chunks: List[dict]) -> str:
        """
        Assemble the augmented prompt:
        [CONTEXT]
        [Source N: filename | Page P | Type: T]
        <chunk text>
        ...
        [QUESTION]
        <question>
        """
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            meta = chunk["metadata"]
            context_parts.append(
                f"[Source {i}: {meta['filename']} | Page {meta['page']} | Type: {meta['chunk_type']}]\n"
                f"{chunk['document']}"
            )
        context = "\n\n".join(context_parts)
        return f"[CONTEXT]\n{context}\n\n[QUESTION]\n{question}"


# Singleton instance
rag_engine = RAGEngine()

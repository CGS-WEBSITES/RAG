import logging
from typing import Any

import requests

from api.config import Config
from api.services.search_service import semantic_search

logger = logging.getLogger(__name__)


MAX_CHUNK_LENGTH = 300  # Truncar chunks longos para reduzir tokens do prompt
RELEVANCE_THRESHOLD = 1.0  # Ignorar chunks com distância > este valor


def _filter_chunks(chunks: list[dict]) -> list[dict]:
    """Remove chunks de baixa relevância e trunca texto longo."""
    return [c for c in chunks if c["distance"] < RELEVANCE_THRESHOLD]


def _build_sources(chunks: list[dict]) -> list[dict]:
    """Formata chunks como lista de sources para a resposta."""
    return [
        {
            "id": chunk["id"],
            "title": chunk["title"],
            "chunk": chunk["chunk"],
            "distance": round(float(chunk["distance"]), 4),
        }
        for chunk in chunks
    ]


def generate_rag_response(
    question: str,
    max_chunks: int = 5,
    model: str | None = None,
    source: str | None = None,
    exclude_sources: list[str] | None = None,
) -> dict[str, Any]:
    model = model or Config.LLM_MODEL

    chunks = semantic_search(
        question,
        limit=max_chunks,
        source=source,
        exclude_sources=exclude_sources,
    )
    chunks = _filter_chunks(chunks)

    if not chunks:
        return {
            "question": question,
            "answer": "No relevant documents found in the knowledge base.",
            "sources": [],
            "model": model,
        }

    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        text = chunk["chunk"]
        if len(text) > MAX_CHUNK_LENGTH:
            text = text[:MAX_CHUNK_LENGTH] + "..."
        context_parts.append(f"[Document {i} - {chunk['title']}]:\n{text}")

    context = "\n\n".join(context_parts)

    prompt = (
        "You are a helpful assistant that answers questions based ONLY on the "
        "documents provided below.\n\n"
        "INSTRUCTIONS:\n"
        "1. Use ONLY information from the provided documents to answer\n"
        "2. If the information is in the documents, provide a clear and complete answer\n"
        "3. Cite relevant documents when appropriate (e.g., 'According to Document 2...')\n"
        "4. If the information is NOT in the documents, respond with EXACTLY: "
        "'I could not find information about this in the available documents.'\n\n"
        f"DOCUMENTS:\n{context}\n\n"
        f"QUESTION: {question}\n\n"
        "ANSWER:"
    )

    try:
        response = requests.post(
            f"{Config.OLLAMA_HOST}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "num_predict": 512,
                },
            },
            timeout=300,  # 5 minutos para evitar timeout em máquinas lentas
        )
        response.raise_for_status()
    except requests.ConnectionError:
        logger.error("Ollama not accessible at %s", Config.OLLAMA_HOST)
        raise ConnectionError(
            f"Ollama not accessible at {Config.OLLAMA_HOST}. "
            "Please check if the container is running."
        )
    except requests.Timeout:
        logger.error("Timeout calling LLM")
        raise RuntimeError("Timeout generating response. Please try again.")

    data = response.json()

    if "error" in data:
        logger.error("Ollama error: %s", data["error"])
        raise RuntimeError(f"Ollama error: {data['error']}")

    answer = data.get("response", "No response from model.").strip()
    sources = _build_sources(chunks)

    logger.info(
        "RAG completed: question='%s', sources=%d, model=%s, source=%s",
        question[:50],
        len(sources),
        model,
        source or "all",
    )

    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "model": model,
    }

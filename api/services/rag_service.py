import logging
from typing import Any

import requests

from api.config import Config
from api.services.search_service import semantic_search

logger = logging.getLogger(__name__)


def generate_rag_response(
    question: str,
    max_chunks: int = 5,
    model: str | None = None,
) -> dict[str, Any]:
    model = model or Config.LLM_MODEL

    chunks = semantic_search(question, limit=max_chunks)

    if not chunks:
        return {
            "question": question,
            "answer": "No relevant documents found in the knowledge base.",
            "sources": [],
            "model": model,
        }

    # Build numbered context
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        context_parts.append(f"[Document {i} - {chunk['title']}]:\n{chunk['chunk']}")

    context = "\n\n".join(context_parts)

    # Improved prompt for better responses
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
                },
            },
            timeout=120,
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

    sources = [
        {
            "id": chunk["id"],
            "title": chunk["title"],
            "chunk": chunk["chunk"],
            "distance": round(chunk["distance"], 4),
        }
        for chunk in chunks
    ]

    logger.info(
        "RAG completed: question='%s', sources=%d, model=%s",
        question[:50],
        len(sources),
        model,
    )

    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "model": model,
    }

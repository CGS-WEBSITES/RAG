import logging
from typing import Any

from openai import OpenAI

from api.config import Config
from api.services.search_service import semantic_search

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes de otimização
# ---------------------------------------------------------------------------
MAX_CHUNK_LENGTH = 500  # Truncar chunks longos para reduzir tokens do prompt
RELEVANCE_THRESHOLD = 1.5  # Ignorar chunks com distância > este valor

_client = None


def _get_client() -> OpenAI:
    """Lazy singleton do client OpenAI."""
    global _client
    if _client is None:
        if not Config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY não configurada no .env")
        _client = OpenAI(api_key=Config.OPENAI_API_KEY)
    return _client


def _filter_chunks(chunks: list[dict]) -> list[dict]:
    """Remove chunks de baixa relevância."""
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

    system_prompt = (
        "You are a helpful assistant that answers questions based on the "
        "documents provided. Follow these rules:\n"
        "1. Be concise and direct. Cite document numbers when relevant.\n"
        "2. Synthesize information from the documents even if they don't "
        "directly answer the question — extract useful insights when possible.\n"
        "3. Only say you could not find information if the documents are truly "
        "unrelated to the question.\n"
        "4. Always respond in the same language as the question. "
        "If the question is in Portuguese, respond in Portuguese. "
        "If the question is in English, respond in English."
    )

    user_prompt = f"DOCUMENTS:\n{context}\n\n" f"QUESTION: {question}"

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            top_p=0.9,
            max_tokens=1024,
        )
    except Exception as e:
        error_msg = str(e)
        logger.error("OpenAI API error: %s", error_msg)

        if "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
            raise ConnectionError(
                "OpenAI API key inválida ou não configurada. "
                "Verifique OPENAI_API_KEY no .env"
            )

        raise RuntimeError(f"Erro ao gerar resposta via OpenAI: {error_msg}")

    answer = response.choices[0].message.content.strip()
    sources = _build_sources(chunks)

    logger.info(
        "RAG completed: question='%s', sources=%d, model=%s, source=%s, "
        "tokens_in=%d, tokens_out=%d",
        question[:50],
        len(sources),
        model,
        source or "all",
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
    )

    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "model": model,
    }

import logging
from typing import Any

from openai import OpenAI

from api.config import Config
from api.services.search_service import semantic_search

logger = logging.getLogger(__name__)

MAX_CHUNK_LENGTH = 300
RELEVANCE_THRESHOLD = 1.0

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not Config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY não configurada no .env")
        _client = OpenAI(api_key=Config.OPENAI_API_KEY)
    return _client


def _filter_chunks(chunks: list[dict]) -> list[dict]:
    return [c for c in chunks if c["distance"] < RELEVANCE_THRESHOLD]


def _build_sources(chunks: list[dict]) -> list[dict]:
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
        "You are a helpful assistant that answers questions based ONLY on the "
        "documents provided. Be concise and direct. Cite document numbers when "
        "relevant. If the answer is not in the documents, say: "
        "'I could not find this information in the available documents.'"
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
            temperature=0.3,
            top_p=0.9,
            max_tokens=512,
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

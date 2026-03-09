import logging
from typing import Any

import requests
from openai import OpenAI

from api.config import Config
from api.services.search_service import semantic_search

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes de otimização
# ---------------------------------------------------------------------------
MAX_CHUNK_LENGTH = 500
RELEVANCE_THRESHOLD = 1.5

_openai_client = None


def _get_openai_client() -> OpenAI:
    """Lazy singleton do client OpenAI."""
    global _openai_client
    if _openai_client is None:
        if not Config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY não configurada no .env")
        _openai_client = OpenAI(api_key=Config.OPENAI_API_KEY)
    return _openai_client


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


# ---------------------------------------------------------------------------
# LLM providers
# ---------------------------------------------------------------------------


def _openai_generate(model: str, system_prompt: str, user_prompt: str) -> dict:
    """Gera resposta via OpenAI API."""
    client = _get_openai_client()
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
    return {
        "answer": response.choices[0].message.content.strip(),
        "tokens_in": response.usage.prompt_tokens,
        "tokens_out": response.usage.completion_tokens,
    }


def _ollama_generate(model: str, system_prompt: str, user_prompt: str) -> dict:
    """Gera resposta via Ollama local."""
    prompt = f"{system_prompt}\n\n{user_prompt}"

    try:
        response = requests.post(
            f"{Config.OLLAMA_HOST.rstrip('/')}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "num_predict": 1024,
                    "num_ctx": 4096,
                },
            },
            timeout=300,
        )
        response.raise_for_status()
    except requests.ConnectionError:
        raise ConnectionError(
            f"Ollama indisponível em {Config.OLLAMA_HOST}. "
            "Verifique se o container está rodando."
        )
    except requests.Timeout:
        raise RuntimeError("Timeout gerando resposta. Tente novamente.")

    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Ollama error: {data['error']}")

    return {
        "answer": data.get("response", "No response from model.").strip(),
        "tokens_in": data.get("prompt_eval_count", 0),
        "tokens_out": data.get("eval_count", 0),
    }


# ---------------------------------------------------------------------------
# RAG principal
# ---------------------------------------------------------------------------


def generate_rag_response(
    question: str,
    max_chunks: int = 5,
    model: str | None = None,
    source: str | None = None,
    exclude_sources: list[str] | None = None,
) -> dict[str, Any]:
    model = model or Config.get_llm_model()

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
        if Config.is_openai():
            result = _openai_generate(model, system_prompt, user_prompt)
        else:
            result = _ollama_generate(model, system_prompt, user_prompt)
    except (ConnectionError, RuntimeError):
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error("LLM API error: %s", error_msg)

        if "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
            raise ConnectionError(
                "OpenAI API key inválida ou não configurada. "
                "Verifique OPENAI_API_KEY no .env"
            )

        raise RuntimeError(
            f"Erro ao gerar resposta via {Config.LLM_PROVIDER}: {error_msg}"
        )

    sources = _build_sources(chunks)

    logger.info(
        "RAG completed: provider=%s, question='%s', sources=%d, model=%s, source=%s, "
        "tokens_in=%d, tokens_out=%d",
        Config.LLM_PROVIDER,
        question[:50],
        len(sources),
        model,
        source or "all",
        result["tokens_in"],
        result["tokens_out"],
    )

    return {
        "question": question,
        "answer": result["answer"],
        "sources": sources,
        "model": model,
    }

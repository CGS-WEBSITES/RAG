import logging
import re
from typing import Any

import requests
from openai import OpenAI

from api.config import Config
from api.services.search_service import semantic_search, get_all_by_source

logger = logging.getLogger(__name__)

MAX_CHUNK_LENGTH = 500
RELEVANCE_THRESHOLD = 1.5

_openai_client = None


def _get_openai_client() -> OpenAI:
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


def _sanitize_text(text: str) -> str:
    """Remove dados sensíveis do texto antes de enviar ao LLM."""
    # Emails
    text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL]", text)

    # IPs
    text = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[IP]", text)

    # Order IDs (Crowdox, etc)
    text = re.sub(r"(?:Order\s*ID\s*#?\s*|#)\d{5,}", "[ORDER_ID]", text)

    # Endereços completos (linhas com CEP/postal code)
    text = re.sub(r"\b[A-Z]{1,2}\d{1,2}\s?\d[A-Z]{2}\b", "[POSTAL_CODE]", text)  # UK
    text = re.sub(r"\b\d{5}[-]?\d{3}\b", "[CEP]", text)  # Brasil

    # Telefones
    text = re.sub(r"[\+]?\d[\d\s\-\(\)]{8,}\d", "[PHONE]", text)

    # Nomes próprios após saudações comuns
    text = re.sub(
        r"(?:Hi|Hello|Dear|Thanks|Regards|Obrigado|Olá|Prezado)\s*,?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
        lambda m: m.group(0).replace(m.group(1), "[NAME]"),
        text,
    )

    text = re.sub(
        r"raised by\s+[A-Za-z\s]+\s*\([^)]*\)",
        "raised by [REDACTED]",
        text,
    )

    text = re.sub(
        r"raised by\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*",
        "raised by [REDACTED]",
        text,
    )

    text = re.sub(
        r"(?:Em|On)\s+\d{4}-\d{2}-\d{2}.*?escreveu:", "[PREVIOUS_EMAIL]", text
    )

    return text


def _openai_generate(model: str, system_prompt: str, user_prompt: str) -> dict:
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
    try:
        response = requests.post(
            f"{Config.OLLAMA_HOST.rstrip('/')}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
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
            "Verifique se o container está rodando com --profile ollama."
        )
    except requests.Timeout:
        raise RuntimeError("Timeout gerando resposta. Tente novamente.")

    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Ollama error: {data['error']}")

    message = data.get("message", {})
    return {
        "answer": message.get("content", "No response from model.").strip(),
        "tokens_in": data.get("prompt_eval_count", 0),
        "tokens_out": data.get("eval_count", 0),
    }


def generate_rag_response(
    question: str,
    max_chunks: int = 3,
    model: str | None = None,
    source: str | None = None,
    exclude_sources: list[str] | None = None,
) -> dict[str, Any]:
    if Config.is_openai_llm():
        model = model or Config.get_llm_model()
    else:
        model = Config.get_llm_model()

    ticket_chunks = semantic_search(
        question,
        limit=max_chunks,
        source="tickets",
    )
    ticket_chunks = _filter_chunks(ticket_chunks)

    logistics_chunks = semantic_search(
        question,
        limit=2,
        source="logistics",
    )
    logistics_chunks = _filter_chunks(logistics_chunks)

    voice_tone_docs = get_all_by_source("voice_tone")

    all_source_chunks = ticket_chunks + logistics_chunks

    if not all_source_chunks:
        return {
            "question": question,
            "answer": "No relevant documents found in the knowledge base.",
            "sources": [],
            "model": model,
        }

    voice_tone_text = "\n".join(
        f"- {doc['title']}: {doc['content']}" for doc in voice_tone_docs
    )

    context_parts = []
    for i, chunk in enumerate(ticket_chunks, 1):
        text = _sanitize_text(chunk["chunk"])
        if len(text) > MAX_CHUNK_LENGTH:
            text = text[:MAX_CHUNK_LENGTH] + "..."
        context_parts.append(f"[Ticket {i} - {chunk['title']}]:\n{text}")

    for i, chunk in enumerate(logistics_chunks, 1):
        text = chunk["chunk"]
        if len(text) > MAX_CHUNK_LENGTH:
            text = text[:MAX_CHUNK_LENGTH] + "..."
        context_parts.append(f"[Logistics {i} - {chunk['title']}]:\n{text}")

    context = "\n\n".join(context_parts)

    system_prompt = (
        "You are a customer support assistant for Creative Games Studio (CGS), "
        "a board game company. Follow these rules strictly:\n\n"
        "VOICE TONE GUIDELINES (always follow this tone):\n"
        f"{voice_tone_text}\n\n"
        "RULES:\n"
        "1. Answer based on the tickets and logistics documents provided.\n"
        "2. Use the voice tone guidelines to shape HOW you respond.\n"
        "3. Be concise and helpful. Cite ticket or logistics document numbers.\n"
        "4. Synthesize information even if documents don't directly answer.\n"
        "5. NEVER include personal data: names, emails, addresses, order IDs.\n"
        "6. Always respond in the same language as the question.\n"
        "7. If no relevant info is found, politely say so."
    )

    user_prompt = f"DOCUMENTS:\n{context}\n\n" f"QUESTION: {question}"

    try:
        if Config.is_openai_llm():
            result = _openai_generate(model, system_prompt, user_prompt)
        else:
            result = _ollama_generate(model, system_prompt, user_prompt)
    except (ConnectionError, RuntimeError):
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error("LLM API error [%s]: %s", Config.LLM_PROVIDER, error_msg)

        if "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
            raise ConnectionError(
                "OpenAI API key inválida ou não configurada. "
                "Verifique OPENAI_API_KEY no .env"
            )

        raise RuntimeError(
            f"Erro ao gerar resposta via {Config.LLM_PROVIDER}: {error_msg}"
        )

    sources = _build_sources(all_source_chunks)

    logger.info(
        "RAG completed: provider=%s, question='%s', tickets=%d, logistics=%d, "
        "voice_tone=%d, model=%s, tokens_in=%d, tokens_out=%d",
        Config.LLM_PROVIDER,
        question[:50],
        len(ticket_chunks),
        len(logistics_chunks),
        len(voice_tone_docs),
        model,
        result["tokens_in"],
        result["tokens_out"],
    )

    return {
        "question": question,
        "answer": result["answer"],
        "sources": sources,
        "model": model,
    }

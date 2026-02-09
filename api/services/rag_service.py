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
            "answer": "Nenhum documento relevante encontrado na base de dados.",
            "sources": [],
            "model": model,
        }

    context = "\n\n".join(f"[{chunk['title']}]: {chunk['chunk']}" for chunk in chunks)

    prompt = (
        "Você é um assistente que responde perguntas baseado apenas "
        "no contexto fornecido. Se a resposta não estiver no contexto, "
        "diga que não tem informação suficiente.\n\n"
        f"Contexto:\n{context}\n\n"
        f"Pergunta: {question}\n\n"
        "Resposta:"
    )

    try:
        response = requests.post(
            f"{Config.OLLAMA_HOST}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
    except requests.ConnectionError:
        logger.error("Ollama não acessível em %s", Config.OLLAMA_HOST)
        raise ConnectionError(
            f"Ollama não acessível em {Config.OLLAMA_HOST}. "
            "Verifique se o container está rodando."
        )
    except requests.Timeout:
        logger.error("Timeout ao chamar o LLM")
        raise RuntimeError("Timeout ao gerar resposta. Tente novamente.")

    data = response.json()

    if "error" in data:
        logger.error("Erro do Ollama: %s", data["error"])
        raise RuntimeError(f"Erro do Ollama: {data['error']}")

    answer = data.get("response", "Sem resposta do modelo.")

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
        "RAG concluído: question='%s', sources=%d, model=%s",
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

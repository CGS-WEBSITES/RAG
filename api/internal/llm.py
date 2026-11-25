"""Cliente da OpenAI e embeddings."""

import logging

from openai import OpenAI

from api.config import Config

logger = logging.getLogger(__name__)
_client: OpenAI | None = None


def openai_client() -> OpenAI:
    global _client
    if _client is None:
        if not Config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY não configurada")
        _client = OpenAI(api_key=Config.OPENAI_API_KEY, timeout=90, max_retries=2)
    return _client


def embed(texts: list[str]) -> list[list[float]]:
    response = openai_client().embeddings.create(
        model=Config.EMBEDDING_MODEL,
        input=[t[:8000] for t in texts],
        dimensions=768,
    )
    return [item.embedding for item in response.data]


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in values) + "]"


def query_vector(query: str) -> str | None:
    """None quando a OpenAI está fora: a busca segue só por texto."""
    try:
        return vector_literal(embed([query])[0])
    except Exception as e:
        logger.warning("Busca sem vetor (embedding indisponível): %s", type(e).__name__)
        return None


def snippet(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " […]"

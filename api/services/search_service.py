import logging
from functools import lru_cache
from typing import Any

from openai import OpenAI

from api.config import Config
from api.database import get_cursor

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> OpenAI:
    """Lazy singleton do client OpenAI."""
    global _client
    if _client is None:
        if not Config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY não configurada no .env")
        _client = OpenAI(api_key=Config.OPENAI_API_KEY)
    return _client


def _openai_embed(text: str) -> list[float]:
    """Gera embedding via OpenAI API."""
    client = _get_client()

    try:
        response = client.embeddings.create(
            model=Config.EMBEDDING_MODEL,
            input=text,
            dimensions=Config.EMBEDDING_DIMENSIONS,
        )
    except Exception as e:
        raise RuntimeError(f"Erro ao gerar embedding via OpenAI: {e}") from e

    embedding = response.data[0].embedding

    if not isinstance(embedding, list) or not embedding:
        raise RuntimeError(f"Embedding inválido retornado: {response}")

    return embedding


@lru_cache(maxsize=256)
def _openai_embed_cached(text: str) -> tuple[float, ...]:
    """Cache embeddings para queries repetidas."""
    return tuple(_openai_embed(text))


def semantic_search(
    query: str,
    limit: int = 5,
    max_distance: float = 1.5,
    source: str | None = None,
    exclude_sources: list[str] | None = None,
) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []

    limit = max(1, min(int(limit), 20))

    # Usa cache para evitar re-embeddings de queries repetidas
    query_embedding = list(_openai_embed_cached(query.lower()))
    vec_literal = "[" + ",".join(f"{x:.8f}" for x in query_embedding) + "]"

    # Monta filtros de source
    source_filter = ""
    params: list = [vec_literal]

    if source:
        source_filter = "AND doc.metadata->>'source' = %s"
        params.append(source)
    elif exclude_sources:
        placeholders = ", ".join(["%s"] * len(exclude_sources))
        source_filter = (
            f"AND (doc.metadata->>'source' IS NULL "
            f"OR doc.metadata->>'source' NOT IN ({placeholders}))"
        )
        params.extend(exclude_sources)

    params.append(limit)
    params.append(max_distance)

    # CTE calcula distância uma única vez
    sql = f"""
        WITH ranked AS (
            SELECT
                doc.id,
                doc.title,
                emb.chunk,
                emb.embedding <=> (%s)::vector AS distance
            FROM public.documents_embeddings_store emb
            JOIN public.documents doc ON doc.id = emb.id
            WHERE 1=1
            {source_filter}
            ORDER BY distance
            LIMIT %s
        )
        SELECT * FROM ranked
        WHERE distance <= %s
        ORDER BY distance
    """

    with get_cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {
            "id": row["id"],
            "title": row["title"],
            "chunk": row["chunk"],
            "distance": round(float(row["distance"]), 4),
        }
        for row in rows
    ]

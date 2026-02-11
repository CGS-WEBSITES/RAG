import logging
from typing import Any

import requests

from api.config import Config
from api.database import get_cursor

logger = logging.getLogger(__name__)


def _ollama_embed(text: str) -> list[float]:
    url = f"{Config.OLLAMA_HOST.rstrip('/')}/api/embeddings"
    payload = {"model": Config.EMBEDDING_MODEL, "prompt": text}

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Ollama indisponível em {Config.OLLAMA_HOST}: {e}") from e

    data = resp.json()
    embedding = data.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise RuntimeError(f"Embedding inválido retornado: {data}")

    return [float(x) for x in embedding]


def semantic_search(
    query: str, limit: int = 5, max_distance: float = 1.5
) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []

    limit = max(1, min(int(limit), 20))

    query_embedding = _ollama_embed(query)
    vec_literal = "[" + ",".join(f"{x:.8f}" for x in query_embedding) + "]"

    sql = """
        SELECT
            doc.id,
            doc.title,
            emb.chunk,
            emb.embedding <=> (%s)::vector AS distance
        FROM public.documents_embeddings_store emb
        JOIN public.documents doc ON doc.id = emb.id
        WHERE emb.embedding <=> (%s)::vector <= %s
        ORDER BY distance
        LIMIT %s
    """

    with get_cursor() as cur:
        cur.execute(sql, (vec_literal, vec_literal, max_distance, limit))
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

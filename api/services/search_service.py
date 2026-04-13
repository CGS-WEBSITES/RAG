import logging
from functools import lru_cache
from typing import Any
from openai import OpenAI
from api.config import Config
from api.database import get_cursor

logger = logging.getLogger(__name__)
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not Config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY não configurada no .env")
        _client = OpenAI(api_key=Config.OPENAI_API_KEY)
    return _client


def _openai_embed(text: str) -> list[float]:
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
def _embed_cached(text: str) -> tuple[float, ...]:
    return tuple(_openai_embed(text))


def get_all_by_source(source: str) -> list[dict[str, Any]]:
    sql = """
        SELECT id, title, content
        FROM public.documents
        WHERE metadata->>'source' = %s
        ORDER BY id
    """
    with get_cursor() as cur:
        cur.execute(sql, (source,))
        rows = cur.fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
        }
        for row in rows
    ]


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
    query_embedding = list(_embed_cached(query.lower()))
    vec_literal = "[" + ",".join(f"{x:.8f}" for x in query_embedding) + "]"
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
    sql = f"""
        WITH ranked AS (
            SELECT
                doc.id,
                doc.title,
                emb.chunk,
                emb.embedding <=> (%s)::vector AS distance
            FROM public.documents_embedding_store emb
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


def get_logistics_by_project_region(project: str, region: str) -> list[dict]:
    region_aliases = {
        "brazil": "brasil",
        "brasilien": "brasil",
        "eua": "eua",
        "usa": "eua",
        "us": "eua",
        "europe": "europa",
        "europa": "europa",
        "asia": "ásia",
        "oceania": "oceania",
        "rest of world": "resto do mundo",
    }
    region_normalized = region_aliases.get(region.lower(), region.lower())

    sql = """
        SELECT id, title, content AS chunk
        FROM public.documents
        WHERE metadata->>'source' = 'logistics'
          AND title ILIKE %s
          AND title ILIKE %s
        LIMIT 1
    """
    with get_cursor() as cur:
        cur.execute(sql, (f"%{project}%", f"%{region_normalized}%"))
        row = cur.fetchone()

    if row:
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "chunk": row["chunk"],
                "distance": 0.0,
            }
        ]

    # Fallback: search only by project
    sql_fallback = """
        SELECT id, title, content AS chunk
        FROM public.documents
        WHERE metadata->>'source' = 'logistics'
          AND title ILIKE %s
        LIMIT 1
    """
    with get_cursor() as cur:
        cur.execute(sql_fallback, (f"%{project}%",))
        row = cur.fetchone()

    if row:
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "chunk": row["chunk"],
                "distance": 0.0,
            }
        ]

    return []


def search_manual_segments(query: str, project: str, limit: int = 5) -> list[dict]:
    query = (query or "").strip()
    if not query or not project:
        return []

    limit = max(1, min(int(limit), 10))
    query_embedding = list(_embed_cached(query.lower()))
    vec_literal = "[" + ",".join(f"{x:.8f}" for x in query_embedding) + "]"

    sql = """
        WITH ranked AS (
            SELECT
                ms.id,
                ms.project,
                ms.page_number,
                ms.section_title,
                emb.chunk,
                emb.embedding <=> (%s)::vector AS distance
            FROM public.manual_segments_embedding_store emb
            JOIN public.manual_segments ms ON ms.id = emb.id
            WHERE ms.project = %s
            ORDER BY distance
            LIMIT %s
        )
        SELECT * FROM ranked
        WHERE distance <= 1.2
        ORDER BY distance
    """
    with get_cursor() as cur:
        cur.execute(sql, (vec_literal, project, limit))
        rows = cur.fetchall()

    return [
        {
            "id": row["id"],
            "project": row["project"],
            "page_number": row["page_number"],
            "section_title": row["section_title"],
            "chunk": row["chunk"],
            "distance": round(float(row["distance"]), 4),
        }
        for row in rows
    ]

import logging
from functools import lru_cache
from typing import Any
import re
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
                ms.image_path,
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
        rows = list(cur.fetchall())

        if len(rows) < limit:
            terms = [
                term
                for term in re.findall(r"[A-Za-zÀ-ÿ0-9-]{4,}", query.lower())
                if term not in {"como", "faco", "faço", "para", "sobre", "qual", "quais", "what", "which", "with", "that", "this", "does"}
            ]
            if terms:
                expansions = {
                    "ataque": ["attack"],
                    "atacar": ["attack"],
                    "corpo": ["melee"],
                    "dano": ["damage"],
                    "defesa": ["defense"],
                    "dado": ["dice", "die"],
                    "dados": ["dice"],
                    "cubo": ["cube"],
                    "cubos": ["cube"],
                    "amarelo": ["yellow"],
                    "vermelho": ["red"],
                    "azul": ["blue"],
                    "verde": ["green"],
                    "contra-ataque": ["counterattack", "counter", "fumble"],
                    "contra": ["counterattack", "counter", "fumble"],
                }
                expanded_terms = []
                for term in terms:
                    expanded_terms.append(term)
                    expanded_terms.extend(expansions.get(term, []))
                terms = list(dict.fromkeys(expanded_terms))
                clauses = " OR ".join(["LOWER(content) LIKE %s"] * len(terms))
                text_sql = f"""
                    SELECT
                        id,
                        project,
                        page_number,
                        section_title,
                        image_path,
                        content AS chunk,
                        0.0 AS distance
                    FROM public.manual_segments
                    WHERE project = %s
                      AND ({clauses})
                    ORDER BY page_number NULLS LAST, id
                    LIMIT %s
                """
                seen_ids = {row["id"] for row in rows}
                params = [project, *[f"%{term}%" for term in terms], limit]
                cur.execute(text_sql, params)
                for row in cur.fetchall():
                    if row["id"] not in seen_ids:
                        rows.append(row)
                        seen_ids.add(row["id"])
                    if len(rows) >= limit:
                        break

    return [
        {
            "id": row["id"],
            "project": row["project"],
            "page_number": row["page_number"],
            "section_title": row["section_title"],
            "image_path": row["image_path"],
            "chunk": row["chunk"],
            "distance": round(float(row["distance"]), 4),
        }
        for row in rows
    ]

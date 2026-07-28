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
        "brazil": ["brasil", "brazil"],
        "brasil": ["brasil", "brazil"],
        "brasilien": ["brasil", "brazil"],
        "canada": ["canada"],
        "eua": ["eua", "usa", "united states"],
        "usa": ["eua", "usa", "united states"],
        "us": ["eua", "usa", "united states"],
        "europe": ["europa", "europe"],
        "europa": ["europa", "europe"],
        "asia": ["asia"],
        "australia": ["australia", "oceania"],
        "uk": ["uk", "united kingdom"],
        "united kingdom": ["uk", "united kingdom"],
        "oceania": ["oceania", "australia"],
        "rest of world": ["resto do mundo", "rest of world", "rest of the world"],
        "rest of the world": ["resto do mundo", "rest of world", "rest of the world"],
    }
    region_terms = region_aliases.get(region.lower(), [region.lower()])
    region_filter = " OR ".join(["title ILIKE %s"] * len(region_terms))

    sql = f"""
        SELECT id, title, content AS chunk
        FROM public.documents
        WHERE metadata->>'source' = 'logistics'
          AND title ILIKE %s
          AND ({region_filter})
        LIMIT 1
    """
    with get_cursor() as cur:
        cur.execute(sql, [f"%{project}%", *[f"%{term}%" for term in region_terms]])
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
        WHERE distance <= 0.85
        ORDER BY distance
    """
    with get_cursor() as cur:
        cur.execute(sql, (vec_literal, project, limit))
        rows = list(cur.fetchall())

        if len(rows) < limit:
            terms = [
                term
                for term in re.findall(r"[A-Za-zÀ-ÿ0-9-]{3,}", query.lower())
                if term not in {"como", "faco", "faço", "para", "sobre", "qual", "quais", "what", "which", "with", "that", "this", "does"}
            ]
            if terms:
                expansions = {
                    "ataque": ["attack"],
                    "atacar": ["attack"],
                    "corpo": ["melee"],
                    "dano": ["damage"],
                    "defesa": ["defense"],
                    "dado": ["dice", "die", "d20"],
                    "dados": ["dice", "die", "d20"],
                    "cubo": ["cube", "action cube", "action cubes", "curse cube", "trauma cube", "wild cube"],
                    "cubos": ["cube", "action cubes", "curse cubes", "trauma cubes", "wild cube"],
                    "trauma": ["trauma cube", "trauma cubes", "trauma"],
                    "curse": ["curse cube", "curse cubes", "curse"],
                    "maldição": ["curse cube", "curse cubes", "curse"],
                    "maldicao": ["curse cube", "curse cubes", "curse"],
                    "acao": ["action cube", "action cubes", "cube action"],
                    "ação": ["action cube", "action cubes", "cube action"],
                    "action": ["action cube", "action cubes", "cube action"],
                    "amarelo": ["yellow", "yellow cube", "melee"],
                    "vermelho": ["red", "red cube", "ranged"],
                    "vermelhos": ["red", "red cube", "ranged"],
                    "azul": ["blue", "blue cube", "wisdom"],
                    "verde": ["green", "green cube", "agility"],
                    "contra-ataque": ["counterattack", "counter", "fumble"],
                    "contra": ["counterattack", "counter", "fumble"],
                    "escuridao": ["darkness"],
                    "escuridão": ["darkness"],
                    "habilidade": ["ability", "skill"],
                    "habilidades": ["abilities", "skills"],
                    "monstro": ["monster"],
                    "monstros": ["monsters"],
                    "iniciativa": ["initiative"],
                    "turno": ["turn"],
                    "turnos": ["turns"],
                    "rodada": ["round"],
                    "rodadas": ["rounds"],
                    "corrupcao": ["corruption"],
                    "corrupção": ["corruption"],
                    "reposicionamento": ["reposition"],
                    "fumble": ["fumble"],
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

    if rows:
        missing_image_pages = {
            (row["project"], row["page_number"])
            for row in rows
            if not row["image_path"] and row["page_number"] is not None
        }
        if missing_image_pages:
            page_filters = " OR ".join(["(project = %s AND page_number = %s)"] * len(missing_image_pages))
            params = []
            for page_project, page_number in missing_image_pages:
                params.extend([page_project, page_number])
            with get_cursor() as cur:
                cur.execute(
                    f"""
                        SELECT project, page_number, image_path
                        FROM public.manual_segments
                        WHERE image_path IS NOT NULL
                          AND image_path <> ''
                          AND ({page_filters})
                        ORDER BY project, page_number, id
                    """,
                    params,
                )
                images_by_page = {}
                for image_row in cur.fetchall():
                    key = (image_row["project"], image_row["page_number"])
                    current = images_by_page.setdefault(key, [])
                    current.extend(
                        img.strip()
                        for img in str(image_row["image_path"]).split(",")
                        if img.strip()
                    )

            for row in rows:
                if row["image_path"] or row["page_number"] is None:
                    continue
                images = images_by_page.get((row["project"], row["page_number"]))
                if images:
                    row["image_path"] = ",".join(dict.fromkeys(images))

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


def search_keywords(query: str, project: str = "Drunagor", limit: int = 3) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []

    limit = max(1, min(int(limit), 10))
    clean_query = query.strip().lower()

    # Extract terms & build expansions for exact keyword matching
    terms = [
        term
        for term in re.findall(r"[A-Za-zÀ-ÿ0-9-]{3,}", clean_query)
        if term not in {"como", "faco", "faço", "para", "sobre", "qual", "quais", "what", "which", "with", "that", "this", "does", "the"}
    ]
    expansions = {
        "ataque": ["attack"],
        "atacar": ["attack"],
        "dano": ["damage"],
        "defesa": ["defense"],
        "dado": ["dice", "die", "d20"],
        "dados": ["dice", "die", "d20"],
        "cubo": ["cube", "action cube", "action cubes", "curse cube", "trauma cube", "wild cube"],
        "cubos": ["cube", "action cubes", "curse cubes", "trauma cubes", "wild cube"],
        "trauma": ["trauma cube", "trauma cubes", "trauma"],
        "curse": ["curse cube", "curse cubes", "curse"],
        "maldição": ["curse cube", "curse cubes", "curse"],
        "maldicao": ["curse cube", "curse cubes", "curse"],
        "acao": ["action cube", "action cubes", "cube action"],
        "ação": ["action cube", "action cubes", "cube action"],
        "action": ["action cube", "action cubes", "cube action"],
        "amarelo": ["yellow", "yellow cube", "melee"],
        "vermelho": ["red", "red cube", "ranged"],
        "vermelhos": ["red", "red cube", "ranged"],
        "azul": ["blue", "blue cube", "wisdom"],
        "verde": ["green", "green cube", "agility"],
        "escuridao": ["darkness"],
        "escuridão": ["darkness"],
        "habilidade": ["ability", "skill"],
        "habilidades": ["abilities", "skills"],
        "monstro": ["monster"],
        "iniciativa": ["initiative"],
        "turno": ["turn"],
        "rodada": ["round"],
        "corrupcao": ["corruption"],
        "corrupção": ["corruption"],
        "contra-ataque": ["counterattack", "counter attack"],
        "reposicionamento": ["reposition"],
    }
    search_candidates = [clean_query]
    for t in terms:
        search_candidates.append(t)
        search_candidates.extend(expansions.get(t, []))
    search_candidates = list(dict.fromkeys(search_candidates))

    exact_sql = """
        SELECT
            k.id,
            k.keyword,
            k.description,
            k.icon,
            0.0 AS distance
        FROM public.keywords k
        WHERE (k.project IS NULL OR k.project = %s)
          AND (
            LOWER(k.keyword) = ANY(%s)
            OR LOWER(k.id) = ANY(%s)
            OR EXISTS (
                SELECT 1 FROM unnest(%s::text[]) term 
                WHERE LOWER(k.keyword) LIKE '%%' || term || '%%'
            )
          )
        ORDER BY LENGTH(k.keyword) ASC
        LIMIT %s
    """

    rows = []
    seen_ids = set()
    with get_cursor() as cur:
        cur.execute(exact_sql, (project, search_candidates, search_candidates, search_candidates, limit))
        exact_rows = list(cur.fetchall())

        for r in exact_rows:
            seen_ids.add(r["id"])
            rows.append({
                "id": r["id"],
                "keyword": r["keyword"],
                "description": r["description"],
                "icon": r["icon"],
                "distance": 0.0,
            })

        if len(rows) < limit:
            query_embedding = list(_embed_cached(clean_query))
            vec_literal = "[" + ",".join(f"{x:.8f}" for x in query_embedding) + "]"
            vector_sql = """
                WITH ranked AS (
                    SELECT
                        k.id,
                        k.keyword,
                        k.description,
                        k.icon,
                        emb.embedding <=> (%s)::vector AS distance
                    FROM public.keywords_embedding_store emb
                    JOIN public.keywords k ON k.id = emb.id
                    WHERE (k.project IS NULL OR k.project = %s)
                    ORDER BY distance
                    LIMIT %s
                )
                SELECT * FROM ranked
                WHERE distance <= 1.3
                ORDER BY distance
            """
            cur.execute(vector_sql, (vec_literal, project, limit))
            vec_rows = cur.fetchall()
            for r in vec_rows:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    rows.append({
                        "id": r["id"],
                        "keyword": r["keyword"],
                        "description": r["description"],
                        "icon": r["icon"],
                        "distance": round(float(r["distance"]), 4),
                    })
                if len(rows) >= limit:
                    break

    return rows


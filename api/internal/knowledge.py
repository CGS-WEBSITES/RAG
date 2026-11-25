"""Conhecimento que também pode ser mostrado ao público: manuais, glossário e logística.

Nada aqui lê tickets. É o único módulo de dados que o chat público usa.
"""

import logging

from api.database import get_cursor
from api.internal.llm import query_vector, snippet

logger = logging.getLogger(__name__)
_RRF_K = 60


def search_manual(query: str, project: str, limit: int = 8) -> list[dict]:
    query = (query or "").strip()[:1000]
    if not query:
        return []
    ranked: dict[int, float] = {}
    vec = query_vector(query)
    if vec:
        try:
            with get_cursor() as cur:
                cur.execute(
                    """SELECT ms.id FROM manual_segments_embedding_store e JOIN manual_segments ms ON ms.id = e.id
                       WHERE ms.project = %s ORDER BY e.embedding <=> %s::vector LIMIT 30""",
                    (project, vec),
                )
                ids = list(dict.fromkeys(r["id"] for r in cur.fetchall()))
            for r, i in enumerate(ids, 1):
                ranked[i] = 1 / (_RRF_K + r)
        except Exception as e:
            logger.warning("Vetores do manual indisponíveis: %s", type(e).__name__)
    with get_cursor() as cur:
        cur.execute(
            """WITH tq AS (SELECT replace(plainto_tsquery('english', %s)::text, '&', '|')::tsquery AS q)
               SELECT id FROM manual_segments, tq
               WHERE project = %s AND to_tsvector('english', coalesce(section_title, '') || ' ' || content) @@ tq.q
               ORDER BY ts_rank_cd(to_tsvector('english', coalesce(section_title, '') || ' ' || content), tq.q, 1) DESC
               LIMIT 30""",
            (query, project),
        )
        for r, row in enumerate(cur.fetchall(), 1):
            ranked[row["id"]] = ranked.get(row["id"], 0) + 1 / (_RRF_K + r)
        top = sorted(ranked, key=ranked.get, reverse=True)[:limit]
        if not top:
            return []
        cur.execute(
            """SELECT id, project, page_number, section_title, content, image_path
               FROM manual_segments WHERE id = ANY(%s)""",
            (top,),
        )
        rows = {r["id"]: dict(r) for r in cur.fetchall()}
    return [{**rows[i], "content": snippet(rows[i]["content"], 1800)} for i in top if i in rows]


def search_keywords(query: str, project: str, limit: int = 4) -> list[dict]:
    """Glossário: casa o nome da palavra-chave com os termos da pergunta."""
    terms = [t for t in {w.strip(".,?!()\"'").lower() for w in query.split()} if len(t) > 3]
    if not terms:
        return []
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT keyword, description FROM keywords
                   WHERE (project IS NULL OR project = %s) AND string_to_array(lower(keyword), ' ') && %s::text[]
                   ORDER BY length(keyword) LIMIT %s""",
                (project, terms, limit),
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning("Glossário indisponível: %s", type(e).__name__)
        return []


def list_logistics(project: str | None = None) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, title, content, created_at FROM documents
               WHERE metadata->>'source' = 'logistics' AND title ILIKE %s ORDER BY title LIMIT 60""",
            (f"%{project}%" if project else "%",),
        )
        return [dict(r) for r in cur.fetchall()]

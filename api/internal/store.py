"""Acesso ao banco da base interna: carga, busca híbrida, estatísticas."""

import hashlib
import logging
import uuid
from pathlib import Path

from psycopg2.extras import Json

from api.database import get_cursor
from api.internal.cleaning import clean_message, detect_project, detect_topic
from api.internal.llm import embed, query_vector, snippet, vector_literal

logger = logging.getLogger(__name__)
_SQL = Path(__file__).resolve().parent.parent / "sql" / "internal_tables.sql"
_RRF_K = 60
_CANDIDATES = 40
RECENCY_HALF_LIFE_DAYS = 90
MIN_RECENT = 4
MAX_REVIEW = 2

def ensure_tables() -> None:
    with get_cursor() as cur:
        cur.execute(_SQL.read_text(encoding="utf-8"))


def get_state(key: str) -> str | None:
    with get_cursor() as cur:
        cur.execute("SELECT value FROM internal_state WHERE key = %s", (key,))
        row = cur.fetchone()
        return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO internal_state VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, value),
        )


def get_pet(author: str) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT data FROM pet_state WHERE author = %s", (author,))
        row = cur.fetchone()
        return row["data"] if row else None


def set_pet(author: str, data: dict) -> None:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO pet_state VALUES (%s, %s) ON CONFLICT (author) DO UPDATE SET data = EXCLUDED.data",
            (author, Json(data)),
        )


def content_hash(*parts) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()


def upsert_ticket(cur, t: dict) -> None:
    """Texto novo zera o embedding para ser refeito."""
    cur.execute(
        """
        INSERT INTO support_tickets (id, origin, freshdesk_id, subject, content, project, topic, status,
                                     has_reply, delivery_suspect, blocked, opened_at, content_hash, waiting, last_at, requester)
        VALUES (%(id)s, %(origin)s, %(freshdesk_id)s, %(subject)s, %(content)s, %(project)s, %(topic)s,
                %(status)s, %(has_reply)s, %(delivery_suspect)s, %(blocked)s, %(opened_at)s, %(content_hash)s,
                %(waiting)s, %(last_at)s, %(requester)s)
        ON CONFLICT (id) DO UPDATE SET
            subject = EXCLUDED.subject, content = EXCLUDED.content, project = EXCLUDED.project,
            topic = EXCLUDED.topic, status = EXCLUDED.status, has_reply = EXCLUDED.has_reply,
            delivery_suspect = support_tickets.delivery_suspect OR EXCLUDED.delivery_suspect,
            blocked = EXCLUDED.blocked, waiting = EXCLUDED.waiting, last_at = EXCLUDED.last_at,
            requester = coalesce(EXCLUDED.requester, support_tickets.requester), opened_at = EXCLUDED.opened_at,
            embedding = CASE WHEN support_tickets.content_hash = EXCLUDED.content_hash
                             THEN support_tickets.embedding END,
            content_hash = EXCLUDED.content_hash, updated_at = now()
        """,
        {"waiting": False, "last_at": t["opened_at"], "requester": None, **t},
    )


def embed_pending(batch_size: int = 64) -> int:
    done = 0
    while True:
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, subject, content FROM support_tickets WHERE embedding IS NULL ORDER BY id LIMIT %s",
                (batch_size,),
            )
            rows = cur.fetchall()
        if not rows:
            return done
        vectors = embed([f"{r['subject']}\n{r['content']}" for r in rows])
        with get_cursor() as cur:
            for row, vec in zip(rows, vectors):
                cur.execute(
                    "UPDATE support_tickets SET embedding = %s::vector WHERE id = %s",
                    (vector_literal(vec), row["id"]),
                )
        done += len(rows)
        logger.info("Embeddings: %d", done)


def search_tickets(query: str, project: str | None = None, topic: str | None = None,
                   limit: int = 8) -> list[dict]:
    """Casos confiáveis primeiro, do mais novo ao mais velho; depois até 2 em revisão, sempre
    rotulados. Sem caso confiável recente, completa com o histórico."""
    query = (query or "").strip()[:1000]
    if not query:
        return []
    vec = query_vector(query)
    found = _search_tickets(query, vec, project, topic, None, limit, "origin <> 'historico' AND NOT blocked")
    found.sort(key=lambda t: (t["origin"] == "aprovada", t["opened_at"]), reverse=True)
    if len(found) < MIN_RECENT:
        found += _search_tickets(query, vec, project, topic, None, MIN_RECENT - len(found), "origin = 'historico'")
    return found + _search_tickets(query, vec, project, topic, None, MAX_REVIEW, "blocked")


def _search_tickets(query, vec, project, topic, since, limit, origin_filter) -> list[dict]:
    filters = [f"AND {origin_filter}"]
    params = {"q": query, "n": _CANDIDATES, "k": _RRF_K, "limit": limit, "half": RECENCY_HALF_LIFE_DAYS}
    if project:
        filters.append("AND (project = %(project)s OR project IS NULL)")
        params["project"] = project
    if topic:
        filters.append("AND topic = %(topic)s")
        params["topic"] = topic
    if since:
        filters.append("AND opened_at >= %(since)s::date")
        params["since"] = since
    where = " ".join(filters)
    vector_cte = "SELECT NULL::text AS id, NULL::bigint AS r WHERE FALSE"
    if vec:
        params["vec"] = vec
        vector_cte = f"""SELECT id, row_number() OVER (ORDER BY d) AS r FROM (
            SELECT id, embedding <=> %(vec)s::vector AS d FROM support_tickets
            WHERE embedding IS NOT NULL {where} ORDER BY d LIMIT %(n)s) v"""
    # RRF comprime as notas (1º e 40º diferem ~1,6x), então o peso de recência
    # (1,0 hoje a ~0,4 nos antigos) decide entre casos de relevância parecida.
    sql = f"""
        WITH tq AS (SELECT replace(plainto_tsquery('english', %(q)s)::text, '&', '|')::tsquery AS q),
        vec AS ({vector_cte}),
        txt AS (SELECT id, row_number() OVER (ORDER BY s DESC) AS r FROM (
            SELECT id, ts_rank_cd(tsv, tq.q, 1) AS s FROM support_tickets, tq
            WHERE tsv @@ tq.q {where} ORDER BY s DESC LIMIT %(n)s) t),
        fused AS (SELECT id, sum(1.0 / (%(k)s + r)) AS score
                  FROM (SELECT * FROM vec UNION ALL SELECT * FROM txt) u GROUP BY id)
        SELECT t.id, origin, freshdesk_id, subject, content, project, topic, status, has_reply,
               delivery_suspect, blocked, opened_at
        FROM fused JOIN support_tickets t USING (id)
        ORDER BY score
            * (0.4 + 0.6 * power(0.5, greatest(extract(epoch FROM now() - coalesce(opened_at, now())), 0)
                                        / 86400.0 / %(half)s))
            * CASE WHEN origin = 'aprovada' THEN 1.4 ELSE 1 END
            * CASE WHEN has_reply THEN 1.2 ELSE 0.7 END DESC, t.id
        LIMIT %(limit)s
    """
    with get_cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


_TICKET_COLUMNS = """id, origin, freshdesk_id, subject, content, project, topic, status, has_reply,
    delivery_suspect, blocked, opened_at, waiting, last_at"""


def list_tickets(q: str = "", project: str | None = None, topic: str | None = None, status: str | None = None,
                 days: int = 0, show: str = "", sort: str = "", offset: int = 0, limit: int = 25) -> dict:
    """Tela de tickets. Com texto: busca por significado e palavra; sem texto: os mais novos."""
    q = (q or "").strip()[:300]
    number = q.lstrip("#").removeprefix("fd-")
    where = ["origin <> 'historico'"]
    p: dict = {"limit": limit, "offset": max(0, offset), "k": _RRF_K, "q": q}
    for column, value in (("project", project), ("topic", topic)):
        if value:
            where.append(f"{column} = %({column})s")
            p[column] = value
    if status == "em aberto":
        where.append("status IN ('aberto', 'pendente')")
    elif status:
        where.append("status = %(status)s")
        p["status"] = status
    if days > 0:
        where.append("opened_at > now() - make_interval(days => %(days)s)")
        p["days"] = days
    where += {"exemplos": ["has_reply AND NOT blocked"], "aprovados": ["origin = 'aprovada'"],
              "sem_revisao": ["NOT blocked"], "revisao": ["blocked"], "esperando": ["waiting", "opened_at > now() - interval '120 days'"]}.get(show, [])
    if number.isdigit():
        where.append("freshdesk_id::text LIKE %(number)s")
        p["number"] = f"{number}%"
        q = ""
    conditions = " AND ".join(where)
    columns = _TICKET_COLUMNS.replace("id, origin", "t.id, origin", 1)
    if not q:
        sql = f"""SELECT {columns}, left(content, 260) AS headline, count(*) OVER () AS total
                  FROM support_tickets t WHERE {conditions}
                  ORDER BY {"last_at DESC NULLS LAST" if show == "esperando" else "opened_at DESC"}, t.id DESC LIMIT %(limit)s OFFSET %(offset)s"""
    else:
        vec = query_vector(q)
        vector_cte = "SELECT NULL::text AS id, NULL::bigint AS r WHERE FALSE"
        if vec:
            p["vec"] = vec
            # 0,62 de distância: acima disso o assunto já é outro.
            vector_cte = f"""SELECT id, row_number() OVER (ORDER BY d) AS r FROM (
                SELECT id, embedding <=> %(vec)s::vector AS d FROM support_tickets
                WHERE embedding IS NOT NULL AND {conditions} ORDER BY d LIMIT 80) v WHERE d < 0.62"""
        order = "opened_at DESC" if sort == "recentes" else "score DESC"
        sql = f"""
            WITH tq AS (SELECT websearch_to_tsquery('english', %(q)s) AS q),
            vec AS ({vector_cte}),
            txt AS (SELECT id, row_number() OVER (ORDER BY s DESC) AS r FROM (
                SELECT id, ts_rank_cd(tsv, tq.q, 1) + (subject ILIKE '%%' || %(q)s || '%%')::int AS s
                FROM support_tickets, tq WHERE (tsv @@ tq.q OR subject ILIKE '%%' || %(q)s || '%%') AND {conditions}
                ORDER BY s DESC LIMIT 120) x),
            fused AS (SELECT id, sum(1.0 / (%(k)s + r)) AS score
                      FROM (SELECT * FROM vec UNION ALL SELECT * FROM txt) u GROUP BY id),
            page AS (SELECT {columns}, score * CASE WHEN blocked THEN 0.75 ELSE 1 END AS score, count(*) OVER () AS total FROM fused JOIN support_tickets t USING (id)
                     ORDER BY {order}, id LIMIT %(limit)s OFFSET %(offset)s)
            SELECT page.*, ts_headline('english', content, tq.q,
                       'MaxFragments=1, MaxWords=34, MinWords=18, StartSel=⟦, StopSel=⟧') AS headline
            FROM page, tq ORDER BY {order}, id"""
        sql = sql.replace("SELECT t.id, origin", "SELECT id, origin")
    with get_cursor() as cur:
        cur.execute(sql, p)
        rows = [dict(r) for r in cur.fetchall()]
    return {"rows": rows, "total": rows[0]["total"] if rows else 0}


def count_waiting() -> int:
    with get_cursor() as cur:
        cur.execute("""SELECT count(*) AS n FROM support_tickets
                       WHERE waiting AND origin = 'freshdesk' AND opened_at > now() - interval '120 days'""")
        return cur.fetchone()["n"]


def same_requester(ticket_id: str) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            f"""SELECT {_TICKET_COLUMNS} FROM support_tickets
                WHERE id <> %s AND requester = (SELECT requester FROM support_tickets WHERE id = %s)
                ORDER BY opened_at DESC LIMIT 8""",
            (ticket_id, ticket_id),
        )
        return [dict(r) for r in cur.fetchall()]


def get_ticket(ticket_id: str) -> dict | None:
    ticket_id = str(ticket_id or "").strip().lstrip("#")
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, origin, freshdesk_id, subject, content, project, topic, status, has_reply,
                      delivery_suspect, blocked, opened_at
               FROM support_tickets WHERE id = %s OR id = 'fd-' || %s LIMIT 1""",
            (ticket_id, ticket_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


_GROUPS = {
    "topic": "topic",
    "project": "coalesce(project, 'não identificado')",
    "month": "to_char(opened_at, 'YYYY-MM')",
    "topic_month": "to_char(opened_at, 'YYYY-MM') || ' ' || topic",
    "project_topic": "coalesce(project, 'não identificado') || ' ' || topic",
    "status": "coalesce(status, 'desconhecido')",
}


def ticket_stats(group_by: str = "topic", since: str | None = None, until: str | None = None,
                 project: str | None = None) -> dict:
    group = _GROUPS.get(group_by, "topic")
    sql = f"""SELECT {group} AS grupo, count(*) AS total,
                     count(*) FILTER (WHERE status IN ('aberto', 'pendente')) AS em_aberto
              FROM support_tickets
              WHERE origin = 'freshdesk' AND (%(s)s::date IS NULL OR opened_at >= %(s)s::date)
                AND (%(u)s::date IS NULL OR opened_at < %(u)s::date + 1)
                AND (%(p)s::text IS NULL OR project = %(p)s)
              GROUP BY 1 ORDER BY {"1" if group_by in ("month", "topic_month", "project_topic") else "2 DESC"}"""
    with get_cursor() as cur:
        cur.execute(sql, {"s": since or None, "u": until or None, "p": project or None})
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT max(opened_at)::date::text AS ate FROM support_tickets WHERE origin = 'freshdesk'")
        ate = cur.fetchone()["ate"]
    return {"grupos": rows, "total": sum(r["total"] for r in rows), "dados_ate": ate,
            "observacao": "Exclui spam e notificações automáticas sem resposta."}


def overview() -> dict:
    with get_cursor() as cur:
        cur.execute(
            """SELECT count(*) AS tickets, count(*) FILTER (WHERE origin = 'freshdesk') AS recentes,
                      count(*) FILTER (WHERE origin = 'aprovada') AS aprovadas,
                      count(embedding) AS com_vetor,
                      (max(opened_at) FILTER (WHERE origin = 'freshdesk'))::date::text AS dados_ate
               FROM support_tickets"""
        )
        return {**cur.fetchone(), "sincronizado": get_state("freshdesk_cursor")}


def save_message(**m) -> str:
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO internal_messages (conversation_id, author, question, answer, model, tokens_in, tokens_out,
                                              latency_ms, source_ids, sources, steps, cited)
               VALUES (%(conversation_id)s, %(author)s, %(question)s, %(answer)s, %(model)s, %(tokens_in)s,
                       %(tokens_out)s, %(latency_ms)s, %(source_ids)s, %(sources)s, %(steps)s, %(cited)s)
               RETURNING id::text""",
            {**m, "sources": Json(m["sources"]), "steps": Json(m["steps"])},
        )
        return cur.fetchone()["id"]


def list_conversations(author: str) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT conversation_id AS id, (array_agg(left(question, 160) ORDER BY created_at))[1] AS title,
                      max(created_at) AS at
               FROM internal_messages WHERE author = %s AND NOT hidden AND conversation_id NOT LIKE 't-%%'
               GROUP BY 1 ORDER BY 3 DESC LIMIT 100""",
            (author,),
        )
        return [{**r, "at": r["at"].isoformat()} for r in cur.fetchall()]


def get_conversation(author: str, conversation_id: str) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT id::text, question, answer, sources, steps, cited, approved, feedback FROM internal_messages
               WHERE author = %s AND conversation_id = %s AND NOT hidden ORDER BY created_at""",
            (author, conversation_id),
        )
        return [dict(r) for r in cur.fetchall()]


def hide_conversation(author: str, conversation_id: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE internal_messages SET hidden = TRUE WHERE author = %s AND conversation_id = %s",
            (author, conversation_id),
        )


def set_feedback(author: str, message_id: str, feedback: str | None) -> bool:
    with get_cursor() as cur:
        cur.execute("UPDATE internal_messages SET feedback = %s WHERE id = %s::uuid AND author = %s",
                    (feedback, message_id, author))
        return cur.rowcount > 0


def mark_approved(author: str, message_id: str) -> None:
    with get_cursor() as cur:
        cur.execute("UPDATE internal_messages SET approved = TRUE WHERE id = %s::uuid AND author = %s",
                    (message_id, author))


def approve_reply(question: str, reply: str) -> str:
    """Resposta validada pela equipe vira fonte prioritária."""
    question, reply = clean_message(question)[:6000], clean_message(reply)[:6000]
    content = f"CLIENTE: {question}\n\nEQUIPE: {reply}"
    digest = content_hash(content)
    ticket = {
        # Id pelo conteúdo: aprovar duas vezes não duplica.
        "id": f"ok-{uuid.UUID(digest[:32]).hex[:12]}", "origin": "aprovada", "freshdesk_id": None,
        "subject": snippet(question.replace("\n", " "), 90), "content": content,
        "project": detect_project(content), "topic": detect_topic(question), "status": None,
        "has_reply": True, "delivery_suspect": False, "blocked": False, "opened_at": None, "content_hash": digest,
    }
    with get_cursor() as cur:
        upsert_ticket(cur, ticket)
        cur.execute("UPDATE support_tickets SET opened_at = now() WHERE id = %s", (ticket["id"],))
    try:
        vec = vector_literal(embed([f"{ticket['subject']}\n{content}"])[0])
        with get_cursor() as cur:
            cur.execute("UPDATE support_tickets SET embedding = %s::vector WHERE id = %s", (vec, ticket["id"]))
    except Exception as e:
        logger.warning("Resposta aprovada salva sem embedding: %s", type(e).__name__)
    return ticket["id"]

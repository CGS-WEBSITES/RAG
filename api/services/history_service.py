import logging
from typing import Any

from api.database import get_cursor

logger = logging.getLogger(__name__)


def save_chat(
    session_id: str,
    question: str,
    answer: str,
    category: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    sources_count: int = 0,
    refinement_round: int = 0,
    parent_message_id: str | None = None,
    language: str | None = None,
) -> str:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_history
                (session_id, question, answer, category, model, provider,
                  tokens_in, tokens_out, sources_count,
                  refinement_round, parent_message_id, language)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                session_id,
                question,
                answer,
                category,
                model,
                provider,
                tokens_in,
                tokens_out,
                sources_count,
                refinement_round,
                parent_message_id,
                language,
            ),
        )
        row = cur.fetchone()
        return str(row["id"]) if row else ""


def update_feedback(chat_id: str, feedback: str) -> bool:
    if feedback not in ("up", "down", None):
        return False
    with get_cursor() as cur:
        cur.execute(
            "UPDATE chat_history SET feedback = %s WHERE id = %s",
            (feedback, chat_id),
        )
        return cur.rowcount > 0


def update_satisfaction(chat_id: str, satisfied: bool) -> bool:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE chat_history SET satisfaction = %s WHERE id = %s",
            (satisfied, chat_id),
        )
        return cur.rowcount > 0


def get_history(session_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, question, answer, category, model, feedback,
                   satisfaction, refinement_round, parent_message_id, created_at
            FROM chat_history
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (session_id, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def get_dashboard_stats() -> dict[str, Any]:
    stats = {}

    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as total FROM chat_history")
        stats["total_conversations"] = cur.fetchone()["total"]

        cur.execute(
            "SELECT COUNT(*) as total FROM chat_history "
            "WHERE created_at >= CURRENT_DATE"
        )
        stats["today"] = cur.fetchone()["total"]

        cur.execute(
            "SELECT COUNT(*) as total FROM chat_history "
            "WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'"
        )
        stats["last_7_days"] = cur.fetchone()["total"]

        cur.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN feedback = 'up' THEN 1 ELSE 0 END), 0)   AS positive,
                COALESCE(SUM(CASE WHEN feedback = 'down' THEN 1 ELSE 0 END), 0) AS negative,
                COALESCE(SUM(CASE WHEN feedback IS NULL THEN 1 ELSE 0 END), 0)  AS no_feedback
            FROM chat_history
            """
        )
        row = cur.fetchone()
        stats["feedback"] = {
            "positive": row["positive"],
            "negative": row["negative"],
            "no_feedback": row["no_feedback"],
        }

        cur.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN satisfaction = TRUE  THEN 1 ELSE 0 END), 0) AS satisfied,
                COALESCE(SUM(CASE WHEN satisfaction = FALSE THEN 1 ELSE 0 END), 0) AS unsatisfied,
                COALESCE(SUM(CASE WHEN satisfaction IS NULL THEN 1 ELSE 0 END), 0) AS pending
            FROM chat_history
            """
        )
        row = cur.fetchone()
        stats["satisfaction"] = {
            "satisfied": row["satisfied"],
            "unsatisfied": row["unsatisfied"],
            "pending": row["pending"],
        }

        cur.execute(
            """
            SELECT
                COALESCE(COUNT(*) FILTER (WHERE refinement_round > 0), 0)    AS total_refined,
                COALESCE(ROUND(AVG(refinement_round)
                    FILTER (WHERE refinement_round > 0), 2), 0)              AS avg_rounds
            FROM chat_history
            """
        )
        row = cur.fetchone()
        stats["refinement"] = {
            "total_refined": row["total_refined"],
            "avg_rounds": float(row["avg_rounds"]),
        }

        cur.execute(
            """
            SELECT category, COUNT(*) as total
            FROM chat_history
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY total DESC
            LIMIT 10
            """
        )
        stats["top_categories"] = [
            {"category": row["category"], "count": row["total"]}
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT
                COALESCE(SUM(tokens_in), 0)  AS total_in,
                COALESCE(SUM(tokens_out), 0) AS total_out
            FROM chat_history
            """
        )
        row = cur.fetchone()
        stats["tokens"] = {
            "total_in": row["total_in"],
            "total_out": row["total_out"],
            "total": row["total_in"] + row["total_out"],
        }

        cur.execute(
            """
            SELECT DATE(created_at) AS day, COUNT(*) AS total
            FROM chat_history
            WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY day
            """
        )
        stats["daily"] = [
            {"day": str(row["day"]), "count": row["total"]} for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT ROUND(AVG(tokens_in + tokens_out)) AS avg_tokens
            FROM chat_history
            WHERE tokens_in > 0
            """
        )
        row = cur.fetchone()
        stats["avg_tokens_per_conversation"] = int(row["avg_tokens"] or 0)

    return stats

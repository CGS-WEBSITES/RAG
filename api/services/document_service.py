import json
import logging
from typing import Any

from api.database import get_cursor

logger = logging.getLogger(__name__)


def create_document(
    title: str, content: str, metadata: dict | None = None
) -> dict[str, Any]:
    metadata = metadata or {}

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (title, content, metadata)
            VALUES (%s, %s, %s)
            RETURNING id, title, content, metadata
            """,
            (title, content, json.dumps(metadata)),
        )
        row = cur.fetchone()

    logger.info("Documento criado: id=%s, title=%s", row["id"], row["title"])
    return dict(row)


def get_all_documents() -> list[dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT id, title, content, metadata FROM documents ORDER BY id")
        return [dict(row) for row in cur.fetchall()]


def get_document_by_id(doc_id: int) -> dict[str, Any] | None:
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, title, content, metadata FROM documents WHERE id = %s",
            (doc_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def delete_document(doc_id: int) -> bool:
    with get_cursor() as cur:
        cur.execute("DELETE FROM documents WHERE id = %s RETURNING id", (doc_id,))
        deleted = cur.fetchone()

    if deleted:
        logger.info("Documento removido: id=%s", doc_id)
        return True
    return False

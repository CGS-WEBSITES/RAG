"""Service de gestão de documentos.

Responsável pelo CRUD de documentos na tabela fonte.
Os embeddings são gerados automaticamente pelo vectorizer worker.
"""

import json
import logging
from typing import Any

from api.database import get_cursor

logger = logging.getLogger(__name__)


def create_document(
    title: str, content: str, metadata: dict | None = None
) -> dict[str, Any]:
    """Insere um novo documento na tabela.

    O vectorizer worker detecta a inserção e gera
    os embeddings automaticamente em background.

    Args:
        title: Título do documento.
        content: Conteúdo textual do documento.
        metadata: Dados adicionais em formato JSON.

    Returns:
        Dicionário com os dados do documento criado.
    """
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
    """Lista todos os documentos.

    Returns:
        Lista de dicionários com os documentos.
    """
    with get_cursor() as cur:
        cur.execute("SELECT id, title, content, metadata FROM documents ORDER BY id")
        return [dict(row) for row in cur.fetchall()]


def get_document_by_id(doc_id: int) -> dict[str, Any] | None:
    """Busca um documento pelo ID.

    Args:
        doc_id: ID do documento.

    Returns:
        Dicionário com o documento ou None se não encontrado.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, title, content, metadata FROM documents WHERE id = %s",
            (doc_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def delete_document(doc_id: int) -> bool:
    """Remove um documento pelo ID.

    Os embeddings associados são removidos automaticamente
    pelo vectorizer worker.

    Args:
        doc_id: ID do documento a remover.

    Returns:
        True se o documento foi removido, False se não existia.
    """
    with get_cursor() as cur:
        cur.execute("DELETE FROM documents WHERE id = %s RETURNING id", (doc_id,))
        deleted = cur.fetchone()

    if deleted:
        logger.info("Documento removido: id=%s", doc_id)
        return True
    return False

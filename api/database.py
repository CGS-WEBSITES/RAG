"""Módulo de conexão com o PostgreSQL.

Gerencia um pool de conexões para reutilização eficiente,
evitando abrir/fechar conexões a cada requisição.
"""

import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from api.config import Config

logger = logging.getLogger(__name__)

_connection_pool: pool.SimpleConnectionPool | None = None


def init_pool(min_conn: int = 2, max_conn: int = 10) -> None:
    """Inicializa o pool de conexões com o PostgreSQL.

    Args:
        min_conn: Número mínimo de conexões mantidas abertas.
        max_conn: Número máximo de conexões permitidas.
    """
    global _connection_pool
    try:
        _connection_pool = pool.SimpleConnectionPool(
            min_conn,
            max_conn,
            Config.get_db_dsn(),
        )
        logger.info("Pool de conexões inicializado com sucesso")
    except psycopg2.Error as e:
        logger.error("Erro ao inicializar pool de conexões: %s", e)
        raise


def close_pool() -> None:
    """Fecha todas as conexões do pool."""
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None
        logger.info("Pool de conexões fechado")


@contextmanager
def get_connection() -> Generator:
    """Context manager que fornece uma conexão do pool.

    Uso:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

    Yields:
        Conexão psycopg2 do pool.

    Raises:
        RuntimeError: Se o pool não foi inicializado.
    """
    if _connection_pool is None:
        raise RuntimeError(
            "Pool de conexões não inicializado. Chame init_pool() primeiro."
        )

    conn = _connection_pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _connection_pool.putconn(conn)


@contextmanager
def get_cursor(dict_cursor: bool = True) -> Generator:
    """Context manager que fornece um cursor diretamente.

    Args:
        dict_cursor: Se True, retorna resultados como dicionários.

    Yields:
        Cursor psycopg2 pronto para uso.
    """
    cursor_factory = RealDictCursor if dict_cursor else None
    with get_connection() as conn:
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            yield cur

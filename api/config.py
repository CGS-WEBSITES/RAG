"""Configuração centralizada da aplicação.

Carrega variáveis de ambiente do arquivo .env na raiz
do projeto e expõe como constantes.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Carrega .env da raiz do projeto (um nível acima de /api)
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


class Config:
    """Configurações da aplicação carregadas do .env"""

    # PostgreSQL
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_NAME: str = os.getenv("DB_NAME", "postgres")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "postgres")

    # Ollama - Python (fora do Docker)
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    # Ollama - SQL (dentro do Docker network)
    OLLAMA_HOST_SQL: str = os.getenv("OLLAMA_HOST_SQL", "http://ollama:11434")

    # Modelos
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
    EMBEDDING_DIMENSIONS: int = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))
    LLM_MODEL: str = os.getenv("LLM_MODEL", "llama3.2")

    @classmethod
    def get_db_dsn(cls) -> str:
        """Retorna o DSN de conexão com o PostgreSQL."""
        return (
            f"host={cls.DB_HOST} "
            f"port={cls.DB_PORT} "
            f"dbname={cls.DB_NAME} "
            f"user={cls.DB_USER} "
            f"password={cls.DB_PASSWORD}"
        )

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


class Config:
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_NAME: str = os.getenv("DB_NAME", "postgres")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "postgres")

    # Embedding sempre OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    EMBEDDING_DIMENSIONS: int = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))

    # LLM provider: "openai" ou "ollama"
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")

    # Ollama (só para LLM)
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://ollama:11434")

    @classmethod
    def get_llm_model(cls) -> str:
        if cls.LLM_MODEL:
            return cls.LLM_MODEL
        return "gpt-4o-mini" if cls.LLM_PROVIDER == "openai" else "llama3.2"

    @classmethod
    def is_openai_llm(cls) -> bool:
        return cls.LLM_PROVIDER == "openai"

    @classmethod
    def get_db_dsn(cls) -> str:
        return (
            f"host={cls.DB_HOST} "
            f"port={cls.DB_PORT} "
            f"dbname={cls.DB_NAME} "
            f"user={cls.DB_USER} "
            f"password={cls.DB_PASSWORD}"
        )

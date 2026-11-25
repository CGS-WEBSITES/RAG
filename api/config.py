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

    # Assistente interno da equipe (fechado enquanto o código não for definido)
    INTERNAL_ACCESS_CODE: str = os.getenv("INTERNAL_ACCESS_CODE", "").strip()
    INTERNAL_USERS: list[str] = [
        u.strip() for u in (os.getenv("INTERNAL_USERS") or "Equipe").split(",")
        if u.strip()
    ]
    # Conta que entra sem senha. Vazio = desligada. Não ligue num servidor público.
    INTERNAL_GUEST: str = os.getenv("INTERNAL_GUEST", "").strip()
    FRESHDESK_API_KEY: str = os.getenv("FRESHDESK_API_KEY", "").strip()
    FRESHDESK_SYNC_MINUTES: int = int(os.getenv("FRESHDESK_SYNC_MINUTES") or "10")
    CLAUDE_API_KEY: str = (os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or "").strip()
    INTERNAL_LLM_MODEL: str = os.getenv("INTERNAL_LLM_MODEL") or "claude-haiku-5-5"
    CLAUDE_EFFORT: str = os.getenv("CLAUDE_EFFORT") or "high"
    # Tentados em ordem se o principal falhar antes de começar a responder
    INTERNAL_FALLBACK_MODELS: list[str] = [
        m.strip() for m in (os.getenv("INTERNAL_FALLBACK_MODELS") or "gpt-6-luna,gpt-5-mini").split(",") if m.strip()
    ]

    # Tickets atendidos por quem não serve de referência sozinho. Os dados ficam só no .env:
    # REVIEW_NAME é regex do nome, REVIEW_AGENTS são IDs de conta, válidos até REVIEW_UNTIL.
    REVIEW_LABEL: str = os.getenv("REVIEW_LABEL") or "Ticket em revisão"
    REVIEW_NAME: str = os.getenv("REVIEW_NAME", "").strip()
    REVIEW_AGENTS: set[int] = {int(x) for x in os.getenv("REVIEW_AGENTS", "").split(",") if x.strip().isdigit()}
    REVIEW_UNTIL: str = os.getenv("REVIEW_UNTIL", "").strip()
    REVIEW_OTHERS: str = os.getenv("REVIEW_OTHERS", "").strip()  # assinaturas confiáveis na mesma conta

    # Parte pública
    PUBLIC_DAILY_QUESTIONS: int = int(os.getenv("PUBLIC_DAILY_QUESTIONS") or "500")
    PUBLIC_HOURLY_PER_IP: int = int(os.getenv("PUBLIC_HOURLY_PER_IP") or "30")
    PUBLIC_LLM_MODEL: str = os.getenv("PUBLIC_LLM_MODEL") or "claude-haiku-5-5"
    PUBLIC_CLAUDE_EFFORT: str = os.getenv("PUBLIC_CLAUDE_EFFORT") or "low"
    VOICE_DAILY_CHARS: int = int(os.getenv("VOICE_DAILY_CHARS") or "100000")
    POLLY_IDENTITY_POOL_ID: str = os.getenv("POLLY_IDENTITY_POOL_ID", "").strip()

    FRESHDESK_URL: str = os.getenv("FRESHDESK_URL") or "https://wearecgs.freshdesk.com"

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

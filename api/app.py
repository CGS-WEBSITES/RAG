import logging
import sys
from pathlib import Path

from flask import Flask
from flask_restx import Api

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.config import Config
from api.database import init_pool, close_pool
from api.resources.documents import ns as documents_ns
from api.resources.search import ns as search_ns
from api.resources.rag import ns as rag_ns
from api.resources.system import ns as system_ns

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)

    api = Api(
        app,
        title="RAG API",
        version="1.0",
        description=(
            "API de busca semântica e RAG com pgai + Ollama.\n\n"
            f"**Embedding Model:** {Config.EMBEDDING_MODEL} "
            f"({Config.EMBEDDING_DIMENSIONS}d)\n\n"
            f"**LLM Model:** {Config.LLM_MODEL}\n\n"
            "**Fluxo:** Inserir documentos → Vectorizer gera embeddings → "
            "Buscar por similaridade → RAG gera respostas"
        ),
        doc="/docs",
    )

    api.add_namespace(documents_ns, path="/api/documents")
    api.add_namespace(search_ns, path="/api/search")
    api.add_namespace(rag_ns, path="/api/rag")
    api.add_namespace(system_ns, path="/api/system")

    with app.app_context():
        try:
            init_pool()
            logger.info("Aplicação iniciada com sucesso")
            logger.info("Swagger UI disponível em: http://localhost:5000/docs")
        except Exception as e:
            logger.error("Falha ao iniciar: %s", e)
            raise

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)

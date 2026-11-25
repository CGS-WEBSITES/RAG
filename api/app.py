import logging
import sys
from pathlib import Path
from flask import Flask, jsonify, request
from flask_restx import Api
from flask_cors import CORS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api.config import Config
from api.database import init_pool
from api.internal import freshdesk
from api.resources.rag import LIMIT_MESSAGE, ns as rag_ns
from api.resources.imports import ns as imports_ns
from api.resources.history import ns as history_ns
from api.resources.internal import ns as internal_ns, require_team
from api.services import limits
from api.resources.health import ns as health_ns

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["TIMEOUT"] = 600
    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        supports_credentials=False,
    )

    @app.before_request
    def protect_import():
        # Importar apaga e regrava a base: só com sessão da equipe.
        if request.path.startswith("/api/import") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if denied := require_team():
                return jsonify(denied[0]), denied[1]

    @app.before_request
    def limit_public():
        if request.method == "POST" and request.path.startswith(("/api/rag/tickets", "/api/rag/drunagor")):
            if not limits.allow_question():
                return jsonify({"message": LIMIT_MESSAGE}), 429

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
        return response
    api = Api(
        app,
        title="RAG API",
        version="2.0",
        description=(
            "API de suporte CGS com RAG multi-source.\n\n"
            f"**Provider:** {Config.LLM_PROVIDER}\n\n"
            f"**Embedding:** {Config.EMBEDDING_MODEL} "
            f"({Config.EMBEDDING_DIMENSIONS}d)\n\n"
            f"**LLM:** {Config.get_llm_model()}\n\n"
        ),
        doc="/docs",
    )
    api.add_namespace(rag_ns, path="/api/rag")
    api.add_namespace(imports_ns, path="/api/import")
    api.add_namespace(history_ns, path="/api/history")
    api.add_namespace(internal_ns, path="/api/internal")
    api.add_namespace(health_ns, path="/health")
    with app.app_context():
        try:
            init_pool()
            freshdesk.start_background()
            logger.info("Aplicação iniciada com sucesso")
            logger.info("Swagger UI disponível em: http://localhost:5000/docs")
        except Exception as e:
            logger.error("Falha ao iniciar: %s", e)
            raise
    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)

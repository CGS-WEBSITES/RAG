from flask_restx import Namespace, Resource, fields

from api.services.rag_service import generate_rag_response

ns = Namespace("rag", description="RAG - Perguntas e respostas com IA")


rag_input = ns.model(
    "RAGInput",
    {
        "question": fields.String(
            required=True,
            description="Pergunta em linguagem natural",
            example="Qual o status atual do projeto?",
        ),
        "max_chunks": fields.Integer(
            default=5,
            description="Máximo de trechos de contexto (1-10)",
            example=5,
        ),
        "model": fields.String(
            default="llama3.2",
            description="Modelo LLM do Ollama",
            example="llama3.2",
        ),
    },
)

source_model = ns.model(
    "Source",
    {
        "id": fields.Integer(description="ID do documento fonte"),
        "title": fields.String(description="Título do documento"),
        "chunk": fields.String(description="Trecho usado como contexto"),
        "distance": fields.Float(description="Distância semântica"),
    },
)

rag_output = ns.model(
    "RAGOutput",
    {
        "question": fields.String(description="Pergunta original"),
        "answer": fields.String(description="Resposta gerada pelo LLM"),
        "sources": fields.List(fields.Nested(source_model)),
        "model": fields.String(description="Modelo LLM utilizado"),
    },
)


def _handle_rag(source: str | None, exclude_sources: list[str] | None = None):
    """Helper compartilhado entre os endpoints."""
    data = ns.payload
    question = data["question"]
    max_chunks = min(max(data.get("max_chunks", 5), 1), 10)
    model = data.get("model")

    try:
        return generate_rag_response(
            question=question,
            max_chunks=max_chunks,
            model=model,
            source=source,
            exclude_sources=exclude_sources,
        )
    except ConnectionError as e:
        ns.abort(503, str(e))
    except RuntimeError as e:
        ns.abort(500, str(e))
    except Exception as e:
        ns.abort(500, f"Erro inesperado: {str(e)}")


@ns.route("/documents")
class RAGDocuments(Resource):
    @ns.doc("rag_documents")
    @ns.expect(rag_input, validate=True)
    @ns.marshal_with(rag_output)
    def post(self):
        """RAG sobre documentos gerais (exclui tickets, logistics e voice_tone)"""
        return _handle_rag(
            source=None,
            exclude_sources=["logistics", "tickets", "voice_tone"],
        )


@ns.route("/logistics")
class RAGLogistics(Resource):
    @ns.doc("rag_logistics")
    @ns.expect(rag_input, validate=True)
    @ns.marshal_with(rag_output)
    def post(self):
        """RAG sobre atualizações de logística"""
        return _handle_rag(source="logistics")


@ns.route("/tickets")
class RAGTickets(Resource):
    @ns.doc("rag_tickets")
    @ns.expect(rag_input, validate=True)
    @ns.marshal_with(rag_output)
    def post(self):
        """RAG sobre tickets de suporte"""
        return _handle_rag(source="tickets")


@ns.route("/voice-tone")
class RAGVoiceTone(Resource):
    @ns.doc("rag_voice_tone")
    @ns.expect(rag_input, validate=True)
    @ns.marshal_with(rag_output)
    def post(self):
        """RAG sobre diretrizes de Tom de Voz e IPs"""
        return _handle_rag(source="voice_tone")

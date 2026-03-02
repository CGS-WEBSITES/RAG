from flask_restx import Namespace, Resource, fields

from api.services.rag_service import generate_rag_response

ns = Namespace("rag", description="RAG - Perguntas e respostas com IA")

# --- Modelos ---

_base_fields = {
    "question": fields.String(
        required=True,
        description="Pergunta em linguagem natural",
        example="Qual o status atual do projeto?",
    ),
    "model": fields.String(
        default="gpt-4o-mini",
        description="Modelo LLM da OpenAI",
        example="gpt-4o-mini",
    ),
}

rag_input_logistics = ns.model(
    "RAGInputLogistics",
    {
        **_base_fields,
        "max_chunks": fields.Integer(
            default=1,
            description="Máximo de trechos de contexto (1-10)",
            example=1,
        ),
    },
)

rag_input_tickets = ns.model(
    "RAGInputTickets",
    {
        **_base_fields,
        "max_chunks": fields.Integer(
            default=3,
            description="Máximo de trechos de contexto (1-10)",
            example=3,
        ),
    },
)

rag_input_voice_tone = ns.model(
    "RAGInputVoiceTone",
    {
        **_base_fields,
        "max_chunks": fields.Integer(
            default=3,
            description="Máximo de trechos de contexto (1-10)",
            example=3,
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


def _handle_rag(source: str, default_max_chunks: int = 3):
    data = ns.payload
    question = data["question"]
    max_chunks = min(max(data.get("max_chunks", default_max_chunks), 1), 10)
    model = data.get("model")

    try:
        return generate_rag_response(
            question=question,
            max_chunks=max_chunks,
            model=model,
            source=source,
        )
    except ConnectionError as e:
        ns.abort(503, str(e))
    except RuntimeError as e:
        ns.abort(500, str(e))
    except Exception as e:
        ns.abort(500, f"Erro inesperado: {str(e)}")


@ns.route("/logistics")
class RAGLogistics(Resource):
    @ns.doc("rag_logistics")
    @ns.expect(rag_input_logistics, validate=True)
    @ns.marshal_with(rag_output)
    def post(self):
        """RAG sobre atualizações de logística"""
        return _handle_rag(source="logistics", default_max_chunks=1)


@ns.route("/tickets")
class RAGTickets(Resource):
    @ns.doc("rag_tickets")
    @ns.expect(rag_input_tickets, validate=True)
    @ns.marshal_with(rag_output)
    def post(self):
        """RAG sobre tickets de suporte"""
        return _handle_rag(source="tickets", default_max_chunks=3)


@ns.route("/voice-tone")
class RAGVoiceTone(Resource):
    @ns.doc("rag_voice_tone")
    @ns.expect(rag_input_voice_tone, validate=True)
    @ns.marshal_with(rag_output)
    def post(self):
        """RAG sobre diretrizes de Tom de Voz e IPs"""
        return _handle_rag(source="voice_tone", default_max_chunks=3)

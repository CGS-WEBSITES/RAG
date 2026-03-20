from flask import Response, request
from flask_restx import Namespace, Resource, fields

from api.services.rag_service import generate_rag_response, generate_rag_stream

ns = Namespace("rag", description="RAG - Perguntas e respostas com IA")

rag_input = ns.model(
    "RAGInput",
    {
        "question": fields.String(
            required=True,
            description="Pergunta em linguagem natural",
            example="Meu pedido está atrasado, o que eu faço?",
        ),
        "max_chunks": fields.Integer(
            default=5,
            description="Máximo de tickets de contexto (1-10)",
            example=5,
        ),
        "session_id": fields.String(
            default="",
            description="ID da sessão para histórico",
        ),
        "chat_history": fields.List(
            fields.Raw,
            description="Histórico da conversa [{role, content}]",
            default=[],
        ),
    },
)

ticket_source = ns.model(
    "TicketSource",
    {
        "id": fields.Integer,
        "title": fields.String,
        "chunk": fields.String,
        "distance": fields.Float,
    },
)

logistics_source = ns.model(
    "LogisticsSource",
    {
        "id": fields.Integer,
        "title": fields.String,
        "chunk": fields.String,
        "distance": fields.Float,
    },
)

sources_model = ns.model(
    "Sources",
    {
        "tickets": fields.List(fields.Nested(ticket_source)),
        "logistics": fields.List(fields.Nested(logistics_source)),
    },
)

rag_output = ns.model(
    "RAGOutput",
    {
        "question": fields.String(description="Pergunta original"),
        "answer": fields.String(description="Resposta gerada pelo LLM"),
        "sources": fields.Nested(sources_model),
        "model": fields.String(description="Modelo LLM utilizado"),
        "category": fields.String(description="Classificação automática"),
        "chat_id": fields.Integer(description="ID no histórico"),
    },
)


@ns.route("/tickets")
class RAGTickets(Resource):
    @ns.doc("rag_tickets")
    @ns.expect(rag_input, validate=True)
    @ns.marshal_with(rag_output)
    def post(self):
        data = ns.payload
        question = data["question"]
        max_chunks = min(max(data.get("max_chunks", 5), 1), 10)
        session_id = data.get("session_id", "")
        chat_history = data.get("chat_history", [])

        try:
            return generate_rag_response(
                question=question,
                max_chunks=max_chunks,
                session_id=session_id,
                chat_history=chat_history,
            )
        except ConnectionError as e:
            ns.abort(503, str(e))
        except RuntimeError as e:
            ns.abort(500, str(e))
        except Exception as e:
            ns.abort(500, f"Erro inesperado: {str(e)}")


@ns.route("/tickets/stream")
class RAGTicketsStream(Resource):
    @ns.doc("rag_tickets_stream")
    def post(self):
        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return {"message": "question is required"}, 400

        max_chunks = min(max(data.get("max_chunks", 5), 1), 10)
        session_id = data.get("session_id", "")
        chat_history = data.get("chat_history", [])

        return Response(
            generate_rag_stream(
                question=question,
                max_chunks=max_chunks,
                session_id=session_id,
                chat_history=chat_history,
            ),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

import json
from flask import Response, request
from flask_restx import Namespace, Resource, fields

from api.services.history_service import update_satisfaction
from api.services.rag_service import generate_rag_response, generate_rag_stream
from api.database import get_cursor

ns = Namespace("rag", description="RAG - Perguntas e respostas com IA")

ticket_input = ns.model(
    "TicketInput",
    {
        "question": fields.String(required=True, description="Pergunta do usuário"),
        "max_chunks": fields.Integer(default=5, description="Máximo de chunks"),
        "session_id": fields.String(default="", description="ID da sessão"),
        "chat_history": fields.List(fields.Raw, default=[], description="Histórico"),
        "language": fields.String(
            default=None, description="Idioma detectado pelo frontend"
        ),
        "refinement_round": fields.Integer(
            default=0, description="Rodada de refinamento"
        ),
        "parent_message_id": fields.String(
            default=None, description="ID da mensagem original"
        ),
        "original_question": fields.String(
            default=None, description="Pergunta original não satisfeita"
        ),
        "original_answer": fields.String(
            default=None, description="Resposta original não satisfeita"
        ),
    },
)

satisfaction_input = ns.model(
    "SatisfactionInput",
    {
        "chat_id": fields.String(required=True, description="ID da mensagem"),
        "satisfied": fields.Boolean(required=True, description="Usuário satisfeito?"),
    },
)


@ns.route("/tickets")
class RAGTickets(Resource):
    @ns.doc("rag_tickets")
    @ns.expect(ticket_input)
    def post(self):
        """RAG unificado (síncrono)"""
        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return {"message": "question is required"}, 400

        max_chunks = min(max(data.get("max_chunks", 5), 1), 10)

        try:
            return generate_rag_response(
                question=question,
                max_chunks=max_chunks,
                session_id=data.get("session_id", ""),
                chat_history=data.get("chat_history", []),
                language=data.get("language"),
                project=data.get("project"),
                region=data.get("region"),
                refinement_round=data.get("refinement_round", 0),
                parent_message_id=data.get("parent_message_id"),
                original_question=data.get("original_question"),
                original_answer=data.get("original_answer"),
            )
        except ConnectionError as e:
            ns.abort(503, str(e))
        except RuntimeError as e:
            ns.abort(500, str(e))
        except Exception as e:
            ns.abort(500, f"Unexpected error: {str(e)}")


@ns.route("/tickets/stream")
class RAGTicketsStream(Resource):
    @ns.doc("rag_tickets_stream")
    def post(self):
        """RAG unificado (streaming via SSE)"""
        data = request.get_json(force=True)
        question = (data.get("question") or "").strip()
        if not question:
            return {"message": "question is required"}, 400

        max_chunks = min(max(data.get("max_chunks", 5), 1), 10)

        return Response(
            generate_rag_stream(
                question=question,
                max_chunks=max_chunks,
                session_id=data.get("session_id", ""),
                chat_history=data.get("chat_history", []),
                language=data.get("language"),
                project=data.get("project"),
                region=data.get("region"),
                refinement_round=data.get("refinement_round", 0),
                parent_message_id=data.get("parent_message_id"),
                original_question=data.get("original_question"),
                original_answer=data.get("original_answer"),
            ),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


@ns.route("/popular-questions")
class RAGPopularQuestions(Resource):
    @ns.doc("popular_questions")
    def get(self):
        """Return top 5 most asked questions (excluding suggestion clicks and short inputs)"""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    SELECT question, COUNT(*) as total
                    FROM chat_history
                    WHERE length(question) > 15
                        AND language = 'en'
                        AND category NOT IN ('outro')
                        AND question ~ '[?!]|how|what|where|when|why|can |do |is |are |my |want|need|refund|delay|track|cancel|address'
                        AND question !~ '^(Drunagor|Battleforge|Dante|ForFun|Oathfall|Magnus|Frosthaven|Brasil|Europe|EUA|Asia|Oceania|Brazil)(,\s*(Drunagor|Battleforge|Dante|Brasil|Europe|EUA|Asia|Oceania|Brazil))?$'
                    GROUP BY question
                    ORDER BY total DESC
                    LIMIT 5
                """)
                rows = cur.fetchall()
                return {"questions": [r["question"] for r in rows]}, 200
        except Exception as e:
            return {"questions": []}, 200


@ns.route("/drunagor/rules")
class DrunagorRules(Resource):
    @ns.doc("drunagor_rules_stream")
    def post(self):
        data = request.get_json(force=True, silent=True) or {}
        question = (data.get("question") or "").strip()
        session_id = data.get("session_id") or ""
        language = data.get("language") or None
        chat_history = data.get("chat_history") or []

        if not question:
            return {"error": "question is required"}, 400

        def stream():
            try:
                for chunk in generate_rag_stream(
                    question=question,
                    session_id=session_id,
                    chat_history=chat_history,
                    language=language,
                    project="Drunagor",
                    region=None,
                ):
                    yield chunk
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        return Response(
            stream_with_context(stream()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )


@ns.route("/satisfaction")
class RAGSatisfaction(Resource):
    @ns.doc("rag_satisfaction")
    @ns.expect(satisfaction_input)
    def post(self):
        """Registra satisfação do usuário com a resposta"""
        data = request.get_json(force=True)
        chat_id = (data.get("chat_id") or "").strip()
        satisfied = data.get("satisfied")

        if not chat_id:
            return {"message": "chat_id is required"}, 400
        if satisfied is None:
            return {"message": "satisfied is required"}, 400

        updated = update_satisfaction(chat_id, bool(satisfied))
        if not updated:
            return {"message": "chat message not found"}, 404

        return {"status": "ok"}, 200

import json
import logging
import re

from flask import Response, request, stream_with_context
from flask_restx import Namespace, Resource, fields

from api.services import limits, public_chat, voice_service
from api.config import Config
from api.services.history_service import update_satisfaction
from api.services.rag_service import generate_rag_response, generate_rag_stream
from api.database import get_cursor

ns = Namespace("rag", description="RAG - Perguntas e respostas com IA")
logger = logging.getLogger(__name__)
LIMIT_MESSAGE = "We have reached the usage limit for now. Please try again later."


def _public(sources):
    """Trecho de ticket é conversa de outro cliente: nunca sai pela API pública."""
    return {**sources, "tickets": []} if isinstance(sources, dict) else sources


def _public_stream(chunks):
    for chunk in chunks:
        if '"sources"' in chunk and chunk.startswith("data: "):
            try:
                event = json.loads(chunk[6:])
                event["sources"] = _public(event.get("sources"))
                chunk = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except ValueError:
                # Formato inesperado: melhor perder o evento do que vazar.
                continue
        yield chunk

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
        "product_language": fields.String(
            default=None, description="Idioma/versão do produto ou pacote"
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


def _get_product_language(data: dict) -> str | None:
    return (
        data.get("product_language")
        or data.get("productLanguage")
        or data.get("package_language")
        or data.get("packageLanguage")
        or data.get("item_language")
        or data.get("itemLanguage")
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
            response = generate_rag_response(
                question=question,
                max_chunks=max_chunks,
                session_id=data.get("session_id", ""),
                chat_history=data.get("chat_history", []),
                language=data.get("language"),
                project=data.get("project"),
                region=data.get("region"),
                product_language=_get_product_language(data),
                refinement_round=data.get("refinement_round", 0),
                parent_message_id=data.get("parent_message_id"),
                original_question=data.get("original_question"),
                original_answer=data.get("original_answer"),
            )
            return {**response, "sources": _public(response.get("sources"))}
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
            _public_stream(generate_rag_stream(
                question=question,
                max_chunks=max_chunks,
                session_id=data.get("session_id", ""),
                chat_history=data.get("chat_history", []),
                language=data.get("language"),
                project=data.get("project"),
                region=data.get("region"),
                product_language=_get_product_language(data),
                refinement_round=data.get("refinement_round", 0),
                parent_message_id=data.get("parent_message_id"),
                original_question=data.get("original_question"),
                original_answer=data.get("original_answer"),
            )),
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
                for chunk in _public_stream(generate_rag_stream(
                    question=question,
                    session_id=session_id,
                    chat_history=chat_history,
                    language=language,
                    project="Drunagor",
                    region="global",
                )):
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


@ns.route("/public/chat")
class PublicChat(Resource):
    @ns.doc("public_chat")
    def post(self):
        """Chat da comunidade (SSE). Não usa tickets."""
        data = request.get_json(force=True, silent=True) or {}
        question = str(data.get("question") or "").strip()[:1500]
        project = data.get("project")
        if not question:
            return {"message": "question is required"}, 400
        session = re.sub(r"[^A-Za-z0-9-]", "", str(data.get("session_id") or ""))[:60]
        if not limits.allow_question(session):
            return {"message": LIMIT_MESSAGE}, 429
        if project not in public_chat.PROJECTS:
            project = None

        def events():
            try:
                for event in public_chat.stream_answer(
                    question, data.get("history") or [], project,
                    re.sub(r"[^A-Za-z ]", "", str(data.get("region") or ""))[:30], session or "web",
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            except Exception:
                logger.exception("Falha no chat público")
                yield 'data: {"type": "error"}\n\n'

        return Response(stream_with_context(events()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@ns.route("/voice")
class RAGVoice(Resource):
    @ns.doc("voice")
    def post(self):
        """Lê um texto com a voz do personagem (MP3)"""
        data = request.get_json(force=True, silent=True) or {}
        text = str(data.get("text") or "").strip()[: voice_service.MAX_CHARS]
        if not text or not Config.POLLY_IDENTITY_POOL_ID:
            return {"message": "voice unavailable"}, 404
        if data.get("lang"):
            voice = voice_service.VOICES.get(str(data["lang"]), "Joanna")
        else:
            voice = voice_service.voice_for(*(str(data.get(k) or "") for k in ("project", "character", "region")))
        audio = voice_service.cached(text, voice)
        if audio is None:
            if not limits.allow_voice(len(text)):
                return {"message": LIMIT_MESSAGE}, 429
            try:
                audio = voice_service.synthesize(text, voice)
            except Exception as e:
                logger.warning("Polly falhou: %s", e)
                return {"message": "voice unavailable"}, 502
        return Response(audio, mimetype="audio/mpeg")


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

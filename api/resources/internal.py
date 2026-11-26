import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from functools import wraps

import openai
from flask import Response, g, request, stream_with_context
from flask_restx import Namespace, Resource
from itsdangerous import BadData, URLSafeTimedSerializer

from api.config import Config
from api.internal import assistant, copilot, store

logger = logging.getLogger(__name__)
ns = Namespace("internal", description="Assistente interno da equipe de suporte")
MAX_QUESTION = 15000
SESSION_SECONDS = 30 * 24 * 3600

# A senha da equipe é curta, então o limite é global (o IP do cliente é forjável
# atrás do CloudFront). Quem já entrou continua usando durante o bloqueio.
MAX_FAILURES = 20
FAILURE_WINDOW = 12 * 3600
_failures: list[float] = []
_lock = threading.Lock()


def accounts() -> list[str]:
    return ([Config.INTERNAL_GUEST] if Config.INTERNAL_GUEST else []) + Config.INTERNAL_USERS


def _signer() -> URLSafeTimedSerializer:
    # Deriva da senha e da chave da OpenAI: trocar qualquer uma encerra as sessões.
    seed = f"iris\x1f{Config.INTERNAL_ACCESS_CODE}\x1f{Config.OPENAI_API_KEY}"
    return URLSafeTimedSerializer(hashlib.sha256(seed.encode()).hexdigest())


def _closed():
    # Sem senha ou chave configurada a área fica fechada, nunca aberta.
    if not Config.INTERNAL_ACCESS_CODE or not Config.OPENAI_API_KEY:
        return {"message": "Acesso interno não configurado no servidor"}, 503
    return None


def team_only(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if closed := _closed():
            return closed
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        try:
            user = _signer().loads(token, max_age=SESSION_SECONDS)
        except BadData:
            user = None
        if user not in accounts():
            return {"message": "Sua sessão terminou. Entre de novo."}, 401
        g.user = user
        return fn(*args, **kwargs)
    return wrapper


def require_team():
    """Para proteger rotas fora deste namespace (ex.: /api/import)."""
    return team_only(lambda: None)()


def _body() -> dict:
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def _message_id(data: dict) -> str | None:
    try:
        return str(uuid.UUID(str(data.get("message_id"))))
    except ValueError:
        return None


def _friendly_error(e: Exception) -> str:
    if isinstance(e, openai.AuthenticationError) or "OPENAI_API_KEY" in str(e):
        return "A chave da OpenAI está ausente ou inválida. Avise quem cuida do servidor."
    if isinstance(e, openai.RateLimitError):
        return "O limite da OpenAI foi atingido. Tente de novo em instantes ou confira o saldo."
    if isinstance(e, openai.APIConnectionError):
        return "Não consegui falar com a OpenAI. Tente de novo."
    return "Algo deu errado ao gerar a resposta. Tente de novo."


@ns.route("/users")
class Users(Resource):
    def get(self):
        """Contas para a tela de entrada."""
        return {"users": accounts(), "guest": Config.INTERNAL_GUEST or None}


@ns.route("/login")
class Login(Resource):
    def post(self):
        if closed := _closed():
            return closed
        data = _body()
        user, code = str(data.get("user") or ""), str(data.get("code") or "").strip()
        if Config.INTERNAL_GUEST and user == Config.INTERNAL_GUEST:
            return {"user": user, "token": _signer().dumps(user)}
        now = time.time()
        with _lock:
            _failures[:] = [t for t in _failures if now - t < FAILURE_WINDOW]
            if len(_failures) >= MAX_FAILURES:
                return {"message": "Muitas senhas erradas. A entrada está bloqueada por algumas horas."}, 429
            valid = hmac.compare_digest(code.encode(), Config.INTERNAL_ACCESS_CODE.encode())
            if not valid or user not in Config.INTERNAL_USERS:
                _failures.append(now)
                return {"message": "Conta ou senha incorreta"}, 401
        return {"user": user, "token": _signer().dumps(user)}


@ns.route("/me")
class Me(Resource):
    method_decorators = [team_only]

    def get(self):
        return {"user": g.user, "base": store.overview(), "review": Config.REVIEW_LABEL}


@ns.route("/pet")
class Pet(Resource):
    method_decorators = [team_only]

    def get(self):
        """Quintal da mascote desta conta e as moedas que o time ganhou respondendo tickets."""
        return {"data": store.get_pet(g.user), "wallet": store.pet_wallet(g.user)}

    def put(self):
        data = _body()
        if len(json.dumps(data)) > 6000:
            return {"message": "Grande demais"}, 400
        store.set_pet(g.user, data)
        return {"status": "ok"}


@ns.route("/pet/spend")
class PetSpend(Resource):
    method_decorators = [team_only]

    def post(self):
        """Gasta moedas: brincar custa 1, itens custam o preço da loja."""
        data = _body()
        try:
            amount = int(data.get("amount"))
        except (TypeError, ValueError):
            return {"message": "Valor inválido"}, 400
        item = data.get("item")
        if not 1 <= amount <= 1000 or (item is not None and (not isinstance(item, str) or len(item) > 40)):
            return {"message": "Valor inválido"}, 400
        wallet = store.pet_spend(g.user, amount, item)
        if wallet is None:
            return {"message": "Sem moedas", "wallet": store.pet_wallet(g.user)}, 402
        return {"wallet": wallet}


@ns.route("/conversations")
class Conversations(Resource):
    method_decorators = [team_only]

    def get(self):
        return {"conversations": store.list_conversations(g.user)}


@ns.route("/conversations/<string:conversation_id>")
class Conversation(Resource):
    method_decorators = [team_only]

    def get(self, conversation_id):
        return {"messages": store.get_conversation(g.user, conversation_id)}

    def delete(self, conversation_id):
        store.hide_conversation(g.user, conversation_id)
        return {"status": "ok"}


@ns.route("/tickets")
class Tickets(Resource):
    method_decorators = [team_only]

    def get(self):
        a = request.args
        offset = a.get("offset", 0, type=int)
        found = store.list_tickets(
            a.get("q", ""), a.get("project"), a.get("topic"), a.get("status"), a.get("days", 0, type=int),
            a.get("show", ""), a.get("sort", ""), offset)
        tickets = [{**assistant.ticket_source(t), "headline": t["headline"], "replied": t["has_reply"]}
                   for t in found["rows"]]
        return {"tickets": tickets, "total": found["total"], "waiting": store.count_waiting()}


@ns.route("/tickets/<string:ticket_id>")
class Ticket(Resource):
    method_decorators = [team_only]

    def get(self, ticket_id):
        t = assistant.load_ticket(ticket_id)
        if not t:
            return {"message": "Ticket não encontrado"}, 404
        return {"ticket": {**assistant.ticket_source(t), "content": t["content"]}}


def _ticket_ai(ticket_id: str, build):
    t = store.get_ticket(ticket_id)
    if not t:
        return {"message": "Ticket não encontrado"}, 404
    try:
        return build(t)
    except Exception as e:
        logger.exception("Falha ao ler o ticket %s", ticket_id)
        return {"message": _friendly_error(e)}, 502


@ns.route("/tickets/<string:ticket_id>/summary")
class TicketSummary(Resource):
    method_decorators = [team_only]

    def get(self, ticket_id):
        return _ticket_ai(ticket_id, copilot.summary)


@ns.route("/tickets/<string:ticket_id>/translation")
class TicketTranslation(Resource):
    method_decorators = [team_only]

    def get(self, ticket_id):
        return _ticket_ai(ticket_id, lambda t: {"content": copilot.translation(t)})


@ns.route("/tickets/<string:ticket_id>/related")
class TicketRelated(Resource):
    method_decorators = [team_only]

    def get(self, ticket_id):
        return _ticket_ai(ticket_id, copilot.related)


@ns.route("/chat")
class Chat(Resource):
    method_decorators = [team_only]

    def post(self):
        """Pergunta ao assistente (SSE)."""
        data = _body()
        question = str(data.get("question") or "").strip()
        conversation_id = str(data.get("conversation_id") or "")[:80]
        if not question or not conversation_id:
            return {"message": "Escreva uma pergunta"}, 400
        if len(question) > MAX_QUESTION:
            return {"message": f"Texto longo demais (máximo {MAX_QUESTION} caracteres)"}, 400
        user = g.user
        examples = data.get("examples")
        examples = [str(i)[:40] for i in examples[:3]] if isinstance(examples, list) else []

        def events():
            try:
                for event in assistant.stream_answer(question, data.get("history") or [], user, conversation_id,
                                                     examples):
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            except Exception as e:
                logger.exception("Falha no chat interno")
                yield f"data: {json.dumps({'type': 'error', 'message': _friendly_error(e)}, ensure_ascii=False)}\n\n"

        return Response(stream_with_context(events()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@ns.route("/feedback")
class Feedback(Resource):
    method_decorators = [team_only]

    def post(self):
        data = _body()
        message_id = _message_id(data)
        if not message_id:
            return {"message": "message_id inválido"}, 400
        if data.get("feedback") not in ("up", "down", None):
            return {"message": "feedback deve ser up, down ou null"}, 400
        if not store.set_feedback(g.user, message_id, data.get("feedback")):
            return {"message": "Mensagem não encontrada"}, 404
        return {"status": "ok"}


@ns.route("/approve")
class Approve(Resource):
    method_decorators = [team_only]

    def post(self):
        """Salva uma resposta validada como fonte prioritária."""
        data = _body()
        question, reply = (str(data.get(k) or "").strip() for k in ("question", "reply"))
        if not question or not reply:
            return {"message": "question e reply são obrigatórios"}, 400
        ticket_id = store.approve_reply(question[:MAX_QUESTION], reply[:MAX_QUESTION])
        if message_id := _message_id(data):
            store.mark_approved(g.user, message_id)
        return {"id": ticket_id}, 201

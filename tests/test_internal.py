"""Testes da base interna. Rodam sem banco e sem OpenAI: pytest tests/"""

from types import SimpleNamespace as NS

import pytest
from flask import Flask
from flask_restx import Api

from api.config import Config
from api.internal import agent, assistant, cleaning, store
from api.resources.internal import ns
from api.internal.freshdesk import convert as from_freshdesk


@pytest.mark.parametrize("secret", ["ana@x.com", "123.456.789-00", "+55 11 99999-1234", "1Z999AA10123456784",
                                    "23 Baker Street", "Hauptstraße 12", "1841041W", "https://a.b/c?d"])
def test_remove_identificadores(secret):
    assert secret not in cleaning.clean_message(f"please check {secret} for me")


def test_remove_nomes_e_mantem_o_problema():
    out = cleaning.clean_message("Hi Fulano,\nmy card is missing, thanks for helping.\n\nBest regards,\nJohn Smith")
    assert "Fulano" not in out and "Smith" not in out
    assert "my card is missing, thanks for helping" in out


def test_saudacao_generica_nao_vira_nome():
    assert cleaning.anonymize("Hi There, Dear Team") == "Hi There, Dear Team"


def test_corta_citacao():
    assert cleaning.clean_message("My box arrived damaged today.\nOn Wed, May 12, 2021 x wrote:\nold") == \
        "My box arrived damaged today."


def _fd(**kw):
    return {"id": 7, "subject": "Missing parts", "description_text": "My Dante box is missing a miniature",
            "conversations": [], "tags": [], "type": None, "status": 2, "created_at": "2026-01-01T00:00:00Z", **kw}


def test_ticket_rotula_quem_falou_e_marca_nao_entregue():
    c = [{"created_at": "2026-01-02", "incoming": False, "private": False, "body_text": "We will send it"},
         {"created_at": "2026-01-03", "incoming": False, "private": True, "body_text": "stock is low"}]
    t = from_freshdesk(_fd(conversations=c), {7})
    assert "EQUIPE: We will send it" in t["content"] and "NOTA INTERNA: stock is low" in t["content"]
    assert (t["project"], t["topic"], t["delivery_suspect"]) == ("Dante", "peças", True)


@pytest.mark.parametrize("reply,tags,blocked", [
    ({"created_at": "2026-04-10", "user_id": 11, "body_text": "ok, done"}, [], True),
    ({"created_at": "2026-02-10", "user_id": 1, "body_text": "Best, Fulano Silva"}, [], True),
    ({"created_at": "2026-09-10", "user_id": 11, "body_text": "Best, Alex Reis"}, [], False),
    ({"created_at": "2026-04-10", "user_id": 22, "body_text": "Best, Beltrana"}, [], False),
    ({"created_at": "2026-09-10", "user_id": 1, "body_text": "Best, Alex"}, ["Fulano"], True),
])
def test_identifica_ticket_em_revisao(reply, tags, blocked):
    t = _fd(tags=tags, conversations=[{"incoming": False, "private": False, **reply}])
    assert from_freshdesk(t)["blocked"] is blocked


def test_revisao_sempre_avisa_e_exige_contraprova():
    w, ok, old = {"id": "fd-1", "blocked": True}, {"id": "fd-2", "blocked": False}, {"id": "old-3", "blocked": False, "old": True}
    assert assistant.review_warning([ok]) is None
    assert "Confira com as outras fontes" in assistant.review_warning([w, ok])
    assert "Só há Ticket em revisão" in assistant.review_warning([w])
    assert "Só há Ticket em revisão" in assistant.review_warning([w, old])


def test_chat_publico_nao_tem_acesso_a_tickets():
    import inspect
    from api.internal import knowledge
    from api.services import public_chat
    names = {t["function"]["name"] for t in public_chat.TOOLS}
    assert names == {"buscar_manual", "ver_logistica"}
    assert public_chat._run("buscar_tickets", {"query": "x", "project": "Dante"}) == ("Unknown tool.", [])
    for module in (public_chat, knowledge):
        code = "\n".join(line for line in inspect.getsource(module).split('"""', 2)[2].splitlines())
        assert "support_tickets" not in code and "store" not in code.replace("embedding_store", "")


def test_descarta_notificacao_mas_nao_se_houve_resposta():
    assert from_freshdesk(_fd(subject="New comment reply")) is None
    c = [{"created_at": "x", "incoming": False, "private": False, "body_text": "Here is the answer"}]
    assert from_freshdesk(_fd(subject="New comment reply", conversations=c))


@pytest.fixture(autouse=True)
def fake_keys(monkeypatch):
    monkeypatch.setattr(Config, "OPENAI_API_KEY", "x")
    monkeypatch.setattr(Config, "REVIEW_LABEL", "Ticket em revisão")
    monkeypatch.setattr(Config, "REVIEW_NAME", r"\bfulano\b")
    monkeypatch.setattr(Config, "REVIEW_AGENTS", {11})
    monkeypatch.setattr(Config, "REVIEW_UNTIL", "2026-08-06")
    monkeypatch.setattr(Config, "REVIEW_OTHERS", "Beltrana")
    monkeypatch.setattr(Config, "INTERNAL_GUEST", "")
    monkeypatch.setattr(Config, "INTERNAL_LLM_MODEL", "gpt-x")


@pytest.fixture
def http():
    app = Flask(__name__)
    Api(app).add_namespace(ns, path="/api/internal")
    return app.test_client()


def test_login_e_bloqueio(http, monkeypatch):
    from api.resources import internal
    internal._failures.clear()
    monkeypatch.setattr(Config, "INTERNAL_ACCESS_CODE", "senha-de-teste")
    monkeypatch.setattr(Config, "INTERNAL_USERS", ["Ana"])
    monkeypatch.setattr(store, "overview", lambda: {})

    def login(user, code):
        return http.post("/api/internal/login", json={"user": user, "code": code})

    assert login("Estranho", "senha-de-teste").status_code == 401
    token = login("Ana", "senha-de-teste").get_json()["token"]
    assert http.get("/api/internal/me", headers={"Authorization": f"Bearer {token}"}).get_json()["user"] == "Ana"
    assert http.get("/api/internal/me", headers={"Authorization": f"Bearer {token}x"}).status_code == 401
    for _ in range(internal.MAX_FAILURES):
        login("Ana", "0000")
    assert login("Ana", "senha-de-teste").status_code == 429
    internal._failures.clear()
    # Trocar a senha derruba as sessões abertas.
    monkeypatch.setattr(Config, "INTERNAL_ACCESS_CODE", "outra")
    assert http.get("/api/internal/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_conta_sem_senha_so_quando_ligada(http, monkeypatch):
    monkeypatch.setattr(Config, "INTERNAL_ACCESS_CODE", "senha-de-teste")
    monkeypatch.setattr(Config, "OPENAI_API_KEY", "x")
    monkeypatch.setattr(Config, "INTERNAL_GUEST", "")
    assert http.post("/api/internal/login", json={"user": ""}).status_code == 401
    assert http.post("/api/internal/login", json={"user": "Padrão"}).status_code == 401
    monkeypatch.setattr(Config, "INTERNAL_GUEST", "Padrão")
    assert http.post("/api/internal/login", json={"user": "Padrão"}).status_code == 200
    assert http.post("/api/internal/login", json={"user": "Ana"}).status_code == 401


def test_importacao_exige_sessao(monkeypatch):
    from api import app as app_module
    monkeypatch.setattr(app_module, "init_pool", lambda: None)
    monkeypatch.setattr(app_module.freshdesk, "start_background", lambda: None)
    monkeypatch.setattr(Config, "INTERNAL_ACCESS_CODE", "senha-de-teste")
    monkeypatch.setattr(Config, "OPENAI_API_KEY", "x")
    client = app_module.create_app().test_client()
    assert client.post("/api/import/tickets").status_code == 401
    assert client.delete("/api/import/documents/1").status_code == 401
    token = client.post("/api/internal/login", json={"user": "Ana", "code": "senha-de-teste"}).get_json()["token"]
    assert client.post("/api/import/tickets", headers={"Authorization": f"Bearer {token}"}).status_code == 400


def test_exemplo_fixado_vai_ao_modelo_e_vira_fonte(monkeypatch):
    sent = []

    def create(**kw):
        sent.append(str(kw["messages"]))
        return [_chunk("ok", finish="stop")]

    monkeypatch.setattr(agent, "openai_client", lambda: NS(chat=NS(completions=NS(create=create))))
    monkeypatch.setattr(store, "get_ticket", lambda i: {**from_freshdesk(_fd()), "opened_at": None, "last_at": None} if i == "fd-7" else None)
    monkeypatch.setattr(store, "save_message", lambda **m: "id")
    events = list(assistant.stream_answer("oi", [], "", "c", ["fd-7", "fd-8"]))
    assert "missing a miniature" in sent[0]
    assert [s["id"] for e in events if e["type"] == "sources" for s in e["sources"]] == ["fd-7"]


def test_api_publica_nao_devolve_ticket():
    import json
    from api.resources.rag import _public_stream
    event = {"type": "meta", "sources": {"tickets": [{"chunk": "segredo"}], "manual": [1]}}
    out = list(_public_stream([f"data: {json.dumps(event)}\n\n", 'data: {"type": "token"}\n\n', 'data: {"sources" quebrado']))
    assert "segredo" not in "".join(out) and '"manual": [1]' in out[0] and len(out) == 2


def test_limite_publico_por_ip(monkeypatch):
    from api.services import limits
    limits._hour.clear()
    limits._day.clear()
    with Flask(__name__).test_request_context(headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}):
        assert limits.client_ip() == "9.9.9.9"
        assert [limits.allow_question("a") for _ in range(Config.PUBLIC_HOURLY_PER_IP + 1)][-2:] == [True, False]
        # Outra pessoa na mesma rede ainda pode perguntar.
        assert limits.allow_question("b")
        assert not all(limits.allow_question(f"x{i}") for i in range(Config.PUBLIC_HOURLY_PER_IP * 5))


def test_reserva_assume_so_se_nada_foi_escrito(monkeypatch):
    def create(**kw):
        if kw["model"] == "ruim":
            raise RuntimeError("fora do ar")
        return [_chunk("ok", finish="stop")]

    saved = {}
    monkeypatch.setattr(Config, "INTERNAL_LLM_MODEL", "ruim")
    monkeypatch.setattr(Config, "INTERNAL_FALLBACK_MODELS", ["bom"])
    monkeypatch.setattr(agent, "openai_client", lambda: NS(chat=NS(completions=NS(create=create))))
    monkeypatch.setattr(store, "save_message", lambda **m: saved.update(m))
    assert list(assistant.stream_answer("oi", [], "", "c"))[-1]["type"] == "done"
    assert saved["model"] == "bom"


def test_acesso_fechado_por_padrao(http, monkeypatch):
    monkeypatch.setattr(Config, "INTERNAL_ACCESS_CODE", "")
    assert http.get("/api/internal/me").status_code == 503
    monkeypatch.setattr(Config, "INTERNAL_ACCESS_CODE", "ação")
    assert http.get("/api/internal/me").status_code == 401


def _chunk(content=None, call=None, finish=None, usage=None):
    tc = [NS(index=0, id="c1", function=NS(name=call[0], arguments=call[1]))] if call else None
    return NS(usage=usage, choices=[NS(finish_reason=finish, delta=NS(content=content, tool_calls=tc))])


def test_loop_usa_ferramenta_cita_fonte_e_nao_envia_email(monkeypatch):
    sent = []
    rounds = [[_chunk(call=("buscar_tickets", '{"query": "missing parts"}'))], [_chunk("Veja [fd-7]", finish="stop")]]

    def create(**kw):
        sent.append(str(kw["messages"]))
        return rounds.pop(0)

    monkeypatch.setattr(agent, "openai_client", lambda: NS(chat=NS(completions=NS(create=create))))
    ticket = {**from_freshdesk(_fd()), "opened_at": None, "last_at": None}
    other = {**ticket, "id": "fd-70", "freshdesk_id": 70}
    monkeypatch.setattr(store, "search_tickets", lambda *a: [ticket, other])
    monkeypatch.setattr(store, "save_message", lambda **m: "id")
    events = list(assistant.stream_answer("cliente ana@x.com pediu peça", [], "Ana", "c"))
    assert [e["type"] for e in events] == ["status", "token", "sources", "done"]
    assert [s["id"] for s in events[2]["sources"]] == ["fd-7"]
    assert "ana@x.com" not in sent[0] and "missing a miniature" in sent[1]


def test_falha_da_ferramenta_nao_derruba_a_resposta(monkeypatch):
    rounds = [[_chunk(call=("buscar_tickets", "{quebrado"))], [_chunk("ok", finish="stop")]]
    monkeypatch.setattr(agent, "openai_client", lambda: NS(chat=NS(completions=NS(create=lambda **k: rounds.pop(0)))))
    monkeypatch.setattr(store, "save_message", lambda **m: "id")
    assert list(assistant.stream_answer("x", [], "", "c"))[-1]["type"] == "done"

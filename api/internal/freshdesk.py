"""Freshdesk: conversão de tickets e sincronização. Só faz GET, nunca altera nada lá."""

import base64
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from api.config import Config
from api.database import get_cursor
from api.internal import store
from api.internal.cleaning import anonymize, clean_message, detect_project, detect_topic, is_noise

logger = logging.getLogger(__name__)
MAX_CONTENT = 14000
STATUS = {2: "aberto", 3: "pendente", 4: "resolvido", 5: "fechado"}
# O plano permite 40 chamadas por minuto. A sincronização usa 30 para sobrar
# espaço para abrir ticket no chat.
SYNC_PAUSE = 2.0
_started = False


def enabled() -> bool:
    return bool(Config.FRESHDESK_API_KEY)


def finish(ticket: dict) -> dict:
    ticket["content"] = ticket["content"].replace("\x00", "")[:MAX_CONTENT]
    ticket["subject"] = ticket["subject"].replace("\x00", "")[:300]
    ticket["content_hash"] = store.content_hash(ticket["subject"], ticket["content"])
    return ticket


def is_blocked(t: dict) -> bool:
    """Ticket que só pode ser usado com contraprova (regras no .env)."""
    if Config.REVIEW_NAME:
        name = re.compile(Config.REVIEW_NAME, re.IGNORECASE)
        # Qualquer menção (tag, assinatura, saudação, citação) indica que a pessoa atuou no caso.
        texts = [*(t.get("tags") or []), t.get("subject"), t.get("description_text"),
                 *(c.get("body_text") for c in t.get("conversations") or [])]
        if any(name.search(x or "") for x in texts):
            return True
    # Conta compartilhada: vale a data, e não só o ID do agente.
    for c in t.get("conversations") or []:
        if c["incoming"] or c["private"] or c.get("user_id") not in Config.REVIEW_AGENTS:
            continue
        if c["created_at"] >= Config.REVIEW_UNTIL:
            continue
        ending = (c.get("body_text") or "")[-700:]
        if not (Config.REVIEW_OTHERS and re.search(Config.REVIEW_OTHERS, ending, re.IGNORECASE)):
            return True
    return False


def convert(t: dict, undelivered: set[int] = frozenset(), keep_noise: bool = False) -> dict | None:
    if t.get("spam"):
        return None
    raw_subject = t.get("subject") or ""
    raw_body = t.get("description_text") or ""
    conversations = sorted(t.get("conversations") or [], key=lambda c: c["created_at"])
    public = [c for c in conversations if not c["private"]]
    has_reply = any(not c["incoming"] and not c["private"] for c in conversations)
    if not keep_noise and is_noise(raw_subject, raw_body, has_reply):
        return None
    body = clean_message(raw_body)
    parts = [f"CLIENTE: {body}"] if body else []
    for c in conversations:
        text = clean_message(c.get("body_text"))
        if len(text) < 3:
            continue
        who = "NOTA INTERNA" if c["private"] else "CLIENTE" if c["incoming"] else "EQUIPE"
        parts.append(f"{who}: {text}")
    if not parts:
        return None
    everything = f"{raw_subject} {raw_body}"
    return finish({
        "id": f"fd-{t['id']}", "origin": "freshdesk", "freshdesk_id": t["id"],
        "subject": anonymize(raw_subject), "content": "\n\n".join(parts),
        "project": detect_project(everything, t.get("tags")),
        "topic": detect_topic(everything, t.get("type")),
        "status": STATUS.get(t.get("status")), "has_reply": has_reply,
        "delivery_suspect": t["id"] in undelivered,
        "blocked": is_blocked(t),
        "opened_at": t["created_at"],
        "waiting": t.get("status") in (2, 3) and (not public or public[-1]["incoming"]),
        "last_at": public[-1]["created_at"] if public else t["created_at"],
        "requester": t.get("requester_id"),
    })


def _get(path: str, retries: int = 2, **params):
    url = f"{Config.FRESHDESK_URL.rstrip('/')}/api/v2/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    token = base64.b64encode(f"{Config.FRESHDESK_API_KEY}:X".encode()).decode()
    request = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == retries:
                raise
            time.sleep(min(int(e.headers.get("Retry-After") or 30), 90))


def _with_conversations(t: dict, retries: int = 2, pause: float = 0) -> dict:
    conversations, page = [], 1
    while True:
        time.sleep(pause)
        rows = _get(f"tickets/{t['id']}/conversations", retries=retries, per_page=100, page=page)
        conversations += rows
        if len(rows) < 100:
            return {**t, "conversations": conversations}
        page += 1


def fetch(ticket_id: int) -> dict | None:
    """Ticket ao vivo para o chat. Sem esperar por limite: na falha usa-se a cópia local."""
    try:
        raw = _with_conversations(_get(f"tickets/{int(ticket_id)}", retries=0), retries=0)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            logger.warning("Freshdesk respondeu %s", e.code)
        return None
    except Exception as e:
        logger.warning("Freshdesk indisponível: %s", type(e).__name__)
        return None
    ticket = convert(raw, keep_noise=True)
    with get_cursor() as cur:
        store.add_replies(cur, raw["id"], raw.get("conversations") or [])
        if ticket:
            store.upsert_ticket(cur, ticket)
    return store.get_ticket(ticket["id"]) if ticket else None


def sync() -> int:
    """Traz o que mudou desde a última vez. O cursor só anda se tudo deu certo."""
    cursor = store.get_state("freshdesk_cursor")
    if not cursor:
        last = store.overview()["dados_ate"]
        since = datetime.fromisoformat(last) if last else datetime.now() - timedelta(days=30)
        cursor = (since - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    # Primeira vez com a economia da mascote: relê o dia de hoje para contar as respostas.
    if not store.get_state("pet_since"):
        today = datetime.now(ZoneInfo(store.PET_TZ)).replace(hour=0, minute=0, second=0, microsecond=0)
        store.set_state("pet_since", today.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        cursor = min(cursor, store.get_state("pet_since"))
    started = datetime.now(timezone.utc)
    changed, page = [], 1
    while True:
        rows = _get("tickets", updated_since=cursor, include="description", order_by="updated_at",
                    order_type="asc", per_page=100, page=page)
        changed += rows
        if len(rows) < 100:
            break
        page += 1
        time.sleep(SYNC_PAUSE)
    saved = 0
    for raw in changed:
        full = _with_conversations(raw, pause=SYNC_PAUSE)
        ticket = convert(full)
        with get_cursor() as cur:
            store.add_replies(cur, full["id"], full.get("conversations") or [])
            if ticket:
                store.upsert_ticket(cur, ticket)
                saved += 1
    # Um minuto de folga cobre diferença de relógio; regravar é inofensivo.
    store.set_state("freshdesk_cursor", (started - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    store.embed_pending()
    logger.info("Freshdesk: %d alterados, %d gravados", len(changed), saved)
    return saved


def start_background() -> None:
    global _started
    if _started or not enabled() or Config.FRESHDESK_SYNC_MINUTES <= 0:
        return
    _started = True

    def loop():
        while True:
            try:
                sync()
            except Exception as e:
                logger.error("Sincronização do Freshdesk falhou: %s", e)
            time.sleep(Config.FRESHDESK_SYNC_MINUTES * 60)

    threading.Thread(target=loop, name="freshdesk-sync", daemon=True).start()

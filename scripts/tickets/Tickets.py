"""Carga da base interna de tickets.

    python scripts/tickets/Tickets.py --freshdesk freshdesk_tickets_2026_completo.json --nao-entregues tickets_para_reenviar.csv
    python scripts/tickets/Tickets.py --historico scripts/todos_os_tickets_consolidados.json
    python scripts/tickets/Tickets.py --sync             # traz do Freshdesk o que mudou
    python scripts/tickets/Tickets.py --embed            # só gera embeddings pendentes
    python scripts/tickets/Tickets.py --freshdesk X.json --dry-run

Pode rodar de novo à vontade: só o que mudou é reembedado.
"""

import argparse
import csv
import json
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.internal import freshdesk
from api.internal.cleaning import clean_message, detect_project, detect_topic, is_noise

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("tickets")

def load_undelivered(path: str) -> set[int]:
    """Coluna Ticket do tickets_para_reenviar.csv: respostas que nunca saíram."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {int(row["Ticket"].lstrip("#")) for row in csv.DictReader(f, delimiter=";") if row.get("Ticket")}


def from_historico(t: dict) -> dict | None:
    raw = t.get("texto_original") or ""
    body = clean_message(raw)
    replies = [r for r in map(clean_message, t.get("respostas") or []) if len(r) > 10]
    if not replies or len(body) < 15 or is_noise("", raw, False):
        return None
    # O export antigo não diz quem escreveu cada mensagem, por isso o rótulo neutro.
    return freshdesk.finish({
        "id": f"old-{t['id']}", "origin": "historico", "freshdesk_id": None,
        "subject": body.split("\n")[0][:90],
        "content": "\n\n".join([f"CLIENTE: {body}"] + [f"CONVERSA: {r}" for r in replies]),
        "project": detect_project(raw + " ".join(t.get("respostas") or [])), "topic": detect_topic(body),
        "status": None, "has_reply": True, "delivery_suspect": False, "blocked": False, "opened_at": None,
    })


def convert(path: str, converter) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = data["tickets"] if isinstance(data, dict) else data
    tickets = [t for t in map(converter, raw) if t]
    log.info("%s: %d lidos, %d úteis, %d descartados", Path(path).name, len(raw), len(tickets), len(raw) - len(tickets))
    log.info("  projetos: %s", dict(Counter(t["project"] for t in tickets)))
    log.info("  temas: %s", dict(Counter(t["topic"] for t in tickets)))
    log.info("  com resposta: %d | entrega suspeita: %d | bloqueados: %d",
             *(sum(t[k] for t in tickets) for k in ("has_reply", "delivery_suspect", "blocked")))
    return tickets


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--freshdesk", help="export JSON do Freshdesk (com conversas)")
    ap.add_argument("--historico", help="todos_os_tickets_consolidados.json")
    ap.add_argument("--nao-entregues", help="tickets_para_reenviar.csv: marca respostas que não chegaram")
    ap.add_argument("--sync", action="store_true", help="sincroniza pela API do Freshdesk")
    ap.add_argument("--embed", action="store_true", help="só gera os embeddings pendentes")
    ap.add_argument("--no-embed", action="store_true", help="grava sem chamar a OpenAI")
    ap.add_argument("--dry-run", action="store_true", help="não grava nada")
    args = ap.parse_args()
    if not (args.freshdesk or args.historico or args.embed or args.sync):
        ap.error("informe --freshdesk, --historico, --sync ou --embed")

    undelivered = load_undelivered(args.nao_entregues) if args.nao_entregues else set()
    tickets = []
    if args.freshdesk:
        tickets += convert(args.freshdesk, lambda t: freshdesk.convert(t, undelivered))
    if args.historico:
        tickets += convert(args.historico, from_historico)
    if args.dry_run:
        return 0

    from api.database import close_pool, get_cursor, init_pool
    from api.internal import store

    init_pool(1, 2)
    try:
        store.ensure_tables()
        with get_cursor() as cur:
            for t in tickets:
                store.upsert_ticket(cur, t)
        log.info("Gravados: %d", len(tickets))
        if args.sync:
            log.info("Sincronizados: %d", freshdesk.sync())
        if not args.no_embed:
            try:
                log.info("Embeddings gerados: %d", store.embed_pending())
            except Exception as e:
                log.error("Tickets gravados, mas sem embedding (%s). Corrija a chave e rode --embed.",
                          type(e).__name__)
                return 2
    finally:
        close_pool()
    return 0


if __name__ == "__main__":
    sys.exit(main())

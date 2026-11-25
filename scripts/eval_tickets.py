"""Compara o assistente com o que a equipe respondeu em tickets reais e recentes.

O próprio ticket é escondido da busca, senão o modelo copiaria a resposta.
    python scripts/eval_tickets.py 12 semente   # outra semente sorteia outros tickets
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.database import get_cursor, init_pool
from api.internal import assistant, store
from api.internal.llm import openai_client

JUDGE = """Compare o rascunho de um assistente com a resposta REAL da equipe de suporte ao mesmo ticket.
Responda só JSON: {"nota": "bom"|"parcial"|"ruim", "inventou": true|false, "motivo": "uma frase em português"}
bom = mesma orientação, ou pede com cautela os dados que faltam; parcial = útil, mas falta algo importante;
ruim = orientação errada ou contraditória. inventou = afirma ao cliente fato, prazo, valor ou política sem apoio
nos casos consultados nem na resposta real. Dados do pedido que só a equipe vê não contam contra o assistente."""


def main(n: int, seed: str) -> None:
    init_pool(1, 3)
    tokens = {"in": 0, "out": 0, "ms": 0, "modelos": set()}

    def count(**m):
        tokens["in"] += m["tokens_in"]
        tokens["out"] += m["tokens_out"]
        tokens["ms"] += m["latency_ms"]
        tokens["modelos"].add(m["model"])

    store.save_message = count
    with get_cursor() as cur:
        cur.execute(
            """SELECT * FROM (
                 SELECT DISTINCT ON (topic, project) * FROM support_tickets
                 WHERE origin = 'freshdesk' AND has_reply AND NOT blocked AND opened_at > now() - interval '120 days'
                   AND topic IN ('entrega','peças','reembolso','endereço','campanha','compra','pagamento')
                   AND project IS NOT NULL AND length(split_part(content, 'EQUIPE:', 1)) BETWEEN 120 AND 2500
                   AND length(split_part(content, 'EQUIPE:', 2)) > 150
                 ORDER BY topic, project, md5(id || %s)) s ORDER BY md5(id) LIMIT %s""",
            (seed, n),
        )
        cases = cur.fetchall()

    original, search = store.get_ticket, store._search_tickets
    score: dict[str, int] = {}
    invented = 0
    for case in cases:
        store._search_tickets = lambda *a, _id=case["id"]: [t for t in search(*a) if t["id"] != _id]
        store.get_ticket = lambda i, _id=case["id"]: None if str(i).removeprefix("fd-") == _id[3:] else original(i)
        customer, _, rest = case["content"].partition("EQUIPE:")
        team = rest.split("\n\nCLIENTE:")[0].strip()
        question = "Escreva a resposta para este cliente:\n\n" + customer.removeprefix("CLIENTE:").strip()
        answer, sources = "", []
        for event in assistant.stream_answer(question, [], "Teste", "eval"):
            answer += event.get("content", "") if event["type"] == "token" else ""
            sources = event["sources"] if event["type"] == "sources" else sources
        context = json.dumps([{"id": s["id"], "texto": s["excerpt"]} for s in sources], ensure_ascii=False)[:9000]
        verdict = json.loads(openai_client().chat.completions.create(
            model="gpt-4.1", temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": JUDGE}, {"role": "user", "content":
                       f"TICKET:\n{customer}\n\nRESPOSTA REAL:\n{team}\n\nCASOS CONSULTADOS:\n{context}\n\n"
                       f"ASSISTENTE:\n{answer}"}],
        ).choices[0].message.content)
        score[verdict["nota"]] = score.get(verdict["nota"], 0) + 1
        invented += bool(verdict["inventou"])
        dates = [s.get("date") for s in sources if s.get("date")]
        print(f"\n=== {case['id']} | {case['project']} | {case['topic']} | {verdict['nota']} | "
              f"inventou={verdict['inventou']} | fontes até {max(dates, default='-')}")
        print("MOTIVO:", verdict["motivo"])
        print("CLIENTE:", customer[:350].replace("\n", " "))
        print("EQUIPE:", team[:350].replace("\n", " "))
        print("ASSISTENTE:", answer.split("```")[1][:450].replace("\n", " ") if "```" in answer else answer[:450])
    print("\nRESULTADO", score, "| inventou:", invented, "de", len(cases), "|", tokens)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 12, sys.argv[2] if len(sys.argv) > 2 else "")

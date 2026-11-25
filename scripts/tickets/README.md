# Base interna de tickets (BulinhIA)

Carrega os tickets anonimizados em `support_tickets`, a tabela usada só pelo
assistente interno. O chat público consulta outra tabela.

## 1. `.env` (na raiz do RAG, nunca no Git)

```
OPENAI_API_KEY=...
INTERNAL_ACCESS_CODE=um-codigo-longo-para-a-equipe
CLAUDE_API_KEY=...             # modelo principal; sem ela usa os GPT de reserva
FRESHDESK_API_KEY=...          # só leitura; sincroniza a cada 10 minutos
INTERNAL_GUEST=Padrão          # conta sem senha; só em máquina local
```

Sem `INTERNAL_ACCESS_CODE` a área interna responde 503.

## 2. Subir a API

```
docker compose up -d --build api
```

## 3. Carregar

O `scripts/` do projeto é montado em `/app/scripts`. Copie os exports para o contêiner:

```
docker compose cp freshdesk_tickets_2026_completo.json api:/tmp/fd.json
docker compose cp tickets_para_reenviar.csv api:/tmp/nao.csv
docker compose exec api python scripts/tickets/Tickets.py --freshdesk /tmp/fd.json --nao-entregues /tmp/nao.csv
docker compose exec api python scripts/tickets/Tickets.py --historico scripts/todos_os_tickets_consolidados.json
docker compose exec api rm /tmp/fd.json /tmp/nao.csv
```

Depois da carga, a API sincroniza sozinha com o Freshdesk. Pode repetir a carga: só o
que mudou é reembedado. Se a OpenAI falhar no meio,
rode `python scripts/tickets/Tickets.py --embed` para continuar.

## Limites

- A anonimização usa regex: remove e-mail, telefone, documento, link, rastreio, ID de
  pledge e a maioria dos nomes e endereços, mas não garante 100%.
- O histórico (2021–2025) não tem data nem autor por mensagem.

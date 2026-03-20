# RAG

RAG studies repository — semantic search and AI-powered Q&A using PostgreSQL (pgvector) + OpenAI.

## Como rodar

### Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) e Docker Compose instalados
- Chave de API da OpenAI ([platform.openai.com/api-keys](https://platform.openai.com/api-keys))

### Configuração

1. Copie o `.env.example` ou crie um `.env` na raiz do projeto:

```env
DB_HOST=db
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=postgres

OPENAI_API_KEY=sk-proj-SUA_CHAVE_AQUI

EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=768
LLM_MODEL=gpt-4o-mini
```

2. Substitua `sk-proj-SUA_CHAVE_AQUI` pela sua chave real da OpenAI.

### Subir tudo (API + Banco)

```bash
docker compose up -d --build
```

Na primeira execução vai demorar mais por conta do download das imagens e build. Nas próximas, sobe em segundos.

### Acessos

- **Swagger UI:** http://localhost:5001/docs
- **Frontend:** http://localhost:5173 (em dev com `npm run dev`)

## Comandos úteis

```bash
# Ver logs da API em tempo real
docker compose logs -f api

# Reiniciar a API (após alterar arquivos em api/ ou .env)
docker compose restart api

# Parar tudo
docker compose down

# Parar e apagar os dados (banco)
docker compose down -v

# Rebuild (só necessário após alterar requirements.txt, Dockerfile ou entrypoint.sh)
docker compose build --no-cache api
docker compose up -d api
```

## Quando preciso fazer rebuild?

| Alteração | Comando |
|---|---|
| Arquivos em `api/` ou `scripts/` | Nenhum — hot reload automático |
| `.env` | `docker compose restart api` |
| `requirements.txt` | `docker compose build --no-cache api && docker compose up -d api` |
| `Dockerfile` ou `entrypoint.sh` | `docker compose build --no-cache api && docker compose up -d api` |
| `docker-compose.yml` | `docker compose up -d` |

## Arquitetura

```
Pergunta do usuário
    ↓
[text-embedding-3-small] → vetor 768d → busca cosine no PostgreSQL → chunks relevantes
    ↓
[gpt-4o-mini] → recebe pergunta + chunks → gera resposta
    ↓
Resposta para o usuário
```

### Endpoints RAG

| Endpoint | Source | Max Chunks |
|---|---|---|
| `POST /api/rag/logistics` | logistics | 1 |
| `POST /api/rag/tickets` | tickets | 3 |
| `POST /api/rag/voice-tone` | voice_tone | 3 |
| `POST /api/rag/game-comments` | game_comments | 5 |

### Import

| Endpoint | Formato |
|---|---|
| `POST /api/import/logistics` | JSON (multipart/form-data) |

## Stack

- **Backend:** Flask + Flask-RESTX
- **Database:** PostgreSQL + pgvector (TimescaleDB)
- **Embeddings:** OpenAI text-embedding-3-small (768d)
- **LLM:** OpenAI gpt-4o-mini
- **Frontend:** Vue.js 3 + Pinia + Vite
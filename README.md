# RAG

RAG studies repository

## Como rodar

### Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) e Docker Compose instalados

### Subir tudo (API + Banco + Ollama)

```bash
docker compose up -d --build
```

Na primeira execução vai demorar mais por conta do download das imagens e build. Nas próximas, sobe em segundos.

### Comandos úteis

```bash
# Ver logs da API em tempo real
docker compose logs -f api

# Parar tudo
docker compose down

# Parar e apagar os dados (banco + modelos Ollama)
docker compose down -v

# Rebuild após alterar Dockerfile ou requirements.txt
docker compose up -d --build
```

### Variáveis de ambiente

O arquivo `.env` contém os valores padrão. Dentro do Docker, o `docker-compose.yml` sobrescreve o que for necessário automaticamente.
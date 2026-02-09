# RAG
RAG studies repository

# Para rodar o sistema rodar os comandos abaixo:
source venv/bin/activate.fish

docker compose up -d db
docker compose run --rm --entrypoint "python -m pgai install -d postgres://postgres:postgres@db:5432/postgres" vectorizer-worker
docker compose up -d

python3 api/app.py

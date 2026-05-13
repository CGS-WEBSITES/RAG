#!/bin/bash
set -e
DB_URL="postgres://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
echo "==> LLM Provider: ${LLM_PROVIDER:-openai}"
echo "==> Embedding: OpenAI (sempre)"
echo "==> Aguardando banco de dados..."
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -q; do
    sleep 2
done
echo "==> Instalando pgai..."
python -m pgai install -d "$DB_URL" 2>/dev/null || echo "    pgai já instalado ou não disponível, continuando..."
echo "==> Criando tabelas..."
python3 -m api.sql.setup_tables
echo "==> Configurando vectorizer..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM ai.vectorizer WHERE source_table = 'documents') THEN
        PERFORM ai.create_vectorizer(
            'public.documents'::regclass,
            loading => ai.loading_column('content'),
            embedding => ai.embedding_openai(
                '${EMBEDDING_MODEL:-text-embedding-3-small}',
                ${EMBEDDING_DIMENSIONS:-768}
            ),
            chunking => ai.chunking_recursive_character_text_splitter(
                chunk_size => 800,
                chunk_overlap => 400,
                separators => array[E'\n\n', E'\n', '.', '?', '!', ' ', '']
            ),
            formatting => ai.formatting_python_template('\$title: \$chunk')
        );
        RAISE NOTICE 'Vectorizer documents criado com sucesso';
    ELSE
        RAISE NOTICE 'Vectorizer documents já existe — pulando';
    END IF;
END
\$\$;
" 2>&1 || echo "    Erro ao configurar vectorizer documents, continuando..."

echo "==> Configurando vectorizer de manuais..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM ai.vectorizer WHERE source_table = 'manual_segments') THEN
        PERFORM ai.create_vectorizer(
            'public.manual_segments'::regclass,
            loading => ai.loading_column('content'),
            embedding => ai.embedding_openai(
                '${EMBEDDING_MODEL:-text-embedding-3-small}',
                ${EMBEDDING_DIMENSIONS:-768}
            ),
            chunking => ai.chunking_recursive_character_text_splitter(
                chunk_size => 800,
                chunk_overlap => 200,
                separators => array[E'\n\n', E'\n', '.', '?', '!', ' ', '']
            ),
            formatting => ai.formatting_python_template('\$section_title: \$chunk')
        );
        RAISE NOTICE 'Vectorizer manual_segments criado com sucesso';
    ELSE
        RAISE NOTICE 'Vectorizer manual_segments já existe — pulando';
    END IF;
END
\$\$;
" 2>&1 || echo "    Erro ao configurar vectorizer manual_segments, continuando..."

echo "==> Populando dados iniciais..."
python3 -m scripts.seed_data
echo "==> Iniciando API com Gunicorn + gthread..."
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --worker-class gthread \
    --workers 1 \
    --threads 4 \
    --timeout 600 \
    --log-level info \
    "api.app:create_app()"
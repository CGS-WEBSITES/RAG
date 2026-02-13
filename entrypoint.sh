#!/bin/bash
set -e

DB_URL="postgres://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

echo "==> Aguardando banco de dados..."
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -q; do
  sleep 2
done

echo "==> Instalando pgai..."
python -m pgai install -d "$DB_URL" 2>/dev/null || echo "    pgai já instalado ou não disponível, continuando..."

echo "==> Criando tabelas..."
python3 -m api.sql.setup_tables

echo "==> Iniciando API Flask..."
exec python3 -m api.app
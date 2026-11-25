-- Base interna da equipe. Separada de "documents" de propósito: o chat público
-- nunca consulta estas tabelas, então ticket interno não vaza para a comunidade.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS support_tickets (
    id TEXT PRIMARY KEY,                 -- fd-19487 | old-69005826069 | ok-<hex>
    origin TEXT NOT NULL,                -- freshdesk | historico | aprovada
    freshdesk_id BIGINT,
    subject TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    project TEXT,
    topic TEXT NOT NULL DEFAULT 'outros',
    status TEXT,
    has_reply BOOLEAN NOT NULL DEFAULT FALSE,
    delivery_suspect BOOLEAN NOT NULL DEFAULT FALSE,
    opened_at TIMESTAMPTZ,
    content_hash TEXT NOT NULL,
    embedding vector(768),
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', subject || ' ' || content)) STORED,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- TRUE: atendido por quem não serve de referência. Fica como registro, fora da busca.
ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS blocked BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_support_tickets_tsv ON support_tickets USING gin (tsv);
CREATE INDEX IF NOT EXISTS idx_support_tickets_opened ON support_tickets (opened_at);

CREATE TABLE IF NOT EXISTS internal_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id TEXT NOT NULL,
    author TEXT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    model TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    latency_ms INTEGER,
    source_ids TEXT[] DEFAULT '{}',
    feedback TEXT CHECK (feedback IN ('up', 'down')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS waiting BOOLEAN NOT NULL DEFAULT FALSE;  -- cliente falou por último
ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS last_at TIMESTAMPTZ;
ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS requester BIGINT;
CREATE INDEX IF NOT EXISTS idx_support_tickets_requester ON support_tickets (requester);

-- Resumos e traduções prontos, refeitos só quando o ticket muda.
CREATE TABLE IF NOT EXISTS ticket_ai (
    id TEXT, kind TEXT, content_hash TEXT NOT NULL, data JSONB NOT NULL, PRIMARY KEY (id, kind)
);

CREATE TABLE IF NOT EXISTS internal_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);

ALTER TABLE internal_messages ADD COLUMN IF NOT EXISTS sources JSONB NOT NULL DEFAULT '[]';
ALTER TABLE internal_messages ADD COLUMN IF NOT EXISTS steps JSONB NOT NULL DEFAULT '[]';
ALTER TABLE internal_messages ADD COLUMN IF NOT EXISTS cited BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE internal_messages ADD COLUMN IF NOT EXISTS approved BOOLEAN NOT NULL DEFAULT FALSE;
-- Apagar no chat só esconde: a mensagem continua valendo para as métricas.
ALTER TABLE internal_messages ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_internal_messages_author ON internal_messages (author, conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_internal_messages_created ON internal_messages (created_at DESC);

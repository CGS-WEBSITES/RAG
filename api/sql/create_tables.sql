CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS ai CASCADE;

-- Tabela principal de documentos (usada pelo vectorizer para gerar embeddings)
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_metadata_source ON documents ((metadata->>'source'));

-- Tabela de logística
CREATE TABLE IF NOT EXISTS logistica_status (
    id SERIAL PRIMARY KEY,
    id_update VARCHAR(100) UNIQUE NOT NULL,
    data_relatorio DATE,
    projeto VARCHAR(200),
    regiao VARCHAR(100),
    parceiro_logistico VARCHAR(200),
    status_atual TEXT,
    eta_warehouse VARCHAR(100),
    inicio_envios VARCHAR(100),
    conclusao_estimada VARCHAR(100),
    ocorrencias TEXT,
    links_visuais TEXT,
    observacoes_backer TEXT,
    descricao TEXT,
    embedding vector(768),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logistica_projeto ON logistica_status(projeto);
CREATE INDEX IF NOT EXISTS idx_logistica_embedding ON logistica_status USING ivfflat (embedding vector_cosine_ops);

-- Tabela de tickets
CREATE TABLE IF NOT EXISTS tickets (
    id SERIAL PRIMARY KEY,
    id_original VARCHAR(100) UNIQUE NOT NULL,
    pergunta TEXT NOT NULL,
    resposta TEXT,
    projeto VARCHAR(200),
    embedding vector(768),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tickets_projeto ON tickets(projeto);
CREATE INDEX IF NOT EXISTS idx_tickets_embedding ON tickets USING ivfflat (embedding vector_cosine_ops);

-- Tabela de conhecimento de IPs (Tom de Voz)
CREATE TABLE IF NOT EXISTS conhecimento_ips (
    id SERIAL PRIMARY KEY,
    ip_nome VARCHAR(200) NOT NULL,
    categoria VARCHAR(200) NOT NULL,
    conteudo TEXT NOT NULL,
    embedding vector(768),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conhecimento_ip ON conhecimento_ips(ip_nome);
CREATE INDEX IF NOT EXISTS idx_conhecimento_categoria ON conhecimento_ips(categoria);
CREATE INDEX IF NOT EXISTS idx_conhecimento_embedding ON conhecimento_ips USING ivfflat (embedding vector_cosine_ops);

-- Histórico de conversas do RAG
CREATE TABLE IF NOT EXISTS chat_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(100) NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category VARCHAR(100),
    model VARCHAR(100),
    provider VARCHAR(50),
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    sources_count INTEGER DEFAULT 0,
    feedback VARCHAR(10),
    language VARCHAR(10),
    satisfaction BOOLEAN DEFAULT NULL,
    refinement_round INTEGER DEFAULT 0,
    parent_message_id UUID DEFAULT NULL REFERENCES chat_history (id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_history_session ON chat_history(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_category ON chat_history(category);
CREATE INDEX IF NOT EXISTS idx_chat_history_created ON chat_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_history_satisfaction ON chat_history(satisfaction);
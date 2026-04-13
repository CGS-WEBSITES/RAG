ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS parent_message_id UUID DEFAULT NULL REFERENCES chat_history (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_chat_history_parent_message_id ON chat_history(parent_message_id);

ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT NULL;
ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS satisfaction BOOLEAN DEFAULT NULL;
ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS refinement_round INTEGER DEFAULT 0;

-- Manual segments table
CREATE TABLE IF NOT EXISTS manual_segments (
    id SERIAL PRIMARY KEY,
    manual_id INTEGER NOT NULL,
    project VARCHAR(200) NOT NULL,
    page_number INTEGER,
    section_title TEXT,
    content TEXT NOT NULL,
    image_path TEXT,
    image_description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_manual_segments_project ON manual_segments(project);
CREATE INDEX IF NOT EXISTS idx_manual_segments_manual_id ON manual_segments(manual_id);

-- pgai vectorizer for manual_segments
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM ai.vectorizer WHERE source_table = 'manual_segments') THEN
        PERFORM ai.create_vectorizer(
            'public.manual_segments'::regclass,
            loading => ai.loading_column('content'),
            embedding => ai.embedding_openai(
                'text-embedding-3-small',
                768
            ),
            chunking => ai.chunking_recursive_character_text_splitter(
                chunk_size => 800,
                chunk_overlap => 200,
                separators => array[E'\n\n', E'\n', '.', '?', '!', ' ', '']
            ),
            formatting => ai.formatting_python_template('$title: $chunk')
        );
        RAISE NOTICE 'Vectorizer for manual_segments created';
    ELSE
        RAISE NOTICE 'Vectorizer for manual_segments already exists';
    END IF;
END
$$;
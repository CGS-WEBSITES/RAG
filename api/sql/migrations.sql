ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS parent_message_id UUID DEFAULT NULL REFERENCES chat_history (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_chat_history_parent_message_id ON chat_history(parent_message_id);

ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT NULL;
ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS satisfaction BOOLEAN DEFAULT NULL;
ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS refinement_round INTEGER DEFAULT 0;
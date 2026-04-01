ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS language           VARCHAR(10)  DEFAULT NULL;
ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS satisfaction        BOOLEAN      DEFAULT NULL;
ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS refinement_round   INTEGER      DEFAULT 0;
ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS parent_message_id  UUID         DEFAULT NULL;
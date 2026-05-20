CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'role_enum') THEN
        CREATE TYPE role_enum AS ENUM ('user', 'admin');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'visibility_enum') THEN
        CREATE TYPE visibility_enum AS ENUM ('global', 'user');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'document_status_enum') THEN
        CREATE TYPE document_status_enum AS ENUM ('uploaded', 'processing', 'ready', 'error');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL UNIQUE,
    username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    full_name VARCHAR(512),
    role role_enum NOT NULL DEFAULT 'user',
    department VARCHAR(255),
    project_context TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    original_filename VARCHAR(500) NOT NULL,
    stored_path VARCHAR(1000) NOT NULL,
    file_type VARCHAR(20) NOT NULL,
    visibility visibility_enum NOT NULL,
    owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    module_number INTEGER,
    module_title VARCHAR(255),
    lesson_key VARCHAR(100),
    material_type VARCHAR(100),
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    status document_status_enum NOT NULL DEFAULT 'uploaded',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(1536) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_chunks_document_chunk_index UNIQUE (document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode VARCHAR(100) NOT NULL DEFAULT 'general',
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    token_usage JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_notification_settings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    notification_time VARCHAR(5) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notification_key VARCHAR(100) NOT NULL,
    delivery_date DATE NOT NULL,
    scheduled_time VARCHAR(5) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'sent',
    error_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_notification_delivery_user_key_date_time UNIQUE (
        user_id,
        notification_key,
        delivery_date,
        scheduled_time
    )
);

CREATE TABLE IF NOT EXISTS user_files (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    telegram_file_id VARCHAR(512) NOT NULL,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    original_filename VARCHAR(500) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS app_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS program_media (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    media_type VARCHAR(50) NOT NULL,
    telegram_file_id VARCHAR(512) NOT NULL,
    telegram_file_unique_id VARCHAR(512),
    telegram_kind VARCHAR(50) NOT NULL,
    original_filename VARCHAR(500),
    file_size BIGINT,
    mime_type VARCHAR(255),
    module_number INTEGER,
    module_title VARCHAR(255),
    lesson_key VARCHAR(100),
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS errors (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    context VARCHAR(255) NOT NULL,
    error_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS ix_documents_visibility_owner ON documents(visibility, owner_user_id);
CREATE INDEX IF NOT EXISTS ix_documents_module_number ON documents(module_number);
CREATE INDEX IF NOT EXISTS ix_documents_lesson_key ON documents(lesson_key);
CREATE INDEX IF NOT EXISTS ix_chunks_document_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS ix_messages_user_created_at ON messages(user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_user_notification_settings_user_id ON user_notification_settings(user_id);
CREATE INDEX IF NOT EXISTS ix_notification_deliveries_user_id ON notification_deliveries(user_id);
CREATE INDEX IF NOT EXISTS ix_user_files_user_id ON user_files(user_id);
CREATE INDEX IF NOT EXISTS ix_user_files_document_id ON user_files(document_id);
CREATE INDEX IF NOT EXISTS ix_program_media_type_created_at ON program_media(media_type, created_at);
CREATE INDEX IF NOT EXISTS ix_program_media_module_number ON program_media(module_number);
CREATE INDEX IF NOT EXISTS ix_program_media_lesson_key ON program_media(lesson_key);
CREATE INDEX IF NOT EXISTS ix_errors_created_at ON errors(created_at DESC);

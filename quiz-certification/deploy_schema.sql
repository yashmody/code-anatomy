-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS hstore;

-- 1. Users table (stores authentication and RBAC roles)
CREATE TABLE IF NOT EXISTS users (
    email VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255),
    picture VARCHAR(1024),
    role VARCHAR(32), -- 'FeedCreator', 'Moderator', 'QuizManager', 'User'
    provider VARCHAR(32), -- 'google', 'dev'
    preferences hstore DEFAULT ''::hstore, -- Flat key-value user settings
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 2. Questions table (stores quiz question bank with versioning)
CREATE TABLE IF NOT EXISTS questions (
    id VARCHAR(64) PRIMARY KEY,
    topic VARCHAR(128) NOT NULL,
    difficulty VARCHAR(16) NOT NULL,
    question TEXT NOT NULL,
    options JSONB NOT NULL, -- Array of string choices
    correct_index INT NOT NULL,
    explanation TEXT,
    status VARCHAR(32) DEFAULT 'draft', -- 'draft', 'pending_review', 'published', 'archived'
    version INT DEFAULT 1,
    author_id VARCHAR(255) REFERENCES users(email) ON DELETE SET NULL,
    is_user_submitted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_questions_lookup ON questions(status, difficulty, topic);

-- 3. Attempts table (stores history of user submissions)
CREATE TABLE IF NOT EXISTS attempts (
    id SERIAL PRIMARY KEY,
    test_code VARCHAR(32) UNIQUE NOT NULL,
    cert_id VARCHAR(64) UNIQUE,
    quiz_id VARCHAR(64) NOT NULL,
    user_email VARCHAR(255) REFERENCES users(email) ON DELETE CASCADE,
    difficulty VARCHAR(16) NOT NULL,
    score NUMERIC(5,2) NOT NULL,
    correct INT NOT NULL,
    total INT NOT NULL,
    passed BOOLEAN NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    submitted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    certificate_path TEXT,
    signature VARCHAR(64), -- HMAC anti-tamper seal
    payload JSONB NOT NULL, -- Graded questions, answers, and explanations
    metadata hstore DEFAULT ''::hstore
);
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_email, submitted_at DESC);

-- 4. Feed Items table (stores social posts and scenarios)
CREATE TABLE IF NOT EXISTS feed_items (
    id VARCHAR(64) PRIMARY KEY,
    type VARCHAR(32) NOT NULL, -- 'post', 'video', 'list', 'card', 'vocab', 'scenario'
    status VARCHAR(32) NOT NULL DEFAULT 'published', -- 'draft', 'pending_review', 'published', 'flagged', 'removed'
    author_id VARCHAR(255) REFERENCES users(email) ON DELETE SET NULL,
    framework_ref VARCHAR(64),
    topics TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    data JSONB NOT NULL, -- Payload containing media refs, comments, engagement counters
    search tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(data->>'title','') || ' ' || coalesce(data->>'body',''))
    ) STORED
);
CREATE INDEX IF NOT EXISTS idx_feed_items_ordering ON feed_items (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feed_items_topics ON feed_items USING gin (topics);
CREATE INDEX IF NOT EXISTS idx_feed_items_search ON feed_items USING gin (search);

-- 5. Media Assets Metadata Table (references pg_largeobject OIDs)
CREATE TABLE IF NOT EXISTS media_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    large_object_oid OID NOT NULL, -- Reference to Postgres system pg_largeobject
    filename VARCHAR(255) NOT NULL,
    mime_type VARCHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL,
    uploaded_by VARCHAR(255) REFERENCES users(email) ON DELETE SET NULL,
    uploaded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Enable pgvector extension on startup
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS dblink;

-- Create test database (used by CI)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ai_platform_test') THEN
        PERFORM dblink_exec('dbname=postgres', 'CREATE DATABASE ai_platform_test OWNER platform');
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- Base application schema (idempotent — safe to re-run)
-- Mirrors platform/storage/postgres.py _DDL so the schema exists before
-- the API container starts. ensure_schema() at startup is then a no-op.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS uploads (
    upload_id   TEXT         PRIMARY KEY,
    product_id  TEXT         NOT NULL,
    filename    TEXT         NOT NULL,
    wave        INTEGER      NOT NULL DEFAULT 1,
    country     TEXT         NOT NULL DEFAULT '',
    status      TEXT         NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fitments (
    id                BIGSERIAL    PRIMARY KEY,
    atom_id           TEXT         NOT NULL,
    upload_id         TEXT         NOT NULL,
    product_id        TEXT         NOT NULL,
    module            TEXT         NOT NULL,
    country           TEXT         NOT NULL,
    wave              INTEGER      NOT NULL,
    classification    TEXT         NOT NULL,
    confidence        FLOAT        NOT NULL,
    rationale         TEXT         NOT NULL,
    reviewer_override BOOLEAN      NOT NULL DEFAULT FALSE,
    consultant        TEXT,
    embedding         vector(384),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    -- V1: capability reference for audit and future retrieval use
    d365_capability_ref TEXT,
    -- V2: classification detail fields
    config_steps        TEXT,
    gap_description     TEXT,
    configuration_steps JSONB,
    dev_effort          TEXT,
    gap_type            TEXT
);

CREATE INDEX IF NOT EXISTS fitments_hnsw
    ON fitments USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Migration tracking — records which V*.sql files have been applied.
-- Pre-seeded with the baseline migrations so that fresh Docker installs
-- (which get the full schema from this file) don't re-apply them via
-- `make db-migrate`.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version) VALUES ('V0__base_schema')               ON CONFLICT DO NOTHING;
INSERT INTO schema_migrations (version) VALUES ('V1__add_fitments_capability_ref') ON CONFLICT DO NOTHING;
INSERT INTO schema_migrations (version) VALUES ('V2__add_fitments_classification_fields') ON CONFLICT DO NOTHING;

-- V0: Base schema — idempotent, safe to re-run on any state.
-- Creates the pgvector extension, uploads table, fitments table, and HNSW index.
-- Run this before V1+ migrations when upgrading a database that has no schema yet.

CREATE EXTENSION IF NOT EXISTS vector;

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
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS fitments_hnsw
    ON fitments USING hnsw (embedding vector_cosine_ops);

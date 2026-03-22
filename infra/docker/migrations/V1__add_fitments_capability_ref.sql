-- V1: Store d365_capability_ref on fitments for audit and future retrieval use.
-- ClassificationResult.d365_capability_ref was not persisted at initial schema creation.
-- ADD COLUMN IF NOT EXISTS is idempotent — safe to re-run.
ALTER TABLE fitments
    ADD COLUMN IF NOT EXISTS d365_capability_ref TEXT;

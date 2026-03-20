-- Enable pgvector extension on startup
CREATE EXTENSION IF NOT EXISTS vector;

-- Create test database (used by CI)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ai_platform_test') THEN
        PERFORM dblink_exec('dbname=postgres', 'CREATE DATABASE ai_platform_test OWNER platform');
    END IF;
END
$$;

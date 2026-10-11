-- Infrastructure only. Filing, authentication and business schemas belong to later phases.
CREATE SCHEMA regintel;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public VERSION '0.8.7';

DO $$
BEGIN
    IF (SELECT extversion FROM pg_extension WHERE extname = 'vector') <> '0.8.7' THEN
        RAISE EXCEPTION 'Expected pgvector extension version 0.8.7';
    END IF;
END;
$$;

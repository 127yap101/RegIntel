-- Mutable processing bookkeeping is separate from immutable filing/parse authority.
CREATE TABLE regintel.filing_ingestion_keys (
    source_blob_id regintel.canonical_id PRIMARY KEY REFERENCES regintel.source_blobs(id),
    filing_version_id regintel.canonical_id NOT NULL UNIQUE,
    metadata_sha256 regintel.sha256_hash NOT NULL,
    FOREIGN KEY (filing_version_id, source_blob_id)
        REFERENCES regintel.filing_versions(id, source_blob_id)
);
CREATE TRIGGER immutable_ingestion_keys BEFORE UPDATE OR DELETE ON regintel.filing_ingestion_keys
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_ingestion_keys_truncate BEFORE TRUNCATE ON regintel.filing_ingestion_keys
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

CREATE TABLE regintel.filing_jobs (
    id regintel.canonical_id PRIMARY KEY,
    filing_version_id regintel.canonical_id NOT NULL,
    source_blob_id regintel.canonical_id NOT NULL,
    configuration_sha256 regintel.sha256_hash NOT NULL,
    state TEXT NOT NULL DEFAULT 'QUEUED'
        CHECK (state IN ('QUEUED', 'RUNNING', 'SOURCE_VERIFIED', 'FAILED')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    page_count INTEGER CHECK (page_count BETWEEN 1 AND 2000),
    failure_code TEXT CHECK (failure_code IN ('SOURCE_HASH_MISMATCH', 'INVALID_PDF',
        'PAGE_LIMIT', 'ENCRYPTED_PDF', 'SOURCE_UNAVAILABLE', 'WORKER_CONFIGURATION_MISMATCH')),
    submitted_by UUID NOT NULL REFERENCES regintel.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (filing_version_id, source_blob_id)
        REFERENCES regintel.filing_versions(id, source_blob_id),
    UNIQUE (filing_version_id, configuration_sha256),
    CHECK ((state = 'FAILED') = (failure_code IS NOT NULL)),
    CHECK ((state = 'SOURCE_VERIFIED') = (page_count IS NOT NULL)),
    CHECK ((state = 'QUEUED') = (attempts = 0))
);
CREATE FUNCTION regintel.guard_job_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'QUEUED' OR NEW.attempts <> 0 THEN
            RAISE EXCEPTION 'A job starts queued' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.id, NEW.filing_version_id, NEW.source_blob_id,
               NEW.configuration_sha256, NEW.submitted_by, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.id, OLD.filing_version_id, OLD.source_blob_id,
                                OLD.configuration_sha256, OLD.submitted_by, OLD.created_at)
           OR OLD.state IN ('SOURCE_VERIFIED', 'FAILED')
           OR NOT ((NEW.state = 'RUNNING' AND NEW.attempts = OLD.attempts + 1)
                   OR (OLD.state = 'RUNNING' AND NEW.state IN ('SOURCE_VERIFIED', 'FAILED')
                       AND NEW.attempts = OLD.attempts)) THEN
            RAISE EXCEPTION 'Invalid job transition' USING ERRCODE = '23514';
        END IF;
        NEW.updated_at = clock_timestamp();
    ELSE
        RAISE EXCEPTION 'Jobs cannot be removed' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER job_transitions BEFORE INSERT OR UPDATE OR DELETE ON regintel.filing_jobs
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_job_transition();
CREATE TRIGGER jobs_no_truncate BEFORE TRUNCATE ON regintel.filing_jobs
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

CREATE TABLE regintel.job_dispatch (
    job_id regintel.canonical_id PRIMARY KEY REFERENCES regintel.filing_jobs(id),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    sent_at TIMESTAMPTZ,
    last_failure_code TEXT CHECK (last_failure_code = 'BROKER_UNAVAILABLE')
);

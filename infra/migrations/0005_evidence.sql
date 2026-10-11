-- M1.4 adds exact evidence results; prior migrations and legacy jobs stay intact.
ALTER TABLE regintel.filing_jobs ADD COLUMN parse_version_id regintel.canonical_id
    REFERENCES regintel.parse_versions(id);
ALTER TABLE regintel.filing_jobs DROP CONSTRAINT filing_jobs_state_check;
ALTER TABLE regintel.filing_jobs ADD CONSTRAINT filing_jobs_state_check
    CHECK (state IN ('QUEUED', 'RUNNING', 'SOURCE_VERIFIED', 'PARSED', 'FAILED'));
ALTER TABLE regintel.filing_jobs DROP CONSTRAINT filing_jobs_failure_code_check;
ALTER TABLE regintel.filing_jobs ADD CONSTRAINT filing_jobs_failure_code_check
    CHECK (failure_code IN ('SOURCE_HASH_MISMATCH', 'INVALID_PDF', 'PAGE_LIMIT',
        'ENCRYPTED_PDF', 'SOURCE_UNAVAILABLE', 'WORKER_CONFIGURATION_MISMATCH',
        'PARSE_FAILED', 'ARTIFACT_INVALID', 'PARSER_CONFIGURATION_MISMATCH'));
ALTER TABLE regintel.filing_jobs DROP CONSTRAINT filing_jobs_check1;
ALTER TABLE regintel.filing_jobs ADD CONSTRAINT filing_jobs_page_result_check
    CHECK ((state IN ('SOURCE_VERIFIED', 'PARSED')) = (page_count IS NOT NULL));
ALTER TABLE regintel.filing_jobs ADD CONSTRAINT filing_jobs_parse_result_check
    CHECK ((state = 'PARSED') = (parse_version_id IS NOT NULL));

CREATE OR REPLACE FUNCTION regintel.guard_job_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'QUEUED' OR NEW.attempts <> 0 OR NEW.parse_version_id IS NOT NULL THEN
            RAISE EXCEPTION 'A job starts queued' USING ERRCODE = '23514';
        END IF;
    ELSIF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.id, NEW.filing_version_id, NEW.source_blob_id,
               NEW.configuration_sha256, NEW.submitted_by, NEW.created_at)
           IS DISTINCT FROM ROW(OLD.id, OLD.filing_version_id, OLD.source_blob_id,
                                OLD.configuration_sha256, OLD.submitted_by, OLD.created_at)
           OR OLD.state IN ('SOURCE_VERIFIED', 'PARSED', 'FAILED')
           OR NOT ((NEW.state = 'RUNNING' AND NEW.attempts = OLD.attempts + 1)
                   OR (OLD.state = 'RUNNING' AND NEW.state IN ('SOURCE_VERIFIED', 'PARSED', 'FAILED')
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

CREATE TABLE regintel.parse_artifacts (
    parse_version_id regintel.canonical_id PRIMARY KEY REFERENCES regintel.parse_versions(id),
    job_id regintel.canonical_id NOT NULL UNIQUE REFERENCES regintel.filing_jobs(id),
    artifact_bytes BYTEA NOT NULL CHECK (octet_length(artifact_bytes) BETWEEN 1 AND 67108864),
    configuration_bytes BYTEA NOT NULL CHECK (octet_length(configuration_bytes) BETWEEN 1 AND 65536)
);
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.parse_artifacts
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.parse_artifacts
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER parse_tree_insert_gate AFTER INSERT ON regintel.parse_artifacts
    FOR EACH ROW EXECUTE FUNCTION regintel.require_parse_creation_transaction();

CREATE FUNCTION regintel.validate_parse_artifact() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner RECORD; artifact JSONB; configuration JSONB; provenance JSONB; field_name TEXT;
BEGIN
    SELECT p.*, j.filing_version_id AS job_version, j.source_blob_id AS job_source,
        j.configuration_sha256 AS job_configuration, j.state AS job_state,
        v.filing_id, s.sha256 AS source_sha256, s.byte_size
        INTO owner FROM regintel.parse_versions p
        JOIN regintel.filing_jobs j ON j.id = NEW.job_id
        JOIN regintel.filing_versions v ON v.id = p.filing_version_id
        JOIN regintel.source_blobs s ON s.id = p.source_blob_id
        WHERE p.id = NEW.parse_version_id;
    IF NOT FOUND OR owner.job_state <> 'RUNNING'
       OR owner.creation_transaction <> txid_current()
       OR owner.job_version IS DISTINCT FROM owner.filing_version_id
       OR owner.job_source IS DISTINCT FROM owner.source_blob_id
       OR owner.job_configuration IS DISTINCT FROM owner.configuration_sha256
       OR encode(sha256(NEW.artifact_bytes), 'hex') IS DISTINCT FROM owner.artifact_sha256
       OR encode(sha256(NEW.configuration_bytes), 'hex') IS DISTINCT FROM owner.configuration_sha256 THEN
        RAISE EXCEPTION 'Parse artifact identity must match its running source job'
            USING ERRCODE = '23514';
    END IF;
    artifact := convert_from(NEW.artifact_bytes, 'UTF8')::jsonb;
    configuration := convert_from(NEW.configuration_bytes, 'UTF8')::jsonb;
    provenance := artifact -> 'provenance';
    IF jsonb_typeof(artifact) IS DISTINCT FROM 'object'
       OR jsonb_typeof(configuration) IS DISTINCT FROM 'object'
       OR jsonb_typeof(provenance) IS DISTINCT FROM 'object'
       OR artifact ->> 'schema_version' IS DISTINCT FROM '1.0.0'
       OR configuration ->> 'schema_version' IS DISTINCT FROM '1.0.0'
       OR configuration ->> 'adapter_name' IS DISTINCT FROM 'regintel-docling'
       OR configuration ->> 'adapter_version' IS DISTINCT FROM '1.0.0'
       OR artifact ->> 'id' IS DISTINCT FROM owner.id::text
       OR artifact ->> 'filing_id' IS DISTINCT FROM owner.filing_id::text
       OR artifact ->> 'filing_version_id' IS DISTINCT FROM owner.filing_version_id::text
       OR artifact ->> 'source_blob_id' IS DISTINCT FROM owner.source_blob_id::text
       OR artifact ->> 'source_sha256' IS DISTINCT FROM owner.source_sha256::text
       OR provenance ->> 'adapter_name' IS DISTINCT FROM owner.adapter_name::text
       OR provenance ->> 'adapter_version' IS DISTINCT FROM owner.adapter_version::text
       OR configuration ->> 'adapter_name' IS DISTINCT FROM owner.adapter_name::text
       OR configuration ->> 'adapter_version' IS DISTINCT FROM owner.adapter_version::text
       OR provenance ->> 'backend_name' IS DISTINCT FROM 'ThreadedDoclingParseDocumentBackend'
       OR jsonb_typeof(provenance -> 'backend_version') IS DISTINCT FROM 'string'
       OR provenance ->> 'configuration_sha256'
            IS DISTINCT FROM configuration ->> 'sdk_configuration_sha256'
       OR provenance ->> 'coordinate_frame' IS DISTINCT FROM configuration ->> 'coordinate_frame'
       OR jsonb_typeof(configuration -> 'coordinate_frame') IS DISTINCT FROM 'string'
       OR configuration ->> 'coordinate_frame' NOT IN ('RAW_PDF_BOTTOM_LEFT',
            'MEDIA_RELATIVE_BOTTOM_LEFT', 'CROP_ROTATED_BOTTOM_LEFT', 'CROP_ROTATED_TOP_LEFT')
       OR provenance ->> 'adapter_code_sha256'
            IS DISTINCT FROM configuration ->> 'adapter_code_sha256'
       OR provenance ->> 'backend_code_sha256'
            IS DISTINCT FROM configuration ->> 'backend_code_sha256'
       OR provenance ->> 'model_manifest_sha256'
            IS DISTINCT FROM configuration ->> 'model_manifest_sha256'
       OR provenance ->> 'package_manifest_sha256'
            IS DISTINCT FROM configuration ->> 'package_manifest_sha256'
       OR jsonb_typeof(artifact -> 'pages') IS DISTINCT FROM 'array'
       OR jsonb_typeof(artifact -> 'blocks') IS DISTINCT FROM 'array'
       OR jsonb_typeof(artifact -> 'tables') IS DISTINCT FROM 'array'
       OR jsonb_typeof(artifact -> 'diagnostics') IS DISTINCT FROM 'array'
       OR jsonb_typeof(provenance -> 'packages') IS DISTINCT FROM 'array'
       OR jsonb_typeof(configuration -> 'source_limits') IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'Parse artifact metadata must match its retained configuration'
            USING ERRCODE = '23514';
    END IF;
    FOREACH field_name IN ARRAY ARRAY['adapter_code_sha256','geometry_code_sha256',
        'sdk_code_sha256','artifact_models_code_sha256','sdk_configuration_sha256',
        'model_manifest_sha256','package_manifest_sha256','backend_code_sha256'] LOOP
        IF jsonb_typeof(configuration -> field_name) IS DISTINCT FROM 'string'
           OR configuration ->> field_name IS NULL
           OR configuration ->> field_name !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'Configuration hashes must be explicit' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF jsonb_array_length(artifact -> 'pages') IS DISTINCT FROM owner.page_count
       OR jsonb_typeof(configuration #> '{source_limits,max_pages}') IS DISTINCT FROM 'number'
       OR jsonb_typeof(configuration #> '{source_limits,max_file_bytes}') IS DISTINCT FROM 'number'
       OR owner.page_count > (configuration #>> '{source_limits,max_pages}')::bigint
       OR owner.byte_size > (configuration #>> '{source_limits,max_file_bytes}')::bigint
       OR (configuration #>> '{source_limits,max_pages}')::bigint NOT BETWEEN 1 AND 2000
       OR (configuration #>> '{source_limits,max_file_bytes}')::bigint NOT BETWEEN 1 AND 67108864
       OR provenance ->> 'backend_version' IS DISTINCT FROM
            (SELECT item ->> 'version' FROM jsonb_array_elements(provenance -> 'packages') item
             WHERE item ->> 'name' = 'docling-parse') THEN
        RAISE EXCEPTION 'Parse artifact source limits and backend must match'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'Parse artifact is invalid or mismatches its source/configuration'
        USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER validate_parse_artifact BEFORE INSERT ON regintel.parse_artifacts
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_parse_artifact();

-- This predicate mirrors the supported low-level projection markers. The worker
-- additionally recomputes every raw quadrilateral using the calibrated adapter.
CREATE FUNCTION regintel.exact_artifact_block_eligible(item JSONB) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE reported JSONB;
BEGIN
    IF jsonb_typeof(item -> 'orig') IS DISTINCT FROM 'string'
       OR jsonb_typeof(item -> 'page_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(item -> 'page_index') IS DISTINCT FROM 'number'
       OR jsonb_typeof(item -> 'source_cell_index') IS DISTINCT FROM 'number'
       OR jsonb_typeof(item -> 'from_ocr') IS DISTINCT FROM 'boolean'
       OR item -> 'unavailable_reasons' IS DISTINCT FROM '[]'::jsonb
       OR jsonb_typeof(item -> 'boxes') IS DISTINCT FROM 'array'
       OR jsonb_typeof(item -> 'exact_spans') IS DISTINCT FROM 'array'
       OR jsonb_typeof(item -> 'provenance') IS DISTINCT FROM 'array' THEN RETURN FALSE;
    END IF;
    IF jsonb_array_length(item -> 'boxes') <> 1
       OR jsonb_array_length(item -> 'exact_spans') < 1
       OR jsonb_array_length(item -> 'provenance') <> 1 THEN RETURN FALSE;
    END IF;
    reported := item #> '{provenance,0}';
    RETURN jsonb_typeof(reported -> 'raw_rectangle') = 'object'
        AND reported -> 'raw_box' = 'null'::jsonb
        AND reported -> 'charspan' = 'null'::jsonb
        AND reported ->> 'source_ref' = item ->> 'source_ref'
        AND reported ->> 'page_no' = ((item ->> 'page_index')::bigint + 1)::text
        AND item ->> 'source_ref' = ('page/' || (item ->> 'page_index') || '/text-cell/'
            || (item ->> 'source_cell_index'))
        AND (item ->> 'source_cell_index') ~ '^(0|[1-9][0-9]{0,15})$'
        AND (item ->> 'source_cell_index')::bigint BETWEEN 0 AND 9007199254740991;
EXCEPTION WHEN OTHERS THEN RETURN FALSE;
END;
$$;

CREATE FUNCTION regintel.require_complete_parse_result() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parse_id UUID; trigger_job UUID; result RECORD; artifact JSONB;
BEGIN
    parse_id := NEW.parse_version_id;
    IF TG_TABLE_NAME = 'filing_jobs' THEN trigger_job := NEW.id;
    ELSE trigger_job := NEW.job_id;
    END IF;
    SELECT p.*, j.id AS job_id, j.state AS job_state, j.parse_version_id AS job_parse,
        j.filing_version_id AS job_version, j.source_blob_id AS job_source,
        j.configuration_sha256 AS job_configuration, j.page_count AS job_pages,
        a.artifact_bytes INTO result
        FROM regintel.parse_versions p JOIN regintel.parse_artifacts a ON a.parse_version_id=p.id
        JOIN regintel.filing_jobs j ON j.id=a.job_id WHERE p.id=parse_id;
    IF NOT FOUND OR result.job_state <> 'PARSED' OR result.job_parse IS DISTINCT FROM parse_id
       OR result.job_id IS DISTINCT FROM trigger_job
       OR result.job_version IS DISTINCT FROM result.filing_version_id
       OR result.job_source IS DISTINCT FROM result.source_blob_id
       OR result.job_configuration IS DISTINCT FROM result.configuration_sha256
       OR result.job_pages IS DISTINCT FROM result.page_count
       OR result.creation_transaction <> txid_current() THEN
        RAISE EXCEPTION 'A parsed job needs its complete immutable matching result'
            USING ERRCODE = '23514';
    END IF;
    artifact := convert_from(result.artifact_bytes, 'UTF8')::jsonb;
    IF result.table_count <> 0 OR result.cell_count <> 0
       OR EXISTS (SELECT FROM regintel.tables WHERE parse_version_id=parse_id)
       OR EXISTS (SELECT FROM regintel.cells WHERE parse_version_id=parse_id)
       OR result.block_count <> (SELECT count(*) FROM jsonb_array_elements(artifact -> 'blocks') b
            WHERE jsonb_typeof(b -> 'orig')='string' AND jsonb_typeof(b -> 'page_id')='string')
       OR result.evidence_count <> (SELECT coalesce(sum(jsonb_array_length(b -> 'exact_spans')),0)
            FROM jsonb_array_elements(artifact -> 'blocks') b
            WHERE regintel.exact_artifact_block_eligible(b))
       OR EXISTS (SELECT FROM regintel.evidence WHERE parse_version_id=parse_id AND kind <> 'text') THEN
        RAISE EXCEPTION 'The relational projection must retain original text and exact support only'
            USING ERRCODE = '23514';
    END IF;
    -- Compare original page geometry and Unicode blocks in both directions; SDK
    -- processed tables and missing/mislocated original text remain in the sidecar.
    IF EXISTS (
        (SELECT p.id::text,p.page_index,p.width,p.height,p.media_x0,p.media_y0,p.media_x1,p.media_y1,
             p.crop_x0,p.crop_y0,p.crop_x1,p.crop_y1,p.rotation,p.coordinate_space,p.origin
         FROM regintel.pages p WHERE p.parse_version_id=parse_id
         EXCEPT
         SELECT b ->> 'id',(b ->> 'page_index')::bigint,(b #>> '{geometry,width}')::float8,
             (b #>> '{geometry,height}')::float8,(b #>> '{geometry,media_box,x0}')::float8,
             (b #>> '{geometry,media_box,y0}')::float8,(b #>> '{geometry,media_box,x1}')::float8,
             (b #>> '{geometry,media_box,y1}')::float8,(b #>> '{geometry,crop_box,x0}')::float8,
             (b #>> '{geometry,crop_box,y0}')::float8,(b #>> '{geometry,crop_box,x1}')::float8,
             (b #>> '{geometry,crop_box,y1}')::float8,(b #>> '{geometry,rotation}')::smallint,
             b #>> '{geometry,coordinate_space}',b #>> '{geometry,origin}'
         FROM jsonb_array_elements(artifact -> 'pages') b)
    ) OR EXISTS (
        SELECT FROM regintel.blocks r WHERE r.parse_version_id=parse_id AND NOT EXISTS (
            SELECT FROM jsonb_array_elements(artifact -> 'blocks') b
            WHERE b ->> 'id'=r.id::text AND b ->> 'page_id'=r.page_id::text AND b ->> 'orig'=r.text)
    ) OR EXISTS (
        SELECT FROM jsonb_array_elements(artifact -> 'blocks') b
        WHERE jsonb_typeof(b -> 'orig')='string' AND jsonb_typeof(b -> 'page_id')='string'
        AND NOT EXISTS (SELECT FROM regintel.blocks r WHERE r.parse_version_id=parse_id
            AND r.id::text=b ->> 'id' AND r.page_id::text=b ->> 'page_id' AND r.text=b ->> 'orig')
    ) THEN
        RAISE EXCEPTION 'Projection page geometry and original Unicode must match the artifact'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT FROM regintel.evidence e WHERE e.parse_version_id=parse_id AND NOT EXISTS (
            SELECT FROM jsonb_array_elements(artifact -> 'blocks') b
            CROSS JOIN LATERAL jsonb_array_elements(b -> 'exact_spans') span
            WHERE regintel.exact_artifact_block_eligible(b)
            AND b ->> 'id'=e.block_id::text AND b ->> 'page_id'=e.page_id::text
            AND span ->> 'block_id'=e.block_id::text
            AND (span ->> 'start')::bigint=e.start_offset AND (span ->> 'end')::bigint=e.end_offset
            AND span ->> 'quote'=e.quote
            AND b -> 'boxes'=(SELECT jsonb_agg(jsonb_build_object('x0',x0,'y0',y0,'x1',x1,'y1',y1)
                 ORDER BY box_index) FROM regintel.evidence_boxes WHERE evidence_id=e.id))
    ) OR EXISTS (
        SELECT FROM jsonb_array_elements(artifact -> 'blocks') b
        CROSS JOIN LATERAL jsonb_array_elements(b -> 'exact_spans') span
        WHERE regintel.exact_artifact_block_eligible(b) AND NOT EXISTS (
            SELECT FROM regintel.evidence e WHERE e.parse_version_id=parse_id
            AND e.block_id::text=b ->> 'id' AND e.start_offset=(span ->> 'start')::bigint
            AND e.end_offset=(span ->> 'end')::bigint AND e.quote=span ->> 'quote')
    ) OR EXISTS (
        SELECT FROM regintel.evidence WHERE parse_version_id=parse_id
        GROUP BY block_id,start_offset,end_offset,quote HAVING count(*) <> 1
    ) THEN
        RAISE EXCEPTION 'Every exact evidence span and box must match eligible original support'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'A parsed job needs its complete immutable matching projection'
        USING ERRCODE = '23514';
END;
$$;
CREATE CONSTRAINT TRIGGER complete_parse_result AFTER INSERT ON regintel.parse_artifacts
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION regintel.require_complete_parse_result();
CREATE CONSTRAINT TRIGGER complete_job_parse_result AFTER UPDATE ON regintel.filing_jobs
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.state='PARSED')
    EXECUTE FUNCTION regintel.require_complete_parse_result();

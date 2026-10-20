-- Retained original-page preparation only; no parse/fact acceptance or publication authority.
CREATE TABLE regintel.numerical_page_captures (
    id regintel.canonical_id PRIMARY KEY,
    filing_version_id regintel.canonical_id NOT NULL,
    source_blob_id regintel.canonical_id NOT NULL,
    source_sha256 regintel.sha256_hash NOT NULL,
    page_index INTEGER NOT NULL CHECK (page_index BETWEEN 0 AND 1999),
    source_page_count INTEGER NOT NULL CHECK (source_page_count BETWEEN 1 AND 2000),
    sdk_configuration_sha256 regintel.sha256_hash NOT NULL,
    preparation_code_sha256 regintel.sha256_hash NOT NULL,
    raw_capture_bytes BYTEA NOT NULL CHECK (octet_length(raw_capture_bytes) BETWEEN 1 AND 67108864),
    raw_capture_sha256 regintel.sha256_hash NOT NULL,
    prepared_bytes BYTEA NOT NULL CHECK (octet_length(prepared_bytes) BETWEEN 1 AND 67108864),
    prepared_sha256 regintel.sha256_hash NOT NULL,
    word_count INTEGER NOT NULL CHECK (word_count BETWEEN 0 AND 20000),
    cell_count INTEGER NOT NULL CHECK (cell_count BETWEEN 0 AND 2000),
    submitted_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    acceptance_eligible BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT acceptance_eligible),
    creation_transaction BIGINT NOT NULL DEFAULT txid_current(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (filing_version_id, source_blob_id)
        REFERENCES regintel.filing_versions(id, source_blob_id),
    UNIQUE (filing_version_id, prepared_sha256),
    CHECK (page_index < source_page_count)
);
CREATE TABLE regintel.numerical_source_words (
    capture_id regintel.canonical_id NOT NULL REFERENCES regintel.numerical_page_captures(id),
    word_index INTEGER NOT NULL CHECK (word_index BETWEEN 0 AND 19999),
    word_bytes BYTEA NOT NULL CHECK (octet_length(word_bytes) BETWEEN 1 AND 262144),
    word_sha256 regintel.sha256_hash NOT NULL,
    PRIMARY KEY (capture_id, word_index)
);
CREATE FUNCTION regintel.validate_numerical_page_capture() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE payload JSONB; raw JSONB; source RECORD;
BEGIN
    PERFORM regintel.entity_admin(NEW.submitted_by, NEW.auth_version);
    payload := convert_from(NEW.prepared_bytes, 'UTF8')::JSONB;
    raw := convert_from(NEW.raw_capture_bytes, 'UTF8')::JSONB;
    SELECT s.sha256 INTO source FROM regintel.source_blobs s
        JOIN regintel.filing_versions v ON v.source_blob_id = s.id
        WHERE v.id = NEW.filing_version_id AND s.id = NEW.source_blob_id;
    IF NOT FOUND OR source.sha256 IS DISTINCT FROM NEW.source_sha256
       OR NEW.creation_transaction IS DISTINCT FROM txid_current()
       OR NEW.id IS DISTINCT FROM regintel.candidate_stable_id('numerical-page:'
            || NEW.filing_version_id::TEXT || ':' || NEW.source_blob_id::TEXT || ':'
            || NEW.prepared_sha256)
       OR encode(sha256(NEW.prepared_bytes), 'hex') IS DISTINCT FROM NEW.prepared_sha256
       OR encode(sha256(NEW.raw_capture_bytes), 'hex') IS DISTINCT FROM NEW.raw_capture_sha256
       OR NOT regintel.entity_json_keys(payload, ARRAY['schema_version', 'scope', 'source_sha256',
            'source_page_count', 'page_index', 'page_geometry', 'sdk_configuration_sha256',
            'preparation_code_sha256', 'raw_capture_sha256', 'words', 'cells', 'mappings',
            'acceptance_eligible'])
       OR payload ->> 'schema_version' IS DISTINCT FROM 'numerical-source-page-1'
       OR payload ->> 'scope' IS DISTINCT FROM 'SINGLE_ORIGINAL_PAGE_PREPARATION'
       OR payload -> 'acceptance_eligible' IS DISTINCT FROM 'false'::JSONB
       OR payload ->> 'source_sha256' IS DISTINCT FROM NEW.source_sha256
       OR payload -> 'source_page_count' IS DISTINCT FROM to_jsonb(NEW.source_page_count)
       OR payload -> 'page_index' IS DISTINCT FROM to_jsonb(NEW.page_index)
       OR payload ->> 'sdk_configuration_sha256' IS DISTINCT FROM NEW.sdk_configuration_sha256
       OR payload ->> 'preparation_code_sha256' IS DISTINCT FROM NEW.preparation_code_sha256
       OR payload ->> 'raw_capture_sha256' IS DISTINCT FROM NEW.raw_capture_sha256
       OR jsonb_typeof(payload -> 'words') IS DISTINCT FROM 'array'
       OR jsonb_typeof(payload -> 'cells') IS DISTINCT FROM 'array'
       OR jsonb_typeof(payload -> 'mappings') IS DISTINCT FROM 'array'
       OR raw ->> 'status' IS DISTINCT FROM 'success'
       OR raw -> 'errors' IS DISTINCT FROM '[]'::JSONB
       OR raw ->> 'original_source_sha256' IS DISTINCT FROM NEW.source_sha256
       OR raw -> 'requested_original_pdf_page' IS DISTINCT FROM to_jsonb(NEW.page_index + 1)
       OR raw -> 'configuration' ->> 'configuration_sha256'
            IS DISTINCT FROM NEW.sdk_configuration_sha256 THEN
        RAISE EXCEPTION 'Numerical preparation must bind its immutable uploaded source and scope'
            USING ERRCODE = '23514';
    END IF;
    IF jsonb_array_length(payload -> 'words') <> NEW.word_count
       OR jsonb_array_length(payload -> 'cells') <> NEW.cell_count
       OR jsonb_array_length(payload -> 'mappings') <> NEW.cell_count THEN
        RAISE EXCEPTION 'Numerical preparation counts must retain every proposed/unavailable item'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER numerical_page_capture_gate BEFORE INSERT ON regintel.numerical_page_captures
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_numerical_page_capture();
CREATE FUNCTION regintel.validate_numerical_source_word() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE owner RECORD; payload JSONB;
BEGIN
    SELECT creation_transaction, word_count, submitted_by, auth_version INTO owner
        FROM regintel.numerical_page_captures WHERE id = NEW.capture_id;
    IF NOT FOUND OR owner.creation_transaction IS DISTINCT FROM txid_current()
       OR NEW.word_index >= owner.word_count THEN
        RAISE EXCEPTION 'Original words must be inserted with their owning capture'
            USING ERRCODE = '23514';
    END IF;
    PERFORM regintel.entity_admin(owner.submitted_by, owner.auth_version);
    payload := convert_from(NEW.word_bytes, 'UTF8')::JSONB;
    IF encode(sha256(NEW.word_bytes), 'hex') IS DISTINCT FROM NEW.word_sha256
       OR NOT regintel.entity_json_keys(payload,
            ARRAY['word_index', 'orig', 'from_ocr', 'raw_rectangle', 'box'])
       OR payload -> 'word_index' IS DISTINCT FROM to_jsonb(NEW.word_index) THEN
        RAISE EXCEPTION 'Original word bytes must match their sealed page preparation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER numerical_source_word_gate BEFORE INSERT ON regintel.numerical_source_words
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_numerical_source_word();
CREATE FUNCTION regintel.complete_numerical_page_capture() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT count(*) FROM regintel.numerical_source_words WHERE capture_id = NEW.id)
            <> NEW.word_count THEN
        RAISE EXCEPTION 'Original numerical source words must be retained atomically'
            USING ERRCODE = '23514';
    END IF;
    -- Parse the complete page once at sealing, rather than once for every word.
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(
            convert_from(NEW.prepared_bytes, 'UTF8')::JSONB -> 'words'
        ) WITH ORDINALITY AS expected(payload, position)
        LEFT JOIN regintel.numerical_source_words actual
            ON actual.capture_id = NEW.id AND actual.word_index = expected.position - 1
        WHERE actual.capture_id IS NULL OR convert_from(actual.word_bytes, 'UTF8')::JSONB
            IS DISTINCT FROM expected.payload
    ) THEN
        RAISE EXCEPTION 'Original numerical words must match their sealed page preparation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER numerical_page_capture_completeness
    AFTER INSERT ON regintel.numerical_page_captures
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION regintel.complete_numerical_page_capture();
DO $$
DECLARE target TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY['numerical_page_captures', 'numerical_source_words'] LOOP
        EXECUTE format('CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.%I '
            'FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation()', target);
        EXECUTE format('CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.%I '
            'FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation()', target);
    END LOOP;
END;
$$;

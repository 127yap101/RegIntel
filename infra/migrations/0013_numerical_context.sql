-- Exact preparation-inspection history only. No accepted fact, review or publication authority.
CREATE TABLE regintel.numerical_context_records (
    id regintel.canonical_id PRIMARY KEY,
    filing_version_id regintel.canonical_id NOT NULL,
    source_blob_id regintel.canonical_id NOT NULL,
    source_sha256 regintel.sha256_hash NOT NULL,
    input_bytes BYTEA NOT NULL CHECK (octet_length(input_bytes) BETWEEN 1 AND 16777216),
    input_sha256 regintel.sha256_hash NOT NULL,
    inspection_id regintel.canonical_id NOT NULL,
    inspection_bytes BYTEA NOT NULL CHECK (octet_length(inspection_bytes) BETWEEN 1 AND 1048576),
    inspection_sha256 regintel.sha256_hash NOT NULL,
    context_configuration_sha256 regintel.sha256_hash NOT NULL,
    storage_configuration_sha256 regintel.sha256_hash NOT NULL,
    page_count INTEGER NOT NULL CHECK (page_count BETWEEN 1 AND 4),
    submitted_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    acceptance_eligible BOOLEAN NOT NULL DEFAULT FALSE CHECK (NOT acceptance_eligible),
    mandatory_m1_validation_complete BOOLEAN NOT NULL DEFAULT FALSE
        CHECK (NOT mandatory_m1_validation_complete),
    creation_transaction BIGINT NOT NULL DEFAULT txid_current(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (filing_version_id, source_blob_id)
        REFERENCES regintel.filing_versions(id, source_blob_id),
    UNIQUE (inspection_id, storage_configuration_sha256)
);
CREATE TABLE regintel.numerical_context_pages (
    record_id regintel.canonical_id NOT NULL REFERENCES regintel.numerical_context_records(id),
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 3),
    capture_id regintel.canonical_id NOT NULL REFERENCES regintel.numerical_page_captures(id),
    PRIMARY KEY (record_id, ordinal),
    UNIQUE (record_id, capture_id)
);
CREATE FUNCTION regintel.validate_numerical_context_record() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE source_input JSONB; result JSONB; page JSONB; registered JSONB; found_source RECORD;
    captured RECORD; registry_count BIGINT; registry_sha TEXT; registry_entities JSONB;
    check_codes JSONB; expected_state TEXT;
BEGIN
    PERFORM regintel.entity_admin(NEW.submitted_by, NEW.auth_version);
    source_input := convert_from(NEW.input_bytes, 'UTF8')::JSONB;
    result := convert_from(NEW.inspection_bytes, 'UTF8')::JSONB;
    SELECT sha256 INTO found_source FROM regintel.source_blobs WHERE id=NEW.source_blob_id;
    IF NOT FOUND OR found_source.sha256 IS DISTINCT FROM NEW.source_sha256
       OR NEW.creation_transaction IS DISTINCT FROM txid_current()
       OR encode(sha256(NEW.input_bytes), 'hex') IS DISTINCT FROM NEW.input_sha256
       OR encode(sha256(NEW.inspection_bytes), 'hex') IS DISTINCT FROM NEW.inspection_sha256
       OR NEW.id IS DISTINCT FROM regintel.candidate_stable_id('numerical-context-record:'
            || NEW.inspection_id::TEXT || ':' || NEW.storage_configuration_sha256)
       OR NOT regintel.entity_json_keys(source_input, ARRAY['draft','pages','registry','metric',
            'policy','sdk_configuration_sha256','preparation_code_sha256'])
       OR NOT regintel.entity_json_keys(result, ARRAY['schema_version','id','draft','draft_sha256',
            'source_input_sha256','configuration_sha256','state','checks','quantity',
            'acceptance_eligible','review_required','mandatory_m1_validation_complete'])
       OR result ->> 'schema_version' IS DISTINCT FROM 'numerical-context-inspection-1'
       OR result ->> 'id' IS DISTINCT FROM NEW.inspection_id::TEXT
       OR result ->> 'source_input_sha256' IS DISTINCT FROM NEW.input_sha256
       OR result ->> 'configuration_sha256' IS DISTINCT FROM NEW.context_configuration_sha256
       OR result -> 'draft' IS DISTINCT FROM source_input -> 'draft'
       OR source_input -> 'draft' ->> 'schema_version' IS DISTINCT FROM 'numerical-context-draft-1'
       OR source_input -> 'draft' ->> 'filing_version_id' IS DISTINCT FROM NEW.filing_version_id::TEXT
       OR result -> 'acceptance_eligible' IS DISTINCT FROM 'false'::JSONB
       OR result -> 'review_required' IS DISTINCT FROM 'true'::JSONB
       OR result -> 'mandatory_m1_validation_complete' IS DISTINCT FROM 'false'::JSONB
       OR jsonb_typeof(source_input -> 'pages') IS DISTINCT FROM 'array'
       OR jsonb_typeof(result -> 'checks') IS DISTINCT FROM 'array'
       OR NEW.inspection_id IS DISTINCT FROM regintel.candidate_stable_id(
            (result ->> 'draft_sha256') || ':' || NEW.input_sha256 || ':'
            || NEW.context_configuration_sha256) THEN
        RAISE EXCEPTION 'Context inspection must bind immutable inputs, scope and fingerprints'
            USING ERRCODE='23514';
    END IF;
    IF jsonb_array_length(source_input -> 'pages') <> NEW.page_count
       OR jsonb_array_length(result -> 'checks') <> 11 THEN
        RAISE EXCEPTION 'Context inspection must retain every page and check' USING ERRCODE='23514';
    END IF;
    SELECT jsonb_agg(value -> 'code' ORDER BY ordinal) INTO check_codes
        FROM jsonb_array_elements(result -> 'checks') WITH ORDINALITY AS item(value,ordinal);
    IF check_codes IS DISTINCT FROM '["SOURCE","EXACT_WORDS","TABLE","ISSUER","METRIC",
        "VALUE","UNIT","CURRENCY","PERIOD","BASIS","CONTEXT_SCOPE"]'::JSONB
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(result -> 'checks') AS item(value)
          WHERE NOT regintel.entity_json_keys(value,ARRAY['code','state','message'])
          OR value ->> 'state' NOT IN ('PASS','REVIEW','FAIL')
          OR jsonb_typeof(value -> 'state') IS DISTINCT FROM 'string'
          OR jsonb_typeof(value -> 'message') IS DISTINCT FROM 'string'
          OR char_length(value ->> 'message') NOT BETWEEN 1 AND 300) THEN
        RAISE EXCEPTION 'Context checks must retain their canonical codes and states'
            USING ERRCODE='23514';
    END IF;
    expected_state := CASE
        WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(result -> 'checks') AS item(value)
            WHERE value ->> 'state'='FAIL') THEN 'QUARANTINED'
        WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(result -> 'checks') AS item(value)
            WHERE value ->> 'state'='REVIEW') THEN 'REVIEW_REQUIRED'
        ELSE 'SUPPORTED_PROPOSAL' END;
    IF result ->> 'state' IS DISTINCT FROM expected_state
       OR (expected_state='QUARANTINED' AND result -> 'quantity' IS DISTINCT FROM 'null'::JSONB)
       OR (expected_state='SUPPORTED_PROPOSAL' AND (
            jsonb_typeof(result -> 'quantity') IS DISTINCT FROM 'object')) THEN
        RAISE EXCEPTION 'Context result cannot discard failures or mandatory review'
            USING ERRCODE='23514';
    END IF;
    FOR page IN SELECT value FROM jsonb_array_elements(source_input -> 'pages') LOOP
        SELECT * INTO captured FROM regintel.numerical_page_captures
            WHERE id=(page ->> 'id')::UUID;
        IF NOT FOUND OR page IS DISTINCT FROM jsonb_build_object(
            'schema_version','stored-numerical-page-1','id',captured.id,
            'filing_version_id',captured.filing_version_id,'source_blob_id',captured.source_blob_id,
            'prepared_sha256',captured.prepared_sha256,'submitted_by',captured.submitted_by,
            'auth_version',captured.auth_version,
            'capture',convert_from(captured.prepared_bytes,'UTF8')::JSONB) THEN
            RAISE EXCEPTION 'Context pages must match existing sealed source preparations'
                USING ERRCODE='23514';
        END IF;
    END LOOP;
    SELECT count(*), encode(sha256(convert_to('{"entities":[' ||
            coalesce(string_agg(convert_from(registration_bytes,'UTF8'),',' ORDER BY id),'')
            || ']}','UTF8')),'hex'),
            coalesce(jsonb_agg(convert_from(registration_bytes,'UTF8')::JSONB ORDER BY id),'[]'::JSONB)
        INTO registry_count, registry_sha, registry_entities FROM regintel.entity_registrations;
    IF source_input -> 'registry' IS DISTINCT FROM jsonb_build_object(
            'revision',registry_count,'sha256',registry_sha,'entities',registry_entities) THEN
        RAISE EXCEPTION 'Context must retain the actual approved registry snapshot'
            USING ERRCODE='23514';
    END IF;
    SELECT convert_from(definition_bytes,'UTF8')::JSONB INTO registered
        FROM regintel.metric_definitions WHERE id=(source_input -> 'draft' ->> 'metric_id')::UUID;
    IF source_input -> 'metric' IS DISTINCT FROM coalesce(registered,'null'::JSONB) THEN
        RAISE EXCEPTION 'Context metric must match the actual immutable catalog'
            USING ERRCODE='23514';
    END IF;
    SELECT convert_from(policy_bytes,'UTF8')::JSONB INTO registered
        FROM regintel.numeric_metric_policies WHERE metric_id=(source_input -> 'draft' ->> 'metric_id')::UUID;
    IF source_input -> 'policy' IS DISTINCT FROM coalesce(registered,'null'::JSONB) THEN
        RAISE EXCEPTION 'Context numerical policy must match the actual immutable catalog'
            USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER numerical_context_record_gate BEFORE INSERT ON regintel.numerical_context_records
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_numerical_context_record();
CREATE FUNCTION regintel.validate_numerical_context_page() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE owner RECORD;
BEGIN
    SELECT creation_transaction,page_count,submitted_by,auth_version,input_bytes INTO owner
        FROM regintel.numerical_context_records WHERE id=NEW.record_id;
    IF NOT FOUND OR owner.creation_transaction IS DISTINCT FROM txid_current()
       OR NEW.ordinal >= owner.page_count
       OR convert_from(owner.input_bytes,'UTF8')::JSONB -> 'pages' -> NEW.ordinal ->> 'id'
            IS DISTINCT FROM NEW.capture_id::TEXT THEN
        RAISE EXCEPTION 'Context page membership must be sealed with its owning record'
            USING ERRCODE='23514';
    END IF;
    PERFORM regintel.entity_admin(owner.submitted_by,owner.auth_version);
    RETURN NEW;
END;
$$;
CREATE TRIGGER numerical_context_page_gate BEFORE INSERT ON regintel.numerical_context_pages
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_numerical_context_page();
CREATE FUNCTION regintel.complete_numerical_context_record() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT count(*) FROM regintel.numerical_context_pages WHERE record_id=NEW.id)
            <> NEW.page_count THEN
        RAISE EXCEPTION 'Every retained context page must be sealed atomically'
            USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER numerical_context_record_completeness
    AFTER INSERT ON regintel.numerical_context_records DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION regintel.complete_numerical_context_record();
DO $$
DECLARE target TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY['numerical_context_records','numerical_context_pages'] LOOP
        EXECUTE format('CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.%I '
            'FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation()',target);
        EXECUTE format('CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.%I '
            'FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation()',target);
    END LOOP;
END;
$$;

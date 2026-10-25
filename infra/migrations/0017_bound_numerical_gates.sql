-- Explicit versioned bound numerical gate history. No fact/review/publication writes.
CREATE TABLE regintel.bound_numerical_gate_runs (
    id regintel.canonical_id PRIMARY KEY,
    context_record_id regintel.canonical_id NOT NULL REFERENCES regintel.numerical_context_records(id),
    parse_version_id regintel.canonical_id NOT NULL REFERENCES regintel.parse_versions(id),
    input_bytes BYTEA NOT NULL CHECK (octet_length(input_bytes) BETWEEN 1 AND 41943040),
    input_sha256 regintel.sha256_hash NOT NULL,
    result_bytes BYTEA NOT NULL CHECK (octet_length(result_bytes) BETWEEN 1 AND 262144),
    result_sha256 regintel.sha256_hash NOT NULL,
    configuration_sha256 regintel.sha256_hash NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('READY_FOR_REVIEW','REVIEW_REQUIRED','QUARANTINED')),
    submitted_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version BIGINT NOT NULL CHECK (auth_version>0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION regintel.guard_bound_numerical_gate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE packet JSONB; result JSONB; retained RECORD; sealed RECORD; phrase JSONB; word JSONB;
    codes TEXT[]; expected TEXT;
BEGIN
    PERFORM 1 FROM regintel.users WHERE id=NEW.submitted_by AND role='admin'
        AND is_active AND auth_version=NEW.auth_version FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Current numerical administrator required'; END IF;
    packet:=convert_from(NEW.input_bytes,'UTF8')::jsonb;
    result:=convert_from(NEW.result_bytes,'UTF8')::jsonb;
    SELECT * INTO retained FROM regintel.numerical_context_records WHERE id=NEW.context_record_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'Retained numerical context required'; END IF;
    SELECT p.*,v.filing_id INTO sealed FROM regintel.parse_versions p
        JOIN regintel.parse_artifacts a ON a.parse_version_id=p.id
        JOIN regintel.filing_jobs j ON j.id=a.job_id AND j.state='PARSED' AND j.parse_version_id=p.id
        JOIN regintel.filing_versions v ON v.id=p.filing_version_id
        WHERE p.id=NEW.parse_version_id;
    IF NOT FOUND OR sealed.filing_version_id<>retained.filing_version_id
       OR sealed.source_blob_id<>retained.source_blob_id THEN
        RAISE EXCEPTION 'Gate requires the complete matching sealed M1 parse';
    END IF;
    IF encode(sha256(NEW.input_bytes),'hex') IS DISTINCT FROM NEW.input_sha256
       OR encode(sha256(NEW.result_bytes),'hex') IS DISTINCT FROM NEW.result_sha256
       OR packet#>>'{context,id}' IS DISTINCT FROM NEW.context_record_id::text
       OR packet#>>'{context,input_sha256}' IS DISTINCT FROM retained.input_sha256
       OR packet#>'{context,source_input}' IS DISTINCT FROM convert_from(retained.input_bytes,'UTF8')::jsonb
       OR packet#>'{context,inspection}' IS DISTINCT FROM convert_from(retained.inspection_bytes,'UTF8')::jsonb
       OR packet#>>'{binding,context_record_id}' IS DISTINCT FROM NEW.context_record_id::text
       OR packet#>>'{binding,parse_version_id}' IS DISTINCT FROM NEW.parse_version_id::text
       OR packet#>>'{binding,parse_artifact_sha256}' IS DISTINCT FROM sealed.artifact_sha256
       OR packet#>>'{binding,processing_configuration_sha256}' IS DISTINCT FROM sealed.configuration_sha256
       OR packet#>>'{binding,source_sha256}' IS DISTINCT FROM retained.source_sha256
       OR result->>'id' IS DISTINCT FROM NEW.id::text
       OR result->>'context_record_id' IS DISTINCT FROM NEW.context_record_id::text
       OR result->>'parse_version_id' IS DISTINCT FROM NEW.parse_version_id::text
       OR result->>'evidence_binding_id' IS DISTINCT FROM packet#>>'{binding,id}'
       OR result->>'input_sha256' IS DISTINCT FROM NEW.input_sha256
       OR result->>'source_sha256' IS DISTINCT FROM retained.source_sha256
       OR result->>'configuration_sha256' IS DISTINCT FROM NEW.configuration_sha256
       OR result->>'schema_version' IS DISTINCT FROM 'bound-numerical-gate-1'
       OR result->>'state' IS DISTINCT FROM NEW.state
       OR result->'acceptance_eligible' IS DISTINCT FROM 'false'::jsonb
       OR result->'mandatory_m1_validation_complete' IS DISTINCT FROM 'false'::jsonb
       OR result->'review_required' IS DISTINCT FROM 'true'::jsonb
       OR jsonb_typeof(result->'checks') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Bound gate must retain exact context/source/configuration membership';
    END IF;
    SELECT array_agg(item->>'code' ORDER BY ordinal) INTO codes
        FROM jsonb_array_elements(result->'checks') WITH ORDINALITY AS c(item,ordinal);
    IF codes IS DISTINCT FROM ARRAY[
        'SOURCE','EXACT_WORDS','TABLE','ISSUER','METRIC','VALUE','UNIT','CURRENCY',
        'PERIOD','BASIS','CONTEXT_SCOPE','FRESH_CONTEXT','BOUND_EVIDENCE','SOURCE_LANGUAGE'
    ] OR EXISTS(SELECT FROM jsonb_array_elements(result->'checks') c
        WHERE c->>'state' NOT IN ('PASS','REVIEW','FAIL') OR jsonb_typeof(c->'state') IS DISTINCT FROM 'string') THEN
        RAISE EXCEPTION 'Every ordered gate outcome is required';
    END IF;
    expected:=CASE WHEN EXISTS(SELECT FROM jsonb_array_elements(result->'checks') c WHERE c->>'state'='FAIL') THEN 'QUARANTINED'
        WHEN EXISTS(SELECT FROM jsonb_array_elements(result->'checks') c WHERE c->>'state'='REVIEW') THEN 'REVIEW_REQUIRED'
        ELSE 'READY_FOR_REVIEW' END;
    IF expected<>NEW.state OR (expected='QUARANTINED' AND result->'quantity_proposal' IS DISTINCT FROM 'null'::jsonb)
       OR (expected='READY_FOR_REVIEW' AND result->'quantity_proposal'='null'::jsonb) THEN
        RAISE EXCEPTION 'Gate state cannot hide failed or unresolved checks';
    END IF;
    FOR phrase IN SELECT value FROM jsonb_array_elements(packet#>'{binding,phrases}') LOOP
        FOR word IN SELECT value FROM jsonb_array_elements(phrase->'words') LOOP
            PERFORM 1 FROM regintel.evidence e WHERE e.id=(word#>>'{evidence,id}')::uuid
                AND e.parse_version_id=NEW.parse_version_id AND e.filing_version_id=retained.filing_version_id
                AND e.quote=word#>>'{evidence,span,quote}'
                AND e.start_offset=(word#>>'{evidence,span,start}')::bigint
                AND e.end_offset=(word#>>'{evidence,span,end}')::bigint;
            IF NOT FOUND THEN RAISE EXCEPTION 'Gate word differs from existing M1 evidence'; END IF;
        END LOOP;
    END LOOP;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'Bound numerical gate membership is invalid' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER bound_numerical_gate_guard BEFORE INSERT ON regintel.bound_numerical_gate_runs
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_bound_numerical_gate();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.bound_numerical_gate_runs
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.bound_numerical_gate_runs
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

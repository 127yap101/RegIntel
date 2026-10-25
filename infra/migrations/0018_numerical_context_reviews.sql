-- Staged, immutable numerical-context decisions. No acceptance or publication writes.
CREATE TABLE regintel.numerical_context_reviews (
    id regintel.canonical_id PRIMARY KEY,
    gate_run_id regintel.canonical_id NOT NULL UNIQUE REFERENCES regintel.bound_numerical_gate_runs(id),
    request_bytes BYTEA NOT NULL CHECK (octet_length(request_bytes) BETWEEN 1 AND 65536),
    request_sha256 regintel.sha256_hash NOT NULL,
    review_bytes BYTEA NOT NULL CHECK (octet_length(review_bytes) BETWEEN 1 AND 65536),
    review_sha256 regintel.sha256_hash NOT NULL,
    configuration_sha256 regintel.sha256_hash NOT NULL,
    reviewed_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version BIGINT NOT NULL CHECK (auth_version>0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION regintel.guard_numerical_context_review() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE request JSONB; reviewed JSONB; gate regintel.bound_numerical_gate_runs; outcome JSONB;
BEGIN
    PERFORM 1 FROM regintel.users WHERE id=NEW.reviewed_by AND role='admin'
        AND is_active AND auth_version=NEW.auth_version FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Current numerical administrator required'; END IF;
    SELECT * INTO gate FROM regintel.bound_numerical_gate_runs WHERE id=NEW.gate_run_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'Owned bound numerical gate required'; END IF;
    request:=convert_from(NEW.request_bytes,'UTF8')::jsonb;
    reviewed:=convert_from(NEW.review_bytes,'UTF8')::jsonb;
    outcome:=convert_from(gate.result_bytes,'UTF8')::jsonb;
    IF encode(sha256(NEW.request_bytes),'hex') IS DISTINCT FROM NEW.request_sha256
       OR encode(sha256(NEW.review_bytes),'hex') IS DISTINCT FROM NEW.review_sha256
       OR NOT regintel.entity_json_keys(request,ARRAY['gate_run_id','decision','evidence_ids','note'])
       OR request->>'gate_run_id' IS DISTINCT FROM NEW.gate_run_id::text
       OR jsonb_typeof(request->'decision') IS DISTINCT FROM 'string'
       OR request->>'decision' NOT IN ('CONFIRM_CONTEXT','REJECT')
       OR jsonb_typeof(request->'evidence_ids') IS DISTINCT FROM 'array'
       OR jsonb_typeof(request->'note') IS DISTINCT FROM 'string'
       OR length(request->>'note') NOT BETWEEN 1 AND 2000 OR request->>'note' !~ '\S'
       OR request->'evidence_ids' IS DISTINCT FROM outcome->'evidence_ids'
       OR NOT regintel.entity_json_keys(reviewed,ARRAY['schema_version','id','request',
           'gate_input_sha256','gate_result_sha256','configuration_sha256','reviewed_by',
           'auth_version','acceptance_eligible','mandatory_m1_validation_complete','publishes_fact'])
       OR reviewed->>'schema_version' IS DISTINCT FROM 'bound-numerical-review-1'
       OR reviewed->>'id' IS DISTINCT FROM NEW.id::text
       OR reviewed->'request' IS DISTINCT FROM request
       OR reviewed->>'gate_input_sha256' IS DISTINCT FROM gate.input_sha256
       OR reviewed->>'gate_result_sha256' IS DISTINCT FROM gate.result_sha256
       OR reviewed->>'configuration_sha256' IS DISTINCT FROM NEW.configuration_sha256
       OR reviewed->>'reviewed_by' IS DISTINCT FROM NEW.reviewed_by::text
       OR reviewed->>'auth_version' IS DISTINCT FROM NEW.auth_version::text
       OR reviewed->'acceptance_eligible' IS DISTINCT FROM 'false'::jsonb
       OR reviewed->'mandatory_m1_validation_complete' IS DISTINCT FROM 'false'::jsonb
       OR reviewed->'publishes_fact' IS DISTINCT FROM 'false'::jsonb THEN
        RAISE EXCEPTION 'Numerical review must retain exact immutable gate membership';
    END IF;
    IF request->>'decision'='CONFIRM_CONTEXT' AND (
        gate.state<>'READY_FOR_REVIEW' OR jsonb_array_length(outcome->'evidence_ids')=0
        OR EXISTS(SELECT FROM jsonb_array_elements(outcome->'checks') c WHERE c->>'state'<>'PASS')
    ) THEN
        RAISE EXCEPTION 'Unresolved mandatory gates cannot be reviewer-overridden';
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'Numerical context review membership is invalid' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER numerical_context_review_guard BEFORE INSERT ON regintel.numerical_context_reviews
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_numerical_context_review();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.numerical_context_reviews
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.numerical_context_reviews
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

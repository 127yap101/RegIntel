-- Explicit numerical decisions; public observations/corpora still require atomic publication.
CREATE TABLE regintel.numerical_acceptances (
    id regintel.canonical_id PRIMARY KEY,
    candidate_id regintel.canonical_id NOT NULL UNIQUE REFERENCES regintel.numerical_candidates(id),
    candidate_record_sha256 regintel.sha256_hash NOT NULL,
    candidate_preparation_sha256 regintel.sha256_hash NOT NULL,
    configuration_sha256 regintel.sha256_hash NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('ACCEPT','REJECT')),
    record_bytes BYTEA NOT NULL CHECK (octet_length(record_bytes) BETWEEN 1 AND 65536),
    record_sha256 regintel.sha256_hash NOT NULL,
    reviewed_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version BIGINT NOT NULL CHECK (auth_version>0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION regintel.guard_numerical_acceptance() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE record JSONB; preparation JSONB; proposed JSONB; packet JSONB; outcome JSONB;
    candidate regintel.numerical_candidates; gate regintel.bound_numerical_gate_runs;
BEGIN
    LOCK TABLE regintel.entity_registrations,regintel.metric_definitions,
        regintel.numeric_metric_policies,regintel.numerical_context_reviews,
        regintel.numerical_candidates IN SHARE MODE;
    PERFORM 1 FROM regintel.users WHERE id=NEW.reviewed_by AND role='admin'
        AND is_active AND auth_version=NEW.auth_version FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Current numerical administrator required'; END IF;
    SELECT * INTO candidate FROM regintel.numerical_candidates WHERE id=NEW.candidate_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'Immutable numerical candidate required'; END IF;
    SELECT * INTO gate FROM regintel.bound_numerical_gate_runs WHERE id=candidate.gate_run_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'Selected numerical gate required'; END IF;
    record:=convert_from(NEW.record_bytes,'UTF8')::jsonb;
    preparation:=convert_from(candidate.preparation_bytes,'UTF8')::jsonb;
    proposed:=preparation->'proposed_input';
    packet:=convert_from(gate.input_bytes,'UTF8')::jsonb;
    outcome:=convert_from(gate.result_bytes,'UTF8')::jsonb;
    IF encode(sha256(NEW.record_bytes),'hex') IS DISTINCT FROM NEW.record_sha256
       OR encode(sha256(candidate.record_bytes),'hex') IS DISTINCT FROM NEW.candidate_record_sha256
       OR candidate.record_sha256 IS DISTINCT FROM NEW.candidate_record_sha256
       OR encode(sha256(candidate.preparation_bytes),'hex') IS DISTINCT FROM NEW.candidate_preparation_sha256
       OR candidate.preparation_sha256 IS DISTINCT FROM NEW.candidate_preparation_sha256
       OR NOT regintel.entity_json_keys(record,ARRAY['schema_version','id','request',
            'candidate_record_sha256','candidate_preparation_sha256','configuration_sha256',
            'reviewed_by','auth_version','checks','state','mandatory_m1_validation_complete',
            'publishes_fact','published_corpus_version_id'])
       OR convert_from(NEW.record_bytes,'UTF8') IS DISTINCT FROM regintel.candidate_canonical_json(record)
       OR record->>'schema_version' IS DISTINCT FROM 'numerical-acceptance-1'
       OR record->>'id' IS DISTINCT FROM NEW.id::text
       OR NEW.id IS DISTINCT FROM regintel.candidate_stable_id('numerical-acceptance:'||NEW.candidate_id::text)
       OR NOT regintel.entity_json_keys(record->'request',ARRAY['candidate_id','decision','evidence_ids','note'])
       OR record#>>'{request,candidate_id}' IS DISTINCT FROM NEW.candidate_id::text
       OR record#>>'{request,decision}' IS DISTINCT FROM NEW.decision
       OR record#>'{request,evidence_ids}' IS DISTINCT FROM outcome->'evidence_ids'
       OR NOT regintel.validation_text(record#>'{request,note}',2000)
       OR NOT regintel.validation_nonblank(record#>'{request,note}')
       OR record->>'candidate_record_sha256' IS DISTINCT FROM NEW.candidate_record_sha256
       OR record->>'candidate_preparation_sha256' IS DISTINCT FROM NEW.candidate_preparation_sha256
       OR record->>'configuration_sha256' IS DISTINCT FROM NEW.configuration_sha256
       OR record->>'reviewed_by' IS DISTINCT FROM NEW.reviewed_by::text
       OR record->>'auth_version' IS DISTINCT FROM NEW.auth_version::text
       OR record->'publishes_fact' IS DISTINCT FROM 'false'::jsonb
       OR record->'published_corpus_version_id' IS DISTINCT FROM 'null'::jsonb THEN
        RAISE EXCEPTION 'Exact numerical decision identity, proof, hashes and actor required';
    END IF;
    IF NEW.decision='ACCEPT' THEN
        IF record->>'state' IS DISTINCT FROM 'ACCEPTED_UNPUBLISHED'
           OR record->'mandatory_m1_validation_complete' IS DISTINCT FROM 'true'::jsonb
           OR record->'checks' IS DISTINCT FROM preparation->'checks'
           OR preparation->>'state' IS DISTINCT FROM 'READY_FOR_ADAPTER'
           OR gate.state IS DISTINCT FROM 'READY_FOR_REVIEW'
           OR jsonb_array_length(record->'checks') IS DISTINCT FROM 16
           OR EXISTS(SELECT FROM jsonb_array_elements(record->'checks') c
                WHERE c->>'state' IS DISTINCT FROM 'PASS') THEN
            RAISE EXCEPTION 'All exact mandatory numerical checks must pass';
        END IF;
        IF (SELECT count(*) FROM regintel.entity_registrations) IS DISTINCT FROM
            (packet#>>'{current_context,registry,revision}')::bigint
           OR NOT EXISTS(SELECT FROM regintel.entity_registrations e
                JOIN jsonb_array_elements(packet#>'{current_context,registry,entities}') item
                ON e.id=(item->>'id')::uuid AND convert_from(e.registration_bytes,'UTF8')::jsonb=item
                WHERE e.id=(proposed->>'subject_entity_id')::uuid)
           OR NOT EXISTS(SELECT FROM regintel.metric_definitions m
                WHERE m.id=(proposed#>>'{metric,id}')::uuid
                AND convert_from(m.definition_bytes,'UTF8')::jsonb=proposed->'metric')
           OR NOT EXISTS(SELECT FROM regintel.numeric_metric_policies p
                WHERE p.id=(proposed#>>'{policy,id}')::uuid
                AND convert_from(p.policy_bytes,'UTF8')::jsonb=proposed->'policy') THEN
            RAISE EXCEPTION 'Current numerical approval snapshots must match';
        END IF;
    ELSIF record->>'state' IS DISTINCT FROM 'REJECTED'
       OR record->'mandatory_m1_validation_complete' IS DISTINCT FROM 'false'::jsonb
       OR record->'checks' IS DISTINCT FROM '[]'::jsonb THEN
        RAISE EXCEPTION 'A rejection claims no fresh validation or publication';
    END IF;
    NEW.created_at:=clock_timestamp();
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'Numerical acceptance membership is invalid' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER numerical_acceptance_guard BEFORE INSERT ON regintel.numerical_acceptances
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_numerical_acceptance();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.numerical_acceptances
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.numerical_acceptances
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

-- Immutable M1 numerical proposals. No accepted-fact/audit/corpus writes.
CREATE TABLE regintel.numerical_candidates (
    id regintel.canonical_id PRIMARY KEY,
    gate_run_id regintel.canonical_id NOT NULL REFERENCES regintel.bound_numerical_gate_runs(id),
    prepared_input_id regintel.canonical_id NOT NULL UNIQUE,
    parse_version_id regintel.canonical_id NOT NULL REFERENCES regintel.parse_versions(id),
    context_review_id regintel.canonical_id NOT NULL REFERENCES regintel.numerical_context_reviews(id),
    record_bytes BYTEA NOT NULL CHECK (octet_length(record_bytes) BETWEEN 1 AND 65536),
    record_sha256 regintel.sha256_hash NOT NULL,
    preparation_bytes BYTEA NOT NULL CHECK (octet_length(preparation_bytes) BETWEEN 1 AND 4194304),
    preparation_sha256 regintel.sha256_hash NOT NULL,
    storage_configuration_sha256 regintel.sha256_hash NOT NULL,
    submitted_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version BIGINT NOT NULL CHECK (auth_version>0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION regintel.guard_numerical_candidate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE record JSONB; preparation JSONB; proposed JSONB; packet JSONB; outcome JSONB;
    reviewed JSONB; gate regintel.bound_numerical_gate_runs;
    review regintel.numerical_context_reviews; codes TEXT[];
BEGIN
    LOCK TABLE regintel.entity_registrations,regintel.metric_definitions,
        regintel.numeric_metric_policies,regintel.numerical_context_reviews IN SHARE MODE;
    PERFORM 1 FROM regintel.users WHERE id=NEW.submitted_by AND role='admin'
        AND is_active AND auth_version=NEW.auth_version FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Current numerical administrator required'; END IF;
    SELECT * INTO gate FROM regintel.bound_numerical_gate_runs WHERE id=NEW.gate_run_id;
    IF NOT FOUND OR gate.state<>'READY_FOR_REVIEW' OR gate.parse_version_id<>NEW.parse_version_id THEN
        RAISE EXCEPTION 'Complete supported numerical gate required';
    END IF;
    SELECT * INTO review FROM regintel.numerical_context_reviews WHERE id=NEW.context_review_id;
    IF NOT FOUND OR review.gate_run_id<>NEW.gate_run_id THEN
        RAISE EXCEPTION 'Selected immutable context review required';
    END IF;
    record:=convert_from(NEW.record_bytes,'UTF8')::jsonb;
    preparation:=convert_from(NEW.preparation_bytes,'UTF8')::jsonb;
    proposed:=preparation->'proposed_input';
    packet:=convert_from(gate.input_bytes,'UTF8')::jsonb;
    outcome:=convert_from(gate.result_bytes,'UTF8')::jsonb;
    reviewed:=convert_from(review.review_bytes,'UTF8')::jsonb;
    IF encode(sha256(NEW.record_bytes),'hex') IS DISTINCT FROM NEW.record_sha256
       OR encode(sha256(NEW.preparation_bytes),'hex') IS DISTINCT FROM NEW.preparation_sha256
       OR encode(sha256(gate.input_bytes),'hex') IS DISTINCT FROM gate.input_sha256
       OR encode(sha256(gate.result_bytes),'hex') IS DISTINCT FROM gate.result_sha256
       OR NOT regintel.entity_json_keys(record,ARRAY['schema_version','id','request',
            'preparation_sha256','storage_configuration_sha256','submitted_by','auth_version',
            'state','acceptance_eligible','mandatory_m1_validation_complete','publishes_fact'])
       OR convert_from(NEW.record_bytes,'UTF8') IS DISTINCT FROM regintel.candidate_canonical_json(record)
       OR record->>'schema_version' IS DISTINCT FROM 'numerical-candidate-1'
       OR record->>'id' IS DISTINCT FROM NEW.id::text
       OR NEW.id IS DISTINCT FROM regintel.candidate_stable_id('numerical-candidate:'||NEW.prepared_input_id::text)
       OR NOT regintel.entity_json_keys(record->'request',ARRAY['gate_run_id','prepared_input_id'])
       OR record#>>'{request,gate_run_id}' IS DISTINCT FROM NEW.gate_run_id::text
       OR record#>>'{request,prepared_input_id}' IS DISTINCT FROM NEW.prepared_input_id::text
       OR record->>'preparation_sha256' IS DISTINCT FROM NEW.preparation_sha256
       OR record->>'storage_configuration_sha256' IS DISTINCT FROM NEW.storage_configuration_sha256
       OR record->>'submitted_by' IS DISTINCT FROM NEW.submitted_by::text
       OR record->>'auth_version' IS DISTINCT FROM NEW.auth_version::text
       OR record->>'state' IS DISTINCT FROM 'CANDIDATE'
       OR record->'acceptance_eligible' IS DISTINCT FROM 'false'::jsonb
       OR record->'mandatory_m1_validation_complete' IS DISTINCT FROM 'false'::jsonb
       OR record->'publishes_fact' IS DISTINCT FROM 'false'::jsonb THEN
        RAISE EXCEPTION 'Candidate record identity, actor and hashes must match';
    END IF;
    IF NOT regintel.entity_json_keys(preparation,ARRAY['schema_version','gate_run_id',
            'gate_input_sha256','gate_result_sha256','configuration_sha256','state','checks',
            'proposed_input','acceptance_eligible','mandatory_m1_validation_complete','publishes_fact'])
       OR preparation->>'schema_version' IS DISTINCT FROM 'numerical-publication-preparation-1'
       OR preparation->>'state' IS DISTINCT FROM 'READY_FOR_ADAPTER'
       OR preparation->>'gate_run_id' IS DISTINCT FROM NEW.gate_run_id::text
       OR preparation->>'gate_input_sha256' IS DISTINCT FROM gate.input_sha256
       OR preparation->>'gate_result_sha256' IS DISTINCT FROM gate.result_sha256
       OR preparation->'acceptance_eligible' IS DISTINCT FROM 'false'::jsonb
       OR preparation->'mandatory_m1_validation_complete' IS DISTINCT FROM 'false'::jsonb
       OR preparation->'publishes_fact' IS DISTINCT FROM 'false'::jsonb
       OR jsonb_typeof(preparation->'checks') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Complete non-publishing preparation required';
    END IF;
    SELECT array_agg(item->>'code' ORDER BY ordinal) INTO codes
        FROM jsonb_array_elements(preparation->'checks') WITH ORDINALITY AS c(item,ordinal);
    IF codes IS DISTINCT FROM ARRAY['SOURCE','ENTITY','TABLE_CONTEXT','SOURCE_SCOPE','ATTRIBUTION',
        'DIRECTION','METRIC','VALUE','UNIT','CURRENCY','PERIOD','BASIS','DENOMINATOR',
        'STAKE_KIND','OWNERSHIP_DATE','EXTRACTIVE_REVIEW']
       OR EXISTS(SELECT FROM jsonb_array_elements(preparation->'checks') c
            WHERE c->>'state' IS DISTINCT FROM 'PASS'
            OR NOT regintel.entity_json_keys(c,ARRAY['code','state','message'])
            OR NOT regintel.validation_text(c->'message',500)
            OR NOT regintel.validation_nonblank(c->'message'))
       OR EXISTS(SELECT FROM jsonb_array_elements(outcome->'checks') c
            WHERE c->>'state' IS DISTINCT FROM 'PASS')
       OR reviewed#>>'{request,decision}' IS DISTINCT FROM 'CONFIRM_CONTEXT' THEN
        RAISE EXCEPTION 'All numerical checks and exact context confirmation required';
    END IF;
    IF NOT regintel.entity_json_keys(proposed,ARRAY['schema_version','id','gate_run_id',
            'gate_input_sha256','gate_result_sha256','configuration_sha256','gate',
            'subject_entity_id','metric','policy','quantity','proof','context_review',
            'acceptance_eligible','mandatory_m1_validation_complete','publishes_fact'])
       OR proposed->>'schema_version' IS DISTINCT FROM 'numerical-publication-input-1'
       OR proposed->>'id' IS DISTINCT FROM NEW.prepared_input_id::text
       OR proposed->>'gate_run_id' IS DISTINCT FROM NEW.gate_run_id::text
       OR proposed->>'gate_input_sha256' IS DISTINCT FROM gate.input_sha256
       OR proposed->>'gate_result_sha256' IS DISTINCT FROM gate.result_sha256
       OR proposed->>'configuration_sha256' IS DISTINCT FROM preparation->>'configuration_sha256'
       OR NOT regintel.validation_text(proposed->'configuration_sha256',64)
       OR proposed->>'configuration_sha256' !~ '^[0-9a-f]{64}$'
       OR proposed->'gate' IS DISTINCT FROM outcome
       OR proposed->'quantity' IS DISTINCT FROM outcome->'quantity_proposal'
       OR proposed->'proof' IS DISTINCT FROM packet->'binding'
       OR proposed->'context_review' IS DISTINCT FROM reviewed
       OR proposed->'metric' IS DISTINCT FROM packet#>'{context,source_input,metric}'
       OR proposed->'policy' IS DISTINCT FROM packet#>'{context,source_input,policy}'
       OR proposed->>'subject_entity_id' IS DISTINCT FROM packet#>>'{context,source_input,draft,subject_entity_id}'
       OR proposed->'acceptance_eligible' IS DISTINCT FROM 'false'::jsonb
       OR proposed->'mandatory_m1_validation_complete' IS DISTINCT FROM 'false'::jsonb
       OR proposed->'publishes_fact' IS DISTINCT FROM 'false'::jsonb
       OR proposed#>>'{policy,quantity_kind}' IS DISTINCT FROM 'MONEY'
       OR proposed#>>'{policy,period_kind}' IS DISTINCT FROM 'DURATION'
       OR proposed#>>'{metric,kind}' IS DISTINCT FROM 'numeric_fact'
       OR proposed#>>'{metric,id}' IS DISTINCT FROM proposed#>>'{policy,metric_id}' THEN
        RAISE EXCEPTION 'Prepared quantity and complete proof must match the immutable gate';
    END IF;
    IF NEW.prepared_input_id IS DISTINCT FROM regintel.candidate_stable_id(
        'numerical-publication-input:'||NEW.gate_run_id::text||':'||NEW.context_review_id::text||':'||
        (preparation->>'configuration_sha256')) THEN
        RAISE EXCEPTION 'Prepared input identity must retain exact gate/review/configuration';
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
        RAISE EXCEPTION 'Current immutable approval snapshots must still match';
    END IF;
    NEW.created_at:=clock_timestamp();
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'Numerical candidate membership is invalid' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER numerical_candidate_guard BEFORE INSERT ON regintel.numerical_candidates
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_numerical_candidate();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.numerical_candidates
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.numerical_candidates
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

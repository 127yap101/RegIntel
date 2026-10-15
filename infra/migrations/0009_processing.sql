-- Mutable workflow bookkeeping surrounds immutable, already-gated domain results.
-- No acceptance, observation, corpus or projection gate is opened here.
CREATE FUNCTION regintel.processing_stage_index(stage TEXT) RETURNS INTEGER
LANGUAGE SQL IMMUTABLE STRICT AS $$
    SELECT CASE stage WHEN 'ENTITY' THEN 1 WHEN 'CANDIDATE' THEN 2 WHEN 'VALIDATION' THEN 3 END;
$$;

CREATE TABLE regintel.processing_jobs (
    id regintel.canonical_id PRIMARY KEY,
    idempotency_key regintel.canonical_id NOT NULL UNIQUE,
    parse_version_id regintel.canonical_id NOT NULL REFERENCES regintel.parse_versions(id),
    request_bytes BYTEA NOT NULL CHECK (octet_length(request_bytes) BETWEEN 1 AND 16384),
    request_sha256 regintel.sha256_hash NOT NULL,
    configuration_bytes BYTEA NOT NULL CHECK (octet_length(configuration_bytes) BETWEEN 1 AND 65536),
    configuration_sha256 regintel.sha256_hash NOT NULL,
    submitted_by UUID NOT NULL REFERENCES regintel.users(id),
    submitted_auth_version INTEGER NOT NULL CHECK (submitted_auth_version > 0),
    state TEXT NOT NULL DEFAULT 'QUEUED' CHECK (state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation BETWEEN 0 AND 10000),
    failure_code TEXT CHECK (failure_code IN ('CONFIGURATION_CHANGED','AUTHORIZATION_CHANGED',
        'INPUT_CHANGED','SOURCE_INVALID','PROCESSING_FAILED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK ((state='FAILED')=(failure_code IS NOT NULL)),
    CHECK ((state='QUEUED')=(generation=0))
);
CREATE TABLE regintel.processing_inputs (
    job_id regintel.canonical_id NOT NULL REFERENCES regintel.processing_jobs(id),
    stage TEXT NOT NULL CHECK (stage IN ('ENTITY','CANDIDATE','VALIDATION')),
    stage_index INTEGER GENERATED ALWAYS AS (regintel.processing_stage_index(stage)) STORED,
    input_bytes BYTEA NOT NULL CHECK (octet_length(input_bytes) BETWEEN 1 AND 64000000),
    input_sha256 regintel.sha256_hash NOT NULL,
    configuration_sha256 regintel.sha256_hash NOT NULL,
    generation INTEGER NOT NULL CHECK (generation BETWEEN 1 AND 10000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (job_id,stage),
    UNIQUE (job_id,stage,input_sha256,configuration_sha256)
);
CREATE TABLE regintel.processing_checkpoints (
    job_id regintel.canonical_id NOT NULL REFERENCES regintel.processing_jobs(id),
    stage TEXT NOT NULL CHECK (stage IN ('ENTITY','CANDIDATE','VALIDATION')),
    stage_index INTEGER GENERATED ALWAYS AS (regintel.processing_stage_index(stage)) STORED,
    output_id regintel.canonical_id NOT NULL,
    input_sha256 regintel.sha256_hash NOT NULL,
    configuration_sha256 regintel.sha256_hash NOT NULL,
    generation INTEGER NOT NULL CHECK (generation BETWEEN 1 AND 10000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (job_id,stage),
    FOREIGN KEY (job_id,stage,input_sha256,configuration_sha256)
        REFERENCES regintel.processing_inputs(job_id,stage,input_sha256,configuration_sha256)
);
CREATE TABLE regintel.processing_events (
    job_id regintel.canonical_id NOT NULL REFERENCES regintel.processing_jobs(id),
    sequence INTEGER NOT NULL CHECK (sequence BETWEEN 1 AND 10000),
    generation INTEGER NOT NULL CHECK (generation BETWEEN 1 AND 10000),
    kind TEXT NOT NULL CHECK (kind IN ('STARTED','INPUT_FROZEN','CHECKPOINT','RETRY','FAILED','COMPLETED')),
    stage TEXT CHECK (stage IN ('ENTITY','CANDIDATE','VALIDATION')),
    failure_code TEXT CHECK (failure_code IN ('CONFIGURATION_CHANGED','AUTHORIZATION_CHANGED',
        'INPUT_CHANGED','SOURCE_INVALID','PROCESSING_FAILED','STORAGE_UNAVAILABLE')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (job_id,sequence),
    CHECK ((kind IN ('INPUT_FROZEN','CHECKPOINT'))=(stage IS NOT NULL)),
    CHECK ((kind IN ('RETRY','FAILED'))=(failure_code IS NOT NULL))
);
CREATE UNIQUE INDEX processing_started_generation ON regintel.processing_events(job_id,generation)
    WHERE kind='STARTED';
CREATE UNIQUE INDEX processing_terminal_event ON regintel.processing_events(job_id)
    WHERE kind IN ('FAILED','COMPLETED');
CREATE UNIQUE INDEX processing_stage_event ON regintel.processing_events(job_id,stage,kind)
    WHERE kind IN ('INPUT_FROZEN','CHECKPOINT');
CREATE TABLE regintel.processing_dispatch (
    job_id regintel.canonical_id PRIMARY KEY REFERENCES regintel.processing_jobs(id),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    sent_at TIMESTAMPTZ,
    last_failure_code TEXT CHECK (last_failure_code='BROKER_UNAVAILABLE')
);

CREATE FUNCTION regintel.guard_processing_dispatch() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='INSERT' THEN
        IF NEW.attempts<>0 OR NEW.sent_at IS NOT NULL OR NEW.last_failure_code IS NOT NULL THEN
            RAISE EXCEPTION 'Dispatch intent starts unsent' USING ERRCODE='23514';
        END IF;
    ELSIF TG_OP='UPDATE' THEN
        IF NEW.job_id IS DISTINCT FROM OLD.job_id OR NEW.attempts<>OLD.attempts+1
           OR NOT ((NEW.last_failure_code IS NOT DISTINCT FROM 'BROKER_UNAVAILABLE' AND NEW.sent_at IS NOT DISTINCT FROM OLD.sent_at)
               OR (NEW.last_failure_code IS NULL AND NEW.sent_at IS NOT NULL
                   AND (OLD.sent_at IS NULL OR NEW.sent_at>=OLD.sent_at))) THEN
            RAISE EXCEPTION 'Dispatch attempts retain monotonic delivery history' USING ERRCODE='23514';
        END IF;
    ELSE RAISE EXCEPTION 'Dispatch intent cannot be removed' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER processing_dispatch_gate BEFORE INSERT OR UPDATE OR DELETE ON regintel.processing_dispatch
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_processing_dispatch();
CREATE TRIGGER processing_dispatch_no_truncate BEFORE TRUNCATE ON regintel.processing_dispatch
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

CREATE FUNCTION regintel.processing_configuration(value JSONB) RETURNS BOOLEAN
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE entity JSONB := value->'entity'; candidate JSONB := value->'candidate';
        validation JSONB := value->'validation'; field TEXT;
BEGIN
    IF NOT regintel.entity_json_keys(value,ARRAY['version','code_sha256','entity','candidate','validation'])
       OR value->>'version' IS DISTINCT FROM '1.0.0'
       OR jsonb_typeof(value->'code_sha256') IS DISTINCT FROM 'string'
       OR value->>'code_sha256' !~ '^[0-9a-f]{64}$'
       OR NOT regintel.entity_json_keys(entity,ARRAY['version','spacy_version','rapidfuzz_version',
            'code_sha256','fuzzy_threshold','max_proposals'])
       OR entity->>'version' IS DISTINCT FROM '1.0.0'
       OR jsonb_typeof(entity->'code_sha256') IS DISTINCT FROM 'string'
       OR entity->>'code_sha256' !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(entity->'fuzzy_threshold') IS DISTINCT FROM 'number'
       OR entity->>'fuzzy_threshold' IS DISTINCT FROM '85.0'
       OR jsonb_typeof(entity->'max_proposals') IS DISTINCT FROM 'number'
       OR entity->>'max_proposals' IS DISTINCT FROM '5'
       OR NOT regintel.entity_json_keys(candidate,ARRAY['version','code_sha256',
            'max_window_chars','max_candidates','max_input_chars'])
       OR candidate->>'version' IS DISTINCT FROM '1.0.0'
       OR jsonb_typeof(candidate->'code_sha256') IS DISTINCT FROM 'string'
       OR candidate->>'code_sha256' !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(candidate->'max_window_chars') IS DISTINCT FROM 'number'
       OR candidate->>'max_window_chars' IS DISTINCT FROM '20000'
       OR jsonb_typeof(candidate->'max_candidates') IS DISTINCT FROM 'number'
       OR candidate->>'max_candidates' IS DISTINCT FROM '1000'
       OR jsonb_typeof(candidate->'max_input_chars') IS DISTINCT FROM 'number'
       OR candidate->>'max_input_chars' IS DISTINCT FROM '2000000'
       OR NOT regintel.entity_json_keys(validation,ARRAY['version','code_sha256'])
       OR validation->>'version' IS DISTINCT FROM '1.0.0'
       OR jsonb_typeof(validation->'code_sha256') IS DISTINCT FROM 'string'
       OR validation->>'code_sha256' !~ '^[0-9a-f]{64}$' THEN RETURN FALSE; END IF;
    FOREACH field IN ARRAY ARRAY['spacy_version','rapidfuzz_version'] LOOP
        IF jsonb_typeof(entity->field) IS DISTINCT FROM 'string'
           OR char_length(entity->>field) NOT BETWEEN 1 AND 256 THEN RETURN FALSE; END IF;
    END LOOP;
    -- These are immutable installed/default settings, not client-tunable parameters.
    RETURN TRUE;
END;
$$;

CREATE FUNCTION regintel.guard_processing_job() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE request JSONB; configuration JSONB; item JSONB; metrics TEXT[];
BEGIN
    IF TG_OP='INSERT' THEN
        PERFORM regintel.entity_admin(NEW.submitted_by,NEW.submitted_auth_version);
        request := convert_from(NEW.request_bytes,'UTF8')::JSONB;
        configuration := convert_from(NEW.configuration_bytes,'UTF8')::JSONB;
        IF NEW.state<>'QUEUED' OR NEW.generation<>0 OR NEW.failure_code IS NOT NULL
           OR NOT regintel.entity_json_keys(request,ARRAY['idempotency_key','parse_version_id','metric_ids'])
           OR NOT regintel.candidate_uuid(request->'idempotency_key')
           OR NOT regintel.candidate_uuid(request->'parse_version_id')
           OR request->>'idempotency_key' IS DISTINCT FROM NEW.idempotency_key::TEXT
           OR request->>'parse_version_id' IS DISTINCT FROM NEW.parse_version_id::TEXT
           OR jsonb_typeof(request->'metric_ids') IS DISTINCT FROM 'array'
           OR jsonb_array_length(request->'metric_ids')>100
           OR encode(sha256(NEW.request_bytes),'hex') IS DISTINCT FROM NEW.request_sha256
           OR encode(sha256(NEW.configuration_bytes),'hex') IS DISTINCT FROM NEW.configuration_sha256
           OR convert_from(NEW.request_bytes,'UTF8') IS DISTINCT FROM regintel.candidate_canonical_json(request)
           OR convert_from(NEW.configuration_bytes,'UTF8') IS DISTINCT FROM regintel.candidate_canonical_json(configuration)
           OR NOT regintel.processing_configuration(configuration)
           OR NOT EXISTS (SELECT 1 FROM regintel.parse_versions p JOIN regintel.parse_artifacts a
                ON a.parse_version_id=p.id WHERE p.id=NEW.parse_version_id
                AND p.artifact_sha256=encode(sha256(a.artifact_bytes),'hex')) THEN
            RAISE EXCEPTION 'A processing job requires a sealed source and immutable typed request/configuration'
                USING ERRCODE='23514';
        END IF;
        FOR item IN SELECT jsonb_array_elements(request->'metric_ids') LOOP
            IF NOT regintel.candidate_uuid(item) OR NOT EXISTS (
                SELECT 1 FROM regintel.metric_definitions WHERE id=(item #>> '{}')::UUID) THEN
                RAISE EXCEPTION 'Processing metrics must be registered canonical IDs' USING ERRCODE='23514';
            END IF;
        END LOOP;
        SELECT coalesce(array_agg(entry.value #>> '{}' ORDER BY entry.value #>> '{}'),ARRAY[]::TEXT[]) INTO metrics
            FROM jsonb_array_elements(request->'metric_ids') AS entry(value);
        IF cardinality(metrics)<>(SELECT count(DISTINCT entry) FROM unnest(metrics) entry)
           OR request->'metric_ids' IS DISTINCT FROM to_jsonb(metrics) THEN
            RAISE EXCEPTION 'Processing metric IDs must be sorted and distinct' USING ERRCODE='23514';
        END IF;
    ELSIF TG_OP='UPDATE' THEN
        IF ROW(NEW.id,NEW.idempotency_key,NEW.parse_version_id,NEW.request_bytes,NEW.request_sha256,
               NEW.configuration_bytes,NEW.configuration_sha256,NEW.submitted_by,
               NEW.submitted_auth_version,NEW.created_at)
           IS DISTINCT FROM ROW(OLD.id,OLD.idempotency_key,OLD.parse_version_id,OLD.request_bytes,
               OLD.request_sha256,OLD.configuration_bytes,OLD.configuration_sha256,OLD.submitted_by,
               OLD.submitted_auth_version,OLD.created_at)
           OR OLD.state IN ('SUCCEEDED','FAILED')
           OR NOT ((NEW.state='RUNNING' AND NEW.generation=OLD.generation+1 AND NEW.failure_code IS NULL)
               OR (OLD.state='RUNNING' AND NEW.generation=OLD.generation AND NEW.state IN ('SUCCEEDED','FAILED')))
           OR (NEW.state='SUCCEEDED' AND (SELECT count(*) FROM regintel.processing_checkpoints
                    WHERE job_id=NEW.id)<>3) THEN
            RAISE EXCEPTION 'Invalid or immutable processing job transition' USING ERRCODE='23514';
        END IF;
        NEW.updated_at := clock_timestamp();
    ELSE RAISE EXCEPTION 'Processing jobs cannot be removed' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER processing_job_gate BEFORE INSERT OR UPDATE OR DELETE ON regintel.processing_jobs
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_processing_job();
CREATE TRIGGER processing_jobs_no_truncate BEFORE TRUNCATE ON regintel.processing_jobs
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

CREATE FUNCTION regintel.guard_processing_input() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE owner regintel.processing_jobs; input JSONB; config JSONB; previous UUID;
BEGIN
    SELECT * INTO owner FROM regintel.processing_jobs WHERE id=NEW.job_id FOR UPDATE;
    IF NOT FOUND OR owner.state<>'RUNNING' OR owner.generation<>NEW.generation
       OR (SELECT count(*) FROM regintel.processing_checkpoints WHERE job_id=NEW.job_id)
            <>regintel.processing_stage_index(NEW.stage)-1 THEN
        RAISE EXCEPTION 'Frozen inputs require the current attempt and ordered stage' USING ERRCODE='23514';
    END IF;
    PERFORM regintel.entity_admin(owner.submitted_by,owner.submitted_auth_version);
    input := convert_from(NEW.input_bytes,'UTF8')::JSONB;
    config := convert_from(owner.configuration_bytes,'UTF8')::JSONB->lower(NEW.stage);
    IF encode(sha256(NEW.input_bytes),'hex') IS DISTINCT FROM NEW.input_sha256
       OR encode(sha256(convert_to(regintel.candidate_canonical_json(config),'UTF8')),'hex')
            IS DISTINCT FROM NEW.configuration_sha256 THEN
        RAISE EXCEPTION 'Frozen processing input hash differs' USING ERRCODE='23514';
    END IF;
    IF NEW.stage='ENTITY' THEN
        IF NOT regintel.entity_json_keys(input,ARRAY['parse_version_id','artifact_sha256','evidence',
                'registry','configuration'])
           OR input->>'parse_version_id' IS DISTINCT FROM owner.parse_version_id::TEXT
           OR input->'configuration' IS DISTINCT FROM config
           OR jsonb_typeof(input->'evidence') IS DISTINCT FROM 'array'
           OR jsonb_array_length(input->'evidence') NOT BETWEEN 1 AND 10000
           OR NOT regintel.entity_json_keys(input->'registry',ARRAY['revision','sha256','entities'])
           OR jsonb_typeof(input->'registry'->'entities') IS DISTINCT FROM 'array'
           OR input->>'artifact_sha256' IS DISTINCT FROM (
                SELECT artifact_sha256 FROM regintel.parse_versions WHERE id=owner.parse_version_id) THEN
            RAISE EXCEPTION 'Entity input must bind the complete sealed source and configuration'
                USING ERRCODE='23514';
        END IF;
    ELSIF NEW.stage='CANDIDATE' THEN
        SELECT output_id INTO previous FROM regintel.processing_checkpoints
            WHERE job_id=owner.id AND stage='ENTITY';
        IF NOT regintel.entity_json_keys(input,ARRAY['parse_version_id','entity_run','reviews','evidence','metrics'])
           OR input->>'parse_version_id' IS DISTINCT FROM owner.parse_version_id::TEXT
           OR input->'entity_run' IS DISTINCT FROM (SELECT convert_from(run_bytes,'UTF8')::JSONB
                FROM regintel.entity_runs WHERE id=previous)
           OR jsonb_typeof(input->'evidence') IS DISTINCT FROM 'array'
           OR jsonb_typeof(input->'reviews') IS DISTINCT FROM 'array'
           OR jsonb_typeof(input->'metrics') IS DISTINCT FROM 'array'
           OR (SELECT coalesce(jsonb_agg(m.value->'id' ORDER BY m.value->>'id'),'[]'::JSONB)
                FROM jsonb_array_elements(input->'metrics') AS m(value)) IS DISTINCT FROM
                    (convert_from(owner.request_bytes,'UTF8')::JSONB->'metric_ids') THEN
            RAISE EXCEPTION 'Candidate input must consume its sealed entity checkpoint' USING ERRCODE='23514';
        END IF;
    ELSE
        SELECT output_id INTO previous FROM regintel.processing_checkpoints
            WHERE job_id=owner.id AND stage='CANDIDATE';
        IF NOT regintel.entity_json_keys(input,ARRAY['candidate_run','source','source_input_sha256',
                'entity_reviews','policies','table_evidence_ids','transcription_evidence_ids'])
           OR input->'candidate_run' IS DISTINCT FROM (SELECT regintel.validation_candidate_snapshot(r)
                FROM regintel.candidate_runs r WHERE id=previous)
           OR input->'source' IS DISTINCT FROM (SELECT convert_from(input_bytes,'UTF8')::JSONB
                FROM regintel.candidate_runs WHERE id=previous) THEN
            RAISE EXCEPTION 'Validation input must consume its sealed candidate checkpoint' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER processing_input_gate BEFORE INSERT ON regintel.processing_inputs
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_processing_input();

CREATE FUNCTION regintel.guard_processing_checkpoint() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE owner regintel.processing_jobs; frozen regintel.processing_inputs; input JSONB;
        output JSONB; configuration JSONB; previous UUID; actual_sha TEXT;
BEGIN
    SELECT * INTO owner FROM regintel.processing_jobs WHERE id=NEW.job_id FOR UPDATE;
    SELECT * INTO frozen FROM regintel.processing_inputs WHERE job_id=NEW.job_id AND stage=NEW.stage;
    IF owner.id IS NULL OR frozen.job_id IS NULL OR owner.state<>'RUNNING'
       OR owner.generation<>NEW.generation
       OR frozen.input_sha256 IS DISTINCT FROM NEW.input_sha256
       OR frozen.configuration_sha256 IS DISTINCT FROM NEW.configuration_sha256
       OR (SELECT count(*) FROM regintel.processing_checkpoints WHERE job_id=NEW.job_id)
            <>regintel.processing_stage_index(NEW.stage)-1 THEN
        RAISE EXCEPTION 'Checkpoint requires current attempt, exact frozen input and ordered completion'
            USING ERRCODE='23514';
    END IF;
    PERFORM regintel.entity_admin(owner.submitted_by,owner.submitted_auth_version);
    input := convert_from(frozen.input_bytes,'UTF8')::JSONB;
    configuration := convert_from(owner.configuration_bytes,'UTF8')::JSONB->lower(NEW.stage);
    IF NEW.stage='ENTITY' THEN
        SELECT convert_from(run_bytes,'UTF8')::JSONB,configuration_sha256 INTO output,actual_sha
            FROM regintel.entity_runs WHERE id=NEW.output_id AND parse_version_id=owner.parse_version_id;
        IF NOT FOUND OR output->>'artifact_sha256' IS DISTINCT FROM input->>'artifact_sha256'
           OR output->>'registry_revision' IS DISTINCT FROM input->'registry'->>'revision'
           OR output->>'registry_sha256' IS DISTINCT FROM input->'registry'->>'sha256'
           OR output->'evidence_ids' IS DISTINCT FROM (SELECT jsonb_agg(e.value->'id' ORDER BY e.ordinal)
                FROM jsonb_array_elements(input->'evidence') WITH ORDINALITY AS e(value,ordinal))
           OR (SELECT convert_from(registry_bytes,'UTF8')::JSONB FROM regintel.entity_runs WHERE id=NEW.output_id)
                IS DISTINCT FROM jsonb_build_object('entities',input->'registry'->'entities') THEN
            RAISE EXCEPTION 'Entity checkpoint must bind its exact sealed registry/source' USING ERRCODE='23514';
        END IF;
    ELSIF NEW.stage='CANDIDATE' THEN
        SELECT output_id INTO previous FROM regintel.processing_checkpoints
            WHERE job_id=owner.id AND stage='ENTITY';
        SELECT convert_from(configuration_bytes,'UTF8')::JSONB,configuration_sha256 INTO output,actual_sha
            FROM regintel.candidate_runs WHERE id=NEW.output_id AND entity_run_id=previous
                AND parse_version_id=owner.parse_version_id AND input_sha256=NEW.input_sha256
                AND convert_from(input_bytes,'UTF8')::JSONB=input;
        IF NOT FOUND THEN RAISE EXCEPTION 'Candidate checkpoint requires its exact sealed input/result'
            USING ERRCODE='23514'; END IF;
        output := jsonb_build_object('configuration',output);
    ELSE
        SELECT output_id INTO previous FROM regintel.processing_checkpoints
            WHERE job_id=owner.id AND stage='CANDIDATE';
        SELECT convert_from(run_bytes,'UTF8')::JSONB,configuration_sha256 INTO output,actual_sha
            FROM regintel.validation_runs WHERE id=NEW.output_id AND candidate_run_id=previous
                AND parse_version_id=owner.parse_version_id AND input_sha256=NEW.input_sha256
                AND convert_from(input_bytes,'UTF8')::JSONB=input;
        IF NOT FOUND THEN RAISE EXCEPTION 'Validation checkpoint requires its exact sealed input/result'
            USING ERRCODE='23514'; END IF;
    END IF;
    IF actual_sha IS DISTINCT FROM NEW.configuration_sha256
       OR output->'configuration' IS DISTINCT FROM configuration THEN
        RAISE EXCEPTION 'Checkpoint configuration differs from frozen workflow' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER processing_checkpoint_gate BEFORE INSERT ON regintel.processing_checkpoints
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_processing_checkpoint();

CREATE FUNCTION regintel.guard_processing_event() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE owner regintel.processing_jobs; expected INTEGER;
BEGIN
    SELECT * INTO owner FROM regintel.processing_jobs WHERE id=NEW.job_id FOR UPDATE;
    SELECT coalesce(max(sequence),0)+1 INTO expected FROM regintel.processing_events WHERE job_id=NEW.job_id;
    IF owner.id IS NULL OR owner.generation<>NEW.generation OR NEW.sequence<>expected
       OR (NEW.kind='STARTED' AND owner.state<>'RUNNING')
       OR (NEW.kind='RETRY' AND (owner.state<>'RUNNING' OR NEW.failure_code<>'STORAGE_UNAVAILABLE'))
       OR (NEW.kind='FAILED' AND (owner.state<>'FAILED' OR NEW.failure_code<>owner.failure_code))
       OR (NEW.kind='COMPLETED' AND owner.state<>'SUCCEEDED')
       OR (NEW.kind='INPUT_FROZEN' AND NOT EXISTS (SELECT 1 FROM regintel.processing_inputs
            WHERE job_id=NEW.job_id AND stage=NEW.stage AND generation=NEW.generation))
       OR (NEW.kind='CHECKPOINT' AND NOT EXISTS (SELECT 1 FROM regintel.processing_checkpoints
            WHERE job_id=NEW.job_id AND stage=NEW.stage AND generation=NEW.generation)) THEN
        RAISE EXCEPTION 'Processing audit must bind current ordered transitions/results' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER processing_event_gate BEFORE INSERT ON regintel.processing_events
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_processing_event();

DO $$ DECLARE target TEXT; BEGIN
    FOREACH target IN ARRAY ARRAY['processing_inputs','processing_checkpoints','processing_events'] LOOP
        EXECUTE format('CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.%I '
            'FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation()',target);
        EXECUTE format('CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.%I '
            'FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation()',target);
    END LOOP;
END; $$;

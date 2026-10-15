-- Entity runs retain sorted evidence membership; frozen source traversal order is independent.
-- Preserve applied0009 and all failed/immutable prior jobs; correct only future checkpoint checks.
CREATE OR REPLACE FUNCTION regintel.guard_processing_checkpoint() RETURNS TRIGGER LANGUAGE plpgsql AS $$
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
           OR output->'evidence_ids' IS DISTINCT FROM (SELECT jsonb_agg(e.value->'id' ORDER BY e.value->>'id')
                FROM jsonb_array_elements(input->'evidence') AS e(value))
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

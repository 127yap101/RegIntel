-- Append-only resolved gates retain the exact original gate and stored attestation.
-- Existing gate/context/acceptance rows and legacy packet bytes remain untouched.
CREATE FUNCTION regintel.guard_numerical_applicability_gate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE packet JSONB; result JSONB; base RECORD; review RECORD; prior JSONB;
    keys TEXT[]; old_check JSONB; new_check JSONB; position INTEGER;
BEGIN
    packet := convert_from(NEW.input_bytes,'UTF8')::jsonb;
    SELECT array_agg(key ORDER BY key) INTO keys FROM jsonb_object_keys(packet) key;
    IF NOT packet ? 'schema_version' THEN
        IF keys IS DISTINCT FROM ARRAY['binding','context','current_context'] THEN
            RAISE EXCEPTION 'Legacy gate packet shape differs';
        END IF;
        RETURN NEW;
    END IF;
    IF packet->>'schema_version' IS DISTINCT FROM 'bound-numerical-applicability-input-1'
       OR keys IS DISTINCT FROM ARRAY['applicability','base_auth_version','base_result',
           'base_submitted_by','binding','context','current_context','schema_version'] THEN
        RAISE EXCEPTION 'Unknown applicability gate input';
    END IF;
    SELECT * INTO base FROM regintel.bound_numerical_gate_runs
        WHERE id=(packet#>>'{base_result,id}')::uuid;
    IF NOT FOUND THEN RAISE EXCEPTION 'Original gate is required'; END IF;
    SELECT * INTO review FROM regintel.numerical_applicability_reviews WHERE gate_run_id=base.id;
    IF NOT FOUND THEN RAISE EXCEPTION 'Stored applicability decision is required'; END IF;
    prior := convert_from(base.result_bytes,'UTF8')::jsonb;
    result := convert_from(NEW.result_bytes,'UTF8')::jsonb;
    IF base.state IS DISTINCT FROM 'REVIEW_REQUIRED'
       OR convert_from(base.input_bytes,'UTF8')::jsonb IS DISTINCT FROM
           jsonb_build_object('context',packet->'context','current_context',packet->'current_context',
               'binding',packet->'binding')
       OR packet->'base_result' IS DISTINCT FROM prior
       OR packet->>'base_submitted_by' IS DISTINCT FROM base.submitted_by::text
       OR packet->'base_auth_version' IS DISTINCT FROM to_jsonb(base.auth_version)
       OR packet->'applicability' IS DISTINCT FROM convert_from(review.review_bytes,'UTF8')::jsonb
       OR packet#>>'{applicability,request,gate_input_sha256}' IS DISTINCT FROM base.input_sha256
       OR packet#>>'{applicability,request,gate_result_sha256}' IS DISTINCT FROM base.result_sha256
       OR NEW.context_record_id IS DISTINCT FROM base.context_record_id
       OR NEW.parse_version_id IS DISTINCT FROM base.parse_version_id
       OR NEW.id=base.id OR NEW.input_sha256=base.input_sha256
       OR NEW.configuration_sha256=base.configuration_sha256
       OR NEW.state IS DISTINCT FROM 'READY_FOR_REVIEW'
       OR (result - ARRAY['id','input_sha256','configuration_sha256','checks','state'])
           IS DISTINCT FROM (prior - ARRAY['id','input_sha256','configuration_sha256','checks','state'])
       OR jsonb_array_length(result->'checks') IS DISTINCT FROM 14 THEN
        RAISE EXCEPTION 'Resolved gate must retain its original audited membership';
    END IF;
    FOR position IN 0..13 LOOP
        old_check:=prior->'checks'->position;
        new_check:=result->'checks'->position;
        IF old_check->>'state'='PASS' THEN
            IF new_check IS DISTINCT FROM old_check THEN
                RAISE EXCEPTION 'Passing checks cannot be replaced';
            END IF;
        ELSIF old_check->>'state'='REVIEW'
          AND old_check->>'code' IN ('CONTEXT_SCOPE','BASIS','SOURCE_LANGUAGE') THEN
            IF new_check->>'state' IS DISTINCT FROM 'PASS'
               OR new_check->>'code' IS DISTINCT FROM old_check->>'code' THEN
                RAISE EXCEPTION 'Only reviewed applicability checks can pass';
            END IF;
        ELSE
            RAISE EXCEPTION 'Applicability cannot override failed or unrelated checks';
        END IF;
    END LOOP;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'Numerical applicability gate membership is invalid' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER numerical_applicability_gate_guard BEFORE INSERT ON regintel.bound_numerical_gate_runs
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_numerical_applicability_gate();

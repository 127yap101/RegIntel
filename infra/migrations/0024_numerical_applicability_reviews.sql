-- Immutable applicability attestations tied to an existing numerical gate.
CREATE TABLE regintel.numerical_applicability_reviews (
    id regintel.canonical_id PRIMARY KEY,
    gate_run_id regintel.canonical_id NOT NULL UNIQUE REFERENCES regintel.bound_numerical_gate_runs(id),
    request_bytes BYTEA NOT NULL CHECK (octet_length(request_bytes) BETWEEN 1 AND 262144),
    request_sha256 regintel.sha256_hash NOT NULL,
    review_bytes BYTEA NOT NULL CHECK (octet_length(review_bytes) BETWEEN 1 AND 262144),
    review_sha256 regintel.sha256_hash NOT NULL,
    configuration_sha256 regintel.sha256_hash NOT NULL,
    reviewed_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version BIGINT NOT NULL CHECK (auth_version>0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION regintel.guard_numerical_applicability_review() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    request JSONB; reviewed JSONB; gate regintel.bound_numerical_gate_runs;
    outcome JSONB; binding JSONB; expected JSONB; pages JSONB; phrase JSONB;
    assertions JSONB := '[]'::jsonb; evidence JSONB; phrase_text TEXT;
    value_page INTEGER; unit_text TEXT; qualified_default BOOLEAN;
    basis_pattern TEXT := '^(Unless (stated|specified) otherwise( or the context requires otherwise)?, )?'
        || 'the financial information( and financial ratios)? in this Prospectus are derived from '
        || 'our Restated (Consolidated|Standalone) (Summary Statements|Financial Information)\.$';
    caption_pattern TEXT := '^(summary of (selected financial information derived from our|our company''s) '
        || 'restated (consolidated|standalone) financial information|restated summary profit and loss)\.?$';
    qualifier_pattern TEXT := '\m(not|never|no longer|may|might|could|would|will|reportedly|allegedly|'
        || 'purportedly|according to|claims?|claimed|denies|denied|disputes|disputed|expects?|expected|'
        || 'intends?|intended|plans?|planned|proposes?|proposed|if|unless|subject to|conditional|'
        || 'previously|formerly|historically)\M';
BEGIN
    PERFORM 1 FROM regintel.users WHERE id=NEW.reviewed_by AND role='admin'
        AND is_active AND auth_version=NEW.auth_version FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Current numerical administrator required'; END IF;
    SELECT * INTO gate FROM regintel.bound_numerical_gate_runs WHERE id=NEW.gate_run_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'Owned bound numerical gate required'; END IF;
    request:=convert_from(NEW.request_bytes,'UTF8')::jsonb;
    reviewed:=convert_from(NEW.review_bytes,'UTF8')::jsonb;
    outcome:=convert_from(gate.result_bytes,'UTF8')::jsonb;
    binding:=convert_from(gate.input_bytes,'UTF8')::jsonb->'binding';
    IF encode(sha256(NEW.request_bytes),'hex') IS DISTINCT FROM NEW.request_sha256
       OR encode(sha256(NEW.review_bytes),'hex') IS DISTINCT FROM NEW.review_sha256
       OR NOT regintel.entity_json_keys(request,ARRAY['schema_version','gate_run_id',
           'gate_input_sha256','gate_result_sha256','binding_id','value_cell_id','row_cell_id',
           'period_cell_id','assertions','reviewed_page_indices','decision','note'])
       OR request->>'schema_version' IS DISTINCT FROM 'numerical-applicability-request-1'
       OR request->>'gate_run_id' IS DISTINCT FROM NEW.gate_run_id::text
       OR request->>'gate_input_sha256' IS DISTINCT FROM gate.input_sha256
       OR request->>'gate_result_sha256' IS DISTINCT FROM gate.result_sha256
       OR request->>'binding_id' IS DISTINCT FROM binding->>'id'
       OR request->>'value_cell_id' IS DISTINCT FROM binding->'cells'->0->>'artifact_cell_id'
       OR request->>'row_cell_id' IS DISTINCT FROM binding->'cells'->1->>'artifact_cell_id'
       OR request->>'period_cell_id' IS DISTINCT FROM binding->'cells'->2->>'artifact_cell_id'
       OR request->>'decision' IS DISTINCT FROM 'APPLIES'
       OR jsonb_typeof(request->'note') IS DISTINCT FROM 'string'
       OR length(request->>'note') NOT BETWEEN 1 AND 2000 OR request->>'note' !~ '\S'
       OR gate.state<>'REVIEW_REQUIRED'
       OR jsonb_typeof(outcome->'quantity_proposal') IS DISTINCT FROM 'object'
       OR coalesce(outcome->'quantity_proposal'->>'basis','') NOT IN ('CONSOLIDATED','STANDALONE')
       OR coalesce(outcome->'quantity_proposal'->>'currency','') NOT IN ('INR','USD')
       OR coalesce(outcome->'quantity_proposal'->>'normalized_unit','') NOT IN ('million','lakh','crore','billion')
       OR outcome->'quantity_proposal'->'period'->>'kind' IS DISTINCT FROM 'DURATION'
       OR jsonb_typeof(outcome->'quantity_proposal'->'period'->'start_date') IS DISTINCT FROM 'string'
       OR jsonb_typeof(outcome->'quantity_proposal'->'period'->'end_date') IS DISTINCT FROM 'string'
       OR EXISTS(SELECT FROM jsonb_array_elements(outcome->'checks') c
           WHERE c->>'state'='FAIL' OR (c->>'state'<>'PASS'
               AND c->>'code' NOT IN ('CONTEXT_SCOPE','BASIS','SOURCE_LANGUAGE')))
       OR NOT regintel.entity_json_keys(reviewed,ARRAY['schema_version','id','request',
           'configuration_sha256','reviewed_by','auth_version','acceptance_eligible',
           'mandatory_m1_validation_complete','publishes_fact'])
       OR reviewed->>'schema_version' IS DISTINCT FROM 'numerical-applicability-review-1'
       OR reviewed->>'id' IS DISTINCT FROM NEW.id::text
       OR reviewed->'request' IS DISTINCT FROM request
       OR reviewed->>'configuration_sha256' IS DISTINCT FROM NEW.configuration_sha256
       OR reviewed->>'reviewed_by' IS DISTINCT FROM NEW.reviewed_by::text
       OR reviewed->>'auth_version' IS DISTINCT FROM NEW.auth_version::text
       OR reviewed->'acceptance_eligible' IS DISTINCT FROM 'false'::jsonb
       OR reviewed->'mandatory_m1_validation_complete' IS DISTINCT FROM 'false'::jsonb
       OR reviewed->'publishes_fact' IS DISTINCT FROM 'false'::jsonb THEN
        RAISE EXCEPTION 'Applicability review must retain exact gate and actor membership';
    END IF;
    value_page:=(binding->'cells'->0->'source'->>'page_index')::integer;
    SELECT jsonb_agg(page_index ORDER BY page_index) INTO pages FROM (
        SELECT DISTINCT (p->'words'->0->'evidence'->'source'->>'page_index')::integer AS page_index
        FROM jsonb_array_elements(binding->'phrases') p
    ) selected;
    FOR phrase IN SELECT p FROM jsonb_array_elements(binding->'phrases') p LOOP
        SELECT jsonb_agg(w->'evidence'->'id' ORDER BY ord),
            string_agg(w->'reference'->>'quote',' ' ORDER BY ord)
        INTO evidence,phrase_text
        FROM jsonb_array_elements(phrase->'words') WITH ORDINALITY words(w,ord);
        -- Interpretation only. Original words and exact spans remain in the binding.
        phrase_text:=btrim(regexp_replace(translate(phrase_text,'’“”','''""'),'[[:space:]]+',' ','g'));
        IF phrase->>'role'='table_scope' AND phrase_text !~* caption_pattern THEN
            RAISE EXCEPTION 'Supported issuer statement caption required';
        END IF;
        IF phrase_text ~* '\m(hypothetical|illustrative|illustration|fictional|for example|suppose|example only|sample sentence|test fixture)\M'
           OR phrase_text ~* '\m(ignore|override|disregard)[[:space:]]+((all|the|previous|prior|system|these)[[:space:]]+)*(instructions?|rules?|prompts?|gates?)\M'
           OR phrase_text ~* '\m(system prompt|developer message|publish all candidates|accept all candidates)\M'
           OR phrase_text ~* '<[[:space:]]*/?[[:space:]]*(system|developer|assistant)[[:space:]]*>'
           OR phrase_text ~* '\m(run|execute)[[:space:]]+(this[[:space:]]+)?(code|command)\M' THEN
            RAISE EXCEPTION 'Illustrative or instruction-bearing context is blocked';
        END IF;
        qualified_default:=false;
        IF phrase->>'role'='unit_header' THEN
            unit_text:=phrase_text;
            IF left(unit_text,1)='(' AND right(unit_text,1)=')' THEN
                unit_text:=substring(unit_text FROM 2 FOR length(unit_text)-2);
            END IF;
            qualified_default:=unit_text ~* '^(in )?(INR|USD|₹|Rs\.) (in )?(millions?|lakhs?|crores?|billions?),? unless otherwise (specified|stated)$';
        ELSIF phrase->>'role'='basis_context' THEN
            qualified_default:=phrase_text ~* basis_pattern;
        END IF;
        IF phrase_text ~* qualifier_pattern AND NOT qualified_default THEN
            RAISE EXCEPTION 'Unsupported qualified source context';
        END IF;
        expected:=jsonb_build_object('role',phrase->'role','ordinal',phrase->'ordinal',
            'evidence_ids',evidence);
        IF (phrase->'words'->0->'evidence'->'source'->>'page_index')::integer<>value_page THEN
            assertions:=assertions || jsonb_build_array(expected || '{"kind":"CROSS_PAGE"}'::jsonb);
        END IF;
        IF phrase->>'role'='basis_context' AND EXISTS(
            SELECT FROM jsonb_array_elements(outcome->'checks') c
            WHERE c->>'code'='BASIS' AND c->>'state'='REVIEW'
        ) THEN
            IF phrase_text !~* basis_pattern THEN
                RAISE EXCEPTION 'Supported separate reporting basis clause required';
            END IF;
            assertions:=assertions || jsonb_build_array(expected || '{"kind":"BASIS"}'::jsonb);
        END IF;
        IF phrase_text ~* qualifier_pattern AND qualified_default THEN
            assertions:=assertions || jsonb_build_array(expected || '{"kind":"QUALIFIED_DEFAULT"}'::jsonb);
        END IF;
    END LOOP;
    IF jsonb_array_length(assertions)=0 OR request->'assertions' IS DISTINCT FROM assertions
       OR request->'reviewed_page_indices' IS DISTINCT FROM pages THEN
        RAISE EXCEPTION 'Every selected applicability phrase and page must be retained';
    END IF;
    IF EXISTS(SELECT FROM jsonb_array_elements(outcome->'checks') c
        WHERE c->>'code'='CONTEXT_SCOPE' AND c->>'state'='REVIEW')
       AND NOT EXISTS(SELECT FROM jsonb_array_elements(assertions) a WHERE a->>'kind'='CROSS_PAGE') THEN
        RAISE EXCEPTION 'Unresolved statement scope requires supported cross-page applicability';
    END IF;
    IF EXISTS(SELECT FROM jsonb_array_elements(outcome->'checks') c
        WHERE c->>'code'='BASIS' AND c->>'state'='REVIEW')
       AND NOT EXISTS(SELECT FROM jsonb_array_elements(assertions) a WHERE a->>'kind'='BASIS') THEN
        RAISE EXCEPTION 'Unresolved basis requires a supported separate statement clause';
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'Numerical applicability review membership is invalid' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER numerical_applicability_review_guard BEFORE INSERT ON regintel.numerical_applicability_reviews
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_numerical_applicability_review();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.numerical_applicability_reviews
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.numerical_applicability_reviews
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

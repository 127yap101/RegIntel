-- M1.7 immutable semantic-gate results and staged reviewer decisions.
-- Accepted corporate observations and corpus publication remain INSERT-gated.
CREATE TABLE regintel.numeric_metric_policies (
    id regintel.canonical_id PRIMARY KEY,
    metric_id regintel.canonical_id NOT NULL UNIQUE REFERENCES regintel.metric_definitions(id),
    policy_bytes BYTEA NOT NULL CHECK (octet_length(policy_bytes) BETWEEN 1 AND 65536),
    policy_sha256 regintel.sha256_hash NOT NULL,
    registered_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE regintel.validation_runs (
    id regintel.canonical_id PRIMARY KEY,
    candidate_run_id regintel.canonical_id NOT NULL,
    parse_version_id regintel.canonical_id NOT NULL,
    input_bytes BYTEA NOT NULL CHECK (octet_length(input_bytes) BETWEEN 1 AND 64000000),
    input_sha256 regintel.sha256_hash NOT NULL,
    configuration_bytes BYTEA NOT NULL CHECK (octet_length(configuration_bytes) BETWEEN 1 AND 65536),
    configuration_sha256 regintel.sha256_hash NOT NULL,
    run_bytes BYTEA NOT NULL CHECK (octet_length(run_bytes) BETWEEN 1 AND 32000000),
    run_sha256 regintel.sha256_hash NOT NULL,
    result_count regintel.safe_index NOT NULL CHECK (result_count <= 1000),
    submitted_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    creation_transaction BIGINT NOT NULL DEFAULT txid_current(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (candidate_run_id, parse_version_id)
        REFERENCES regintel.candidate_runs(id, parse_version_id),
    UNIQUE (candidate_run_id, input_sha256, configuration_sha256),
    UNIQUE (id, candidate_run_id, parse_version_id)
);
CREATE TABLE regintel.validation_reviews (
    id regintel.canonical_id PRIMARY KEY,
    validation_run_id regintel.canonical_id NOT NULL REFERENCES regintel.validation_runs(id),
    candidate_id regintel.canonical_id NOT NULL UNIQUE
        REFERENCES regintel.candidate_run_items(candidate_id),
    decision TEXT NOT NULL CHECK (decision IN ('APPROVE_FOR_PUBLICATION', 'REJECT')),
    review_bytes BYTEA NOT NULL CHECK (octet_length(review_bytes) BETWEEN 1 AND 1048576),
    review_sha256 regintel.sha256_hash NOT NULL,
    reviewed_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION regintel.validation_text(value JSONB, maximum INTEGER, optional BOOLEAN DEFAULT FALSE)
RETURNS BOOLEAN LANGUAGE sql IMMUTABLE AS $$
    SELECT (optional AND value IS NOT DISTINCT FROM 'null'::JSONB)
        OR (jsonb_typeof(value) IS NOT DISTINCT FROM 'string'
            AND char_length(value #>> '{}') BETWEEN 1 AND maximum);
$$;
CREATE FUNCTION regintel.validation_nonblank(value JSONB) RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE AS $$
    SELECT jsonb_typeof(value) IS NOT DISTINCT FROM 'string' AND btrim(translate(value #>> '{}',
        chr(9)||chr(10)||chr(11)||chr(12)||chr(13)||chr(28)||chr(29)||chr(30)||chr(31)||chr(32)
        ||chr(133)||chr(160)||chr(5760)||chr(8192)||chr(8193)||chr(8194)||chr(8195)
        ||chr(8196)||chr(8197)||chr(8198)||chr(8199)||chr(8200)||chr(8201)||chr(8202)
        ||chr(8232)||chr(8233)||chr(8239)||chr(8287)||chr(12288), repeat(' ',29))) <> '';
$$;
CREATE FUNCTION regintel.validation_decimal(value JSONB, optional BOOLEAN DEFAULT FALSE)
RETURNS BOOLEAN LANGUAGE sql IMMUTABLE AS $$
    SELECT (optional AND value IS NOT DISTINCT FROM 'null'::JSONB)
        OR (jsonb_typeof(value) IS NOT DISTINCT FROM 'string'
            AND coalesce(value #>> '{}', '') ~ '^-?(0|[1-9][0-9]{0,119})(\.[0-9]{1,120})?$');
$$;
CREATE FUNCTION regintel.validation_date(value JSONB, optional BOOLEAN DEFAULT FALSE)
RETURNS BOOLEAN LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE rendered TEXT;
BEGIN
    IF optional AND value IS NOT DISTINCT FROM 'null'::JSONB THEN RETURN TRUE; END IF;
    rendered := value #>> '{}';
    IF jsonb_typeof(value) IS DISTINCT FROM 'string' OR rendered IS NULL
       OR rendered !~ '^(000[1-9]|00[1-9][0-9]|0[1-9][0-9]{2}|[1-9][0-9]{3})-[0-9]{2}-[0-9]{2}$' THEN
        RETURN FALSE;
    END IF;
    BEGIN
        RETURN (rendered::DATE)::TEXT = rendered;
    EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format THEN
        RETURN FALSE;
    END;
END;
$$;

CREATE FUNCTION regintel.validate_numeric_metric_policy() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE payload JSONB; unit JSONB; allowed TEXT[]; metric RECORD;
BEGIN
    PERFORM regintel.entity_admin(NEW.registered_by, NEW.auth_version);
    payload := convert_from(NEW.policy_bytes, 'UTF8')::JSONB;
    SELECT definition_bytes INTO metric FROM regintel.metric_definitions WHERE id = NEW.metric_id;
    IF NOT FOUND OR convert_from(metric.definition_bytes, 'UTF8')::JSONB ->> 'kind' <> 'numeric_fact'
       OR NOT regintel.entity_json_keys(payload, ARRAY['id','metric_id','quantity_kind',
            'period_kind','allowed_unit_labels','required_reporting_basis','review_note'])
       OR convert_from(NEW.policy_bytes, 'UTF8') IS DISTINCT FROM regintel.candidate_canonical_json(payload)
       OR encode(sha256(NEW.policy_bytes), 'hex') IS DISTINCT FROM NEW.policy_sha256
       OR payload ->> 'id' IS DISTINCT FROM NEW.id::TEXT
       OR payload ->> 'metric_id' IS DISTINCT FROM NEW.metric_id::TEXT
       OR NOT regintel.validation_text(payload -> 'quantity_kind', 16)
       OR payload ->> 'quantity_kind' NOT IN ('MONEY','COUNT','POWER','PERCENTAGE')
       OR NOT regintel.validation_text(payload -> 'period_kind', 16)
       OR payload ->> 'period_kind' NOT IN ('INSTANT','DURATION')
       OR jsonb_typeof(payload -> 'required_reporting_basis') IS DISTINCT FROM 'boolean'
       OR NOT regintel.validation_text(payload -> 'review_note', 2000)
       OR NOT regintel.validation_nonblank(payload -> 'review_note')
       OR jsonb_typeof(payload -> 'allowed_unit_labels') IS DISTINCT FROM 'array'
       OR jsonb_array_length(payload -> 'allowed_unit_labels') NOT BETWEEN 1 AND 16 THEN
        RAISE EXCEPTION 'Numeric policies require a reviewed immutable matching metric contract'
            USING ERRCODE = '23514';
    END IF;
    allowed := CASE payload ->> 'quantity_kind'
        WHEN 'MONEY' THEN ARRAY['INR','USD','rupees','crore','crores','lakh','lakhs',
            'million','millions','billion','billions']
        WHEN 'COUNT' THEN ARRAY['shares'] WHEN 'POWER' THEN ARRAY['MW','GW'] ELSE ARRAY['%'] END;
    FOR unit IN SELECT jsonb_array_elements(payload -> 'allowed_unit_labels') LOOP
        IF jsonb_typeof(unit) IS DISTINCT FROM 'string' OR NOT (unit #>> '{}' = ANY(allowed)) THEN
            RAISE EXCEPTION 'Metric units must match the policy quantity family' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF (SELECT count(DISTINCT entry) FROM jsonb_array_elements(payload -> 'allowed_unit_labels') entry)
       <> jsonb_array_length(payload -> 'allowed_unit_labels') THEN
        RAISE EXCEPTION 'Metric policy units must be distinct' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER numeric_metric_policy_gate BEFORE INSERT ON regintel.numeric_metric_policies
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_numeric_metric_policy();

CREATE FUNCTION regintel.validation_quantity(quantity JSONB, draft JSONB, expected_parse UUID)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE period JSONB; field TEXT; raw JSONB; span JSONB;
BEGIN
    raw := draft -> 'raw_quantity';
    IF NOT regintel.entity_json_keys(quantity, ARRAY['raw_value','normalized_value','raw_unit',
            'normalized_unit','raw_currency','currency','period','basis','raw_basis_label',
            'denominator','stake_kind','ownership_date','evidence_ids'])
       OR NOT regintel.validation_text(quantity -> 'raw_value', 200000)
       OR NOT regintel.validation_decimal(quantity -> 'normalized_value', TRUE)
       OR NOT regintel.validation_text(quantity -> 'normalized_unit', 256, TRUE)
       OR NOT regintel.validation_text(quantity -> 'currency', 256, TRUE)
       OR NOT regintel.validation_text(quantity -> 'basis', 32)
       OR quantity ->> 'basis' NOT IN ('STANDALONE','CONSOLIDATED','UNKNOWN')
       OR NOT regintel.validation_date(quantity -> 'ownership_date', TRUE)
       OR jsonb_typeof(quantity -> 'evidence_ids') IS DISTINCT FROM 'array'
       OR jsonb_array_length(quantity -> 'evidence_ids') NOT BETWEEN 1 AND 16
       OR (SELECT count(DISTINCT entry) FROM jsonb_array_elements(quantity -> 'evidence_ids') entry)
            <> jsonb_array_length(quantity -> 'evidence_ids') THEN
        RAISE EXCEPTION 'Interpreted quantities require bounded exact Decimal-string context'
            USING ERRCODE = '23514';
    END IF;
    FOREACH field IN ARRAY ARRAY['raw_unit','raw_currency','raw_basis_label','denominator','stake_kind'] LOOP
        IF NOT regintel.validation_text(quantity -> field,
            CASE WHEN field IN ('denominator','stake_kind') THEN 256 ELSE 200000 END, TRUE) THEN
            RAISE EXCEPTION 'Interpreted quantity labels must be bounded nullable strings'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    period := quantity -> 'period';
    IF NOT regintel.entity_json_keys(period, ARRAY['kind','start_date','end_date','instant_date','raw_label'])
       OR NOT regintel.validation_text(period -> 'kind', 16)
       OR period ->> 'kind' NOT IN ('INSTANT','DURATION','UNKNOWN')
       OR NOT regintel.validation_date(period -> 'start_date', TRUE)
       OR NOT regintel.validation_date(period -> 'end_date', TRUE)
       OR NOT regintel.validation_date(period -> 'instant_date', TRUE)
       OR NOT regintel.validation_text(period -> 'raw_label', 200000, TRUE)
       OR (period ->> 'kind' = 'INSTANT' AND (period -> 'start_date' <> 'null'::JSONB
            OR period -> 'end_date' <> 'null'::JSONB))
       OR (period ->> 'kind' = 'DURATION' AND (period -> 'instant_date' <> 'null'::JSONB
            OR (period ->> 'start_date' IS NOT NULL AND period ->> 'end_date' IS NOT NULL
                AND period ->> 'end_date' < period ->> 'start_date')))
       OR (period ->> 'kind' = 'UNKNOWN' AND (period -> 'start_date' <> 'null'::JSONB
            OR period -> 'end_date' <> 'null'::JSONB OR period -> 'instant_date' <> 'null'::JSONB)) THEN
        RAISE EXCEPTION 'Interpreted periods require valid nonconflicting ISO dates'
            USING ERRCODE = '23514';
    END IF;
    FOR span IN SELECT jsonb_array_elements(quantity -> 'evidence_ids') LOOP
        IF NOT regintel.candidate_uuid(span) OR NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(draft -> 'supports') support
                WHERE support -> 'evidence_id' = span) THEN
            RAISE EXCEPTION 'Quantity evidence must belong to its exact candidate source'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF raw IS DISTINCT FROM 'null'::JSONB
       AND quantity ->> 'raw_value' IS DISTINCT FROM raw -> 'value' ->> 'quote' THEN
        RAISE EXCEPTION 'Normalized values must preserve the original candidate raw value'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

CREATE FUNCTION regintel.validation_candidate_snapshot(owner regintel.candidate_runs)
RETURNS JSONB LANGUAGE plpgsql STABLE AS $$
DECLARE bundle JSONB; entry RECORD; candidate RECORD; context RECORD; ids JSONB;
        records JSONB := '[]'::JSONB; quantities JSONB := '[]'::JSONB;
BEGIN
    bundle := convert_from(owner.bundle_bytes, 'UTF8')::JSONB;
    FOR entry IN SELECT value FROM jsonb_array_elements((bundle -> 'numeric_facts')
        || (bundle -> 'narrative_facts') || (bundle -> 'relations')) LOOP
        SELECT c.* INTO STRICT candidate FROM regintel.candidate_run_items item
            JOIN regintel.candidates c ON c.id = item.candidate_id
            WHERE item.run_id = owner.id
                AND convert_from(item.draft_bytes, 'UTF8')::JSONB = entry.value;
        SELECT jsonb_agg(evidence_id ORDER BY position) INTO ids FROM (
            SELECT DISTINCT ON (value ->> 'evidence_id') value ->> 'evidence_id' AS evidence_id,
                ordinality AS position FROM jsonb_array_elements(entry.value -> 'supports')
                    WITH ORDINALITY ORDER BY value ->> 'evidence_id', ordinality) source_ids;
        records := records || jsonb_build_array(jsonb_build_object('id',candidate.id,
            'parse_version_id',candidate.parse_version_id,'kind',candidate.kind,'state',candidate.state,
            'subject_entity_id',candidate.subject_entity_id,'object_entity_id',candidate.object_entity_id,
            'metric_id',candidate.metric_id,'relation_type',candidate.relation_type,
            'raw_text',candidate.raw_text,'quantitative_context_id',candidate.quantitative_context_id,
            'evidence_ids',ids));
        IF candidate.quantitative_context_id IS NOT NULL THEN
            SELECT * INTO STRICT context FROM regintel.quantitative_contexts
                WHERE id = candidate.quantitative_context_id;
            quantities := quantities || jsonb_build_array(jsonb_build_object('id',context.id,
                'parse_version_id',context.parse_version_id,'quantity',jsonb_build_object(
                    'raw_value',context.raw_value,'normalized_value',context.normalized_value::TEXT,
                    'raw_unit',context.raw_unit,'normalized_unit',context.normalized_unit,
                    'raw_currency',context.raw_currency,'currency',context.currency,
                    'period',jsonb_build_object('kind',context.period_kind,'start_date',context.start_date::TEXT,
                        'end_date',context.end_date::TEXT,'instant_date',context.instant_date::TEXT,
                        'raw_label',context.raw_period_label),
                    'basis',context.basis,'raw_basis_label',context.raw_basis_label,
                    'denominator',context.denominator,'stake_kind',context.stake_kind,
                    'ownership_date',context.ownership_date::TEXT,'evidence_ids',ids)));
        END IF;
    END LOOP;
    RETURN jsonb_build_object('id',owner.id,'parse_version_id',owner.parse_version_id,
        'entity_run_id',owner.entity_run_id,'input_sha256',owner.input_sha256,
        'configuration',convert_from(owner.configuration_bytes,'UTF8')::JSONB,
        'bundle',bundle,'candidates',records,'quantities',quantities);
END;
$$;

CREATE FUNCTION regintel.validation_current_reviews(entity_run_id UUID)
RETURNS JSONB LANGUAGE sql STABLE AS $$
    SELECT coalesce(jsonb_agg(convert_from(review_bytes, 'UTF8')::JSONB ORDER BY mention_id,id),
        '[]'::JSONB) FROM regintel.entity_reviews WHERE run_id = entity_run_id;
$$;
CREATE FUNCTION regintel.validation_current_policies(source JSONB)
RETURNS JSONB LANGUAGE sql STABLE AS $$
    SELECT coalesce(jsonb_agg(convert_from(policy_bytes,'UTF8')::JSONB ORDER BY id),
        '[]'::JSONB) FROM regintel.numeric_metric_policies p WHERE EXISTS (
            SELECT 1 FROM jsonb_array_elements(source -> 'metrics') metric
                WHERE metric ->> 'id' = p.metric_id::TEXT);
$$;

CREATE FUNCTION regintel.validate_validation_result(result JSONB, draft JSONB, expected_parse UUID)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE check_item JSONB; witness JSONB; primary_span JSONB; quantity JSONB;
        states TEXT[]; role TEXT; raw_label TEXT; required_codes TEXT[];
BEGIN
    required_codes := ARRAY['SOURCE','ENTITY','TABLE_CONTEXT','SOURCE_SCOPE','ATTRIBUTION','DIRECTION','METRIC',
        'VALUE','UNIT','CURRENCY','PERIOD','BASIS','DENOMINATOR','STAKE_KIND','OWNERSHIP_DATE','EXTRACTIVE_REVIEW'];
    IF NOT regintel.entity_json_keys(result, ARRAY['candidate_id','state','checks','quantity',
            'context_supports','reviewer_eligible'])
       OR NOT regintel.candidate_uuid(result -> 'candidate_id')
       OR NOT regintel.validation_text(result -> 'state', 16)
       OR result ->> 'state' NOT IN ('PASS','REVIEW','QUARANTINED')
       OR jsonb_typeof(result -> 'checks') IS DISTINCT FROM 'array'
       OR jsonb_array_length(result -> 'checks') <> cardinality(required_codes)
       OR jsonb_typeof(result -> 'quantity') NOT IN ('object','null')
       OR jsonb_typeof(result -> 'context_supports') IS DISTINCT FROM 'array'
       OR jsonb_array_length(result -> 'context_supports') > 16
       OR jsonb_typeof(result -> 'reviewer_eligible') IS DISTINCT FROM 'boolean' THEN
        RAISE EXCEPTION 'Validation results require all distinct mandatory gate checks'
            USING ERRCODE = '23514';
    END IF;
    FOR check_item IN SELECT jsonb_array_elements(result -> 'checks') LOOP
        IF NOT regintel.entity_json_keys(check_item, ARRAY['code','state','message'])
           OR NOT regintel.validation_text(check_item -> 'code', 32)
           OR NOT (check_item ->> 'code' = ANY(required_codes))
           OR NOT regintel.validation_text(check_item -> 'state', 16)
           OR check_item ->> 'state' NOT IN ('PASS','REVIEW','FAIL')
           OR NOT regintel.validation_text(check_item -> 'message', 500) THEN
            RAISE EXCEPTION 'Validation checks require known codes and bounded states/messages'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF (SELECT count(DISTINCT item ->> 'code') FROM jsonb_array_elements(result -> 'checks') item)
            <> cardinality(required_codes) THEN
        RAISE EXCEPTION 'Validation checks must exactly complete the mandatory contract'
            USING ERRCODE = '23514';
    END IF;
    SELECT array_agg(item ->> 'state') INTO states FROM jsonb_array_elements(result -> 'checks') item;
    IF result ->> 'state' IS DISTINCT FROM (CASE WHEN 'FAIL' = ANY(states) THEN 'QUARANTINED'
            WHEN 'REVIEW' = ANY(states) THEN 'REVIEW' ELSE 'PASS' END)
       OR (result ->> 'reviewer_eligible')::BOOLEAN IS DISTINCT FROM
            (NOT ('FAIL' = ANY(states)) AND NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(result -> 'checks') item
                    WHERE item ->> 'state' = 'REVIEW' AND item ->> 'code' <> 'EXTRACTIVE_REVIEW')) THEN
        RAISE EXCEPTION 'Mandatory failure or ambiguity cannot be reviewer-overridden'
            USING ERRCODE = '23514';
    END IF;
    primary_span := draft -> 'supports' -> 0;
    FOR witness IN SELECT jsonb_array_elements(result -> 'context_supports') LOOP
        IF NOT regintel.entity_json_keys(witness, ARRAY['role','span'])
           OR NOT regintel.validation_text(witness -> 'role', 32)
           OR witness ->> 'role' NOT IN ('VALUE','UNIT','CURRENCY','PERIOD','BASIS',
                'DENOMINATOR','STAKE_KIND','OWNERSHIP_DATE') THEN
            RAISE EXCEPTION 'Context witnesses require known exact source roles' USING ERRCODE = '23514';
        END IF;
        PERFORM regintel.candidate_span(witness -> 'span', expected_parse);
        IF witness -> 'span' ->> 'evidence_id' IS DISTINCT FROM primary_span ->> 'evidence_id'
           OR (witness -> 'span' ->> 'start')::BIGINT < (primary_span ->> 'start')::BIGINT
           OR (witness -> 'span' ->> 'end')::BIGINT > (primary_span ->> 'end')::BIGINT THEN
            RAISE EXCEPTION 'Context witnesses must remain inside the exact primary statement'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF (SELECT count(DISTINCT entry) FROM jsonb_array_elements(result -> 'context_supports') entry)
       <> jsonb_array_length(result -> 'context_supports') THEN
        RAISE EXCEPTION 'Context witnesses must be distinct' USING ERRCODE = '23514';
    END IF;
    quantity := result -> 'quantity';
    IF quantity IS DISTINCT FROM 'null'::JSONB THEN
        IF draft ->> 'kind' = 'narrative_fact' OR draft -> 'raw_quantity' = 'null'::JSONB THEN
            RAISE EXCEPTION 'A draft without quantity cannot gain financial interpretation'
                USING ERRCODE = '23514';
        END IF;
        PERFORM regintel.validation_quantity(quantity, draft, expected_parse);
        FOREACH role IN ARRAY ARRAY['VALUE','UNIT','CURRENCY','PERIOD','BASIS','DENOMINATOR','STAKE_KIND'] LOOP
            raw_label := CASE role WHEN 'VALUE' THEN quantity ->> 'raw_value'
                WHEN 'UNIT' THEN quantity ->> 'raw_unit' WHEN 'CURRENCY' THEN quantity ->> 'raw_currency'
                WHEN 'PERIOD' THEN quantity -> 'period' ->> 'raw_label'
                WHEN 'BASIS' THEN quantity ->> 'raw_basis_label' WHEN 'DENOMINATOR' THEN quantity ->> 'denominator'
                ELSE quantity ->> 'stake_kind' END;
            IF raw_label IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(result -> 'context_supports') witness_item
                    WHERE witness_item ->> 'role' = role
                        AND witness_item -> 'span' ->> 'quote' = raw_label) THEN
                RAISE EXCEPTION 'Every raw quantitative label requires its exact role witness'
                    USING ERRCODE = '23514';
            END IF;
        END LOOP;
    END IF;
END;
$$;

CREATE FUNCTION regintel.validate_validation_run() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE payload JSONB; input JSONB; configuration JSONB; owner regintel.candidate_runs;
        item JSONB; result JSONB; draft JSONB;
BEGIN
    PERFORM regintel.entity_admin(NEW.submitted_by, NEW.auth_version);
    NEW.creation_transaction := txid_current();
    payload := convert_from(NEW.run_bytes, 'UTF8')::JSONB;
    input := convert_from(NEW.input_bytes, 'UTF8')::JSONB;
    configuration := convert_from(NEW.configuration_bytes, 'UTF8')::JSONB;
    SELECT * INTO owner FROM regintel.candidate_runs WHERE id = NEW.candidate_run_id FOR SHARE;
    IF NOT FOUND OR NEW.parse_version_id IS DISTINCT FROM owner.parse_version_id
       OR NOT regintel.entity_json_keys(input, ARRAY['candidate_run','source','source_input_sha256',
            'entity_reviews','policies','table_evidence_ids','transcription_evidence_ids'])
       OR input -> 'source' IS DISTINCT FROM convert_from(owner.input_bytes,'UTF8')::JSONB
       OR input ->> 'source_input_sha256' IS DISTINCT FROM owner.input_sha256
       OR input -> 'candidate_run' IS DISTINCT FROM regintel.validation_candidate_snapshot(owner)
       OR encode(sha256(NEW.input_bytes),'hex') IS DISTINCT FROM NEW.input_sha256
       OR encode(sha256(NEW.configuration_bytes),'hex') IS DISTINCT FROM NEW.configuration_sha256
       OR encode(sha256(NEW.run_bytes),'hex') IS DISTINCT FROM NEW.run_sha256
       OR convert_from(NEW.configuration_bytes,'UTF8') IS DISTINCT FROM regintel.candidate_canonical_json(configuration)
       OR convert_from(NEW.run_bytes,'UTF8') IS DISTINCT FROM regintel.candidate_canonical_json(payload)
       OR NOT regintel.entity_json_keys(configuration, ARRAY['version','code_sha256'])
       OR configuration ->> 'version' IS DISTINCT FROM '1.0.0'
       OR jsonb_typeof(configuration -> 'code_sha256') IS DISTINCT FROM 'string'
       OR configuration ->> 'code_sha256' !~ '^[0-9a-f]{64}$'
       OR NEW.id IS DISTINCT FROM regintel.candidate_stable_id(
            'validation-run:' || NEW.input_sha256 || ':' || NEW.configuration_sha256)
       OR NOT regintel.entity_json_keys(payload, ARRAY['id','candidate_run_id','parse_version_id',
            'input_sha256','configuration','results'])
       OR payload ->> 'id' IS DISTINCT FROM NEW.id::TEXT
       OR payload ->> 'candidate_run_id' IS DISTINCT FROM NEW.candidate_run_id::TEXT
       OR payload ->> 'parse_version_id' IS DISTINCT FROM NEW.parse_version_id::TEXT
       OR payload ->> 'input_sha256' IS DISTINCT FROM NEW.input_sha256
       OR payload -> 'configuration' IS DISTINCT FROM configuration
       OR jsonb_typeof(payload -> 'results') IS DISTINCT FROM 'array'
       OR jsonb_array_length(payload -> 'results') <> NEW.result_count
       OR NEW.result_count <> owner.candidate_count
       OR jsonb_typeof(input -> 'entity_reviews') IS DISTINCT FROM 'array'
       OR input -> 'entity_reviews' IS DISTINCT FROM regintel.validation_current_reviews(owner.entity_run_id)
       OR jsonb_typeof(input -> 'policies') IS DISTINCT FROM 'array'
       OR input -> 'policies' IS DISTINCT FROM regintel.validation_current_policies(input -> 'source')
       OR jsonb_typeof(input -> 'table_evidence_ids') IS DISTINCT FROM 'array'
       OR jsonb_array_length(input -> 'table_evidence_ids') > 10000
       OR jsonb_typeof(input -> 'transcription_evidence_ids') IS DISTINCT FROM 'array'
       OR jsonb_array_length(input -> 'transcription_evidence_ids') > 10000 THEN
        RAISE EXCEPTION 'Validation runs require complete sealed candidates and current audited dependencies'
            USING ERRCODE = '23514';
    END IF;
    IF (SELECT count(DISTINCT entry ->> 'candidate_id') FROM jsonb_array_elements(payload -> 'results') entry)
            <> NEW.result_count
       OR (SELECT count(DISTINCT entry) FROM jsonb_array_elements(input -> 'table_evidence_ids') entry)
            <> jsonb_array_length(input -> 'table_evidence_ids')
       OR (SELECT count(DISTINCT entry) FROM jsonb_array_elements(input -> 'transcription_evidence_ids') entry)
            <> jsonb_array_length(input -> 'transcription_evidence_ids') THEN
        RAISE EXCEPTION 'Validation results and table-risk IDs must be distinct' USING ERRCODE = '23514';
    END IF;
    FOR item IN SELECT jsonb_array_elements(input -> 'table_evidence_ids') LOOP
        IF NOT regintel.candidate_uuid(item) OR NOT EXISTS (
            SELECT 1 FROM regintel.evidence WHERE id = (item #>> '{}')::UUID
                AND parse_version_id = NEW.parse_version_id AND kind = 'text') THEN
            RAISE EXCEPTION 'Table-risk IDs must belong to sealed source text' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    FOR item IN SELECT jsonb_array_elements(input -> 'transcription_evidence_ids') LOOP
        IF NOT regintel.candidate_uuid(item) OR NOT EXISTS (
            SELECT 1 FROM regintel.evidence WHERE id = (item #>> '{}')::UUID
                AND parse_version_id = NEW.parse_version_id AND kind = 'text') THEN
            RAISE EXCEPTION 'Transcription-risk IDs must belong to sealed source text' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    FOR result IN SELECT jsonb_array_elements(payload -> 'results') LOOP
        SELECT convert_from(draft_bytes,'UTF8')::JSONB INTO draft FROM regintel.candidate_run_items
            WHERE run_id = NEW.candidate_run_id AND candidate_id::TEXT = result ->> 'candidate_id';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Validation results must own every sealed candidate exactly once'
                USING ERRCODE = '23514';
        END IF;
        PERFORM regintel.validate_validation_result(result, draft, NEW.parse_version_id);
    END LOOP;
    RETURN NEW;
END;
$$;
CREATE TRIGGER validation_run_gate BEFORE INSERT ON regintel.validation_runs
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_validation_run();

CREATE FUNCTION regintel.validate_validation_review() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE payload JSONB; owner regintel.validation_runs; candidate_owner regintel.candidate_runs;
        result JSONB; draft JSONB; input JSONB; span JSONB; primary_span JSONB;
BEGIN
    PERFORM regintel.entity_admin(NEW.reviewed_by, NEW.auth_version);
    payload := convert_from(NEW.review_bytes,'UTF8')::JSONB;
    SELECT * INTO owner FROM regintel.validation_runs WHERE id = NEW.validation_run_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Review requires an immutable validation run' USING ERRCODE = '23514';
    END IF;
    SELECT convert_from(draft_bytes,'UTF8')::JSONB INTO draft FROM regintel.candidate_run_items
        WHERE run_id = owner.candidate_run_id AND candidate_id = NEW.candidate_id;
    IF NOT FOUND OR NOT regintel.entity_json_keys(payload, ARRAY['id','validation_run_id',
            'candidate_id','decision','supports','review_note'])
       OR convert_from(NEW.review_bytes,'UTF8') IS DISTINCT FROM regintel.candidate_canonical_json(payload)
       OR encode(sha256(NEW.review_bytes),'hex') IS DISTINCT FROM NEW.review_sha256
       OR payload ->> 'id' IS DISTINCT FROM NEW.id::TEXT
       OR payload ->> 'validation_run_id' IS DISTINCT FROM NEW.validation_run_id::TEXT
       OR payload ->> 'candidate_id' IS DISTINCT FROM NEW.candidate_id::TEXT
       OR payload ->> 'decision' IS DISTINCT FROM NEW.decision
       OR jsonb_typeof(payload -> 'supports') IS DISTINCT FROM 'array'
       OR jsonb_array_length(payload -> 'supports') NOT BETWEEN 1 AND 16
       OR NOT regintel.validation_text(payload -> 'review_note', 2000)
       OR NOT regintel.validation_nonblank(payload -> 'review_note') THEN
        RAISE EXCEPTION 'Validation review requires a bounded exact immutable audit'
            USING ERRCODE = '23514';
    END IF;
    primary_span := draft -> 'supports' -> 0;
    IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(payload -> 'supports') support
            WHERE support = primary_span)
       OR (SELECT count(DISTINCT support) FROM jsonb_array_elements(payload -> 'supports') support)
            <> jsonb_array_length(payload -> 'supports') THEN
        RAISE EXCEPTION 'Review requires the full original primary statement and distinct support'
            USING ERRCODE = '23514';
    END IF;
    FOR span IN SELECT jsonb_array_elements(payload -> 'supports') LOOP
        PERFORM regintel.candidate_span(span, owner.parse_version_id);
        IF span ->> 'evidence_id' IS DISTINCT FROM primary_span ->> 'evidence_id'
           OR (span ->> 'start')::BIGINT < (primary_span ->> 'start')::BIGINT
           OR (span ->> 'end')::BIGINT > (primary_span ->> 'end')::BIGINT THEN
            RAISE EXCEPTION 'Review support must remain within the original primary statement'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF NEW.decision = 'APPROVE_FOR_PUBLICATION' THEN
        SELECT item INTO result FROM jsonb_array_elements(convert_from(owner.run_bytes,'UTF8')::JSONB -> 'results') item
            WHERE item ->> 'candidate_id' = NEW.candidate_id::TEXT;
        input := convert_from(owner.input_bytes,'UTF8')::JSONB;
        SELECT * INTO candidate_owner FROM regintel.candidate_runs WHERE id = owner.candidate_run_id;
        IF result -> 'reviewer_eligible' IS DISTINCT FROM 'true'::JSONB
           OR result ->> 'state' NOT IN ('PASS','REVIEW')
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(result -> 'checks') item
                WHERE (item ->> 'code' <> 'EXTRACTIVE_REVIEW' AND item ->> 'state' <> 'PASS')
                    OR item ->> 'state' = 'FAIL')
           OR input -> 'entity_reviews' IS DISTINCT FROM regintel.validation_current_reviews(candidate_owner.entity_run_id)
           OR input -> 'policies' IS DISTINCT FROM regintel.validation_current_policies(input -> 'source') THEN
            RAISE EXCEPTION 'Approval cannot bypass mandatory gates or stale audited dependencies'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER validation_review_gate BEFORE INSERT ON regintel.validation_reviews
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_validation_review();

DO $$
DECLARE target TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY['numeric_metric_policies','validation_runs','validation_reviews'] LOOP
        EXECUTE format('CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.%I '
            'FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation()', target);
        EXECUTE format('CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.%I '
            'FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation()', target);
    END LOOP;
END;
$$;

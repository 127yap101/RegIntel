-- M1.6 immutable extraction proposals. Acceptance and publication remain closed.
CREATE TABLE regintel.metric_definitions (
    id regintel.canonical_id PRIMARY KEY,
    metric_key TEXT COLLATE "C" NOT NULL UNIQUE
        CHECK (metric_key ~ '^[a-z][a-z0-9_]{0,63}$'),
    definition_bytes BYTEA NOT NULL CHECK (octet_length(definition_bytes) BETWEEN 1 AND 65536),
    definition_sha256 regintel.sha256_hash NOT NULL,
    registered_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE regintel.candidate_runs (
    id regintel.canonical_id PRIMARY KEY,
    entity_run_id regintel.canonical_id NOT NULL,
    parse_version_id regintel.canonical_id NOT NULL,
    input_bytes BYTEA NOT NULL CHECK (octet_length(input_bytes) BETWEEN 1 AND 32000000),
    input_sha256 regintel.sha256_hash NOT NULL,
    configuration_bytes BYTEA NOT NULL
        CHECK (octet_length(configuration_bytes) BETWEEN 1 AND 65536),
    configuration_sha256 regintel.sha256_hash NOT NULL,
    bundle_bytes BYTEA NOT NULL CHECK (octet_length(bundle_bytes) BETWEEN 1 AND 32000000),
    bundle_sha256 regintel.sha256_hash NOT NULL,
    candidate_count regintel.safe_index NOT NULL CHECK (candidate_count <= 1000),
    submitted_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    creation_transaction BIGINT NOT NULL DEFAULT txid_current(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (entity_run_id, parse_version_id)
        REFERENCES regintel.entity_runs(id, parse_version_id),
    UNIQUE (entity_run_id, input_sha256, configuration_sha256),
    UNIQUE (id, parse_version_id)
);
CREATE TABLE regintel.candidate_run_items (
    run_id regintel.canonical_id NOT NULL,
    candidate_id regintel.canonical_id NOT NULL UNIQUE,
    parse_version_id regintel.canonical_id NOT NULL,
    draft_bytes BYTEA NOT NULL CHECK (octet_length(draft_bytes) BETWEEN 1 AND 1048576),
    PRIMARY KEY (run_id, candidate_id),
    FOREIGN KEY (run_id, parse_version_id)
        REFERENCES regintel.candidate_runs(id, parse_version_id),
    FOREIGN KEY (candidate_id, parse_version_id)
        REFERENCES regintel.candidates(id, parse_version_id)
);

CREATE FUNCTION regintel.candidate_uuid(value JSONB) RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE AS $$
    SELECT jsonb_typeof(value) IS NOT DISTINCT FROM 'string' AND coalesce(value #>> '{}', '')
        ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$';
$$;
CREATE FUNCTION regintel.candidate_stable_id(value TEXT) RETURNS UUID
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE hash BYTEA; rendered TEXT;
BEGIN
    hash := sha256(convert_to(value, 'UTF8'));
    rendered := encode(substr(hash, 1, 16), 'hex');
    rendered := substr(rendered, 1, 12) || '4' || substr(rendered, 14, 3)
        || to_hex(((get_byte(hash, 8) >> 4) & 3) | 8) || substr(rendered, 18, 15);
    RETURN (substr(rendered, 1, 8) || '-' || substr(rendered, 9, 4) || '-'
        || substr(rendered, 13, 4) || '-' || substr(rendered, 17, 4) || '-'
        || substr(rendered, 21, 12))::UUID;
END;
$$;
CREATE FUNCTION regintel.candidate_canonical_json(value JSONB) RETURNS TEXT
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE kind TEXT; result TEXT; item RECORD;
BEGIN
    kind := jsonb_typeof(value);
    IF kind = 'object' THEN
        result := '';
        FOR item IN SELECT key, val FROM jsonb_each(value) AS fields(key, val)
            ORDER BY key COLLATE "C" LOOP
            result := result || CASE WHEN result = '' THEN '' ELSE ',' END
                || to_json(item.key)::TEXT || ':' || regintel.candidate_canonical_json(item.val);
        END LOOP;
        RETURN '{' || result || '}';
    ELSIF kind = 'array' THEN
        result := '';
        FOR item IN SELECT val FROM jsonb_array_elements(value) AS items(val) LOOP
            result := result || CASE WHEN result = '' THEN '' ELSE ',' END
                || regintel.candidate_canonical_json(item.val);
        END LOOP;
        RETURN '[' || result || ']';
    END IF;
    RETURN value::TEXT;
END;
$$;
CREATE FUNCTION regintel.candidate_span(anchor JSONB, expected_parse UUID) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE source RECORD; start_at BIGINT; end_at BIGINT;
BEGIN
    IF NOT regintel.entity_json_keys(anchor, ARRAY['evidence_id', 'start', 'end', 'quote'])
       OR NOT regintel.candidate_uuid(anchor -> 'evidence_id')
       OR jsonb_typeof(anchor -> 'start') IS DISTINCT FROM 'number'
       OR jsonb_typeof(anchor -> 'end') IS DISTINCT FROM 'number'
       OR anchor ->> 'start' !~ '^[0-9]{1,16}$'
       OR anchor ->> 'end' !~ '^[0-9]{1,16}$'
       OR jsonb_typeof(anchor -> 'quote') IS DISTINCT FROM 'string'
       OR char_length(anchor ->> 'quote') NOT BETWEEN 1 AND 20000 THEN
        RAISE EXCEPTION 'Candidate support requires a bounded exact Unicode source span'
            USING ERRCODE = '23514';
    END IF;
    start_at := (anchor ->> 'start')::BIGINT;
    end_at := (anchor ->> 'end')::BIGINT;
    SELECT e.* INTO source FROM regintel.evidence e
        JOIN regintel.parse_artifacts a ON a.parse_version_id = e.parse_version_id
        JOIN regintel.filing_jobs j ON j.id = a.job_id AND j.state = 'PARSED'
            AND j.parse_version_id = e.parse_version_id
        WHERE e.id = (anchor ->> 'evidence_id')::UUID AND e.kind = 'text'
            AND e.parse_version_id = expected_parse;
    IF NOT FOUND OR start_at < source.start_offset OR end_at > source.end_offset
       OR end_at <= start_at OR end_at > 9007199254740991
       OR substr(source.quote, (start_at - source.start_offset + 1)::INTEGER,
            (end_at - start_at)::INTEGER) IS DISTINCT FROM anchor ->> 'quote' THEN
        RAISE EXCEPTION 'Candidate span must match sealed exact text evidence'
            USING ERRCODE = '23514';
    END IF;
END;
$$;
CREATE FUNCTION regintel.validate_metric_definition() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE payload JSONB; cue JSONB;
BEGIN
    PERFORM regintel.entity_admin(NEW.registered_by, NEW.auth_version);
    payload := convert_from(NEW.definition_bytes, 'UTF8')::JSONB;
    IF NOT regintel.entity_json_keys(payload, ARRAY['id', 'key', 'label', 'kind', 'cue_phrases'])
       OR convert_from(NEW.definition_bytes, 'UTF8')
            IS DISTINCT FROM regintel.candidate_canonical_json(payload)
       OR encode(sha256(NEW.definition_bytes), 'hex') IS DISTINCT FROM NEW.definition_sha256
       OR payload ->> 'id' IS DISTINCT FROM NEW.id::TEXT
       OR payload ->> 'key' IS DISTINCT FROM NEW.metric_key
       OR jsonb_typeof(payload -> 'label') IS DISTINCT FROM 'string'
       OR char_length(payload ->> 'label') NOT BETWEEN 1 AND 256
       OR jsonb_typeof(payload -> 'kind') IS DISTINCT FROM 'string'
       OR payload ->> 'kind' IS NULL
       OR payload ->> 'kind' NOT IN ('numeric_fact', 'narrative_fact')
       OR jsonb_typeof(payload -> 'cue_phrases') IS DISTINCT FROM 'array'
       OR jsonb_array_length(payload -> 'cue_phrases') NOT BETWEEN 1 AND 16 THEN
        RAISE EXCEPTION 'Metric definitions require a bounded immutable extraction contract'
            USING ERRCODE = '23514';
    END IF;
    FOR cue IN SELECT jsonb_array_elements(payload -> 'cue_phrases') LOOP
        IF jsonb_typeof(cue) IS DISTINCT FROM 'string'
           OR char_length(cue #>> '{}') NOT BETWEEN 1 AND 128
           OR cue #>> '{}' !~ '[[:alnum:]]'
           OR ascii(left(cue #>> '{}', 1)) IN (9,10,11,12,13,28,29,30,31,32,133,160,
                5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288)
           OR ascii(right(cue #>> '{}', 1)) IN (9,10,11,12,13,28,29,30,31,32,133,160,
                5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288) THEN
            RAISE EXCEPTION 'Metric cues require literal bounded text'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF (SELECT count(DISTINCT lower(item)) FROM jsonb_array_elements_text(payload -> 'cue_phrases') item)
       <> jsonb_array_length(payload -> 'cue_phrases') THEN
        RAISE EXCEPTION 'Metric cues must be distinct' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER metric_definition_gate BEFORE INSERT ON regintel.metric_definitions
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_metric_definition();

CREATE FUNCTION regintel.candidate_effective_entity(input JSONB, mention_id TEXT) RETURNS TEXT
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE mention JSONB; review JSONB;
BEGIN
    SELECT item INTO mention FROM jsonb_array_elements(input -> 'entity_run' -> 'mentions') item
        WHERE item ->> 'id' = mention_id;
    IF NOT FOUND THEN RETURN NULL; END IF;
    SELECT item INTO review FROM jsonb_array_elements(input -> 'reviews') item
        WHERE item ->> 'mention_id' = mention_id;
    IF FOUND THEN
        RETURN CASE WHEN review ->> 'decision' = 'RESOLVE' THEN review ->> 'entity_id' END;
    END IF;
    RETURN CASE WHEN mention -> 'resolution' ->> 'state' = 'RESOLVED'
        THEN mention -> 'resolution' ->> 'entity_id' END;
END;
$$;
CREATE FUNCTION regintel.validate_candidate_draft(draft JSONB, input JSONB, expected_kind TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE support JSONB; raw JSONB; item JSONB; role_name TEXT; mention JSONB; primary_text TEXT;
BEGIN
    IF NOT regintel.entity_json_keys(draft, ARRAY['kind', 'subject_entity_id',
            'subject_mention_id', 'object_entity_id', 'object_mention_id', 'metric_id',
            'relation_type', 'supports', 'raw_text', 'raw_quantity'])
       OR draft ->> 'kind' IS DISTINCT FROM expected_kind
       OR NOT regintel.candidate_uuid(draft -> 'subject_entity_id')
       OR NOT regintel.candidate_uuid(draft -> 'subject_mention_id')
       OR regintel.candidate_effective_entity(input, draft ->> 'subject_mention_id')
            IS DISTINCT FROM draft ->> 'subject_entity_id'
       OR jsonb_typeof(draft -> 'supports') IS DISTINCT FROM 'array'
       OR jsonb_array_length(draft -> 'supports') NOT BETWEEN 1 AND 16
       OR jsonb_typeof(draft -> 'raw_text') IS DISTINCT FROM 'string'
       OR char_length(draft ->> 'raw_text') NOT BETWEEN 1 AND 20000
       OR draft ->> 'raw_text' IS DISTINCT FROM draft -> 'supports' -> 0 ->> 'quote'
       OR jsonb_typeof(draft -> 'raw_quantity') NOT IN ('object', 'null') THEN
        RAISE EXCEPTION 'Candidate drafts require supplied resolved identities and exact support'
            USING ERRCODE = '23514';
    END IF;
    primary_text := draft -> 'supports' -> 0 ->> 'quote';
    IF primary_text ~ E'[\\r\\n]'
       OR regexp_replace(translate(primary_text,
                chr(9)||chr(10)||chr(11)||chr(12)||chr(13)||chr(28)||chr(29)||chr(30)||chr(31)||chr(32)
                ||chr(133)||chr(160)||chr(5760)||chr(8192)||chr(8193)||chr(8194)||chr(8195)
                ||chr(8196)||chr(8197)||chr(8198)||chr(8199)||chr(8200)||chr(8201)||chr(8202)
                ||chr(8232)||chr(8233)||chr(8239)||chr(8287)||chr(12288), repeat(' ',29)),
            '(Ltd|Pvt|Mr|Mrs|Ms|Dr|Co|Rs)\.', '\1', 'gi')
            ~ '[.!?][[:space:]]+[A-Z0-9]' THEN
        RAISE EXCEPTION 'Candidate primary spans must occupy one bounded source statement'
            USING ERRCODE = '23514';
    END IF;
    IF expected_kind = 'relation' THEN
        IF NOT regintel.candidate_uuid(draft -> 'object_entity_id')
           OR NOT regintel.candidate_uuid(draft -> 'object_mention_id')
           OR regintel.candidate_effective_entity(input, draft ->> 'object_mention_id')
                IS DISTINCT FROM draft ->> 'object_entity_id'
           OR draft ->> 'object_entity_id' = draft ->> 'subject_entity_id'
           OR draft -> 'metric_id' IS DISTINCT FROM 'null'::JSONB
           OR jsonb_typeof(draft -> 'relation_type') IS DISTINCT FROM 'string'
           OR draft ->> 'relation_type' IS NULL
           OR draft ->> 'relation_type' NOT IN
                ('OWNS', 'PROMOTER_OF', 'SUBSIDIARY_OF', 'SUPPLIES_TO', 'AUDITS', 'LENDS_TO') THEN
            RAISE EXCEPTION 'Relation drafts require distinct directed supplied endpoints'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NOT regintel.candidate_uuid(draft -> 'metric_id')
           OR draft -> 'object_entity_id' IS DISTINCT FROM 'null'::JSONB
           OR draft -> 'object_mention_id' IS DISTINCT FROM 'null'::JSONB
           OR draft -> 'relation_type' IS DISTINCT FROM 'null'::JSONB
           OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(input -> 'metrics') metric
                WHERE metric ->> 'id' = draft ->> 'metric_id'
                    AND metric ->> 'kind' = expected_kind)
           OR (expected_kind = 'numeric_fact'
                AND jsonb_typeof(draft -> 'raw_quantity') IS DISTINCT FROM 'object')
           OR (expected_kind = 'narrative_fact'
                AND draft -> 'raw_quantity' IS DISTINCT FROM 'null'::JSONB) THEN
            RAISE EXCEPTION 'Fact drafts require a supplied matching immutable metric'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    FOR support IN SELECT jsonb_array_elements(draft -> 'supports') LOOP
        PERFORM regintel.candidate_span(support, (input ->> 'parse_version_id')::UUID);
        IF support ->> 'evidence_id' IS DISTINCT FROM draft -> 'supports' -> 0 ->> 'evidence_id'
           OR (support ->> 'start')::BIGINT < (draft -> 'supports' -> 0 ->> 'start')::BIGINT
           OR (support ->> 'end')::BIGINT > (draft -> 'supports' -> 0 ->> 'end')::BIGINT THEN
            RAISE EXCEPTION 'Candidate spans must remain inside one exact primary statement'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF (SELECT count(DISTINCT entry) FROM jsonb_array_elements(draft -> 'supports') entry)
       <> jsonb_array_length(draft -> 'supports') THEN
        RAISE EXCEPTION 'Candidate support spans must be distinct' USING ERRCODE = '23514';
    END IF;
    FOREACH role_name IN ARRAY ARRAY['subject_mention_id', 'object_mention_id'] LOOP
        IF draft ->> role_name IS NOT NULL THEN
            SELECT entry INTO mention FROM jsonb_array_elements(input -> 'entity_run' -> 'mentions') entry
                WHERE entry ->> 'id' = draft ->> role_name;
            IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(draft -> 'supports') span
                WHERE span ->> 'evidence_id' = mention -> 'support' ->> 'evidence_id'
                    AND (span ->> 'start')::BIGINT <= (mention -> 'support' ->> 'start')::BIGINT
                    AND (span ->> 'end')::BIGINT >= (mention -> 'support' ->> 'end')::BIGINT) THEN
                RAISE EXCEPTION 'Candidate endpoint mentions must lie in its bounded support'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END LOOP;
    raw := draft -> 'raw_quantity';
    IF jsonb_typeof(raw) = 'object' THEN
        IF NOT regintel.entity_json_keys(raw, ARRAY['value', 'unit', 'currency', 'period',
                'basis', 'denominator', 'stake_kind', 'ownership_date']) THEN
            RAISE EXCEPTION 'Raw quantities require an exact context-role contract'
                USING ERRCODE = '23514';
        END IF;
        FOREACH role_name IN ARRAY ARRAY['value', 'unit', 'currency', 'period', 'basis',
                'denominator', 'stake_kind', 'ownership_date'] LOOP
            item := raw -> role_name;
            IF role_name = 'value' OR item IS DISTINCT FROM 'null'::JSONB THEN
                PERFORM regintel.candidate_span(item, (input ->> 'parse_version_id')::UUID);
                IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(draft -> 'supports') span
                    WHERE span ->> 'evidence_id' = item ->> 'evidence_id'
                        AND (span ->> 'start')::BIGINT <= (item ->> 'start')::BIGINT
                        AND (span ->> 'end')::BIGINT >= (item ->> 'end')::BIGINT) THEN
                    RAISE EXCEPTION 'Raw context roles must lie within candidate support'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
        END LOOP;
    END IF;
END;
$$;

CREATE FUNCTION regintel.validate_candidate_run() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE input JSONB; bundle JSONB; configuration JSONB; owner RECORD; item JSONB;
        source RECORD; metric JSONB; current_reviews JSONB; collection TEXT; kind TEXT;
        geometry JSONB; boxes JSONB;
BEGIN
    PERFORM regintel.entity_admin(NEW.submitted_by, NEW.auth_version);
    NEW.creation_transaction := txid_current();
    input := convert_from(NEW.input_bytes, 'UTF8')::JSONB;
    bundle := convert_from(NEW.bundle_bytes, 'UTF8')::JSONB;
    configuration := convert_from(NEW.configuration_bytes, 'UTF8')::JSONB;
    SELECT run_bytes, parse_version_id INTO owner FROM regintel.entity_runs
        WHERE id = NEW.entity_run_id FOR SHARE;
    IF NOT FOUND
       OR NOT regintel.entity_json_keys(input,
            ARRAY['parse_version_id', 'entity_run', 'reviews', 'evidence', 'metrics'])
       OR input ->> 'parse_version_id' IS DISTINCT FROM NEW.parse_version_id::TEXT
       OR owner.parse_version_id IS DISTINCT FROM NEW.parse_version_id
       OR input -> 'entity_run' IS DISTINCT FROM convert_from(owner.run_bytes, 'UTF8')::JSONB
       OR encode(sha256(NEW.input_bytes), 'hex') IS DISTINCT FROM NEW.input_sha256
       OR encode(sha256(NEW.configuration_bytes), 'hex')
            IS DISTINCT FROM NEW.configuration_sha256
       OR encode(sha256(NEW.bundle_bytes), 'hex') IS DISTINCT FROM NEW.bundle_sha256
       OR convert_from(NEW.configuration_bytes, 'UTF8')
            IS DISTINCT FROM regintel.candidate_canonical_json(configuration)
       OR convert_from(NEW.bundle_bytes, 'UTF8')
            IS DISTINCT FROM regintel.candidate_canonical_json(bundle)
       OR NEW.id IS DISTINCT FROM regintel.candidate_stable_id(
            'candidate-run:' || NEW.input_sha256 || ':' || NEW.configuration_sha256)
       OR NOT regintel.entity_json_keys(configuration, ARRAY['version', 'code_sha256',
            'max_window_chars', 'max_candidates', 'max_input_chars'])
       OR configuration ->> 'version' IS DISTINCT FROM '1.0.0'
       OR jsonb_typeof(configuration -> 'code_sha256') IS DISTINCT FROM 'string'
       OR configuration ->> 'code_sha256' !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(configuration -> 'max_window_chars') IS DISTINCT FROM 'number'
       OR configuration ->> 'max_window_chars' IS DISTINCT FROM '20000'
       OR jsonb_typeof(configuration -> 'max_candidates') IS DISTINCT FROM 'number'
       OR configuration ->> 'max_candidates' IS DISTINCT FROM '1000'
       OR jsonb_typeof(configuration -> 'max_input_chars') IS DISTINCT FROM 'number'
       OR configuration ->> 'max_input_chars' IS DISTINCT FROM '2000000'
       OR jsonb_typeof(input -> 'reviews') IS DISTINCT FROM 'array'
       OR jsonb_array_length(input -> 'reviews') > 25000
       OR jsonb_typeof(input -> 'evidence') IS DISTINCT FROM 'array'
       OR jsonb_array_length(input -> 'evidence') NOT BETWEEN 1 AND 10000
       OR jsonb_array_length(input -> 'evidence') <> jsonb_array_length(
            input -> 'entity_run' -> 'evidence_ids')
       OR jsonb_typeof(input -> 'metrics') IS DISTINCT FROM 'array'
       OR jsonb_array_length(input -> 'metrics') > 100
       OR NOT regintel.entity_json_keys(bundle,
            ARRAY['numeric_facts', 'narrative_facts', 'relations', 'issues'])
       OR jsonb_typeof(bundle -> 'numeric_facts') IS DISTINCT FROM 'array'
       OR jsonb_typeof(bundle -> 'narrative_facts') IS DISTINCT FROM 'array'
       OR jsonb_typeof(bundle -> 'relations') IS DISTINCT FROM 'array'
       OR jsonb_typeof(bundle -> 'issues') IS DISTINCT FROM 'array'
       OR jsonb_array_length(bundle -> 'issues') > 1000
       OR NEW.candidate_count <> jsonb_array_length(bundle -> 'numeric_facts')
            + jsonb_array_length(bundle -> 'narrative_facts')
            + jsonb_array_length(bundle -> 'relations') THEN
        RAISE EXCEPTION 'Candidate runs require sealed source inputs and a bounded frozen bundle'
            USING ERRCODE = '23514';
    END IF;
    SELECT coalesce(jsonb_agg(convert_from(review_bytes, 'UTF8')::JSONB ORDER BY mention_id, id), '[]'::JSONB)
        INTO current_reviews FROM regintel.entity_reviews WHERE run_id = NEW.entity_run_id;
    IF input -> 'reviews' IS DISTINCT FROM current_reviews THEN
        RAISE EXCEPTION 'Candidate input must freeze all current audited entity reviews'
            USING ERRCODE = '23514';
    END IF;
    IF (SELECT coalesce(sum(char_length(entry -> 'span' ->> 'quote')), 0)
        FROM jsonb_array_elements(input -> 'evidence') entry) > 2000000 THEN
        RAISE EXCEPTION 'Candidate input exceeds its explicit source-text limit'
            USING ERRCODE = '23514';
    END IF;
    IF (SELECT count(DISTINCT entry ->> 'id') FROM jsonb_array_elements(input -> 'evidence') entry)
            <> jsonb_array_length(input -> 'evidence')
       OR (SELECT count(DISTINCT entry ->> 'id') FROM jsonb_array_elements(input -> 'metrics') entry)
            <> jsonb_array_length(input -> 'metrics') THEN
        RAISE EXCEPTION 'Candidate input evidence and metrics must have distinct supplied IDs'
            USING ERRCODE = '23514';
    END IF;
    FOR item IN SELECT jsonb_array_elements(input -> 'evidence') LOOP
        IF NOT regintel.entity_json_keys(item,
                ARRAY['id', 'kind', 'source', 'page_geometry', 'boxes', 'span'])
           OR NOT regintel.candidate_uuid(item -> 'id')
           OR item ->> 'kind' IS DISTINCT FROM 'text'
           OR NOT (input -> 'entity_run' -> 'evidence_ids' ? (item ->> 'id'))
           OR NOT regintel.entity_json_keys(item -> 'source', ARRAY['filing_id',
                'filing_version_id', 'parse_version_id', 'page_id', 'page_index'])
           OR NOT regintel.entity_json_keys(item -> 'span', ARRAY['block_id', 'start', 'end', 'quote'])
           OR jsonb_typeof(item -> 'source' -> 'page_index') IS DISTINCT FROM 'number'
           OR jsonb_typeof(item -> 'span' -> 'start') IS DISTINCT FROM 'number'
           OR jsonb_typeof(item -> 'span' -> 'end') IS DISTINCT FROM 'number'
           OR jsonb_typeof(item -> 'span' -> 'quote') IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'Candidate input requires complete immutable exact text records'
                USING ERRCODE = '23514';
        END IF;
        SELECT e.*, p.page_index, v.filing_id INTO source FROM regintel.evidence e
            JOIN regintel.pages p ON p.id = e.page_id
            JOIN regintel.filing_versions v ON v.id = e.filing_version_id
            WHERE e.id = (item ->> 'id')::UUID AND e.parse_version_id = NEW.parse_version_id
                AND e.kind = 'text';
        IF NOT FOUND
           OR item -> 'source' ->> 'parse_version_id' IS DISTINCT FROM source.parse_version_id::TEXT
           OR item -> 'source' ->> 'filing_version_id' IS DISTINCT FROM source.filing_version_id::TEXT
           OR item -> 'source' ->> 'filing_id' IS DISTINCT FROM source.filing_id::TEXT
           OR item -> 'source' ->> 'page_id' IS DISTINCT FROM source.page_id::TEXT
           OR item -> 'source' ->> 'page_index' IS DISTINCT FROM source.page_index::TEXT
           OR item -> 'span' ->> 'block_id' IS DISTINCT FROM source.block_id::TEXT
           OR item -> 'span' ->> 'start' IS DISTINCT FROM source.start_offset::TEXT
           OR item -> 'span' ->> 'end' IS DISTINCT FROM source.end_offset::TEXT
           OR item -> 'span' ->> 'quote' IS DISTINCT FROM source.quote::TEXT THEN
            RAISE EXCEPTION 'Candidate source records must equal their sealed authoritative text'
                USING ERRCODE = '23514';
        END IF;
        SELECT jsonb_build_object('width', p.width, 'height', p.height,
            'media_box', jsonb_build_object('x0', p.media_x0, 'y0', p.media_y0,
                'x1', p.media_x1, 'y1', p.media_y1),
            'crop_box', jsonb_build_object('x0', p.crop_x0, 'y0', p.crop_y0,
                'x1', p.crop_x1, 'y1', p.crop_y1),
            'rotation', p.rotation, 'coordinate_space', p.coordinate_space, 'origin', p.origin)
            INTO geometry FROM regintel.pages p WHERE p.id = source.page_id;
        SELECT jsonb_agg(jsonb_build_object('x0', b.x0, 'y0', b.y0, 'x1', b.x1, 'y1', b.y1)
            ORDER BY box_index) INTO boxes FROM regintel.evidence_boxes b
            WHERE b.evidence_id = source.id;
        IF item -> 'page_geometry' IS DISTINCT FROM geometry OR item -> 'boxes' IS DISTINCT FROM boxes THEN
            RAISE EXCEPTION 'Candidate input geometry must equal its sealed exact source projection'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    FOR metric IN SELECT jsonb_array_elements(input -> 'metrics') LOOP
        IF NOT regintel.candidate_uuid(metric -> 'id') OR NOT EXISTS (
            SELECT 1 FROM regintel.metric_definitions m WHERE m.id = (metric ->> 'id')::UUID
                AND convert_from(m.definition_bytes, 'UTF8')::JSONB = metric) THEN
            RAISE EXCEPTION 'Candidate metrics must equal immutable registered definitions'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    FOREACH collection IN ARRAY ARRAY['numeric_facts', 'narrative_facts', 'relations'] LOOP
        kind := CASE collection WHEN 'relations' THEN 'relation'
            WHEN 'numeric_facts' THEN 'numeric_fact' ELSE 'narrative_fact' END;
        FOR item IN SELECT jsonb_array_elements(bundle -> collection) LOOP
            PERFORM regintel.validate_candidate_draft(item, input, kind);
        END LOOP;
    END LOOP;
    FOR item IN SELECT jsonb_array_elements(bundle -> 'issues') LOOP
        IF NOT regintel.entity_json_keys(item, ARRAY['code', 'evidence_ids', 'message'])
           OR jsonb_typeof(item -> 'code') IS DISTINCT FROM 'string'
           OR item ->> 'code' IS NULL
           OR item ->> 'code' NOT IN ('UNRESOLVED_ENTITY', 'MISSING_VALUE',
                'AMBIGUOUS_CONTEXT', 'NO_SUPPORTED_CANDIDATE')
           OR jsonb_typeof(item -> 'message') IS DISTINCT FROM 'string'
           OR char_length(item ->> 'message') NOT BETWEEN 1 AND 500
           OR jsonb_typeof(item -> 'evidence_ids') IS DISTINCT FROM 'array'
           OR jsonb_array_length(item -> 'evidence_ids') > 16
           OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(item -> 'evidence_ids') value)
                <> jsonb_array_length(item -> 'evidence_ids')
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(item -> 'evidence_ids') value
                WHERE NOT regintel.candidate_uuid(value)
                    OR NOT (input -> 'entity_run' -> 'evidence_ids' ? (value #>> '{}'))) THEN
            RAISE EXCEPTION 'Extraction issues require bounded supplied source references'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$;
CREATE TRIGGER candidate_run_gate BEFORE INSERT ON regintel.candidate_runs
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_candidate_run();

CREATE FUNCTION regintel.validate_candidate_run_item() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE owner RECORD; candidate RECORD; quantity RECORD; draft JSONB; input JSONB;
        bundle JSONB; role_name TEXT; expected TEXT; stored TEXT;
BEGIN
    SELECT creation_transaction, input_bytes, bundle_bytes INTO owner
        FROM regintel.candidate_runs WHERE id = NEW.run_id;
    input := convert_from(owner.input_bytes, 'UTF8')::JSONB;
    bundle := convert_from(owner.bundle_bytes, 'UTF8')::JSONB;
    draft := convert_from(NEW.draft_bytes, 'UTF8')::JSONB;
    SELECT *, xmin::TEXT::BIGINT AS row_transaction INTO candidate FROM regintel.candidates
        WHERE id = NEW.candidate_id AND parse_version_id = NEW.parse_version_id;
    IF NOT FOUND OR owner.creation_transaction IS DISTINCT FROM txid_current()
       OR convert_from(NEW.draft_bytes, 'UTF8')
            IS DISTINCT FROM regintel.candidate_canonical_json(draft)
       OR NEW.candidate_id IS DISTINCT FROM regintel.candidate_stable_id(
            'candidate:' || NEW.run_id::TEXT || ':' || encode(sha256(NEW.draft_bytes), 'hex'))
       OR candidate.row_transaction IS DISTINCT FROM (txid_current() % 4294967296)
       OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(
            (bundle -> 'numeric_facts') || (bundle -> 'narrative_facts') || (bundle -> 'relations')) item
                WHERE item = draft)
       OR candidate.kind IS DISTINCT FROM draft ->> 'kind'
       OR candidate.state IS DISTINCT FROM 'CANDIDATE'
       OR candidate.subject_entity_id::TEXT IS DISTINCT FROM draft ->> 'subject_entity_id'
       OR candidate.object_entity_id::TEXT IS DISTINCT FROM draft ->> 'object_entity_id'
       OR candidate.metric_id::TEXT IS DISTINCT FROM draft ->> 'metric_id'
       OR candidate.relation_type IS DISTINCT FROM draft ->> 'relation_type'
       OR candidate.raw_text::TEXT IS DISTINCT FROM draft ->> 'raw_text'
       OR candidate.evidence_count <> (SELECT count(DISTINCT span ->> 'evidence_id')
            FROM jsonb_array_elements(draft -> 'supports') span)
       OR EXISTS (SELECT 1 FROM regintel.candidate_evidence e
            WHERE e.candidate_id = NEW.candidate_id AND NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(draft -> 'supports') span
                    WHERE span ->> 'evidence_id' = e.evidence_id::TEXT)) THEN
        RAISE EXCEPTION 'Candidate items require atomic matching immutable run proposals'
            USING ERRCODE = '23514';
    END IF;
    IF draft -> 'raw_quantity' IS DISTINCT FROM 'null'::JSONB THEN
        SELECT *, xmin::TEXT::BIGINT AS row_transaction INTO quantity
            FROM regintel.quantitative_contexts WHERE id = candidate.quantitative_context_id
                AND parse_version_id = NEW.parse_version_id;
        IF NOT FOUND OR quantity.row_transaction IS DISTINCT FROM (txid_current() % 4294967296)
           OR quantity.id IS DISTINCT FROM regintel.candidate_stable_id(
                'candidate-quantity:' || NEW.candidate_id::TEXT)
           OR quantity.raw_value::TEXT IS DISTINCT FROM draft -> 'raw_quantity' -> 'value' ->> 'quote'
           OR quantity.normalized_value IS NOT NULL OR quantity.normalized_unit IS NOT NULL
           OR quantity.currency IS NOT NULL OR quantity.period_kind <> 'UNKNOWN'
           OR quantity.start_date IS NOT NULL OR quantity.end_date IS NOT NULL
           OR quantity.instant_date IS NOT NULL OR quantity.basis <> 'UNKNOWN'
           OR quantity.ownership_date IS NOT NULL
           OR quantity.evidence_count <> candidate.evidence_count
           OR EXISTS (SELECT 1 FROM regintel.quantitative_context_evidence e
                WHERE e.context_id = quantity.id AND NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(draft -> 'supports') span
                        WHERE span ->> 'evidence_id' = e.evidence_id::TEXT)) THEN
            RAISE EXCEPTION 'Candidate raw quantities cannot carry interpreted financial context'
                USING ERRCODE = '23514';
        END IF;
        FOREACH role_name IN ARRAY ARRAY['unit', 'currency', 'period', 'basis', 'denominator', 'stake_kind'] LOOP
            expected := draft -> 'raw_quantity' -> role_name ->> 'quote';
            stored := CASE role_name WHEN 'unit' THEN quantity.raw_unit
                WHEN 'currency' THEN quantity.raw_currency WHEN 'period' THEN quantity.raw_period_label
                WHEN 'basis' THEN quantity.raw_basis_label WHEN 'denominator' THEN quantity.denominator
                ELSE quantity.stake_kind END;
            IF expected IS DISTINCT FROM stored THEN
                RAISE EXCEPTION 'Candidate context rows must retain exact raw role values'
                    USING ERRCODE = '23514';
            END IF;
        END LOOP;
    ELSIF candidate.quantitative_context_id IS NOT NULL THEN
        RAISE EXCEPTION 'A candidate without raw quantity cannot gain quantitative context'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER candidate_run_item_gate BEFORE INSERT ON regintel.candidate_run_items
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_candidate_run_item();
CREATE FUNCTION regintel.complete_candidate_run() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE bundle JSONB;
BEGIN
    bundle := convert_from(NEW.bundle_bytes, 'UTF8')::JSONB;
    IF (SELECT count(*) FROM regintel.candidate_run_items WHERE run_id = NEW.id)
            <> NEW.candidate_count
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(
            (bundle -> 'numeric_facts') || (bundle -> 'narrative_facts') || (bundle -> 'relations')) draft
                WHERE NOT EXISTS (SELECT 1 FROM regintel.candidate_run_items item
                    WHERE item.run_id = NEW.id AND convert_from(item.draft_bytes, 'UTF8')::JSONB = draft))
       OR (SELECT count(DISTINCT draft) FROM jsonb_array_elements(
            (bundle -> 'numeric_facts') || (bundle -> 'narrative_facts') || (bundle -> 'relations')) draft)
            <> NEW.candidate_count THEN
        RAISE EXCEPTION 'Candidate run items must exactly complete the frozen bundle atomically'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER candidate_run_completeness AFTER INSERT ON regintel.candidate_runs
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION regintel.complete_candidate_run();
DO $$
DECLARE target TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY['metric_definitions', 'candidate_runs', 'candidate_run_items'] LOOP
        EXECUTE format('CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.%I '
            'FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation()', target);
        EXECUTE format('CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.%I '
            'FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation()', target);
    END LOOP;
END;
$$;

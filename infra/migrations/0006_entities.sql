-- M1.5 registry and mention resolution only. Financial authority remains closed.
CREATE FUNCTION regintel.entity_json_keys(payload JSONB, required_keys TEXT[]) RETURNS BOOLEAN
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
BEGIN
    IF jsonb_typeof(payload) IS DISTINCT FROM 'object' THEN RETURN FALSE; END IF;
    RETURN payload ?& required_keys AND NOT EXISTS (
        SELECT 1 FROM jsonb_object_keys(payload) AS fields(name)
            WHERE NOT (fields.name = ANY(required_keys))
    );
END;
$$;
CREATE FUNCTION regintel.valid_entity_identifier(kind TEXT, value TEXT) RETURNS BOOLEAN
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE expanded TEXT := ''; item TEXT; position_at INTEGER; number INTEGER; total INTEGER := 0;
BEGIN
    IF kind = 'CIN' THEN
        RETURN value ~ '^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$';
    END IF;
    IF kind <> 'ISIN' OR value !~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$' THEN
        RETURN FALSE;
    END IF;
    FOR position_at IN 1..char_length(value) LOOP
        item := substr(value, position_at, 1);
        expanded := expanded || CASE WHEN item ~ '^[A-Z]$'
            THEN (ascii(item) - 55)::TEXT ELSE item END;
    END LOOP;
    FOR position_at IN 1..char_length(expanded) LOOP
        number := substr(expanded, char_length(expanded) - position_at + 1, 1)::INTEGER;
        IF position_at % 2 = 0 THEN number := number * 2; END IF;
        total := total + number / 10 + number % 10;
    END LOOP;
    RETURN total % 10 = 0;
END;
$$;
CREATE TABLE regintel.entity_registrations (
    id regintel.canonical_id PRIMARY KEY,
    registration_bytes BYTEA NOT NULL
        CHECK (octet_length(registration_bytes) BETWEEN 1 AND 8388608),
    registration_sha256 regintel.sha256_hash NOT NULL,
    registered_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE regintel.entity_identifiers (
    entity_id regintel.canonical_id NOT NULL REFERENCES regintel.entity_registrations(id),
    kind TEXT NOT NULL CHECK (kind IN ('CIN', 'ISIN')),
    value TEXT COLLATE "C" NOT NULL,
    PRIMARY KEY (kind, value),
    UNIQUE (entity_id, kind, value),
    CHECK (regintel.valid_entity_identifier(kind, value))
);
CREATE TABLE regintel.entity_runs (
    id regintel.canonical_id PRIMARY KEY,
    parse_version_id regintel.canonical_id NOT NULL REFERENCES regintel.parse_versions(id),
    artifact_sha256 regintel.sha256_hash NOT NULL,
    registry_revision regintel.safe_index NOT NULL,
    registry_sha256 regintel.sha256_hash NOT NULL,
    configuration_sha256 regintel.sha256_hash NOT NULL,
    configuration_bytes BYTEA NOT NULL
        CHECK (octet_length(configuration_bytes) BETWEEN 1 AND 65536),
    registry_bytes BYTEA NOT NULL CHECK (octet_length(registry_bytes) BETWEEN 1 AND 67108864),
    run_bytes BYTEA NOT NULL CHECK (octet_length(run_bytes) BETWEEN 1 AND 67108864),
    run_sha256 regintel.sha256_hash NOT NULL,
    mention_count regintel.safe_index NOT NULL CHECK (mention_count <= 25000),
    submitted_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    creation_transaction BIGINT NOT NULL DEFAULT txid_current(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (parse_version_id, registry_revision, registry_sha256, configuration_sha256),
    UNIQUE (id, parse_version_id)
);
CREATE TABLE regintel.entity_mentions (
    id regintel.canonical_id PRIMARY KEY,
    run_id regintel.canonical_id NOT NULL,
    parse_version_id regintel.canonical_id NOT NULL,
    evidence_id regintel.canonical_id NOT NULL,
    start_offset regintel.safe_index NOT NULL,
    end_offset regintel.safe_index NOT NULL,
    quote regintel.stored_text NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('NAME', 'CIN', 'ISIN')),
    mention_bytes BYTEA NOT NULL CHECK (octet_length(mention_bytes) BETWEEN 1 AND 1048576),
    FOREIGN KEY (run_id, parse_version_id) REFERENCES regintel.entity_runs(id, parse_version_id),
    FOREIGN KEY (evidence_id, parse_version_id) REFERENCES regintel.evidence(id, parse_version_id),
    UNIQUE (run_id, id),
    UNIQUE (run_id, evidence_id, start_offset, end_offset, kind),
    CHECK (end_offset > start_offset AND end_offset - start_offset = char_length(quote))
);
CREATE TABLE regintel.entity_reviews (
    id regintel.canonical_id PRIMARY KEY,
    run_id regintel.canonical_id NOT NULL REFERENCES regintel.entity_runs(id),
    mention_id regintel.canonical_id NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('RESOLVE', 'REJECT')),
    entity_id regintel.canonical_id REFERENCES regintel.entity_registrations(id),
    review_bytes BYTEA NOT NULL CHECK (octet_length(review_bytes) BETWEEN 1 AND 1048576),
    review_sha256 regintel.sha256_hash NOT NULL,
    reviewed_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (run_id, mention_id) REFERENCES regintel.entity_mentions(run_id, id),
    UNIQUE (run_id, mention_id),
    CHECK ((decision = 'RESOLVE') = (entity_id IS NOT NULL))
);

CREATE FUNCTION regintel.entity_admin(actor UUID, expected_version INTEGER) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE account RECORD;
BEGIN
    SELECT role, is_active, auth_version INTO account FROM regintel.users
        WHERE id = actor FOR SHARE;
    IF NOT FOUND OR account.role <> 'admin' OR NOT account.is_active
       OR account.auth_version IS DISTINCT FROM expected_version THEN
        RAISE EXCEPTION 'Entity writes require a current active administrator'
            USING ERRCODE = '23514';
    END IF;
END;
$$;
CREATE FUNCTION regintel.entity_anchor(anchor JSONB, expected_parse UUID DEFAULT NULL)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE source RECORD; start_at BIGINT; end_at BIGINT;
BEGIN
    IF NOT regintel.entity_json_keys(anchor, ARRAY['evidence_id', 'start', 'end', 'quote'])
       OR jsonb_typeof(anchor) IS DISTINCT FROM 'object'
       OR jsonb_typeof(anchor -> 'evidence_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(anchor -> 'start') IS DISTINCT FROM 'number'
       OR jsonb_typeof(anchor -> 'end') IS DISTINCT FROM 'number'
       OR jsonb_typeof(anchor -> 'quote') IS DISTINCT FROM 'string'
       OR anchor ->> 'evidence_id' !~
            '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
       OR char_length(anchor ->> 'quote') NOT BETWEEN 1 AND 256
       OR anchor ->> 'start' !~ '^[0-9]{1,16}$'
       OR anchor ->> 'end' !~ '^[0-9]{1,16}$' THEN
        RAISE EXCEPTION 'Entity support requires an exact Unicode source span'
            USING ERRCODE = '23514';
    END IF;
    start_at := (anchor ->> 'start')::BIGINT;
    end_at := (anchor ->> 'end')::BIGINT;
    SELECT e.* INTO source FROM regintel.evidence e
        JOIN regintel.parse_artifacts a ON a.parse_version_id = e.parse_version_id
        JOIN regintel.filing_jobs j ON j.id = a.job_id AND j.state = 'PARSED'
            AND j.parse_version_id = e.parse_version_id
        WHERE e.id = (anchor ->> 'evidence_id')::UUID AND e.kind = 'text';
    IF NOT FOUND OR (expected_parse IS NOT NULL AND source.parse_version_id <> expected_parse)
       OR start_at < source.start_offset OR end_at > source.end_offset OR end_at <= start_at
       OR end_at > 9007199254740991
       OR substr(source.quote, (start_at - source.start_offset + 1)::INTEGER,
            (end_at - start_at)::INTEGER) IS DISTINCT FROM anchor ->> 'quote' THEN
        RAISE EXCEPTION 'Entity span must match sealed exact text evidence'
            USING ERRCODE = '23514';
    END IF;
END;
$$;
CREATE FUNCTION regintel.validate_entity_registration() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE payload JSONB; item JSONB;
BEGIN
    PERFORM pg_advisory_xact_lock(5928237198818004551);
    PERFORM regintel.entity_admin(NEW.registered_by, NEW.auth_version);
    payload := convert_from(NEW.registration_bytes, 'UTF8')::JSONB;
    IF NOT regintel.entity_json_keys(payload, ARRAY['id', 'kind', 'legal_name',
            'legal_name_support', 'aliases', 'identifiers', 'review_note'])
       OR encode(sha256(NEW.registration_bytes), 'hex') IS DISTINCT FROM NEW.registration_sha256
       OR payload ->> 'id' IS DISTINCT FROM NEW.id::TEXT
       OR payload ->> 'kind' IS NULL
       OR jsonb_typeof(payload -> 'kind') IS DISTINCT FROM 'string'
       OR payload ->> 'kind' NOT IN ('COMPANY', 'PERSON', 'ORGANIZATION')
       OR jsonb_typeof(payload -> 'legal_name') IS DISTINCT FROM 'string'
       OR char_length(payload ->> 'legal_name') NOT BETWEEN 1 AND 256
       OR payload ->> 'legal_name' !~ '[[:alnum:]]'
       OR jsonb_typeof(payload -> 'aliases') IS DISTINCT FROM 'array'
       OR jsonb_typeof(payload -> 'identifiers') IS DISTINCT FROM 'array'
       OR jsonb_array_length(payload -> 'aliases') > 100
       OR jsonb_array_length(payload -> 'identifiers') > 100
       OR jsonb_typeof(payload -> 'review_note') IS DISTINCT FROM 'string'
       OR char_length(payload ->> 'review_note') NOT BETWEEN 1 AND 2000
       OR payload ->> 'legal_name' IS DISTINCT FROM payload -> 'legal_name_support' ->> 'quote' THEN
        RAISE EXCEPTION 'Entity registration requires bounded audited source support'
            USING ERRCODE = '23514';
    END IF;
    PERFORM regintel.entity_anchor(payload -> 'legal_name_support');
    FOR item IN SELECT jsonb_array_elements(payload -> 'aliases') LOOP
        IF NOT regintel.entity_json_keys(item, ARRAY['name', 'support'])
           OR jsonb_typeof(item -> 'name') IS DISTINCT FROM 'string'
           OR char_length(item ->> 'name') NOT BETWEEN 1 AND 256
           OR item ->> 'name' !~ '[[:alnum:]]'
           OR item ->> 'name' IS DISTINCT FROM item -> 'support' ->> 'quote' THEN
            RAISE EXCEPTION 'An approved alias requires exact source support'
                USING ERRCODE = '23514';
        END IF;
        PERFORM regintel.entity_anchor(item -> 'support');
    END LOOP;
    IF (SELECT count(DISTINCT names.name) FROM (
        SELECT payload ->> 'legal_name' AS name
        UNION ALL SELECT alias ->> 'name' FROM jsonb_array_elements(payload -> 'aliases') alias
    ) names) <> 1 + jsonb_array_length(payload -> 'aliases') THEN
        RAISE EXCEPTION 'Approved names must be distinct within an entity'
            USING ERRCODE = '23514';
    END IF;
    FOR item IN SELECT jsonb_array_elements(payload -> 'identifiers') LOOP
        IF NOT regintel.entity_json_keys(item, ARRAY['kind', 'value', 'support'])
           OR item ->> 'kind' IS NULL
           OR jsonb_typeof(item -> 'kind') IS DISTINCT FROM 'string'
           OR item ->> 'kind' NOT IN ('CIN', 'ISIN')
           OR jsonb_typeof(item -> 'value') IS DISTINCT FROM 'string'
           OR NOT regintel.valid_entity_identifier(item ->> 'kind', item ->> 'value')
           OR (item ->> 'kind' = 'CIN' AND payload ->> 'kind' <> 'COMPANY')
           OR item -> 'support' ->> 'quote' IS DISTINCT FROM item ->> 'value' THEN
            RAISE EXCEPTION 'An approved identifier requires exact source support'
                USING ERRCODE = '23514';
        END IF;
        PERFORM regintel.entity_anchor(item -> 'support');
    END LOOP;
    RETURN NEW;
END;
$$;
CREATE TRIGGER entity_registration_gate BEFORE INSERT ON regintel.entity_registrations
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_entity_registration();
CREATE FUNCTION regintel.validate_entity_identifiers() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE payload JSONB;
BEGIN
    SELECT convert_from(registration_bytes, 'UTF8')::JSONB INTO payload
        FROM regintel.entity_registrations WHERE id = NEW.entity_id;
    IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(payload -> 'identifiers') item
        WHERE item ->> 'kind' = NEW.kind AND item ->> 'value' = NEW.value) THEN
        RAISE EXCEPTION 'Identifier must be part of the immutable approved registration'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER entity_identifier_gate BEFORE INSERT ON regintel.entity_identifiers
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_entity_identifiers();
CREATE FUNCTION regintel.complete_entity_identifiers() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE payload JSONB;
BEGIN
    payload := convert_from(NEW.registration_bytes, 'UTF8')::JSONB;
    IF (SELECT count(*) FROM regintel.entity_identifiers WHERE entity_id = NEW.id)
       <> jsonb_array_length(payload -> 'identifiers') THEN
        RAISE EXCEPTION 'All approved identifiers must be uniquely registered atomically'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER entity_identifier_completeness AFTER INSERT
    ON regintel.entity_registrations DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION regintel.complete_entity_identifiers();

CREATE FUNCTION regintel.validate_entity_run() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE payload JSONB; registry JSONB; current_registry JSONB; evidence_id TEXT; parse RECORD;
BEGIN
    PERFORM pg_advisory_xact_lock(5928237198818004551);
    PERFORM regintel.entity_admin(NEW.submitted_by, NEW.auth_version);
    NEW.creation_transaction := txid_current();
    payload := convert_from(NEW.run_bytes, 'UTF8')::JSONB;
    registry := convert_from(NEW.registry_bytes, 'UTF8')::JSONB;
    SELECT jsonb_build_object('entities', coalesce(jsonb_agg(
        convert_from(registration_bytes, 'UTF8')::JSONB ORDER BY id), '[]'::JSONB))
        INTO current_registry FROM regintel.entity_registrations;
    SELECT p.artifact_sha256 INTO parse FROM regintel.parse_versions p
        JOIN regintel.parse_artifacts a ON a.parse_version_id = p.id
        JOIN regintel.filing_jobs j ON j.id = a.job_id AND j.state = 'PARSED'
            AND j.parse_version_id = p.id WHERE p.id = NEW.parse_version_id;
    IF NOT FOUND
       OR NOT regintel.entity_json_keys(payload, ARRAY['id', 'parse_version_id',
            'artifact_sha256', 'registry_revision', 'registry_sha256', 'configuration',
            'evidence_ids', 'mentions'])
       OR NOT regintel.entity_json_keys(payload -> 'configuration', ARRAY['version',
            'spacy_version', 'rapidfuzz_version', 'code_sha256', 'fuzzy_threshold', 'max_proposals'])
       OR parse.artifact_sha256 IS DISTINCT FROM NEW.artifact_sha256
       OR encode(sha256(NEW.run_bytes), 'hex') IS DISTINCT FROM NEW.run_sha256
       OR encode(sha256(NEW.registry_bytes), 'hex') IS DISTINCT FROM NEW.registry_sha256
       OR encode(sha256(NEW.configuration_bytes), 'hex')
            IS DISTINCT FROM NEW.configuration_sha256
       OR convert_from(NEW.configuration_bytes, 'UTF8')::JSONB
            IS DISTINCT FROM payload -> 'configuration'
       OR registry IS DISTINCT FROM current_registry
       OR NEW.registry_revision <> (SELECT count(*) FROM regintel.entity_registrations)
       OR payload ->> 'id' IS DISTINCT FROM NEW.id::TEXT
       OR payload ->> 'parse_version_id' IS DISTINCT FROM NEW.parse_version_id::TEXT
       OR payload ->> 'artifact_sha256' IS DISTINCT FROM NEW.artifact_sha256::TEXT
       OR payload ->> 'registry_revision' IS DISTINCT FROM NEW.registry_revision::TEXT
       OR payload ->> 'registry_sha256' IS DISTINCT FROM NEW.registry_sha256::TEXT
       OR jsonb_typeof(payload -> 'configuration') IS DISTINCT FROM 'object'
       OR payload -> 'configuration' ->> 'version' IS DISTINCT FROM '1.0.0'
       OR jsonb_typeof(payload -> 'configuration' -> 'spacy_version') IS DISTINCT FROM 'string'
       OR char_length(payload -> 'configuration' ->> 'spacy_version') NOT BETWEEN 1 AND 256
       OR jsonb_typeof(payload -> 'configuration' -> 'rapidfuzz_version') IS DISTINCT FROM 'string'
       OR char_length(payload -> 'configuration' ->> 'rapidfuzz_version') NOT BETWEEN 1 AND 256
       OR jsonb_typeof(payload -> 'configuration' -> 'code_sha256') IS DISTINCT FROM 'string'
       OR payload -> 'configuration' ->> 'code_sha256' !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(payload -> 'configuration' -> 'fuzzy_threshold') IS DISTINCT FROM 'number'
       OR (payload -> 'configuration' ->> 'fuzzy_threshold')::NUMERIC NOT BETWEEN 0 AND 100
       OR jsonb_typeof(payload -> 'configuration' -> 'max_proposals') IS DISTINCT FROM 'number'
       OR payload -> 'configuration' ->> 'max_proposals' !~ '^[0-9]{1,3}$'
       OR (payload -> 'configuration' ->> 'max_proposals')::INTEGER NOT BETWEEN 1 AND 100
       OR jsonb_typeof(payload -> 'evidence_ids') IS DISTINCT FROM 'array'
       OR jsonb_typeof(payload -> 'mentions') IS DISTINCT FROM 'array'
       OR jsonb_array_length(payload -> 'evidence_ids') NOT BETWEEN 1 AND 10000
       OR jsonb_array_length(payload -> 'evidence_ids') <> (SELECT count(*)
            FROM regintel.evidence WHERE parse_version_id = NEW.parse_version_id AND kind = 'text')
       OR jsonb_array_length(payload -> 'mentions') <> NEW.mention_count THEN
        RAISE EXCEPTION 'Entity run must bind the sealed parse and current registry'
            USING ERRCODE = '23514';
    END IF;
    IF (SELECT count(DISTINCT item) FROM jsonb_array_elements_text(payload -> 'evidence_ids') item)
       <> jsonb_array_length(payload -> 'evidence_ids') THEN
        RAISE EXCEPTION 'Entity run evidence IDs must be unique' USING ERRCODE = '23514';
    END IF;
    FOR evidence_id IN SELECT jsonb_array_elements_text(payload -> 'evidence_ids') LOOP
        IF NOT EXISTS (SELECT 1 FROM regintel.evidence e WHERE e.id = evidence_id::UUID
            AND e.parse_version_id = NEW.parse_version_id AND e.kind = 'text') THEN
            RAISE EXCEPTION 'Entity run evidence must belong to its exact parse'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$;
CREATE TRIGGER entity_run_gate BEFORE INSERT ON regintel.entity_runs
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_entity_run();
CREATE FUNCTION regintel.validate_entity_mention() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE owner RECORD; payload JSONB; resolution JSONB; proposal JSONB; known JSONB;
BEGIN
    SELECT creation_transaction, run_bytes, registry_bytes INTO owner
        FROM regintel.entity_runs WHERE id = NEW.run_id;
    payload := convert_from(NEW.mention_bytes, 'UTF8')::JSONB;
    resolution := payload -> 'resolution';
    IF NOT FOUND OR owner.creation_transaction <> txid_current()
       OR NOT regintel.entity_json_keys(payload, ARRAY['id', 'kind', 'support', 'resolution'])
       OR NOT regintel.entity_json_keys(resolution,
            ARRAY['state', 'entity_id', 'method', 'reason', 'proposals'])
       OR payload ->> 'id' IS DISTINCT FROM NEW.id::TEXT
       OR payload ->> 'kind' IS DISTINCT FROM NEW.kind
       OR payload -> 'support' ->> 'evidence_id' IS DISTINCT FROM NEW.evidence_id::TEXT
       OR payload -> 'support' ->> 'start' IS DISTINCT FROM NEW.start_offset::TEXT
       OR payload -> 'support' ->> 'end' IS DISTINCT FROM NEW.end_offset::TEXT
       OR payload -> 'support' ->> 'quote' IS DISTINCT FROM NEW.quote::TEXT
       OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(
            convert_from(owner.run_bytes, 'UTF8')::JSONB -> 'mentions') item WHERE item = payload)
       OR NOT (convert_from(owner.run_bytes, 'UTF8')::JSONB -> 'evidence_ids'
            ? NEW.evidence_id::TEXT)
       OR jsonb_typeof(resolution) IS DISTINCT FROM 'object'
       OR jsonb_typeof(resolution -> 'state') IS DISTINCT FROM 'string'
       OR jsonb_typeof(resolution -> 'reason') IS DISTINCT FROM 'string'
       OR char_length(resolution ->> 'reason') NOT BETWEEN 1 AND 256
       OR resolution ->> 'state' IS NULL
       OR resolution ->> 'state' NOT IN ('RESOLVED', 'REVIEW', 'UNRESOLVED')
       OR jsonb_typeof(resolution -> 'proposals') IS DISTINCT FROM 'array'
       OR jsonb_array_length(resolution -> 'proposals') > 100
       OR jsonb_typeof(resolution -> 'entity_id') NOT IN ('string', 'null')
       OR jsonb_typeof(resolution -> 'method') NOT IN ('string', 'null')
       OR (resolution ->> 'state' = 'RESOLVED')
            IS DISTINCT FROM (resolution ->> 'entity_id' IS NOT NULL)
       OR (resolution ->> 'state' <> 'RESOLVED' AND resolution ->> 'method' IS NOT NULL)
       OR (resolution ->> 'state' = 'UNRESOLVED'
            AND jsonb_array_length(resolution -> 'proposals') <> 0) THEN
        RAISE EXCEPTION 'Entity mention must be an immutable run member'
            USING ERRCODE = '23514';
    END IF;
    PERFORM regintel.entity_anchor(payload -> 'support', NEW.parse_version_id);
    known := convert_from(owner.registry_bytes, 'UTF8')::JSONB -> 'entities';
    FOR proposal IN SELECT jsonb_array_elements(resolution -> 'proposals') LOOP
        IF NOT regintel.entity_json_keys(proposal, ARRAY['entity_id', 'method', 'score'])
           OR jsonb_typeof(proposal) IS DISTINCT FROM 'object'
           OR jsonb_typeof(proposal -> 'entity_id') IS DISTINCT FROM 'string'
           OR jsonb_typeof(proposal -> 'method') IS DISTINCT FROM 'string'
           OR proposal ->> 'method' IS NULL
           OR proposal ->> 'method' NOT IN ('EXACT_CIN', 'EXACT_ISIN', 'EXACT_ALIAS',
                'NORMALIZED_NAME', 'FUZZY')
           OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(known) item
            WHERE item ->> 'id' = proposal ->> 'entity_id') THEN
            RAISE EXCEPTION 'Resolution proposals require supplied registry entity IDs'
                USING ERRCODE = '23514';
        END IF;
        IF proposal ->> 'method' = 'FUZZY' THEN
            IF jsonb_typeof(proposal -> 'score') IS DISTINCT FROM 'number'
               OR (proposal ->> 'score')::NUMERIC NOT BETWEEN 0 AND 100 THEN
                RAISE EXCEPTION 'Fuzzy proposals require a bounded similarity score'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF proposal ->> 'score' IS NOT NULL THEN
            RAISE EXCEPTION 'Exact proposals do not carry similarity scores'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF (SELECT count(DISTINCT item ->> 'entity_id')
        FROM jsonb_array_elements(resolution -> 'proposals') item)
        <> jsonb_array_length(resolution -> 'proposals') THEN
        RAISE EXCEPTION 'Resolution proposals must identify distinct registry entities'
            USING ERRCODE = '23514';
    END IF;
    IF resolution ->> 'state' = 'RESOLVED' AND
       (resolution ->> 'method' IS NULL OR resolution ->> 'method' = 'FUZZY'
        OR jsonb_array_length(resolution -> 'proposals') <> 1 OR NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(resolution -> 'proposals') item
            WHERE item ->> 'entity_id' = resolution ->> 'entity_id'
                AND item ->> 'method' = resolution ->> 'method')) THEN
        RAISE EXCEPTION 'Fuzzy proposals cannot independently resolve an entity'
            USING ERRCODE = '23514';
    END IF;
    IF resolution ->> 'state' = 'RESOLVED' THEN
        IF resolution ->> 'method' IN ('EXACT_CIN', 'EXACT_ISIN') AND
           (NEW.kind IS DISTINCT FROM substr(resolution ->> 'method', 7)
            OR NOT EXISTS (SELECT 1 FROM regintel.entity_identifiers
                WHERE entity_id = (resolution ->> 'entity_id')::UUID
                    AND kind = NEW.kind AND value = NEW.quote)) THEN
            RAISE EXCEPTION 'Exact identifier resolution requires the registered source value'
                USING ERRCODE = '23514';
        END IF;
        IF resolution ->> 'method' = 'EXACT_ALIAS' AND NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(known) item
            WHERE item ->> 'id' = resolution ->> 'entity_id'
                AND (item ->> 'legal_name' = NEW.quote OR EXISTS (
                    SELECT 1 FROM jsonb_array_elements(item -> 'aliases') alias
                        WHERE alias ->> 'name' = NEW.quote))) THEN
            RAISE EXCEPTION 'Exact name resolution requires an approved registry name'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER entity_mention_gate BEFORE INSERT ON regintel.entity_mentions
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_entity_mention();
CREATE FUNCTION regintel.complete_entity_run() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT count(*) FROM regintel.entity_mentions WHERE run_id = NEW.id) <> NEW.mention_count THEN
        RAISE EXCEPTION 'Entity run mentions must be persisted atomically'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER entity_run_completeness AFTER INSERT ON regintel.entity_runs
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION regintel.complete_entity_run();
CREATE FUNCTION regintel.validate_entity_review() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE payload JSONB; owner RECORD; support_id TEXT;
BEGIN
    PERFORM regintel.entity_admin(NEW.reviewed_by, NEW.auth_version);
    payload := convert_from(NEW.review_bytes, 'UTF8')::JSONB;
    SELECT r.parse_version_id, r.registry_bytes, m.mention_bytes INTO owner
        FROM regintel.entity_runs r JOIN regintel.entity_mentions m ON m.run_id = r.id
        WHERE r.id = NEW.run_id AND m.id = NEW.mention_id;
    IF NOT FOUND
       OR NOT regintel.entity_json_keys(payload, ARRAY['id', 'run_id', 'mention_id', 'decision',
            'entity_id', 'support_evidence_ids', 'review_note'])
       OR encode(sha256(NEW.review_bytes), 'hex') IS DISTINCT FROM NEW.review_sha256
       OR jsonb_typeof(payload -> 'entity_id') NOT IN ('string', 'null')
       OR payload ->> 'id' IS DISTINCT FROM NEW.id::TEXT
       OR payload ->> 'run_id' IS DISTINCT FROM NEW.run_id::TEXT
       OR payload ->> 'mention_id' IS DISTINCT FROM NEW.mention_id::TEXT
       OR payload ->> 'decision' IS DISTINCT FROM NEW.decision
       OR payload ->> 'entity_id' IS DISTINCT FROM NEW.entity_id::TEXT
       OR jsonb_typeof(payload -> 'support_evidence_ids') IS DISTINCT FROM 'array'
       OR jsonb_array_length(payload -> 'support_evidence_ids') NOT BETWEEN 1 AND 16
       OR jsonb_typeof(payload -> 'review_note') IS DISTINCT FROM 'string'
       OR char_length(payload ->> 'review_note') NOT BETWEEN 1 AND 2000 THEN
        RAISE EXCEPTION 'Entity review requires a bounded immutable audit'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.decision = 'RESOLVE' AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(
            convert_from(owner.mention_bytes, 'UTF8')::JSONB -> 'resolution' -> 'proposals') item
            WHERE item ->> 'entity_id' = NEW.entity_id::TEXT) THEN
        RAISE EXCEPTION 'Reviewed entity must be an existing run proposal'
            USING ERRCODE = '23514';
    END IF;
    IF (SELECT count(DISTINCT item) FROM jsonb_array_elements_text(
        payload -> 'support_evidence_ids') item)
        <> jsonb_array_length(payload -> 'support_evidence_ids') THEN
        RAISE EXCEPTION 'Review evidence IDs must be unique' USING ERRCODE = '23514';
    END IF;
    FOR support_id IN SELECT jsonb_array_elements_text(payload -> 'support_evidence_ids') LOOP
        IF NOT EXISTS (SELECT 1 FROM regintel.evidence WHERE id = support_id::UUID
            AND parse_version_id = owner.parse_version_id AND kind = 'text') THEN
            RAISE EXCEPTION 'Review support must belong to the mention source parse'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$;
CREATE TRIGGER entity_review_gate BEFORE INSERT ON regintel.entity_reviews
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_entity_review();
DO $$
DECLARE target TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY['entity_registrations', 'entity_identifiers',
        'entity_runs', 'entity_mentions', 'entity_reviews'] LOOP
        EXECUTE format('CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.%I '
            'FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation()', target);
        EXECUTE format('CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.%I '
            'FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation()', target);
    END LOOP;
END;
$$;

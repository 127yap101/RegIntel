-- M3 independently reviewed and published learning content. No filing-fact writes.
CREATE TABLE regintel.learning_definitions (
    id regintel.canonical_id PRIMARY KEY,
    payload BYTEA NOT NULL CHECK (octet_length(payload) BETWEEN 1 AND 65536),
    payload_sha256 regintel.sha256_hash NOT NULL,
    submitted_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version BIGINT NOT NULL CHECK (auth_version>0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE regintel.learning_reviews (
    id regintel.canonical_id PRIMARY KEY,
    definition_id regintel.canonical_id NOT NULL UNIQUE REFERENCES regintel.learning_definitions(id),
    review_bytes BYTEA NOT NULL CHECK (octet_length(review_bytes) BETWEEN 1 AND 8192),
    review_sha256 regintel.sha256_hash NOT NULL,
    reviewer_id UUID NOT NULL REFERENCES regintel.users(id),
    auth_version BIGINT NOT NULL CHECK (auth_version>0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE regintel.learning_versions (
    id regintel.canonical_id PRIMARY KEY,
    manifest BYTEA NOT NULL CHECK (octet_length(manifest) BETWEEN 1 AND 2097152),
    manifest_sha256 regintel.sha256_hash NOT NULL,
    published_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version BIGINT NOT NULL CHECK (auth_version>0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    creation_transaction BIGINT NOT NULL DEFAULT txid_current()
);
CREATE TABLE regintel.learning_head (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton),
    version_id regintel.canonical_id NOT NULL REFERENCES regintel.learning_versions(id)
);

CREATE FUNCTION regintel.guard_learning_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor UUID; data JSONB; item JSONB; d RECORD; r RECORD;
BEGIN
    IF TG_TABLE_NAME='learning_definitions' THEN
        actor:=NEW.submitted_by;
        data:=convert_from(NEW.payload,'UTF8')::jsonb;
        IF encode(sha256(NEW.payload),'hex') IS DISTINCT FROM NEW.payload_sha256
           OR data->>'id' IS DISTINCT FROM NEW.id::text
           OR data->>'submitted_by' IS DISTINCT FROM actor::text
           OR jsonb_typeof(data#>'{draft,sources}') IS DISTINCT FROM 'array'
           OR jsonb_array_length(data#>'{draft,sources}') NOT BETWEEN 1 AND 5 THEN
            RAISE EXCEPTION 'Learning draft must retain its actual submitted source content';
        END IF;
    ELSIF TG_TABLE_NAME='learning_reviews' THEN
        actor:=NEW.reviewer_id;
        data:=convert_from(NEW.review_bytes,'UTF8')::jsonb;
        IF encode(sha256(NEW.review_bytes),'hex') IS DISTINCT FROM NEW.review_sha256
           OR data->>'decision' NOT IN ('APPROVE','REJECT')
           OR jsonb_typeof(data->'decision') IS DISTINCT FROM 'string'
           OR jsonb_typeof(data->'note') IS DISTINCT FROM 'string'
           OR length(btrim(data->>'note')) NOT BETWEEN 1 AND 1000 THEN
            RAISE EXCEPTION 'Learning review requires an explicit immutable decision';
        END IF;
    ELSE
        actor:=NEW.published_by;
        data:=convert_from(NEW.manifest,'UTF8')::jsonb;
        IF encode(sha256(NEW.manifest),'hex') IS DISTINCT FROM NEW.manifest_sha256
           OR data->>'glossary_version_id' IS DISTINCT FROM NEW.id::text
           OR data->>'parent_glossary_version_id' IS DISTINCT FROM
                (SELECT version_id::text FROM regintel.learning_head WHERE singleton)
           OR jsonb_typeof(data->'definitions') IS DISTINCT FROM 'array'
           OR jsonb_array_length(data->'definitions') NOT BETWEEN 1 AND 100
           OR NEW.creation_transaction<>txid_current() THEN
            RAISE EXCEPTION 'Learning publication needs its exact independent version';
        END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(data->'definitions') LOOP
            SELECT * INTO d FROM regintel.learning_definitions WHERE id=(item#>>'{definition,id}')::uuid;
            IF NOT FOUND OR convert_from(d.payload,'UTF8')::jsonb IS DISTINCT FROM item->'definition' THEN
                RAISE EXCEPTION 'Published definition differs from retained draft';
            END IF;
            SELECT * INTO r FROM regintel.learning_reviews WHERE definition_id=d.id;
            IF NOT FOUND OR r.id::text IS DISTINCT FROM item->>'review_id'
               OR r.reviewer_id::text IS DISTINCT FROM item->>'reviewed_by'
               OR convert_from(r.review_bytes,'UTF8')::jsonb IS DISTINCT FROM item->'review'
               OR item#>>'{review,decision}' IS DISTINCT FROM 'APPROVE' THEN
                RAISE EXCEPTION 'Published learning content requires its actual approved review';
            END IF;
        END LOOP;
        IF (SELECT count(DISTINCT lower(value#>>'{definition,draft,term}')) FROM jsonb_array_elements(data->'definitions'))
            <>jsonb_array_length(data->'definitions') THEN
            RAISE EXCEPTION 'A learning version cannot repeat conflicting terms';
        END IF;
    END IF;
    PERFORM 1 FROM regintel.users WHERE id=actor AND role='admin' AND is_active AND auth_version=NEW.auth_version FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Current administrator required for learning writes'; END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'Learning publication or review membership is invalid' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER learning_insert_guard BEFORE INSERT ON regintel.learning_definitions
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_learning_insert();
CREATE TRIGGER learning_insert_guard BEFORE INSERT ON regintel.learning_reviews
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_learning_insert();
CREATE TRIGGER learning_insert_guard BEFORE INSERT ON regintel.learning_versions
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_learning_insert();

CREATE FUNCTION regintel.guard_learning_head() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Published learning head cannot be removed'; END IF;
    IF NOT EXISTS(SELECT FROM regintel.learning_versions WHERE id=NEW.version_id AND creation_transaction=txid_current()) THEN
        RAISE EXCEPTION 'Learning head must be part of its new version publication transaction';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER learning_head_guard BEFORE INSERT OR UPDATE OR DELETE ON regintel.learning_head
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_learning_head();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.learning_head
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.learning_definitions
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.learning_reviews
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.learning_versions
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.learning_definitions
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.learning_reviews
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.learning_versions
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

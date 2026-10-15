-- M1.9: immutable approved builds; authority and head become visible together.
-- No existing source, candidate, review, migration or historical observation is changed.
CREATE TABLE regintel.publication_builds (
    id regintel.canonical_id PRIMARY KEY REFERENCES regintel.corpus_versions(id)
        DEFERRABLE INITIALLY DEFERRED,
    idempotency_key regintel.canonical_id NOT NULL UNIQUE,
    request_bytes BYTEA NOT NULL CHECK (octet_length(request_bytes) BETWEEN 1 AND 32000000),
    request_sha256 regintel.sha256_hash NOT NULL,
    manifest_bytes BYTEA NOT NULL CHECK (octet_length(manifest_bytes) BETWEEN 1 AND 128000000),
    manifest_sha256 regintel.sha256_hash NOT NULL,
    dependency_sha256 regintel.sha256_hash NOT NULL,
    approved_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    creation_transaction BIGINT NOT NULL DEFAULT txid_current(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE regintel.publication_retrieval (
    corpus_version_id regintel.canonical_id PRIMARY KEY REFERENCES regintel.publication_builds(id),
    projection_bytes BYTEA NOT NULL CHECK (octet_length(projection_bytes) BETWEEN 1 AND 128000000),
    projection_sha256 regintel.sha256_hash NOT NULL,
    chunk_count INTEGER NOT NULL CHECK (chunk_count BETWEEN 0 AND 100000),
    prepared_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    creation_transaction BIGINT NOT NULL DEFAULT txid_current()
);
CREATE TABLE regintel.retrieval_chunks (
    id regintel.canonical_id PRIMARY KEY,
    corpus_version_id regintel.canonical_id NOT NULL REFERENCES regintel.publication_retrieval(corpus_version_id),
    observation_id regintel.canonical_id NOT NULL,
    evidence_id regintel.canonical_id NOT NULL REFERENCES regintel.evidence(id),
    start_offset regintel.safe_index NOT NULL,
    end_offset regintel.safe_index NOT NULL,
    quote regintel.stored_text NOT NULL,
    token_count INTEGER NOT NULL CHECK (token_count BETWEEN 3 AND 512),
    embedding public.vector(384) NOT NULL,
    term_counts JSONB NOT NULL CHECK (jsonb_typeof(term_counts) = 'object'),
    CHECK (end_offset > start_offset AND end_offset - start_offset = char_length(quote)),
    CHECK (abs(public.vector_norm(embedding) - 1) < 0.00002)
);
CREATE INDEX retrieval_corpus ON regintel.retrieval_chunks(corpus_version_id, observation_id);
CREATE INDEX retrieval_terms ON regintel.retrieval_chunks USING gin(term_counts);
CREATE TABLE regintel.publication_graph_receipts (
    corpus_version_id regintel.canonical_id PRIMARY KEY REFERENCES regintel.publication_builds(id),
    receipt_bytes BYTEA NOT NULL CHECK (octet_length(receipt_bytes) BETWEEN 1 AND 4096),
    receipt_sha256 regintel.sha256_hash NOT NULL,
    prepared_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0)
);
CREATE TABLE regintel.publication_commits (
    corpus_version_id regintel.canonical_id PRIMARY KEY REFERENCES regintel.publication_builds(id),
    parent_corpus_version_id regintel.canonical_id REFERENCES regintel.publication_commits(corpus_version_id),
    manifest_sha256 regintel.sha256_hash NOT NULL,
    retrieval_sha256 regintel.sha256_hash NOT NULL,
    graph_receipt_sha256 regintel.sha256_hash NOT NULL,
    published_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    creation_transaction BIGINT NOT NULL DEFAULT txid_current(),
    published_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE NULLS NOT DISTINCT (parent_corpus_version_id),
    CHECK (parent_corpus_version_id IS DISTINCT FROM corpus_version_id)
);
CREATE TABLE regintel.publication_observations (
    id regintel.canonical_id PRIMARY KEY,
    candidate_id regintel.canonical_id NOT NULL UNIQUE REFERENCES regintel.candidates(id),
    first_corpus_version_id regintel.canonical_id NOT NULL REFERENCES regintel.publication_commits(corpus_version_id),
    observation_bytes BYTEA NOT NULL CHECK (octet_length(observation_bytes) BETWEEN 1 AND 8000000),
    observation_sha256 regintel.sha256_hash NOT NULL,
    normalized_value NUMERIC CHECK (normalized_value IS NULL OR normalized_value::TEXT
        ~ '^-?(0|[1-9][0-9]{0,119})(\.[0-9]{1,120})?$')
);
CREATE TABLE regintel.publication_head (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    corpus_version_id regintel.canonical_id NOT NULL REFERENCES regintel.publication_commits(corpus_version_id)
);
CREATE TABLE regintel.retrieval_rebuilds (
    id regintel.canonical_id PRIMARY KEY,
    corpus_version_id regintel.canonical_id NOT NULL REFERENCES regintel.publication_retrieval(corpus_version_id),
    rebuilt_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version > 0),
    creation_transaction BIGINT NOT NULL DEFAULT txid_current()
);
CREATE FUNCTION regintel.initialize_retrieval_rebuild() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM regintel.entity_admin(NEW.rebuilt_by,NEW.auth_version);
    NEW.creation_transaction:=txid_current();
    RETURN NEW;
END; $$;
CREATE TRIGGER retrieval_rebuild_gate BEFORE INSERT ON regintel.retrieval_rebuilds
    FOR EACH ROW EXECUTE FUNCTION regintel.initialize_retrieval_rebuild();

CREATE FUNCTION regintel.publication_manifest(corpus_id UUID) RETURNS JSONB LANGUAGE sql STABLE AS $$
    SELECT convert_from(manifest_bytes,'UTF8')::JSONB FROM regintel.publication_builds WHERE id=corpus_id;
$$;
CREATE FUNCTION regintel.publication_fail(condition BOOLEAN, message TEXT) RETURNS VOID
LANGUAGE plpgsql AS $$ BEGIN
    IF condition IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION '%', message USING ERRCODE='23514';
    END IF;
END; $$;
CREATE FUNCTION regintel.publication_snapshot(acceptance JSONB, configuration JSONB) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE observation JSONB; fresh JSONB; owner regintel.validation_runs; candidate RECORD;
        result JSONB; draft JSONB; review regintel.validation_reviews; input JSONB;
        candidate_owner regintel.candidate_runs; field TEXT; span JSONB;
BEGIN
    observation := acceptance -> 'observation'; fresh := acceptance -> 'fresh_validation';
    PERFORM regintel.publication_fail(regintel.entity_json_keys(acceptance,
        ARRAY['observation','fresh_validation','original_review']), 'Acceptance snapshot fields differ');
    SELECT * INTO STRICT owner FROM regintel.validation_runs WHERE id=(fresh ->> 'id')::UUID;
    SELECT * INTO STRICT candidate_owner FROM regintel.candidate_runs WHERE id=owner.candidate_run_id;
    SELECT c.* INTO STRICT candidate FROM regintel.candidate_run_items item JOIN regintel.candidates c
        ON c.id=item.candidate_id WHERE item.run_id=owner.candidate_run_id
        AND item.candidate_id=(observation ->> 'candidate_id')::UUID;
    SELECT convert_from(draft_bytes,'UTF8')::JSONB INTO STRICT draft FROM regintel.candidate_run_items
        WHERE run_id=owner.candidate_run_id AND candidate_id=candidate.id;
    SELECT entry INTO STRICT result FROM jsonb_array_elements(fresh -> 'results') entry
        WHERE entry ->> 'candidate_id'=candidate.id::TEXT;
    input := convert_from(owner.input_bytes,'UTF8')::JSONB;
    PERFORM regintel.publication_fail(fresh=convert_from(owner.run_bytes,'UTF8')::JSONB
        AND fresh -> 'configuration' ->> 'code_sha256' IS NOT NULL
        AND owner.configuration_sha256=configuration ->> 'validator_configuration_sha256'
        AND input -> 'entity_reviews'=regintel.validation_current_reviews(candidate_owner.entity_run_id)
        AND input -> 'policies'=regintel.validation_current_policies(input -> 'source')
        AND result -> 'reviewer_eligible'='true'::JSONB
        AND result ->> 'state' IN ('PASS','REVIEW')
        AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(result -> 'checks') check_item
            WHERE check_item ->> 'state'<>'PASS' AND
                NOT (check_item ->> 'code'='EXTRACTIVE_REVIEW' AND check_item ->> 'state'='REVIEW')),
        'Publication cannot bypass a fresh mandatory gate or stale dependencies');
    PERFORM regintel.publication_fail(regintel.entity_json_keys(observation,ARRAY[
        'id','acceptance_audit_id','first_corpus_version_id','candidate_id','candidate_run_id',
        'parse_version_id','filing_version_id','validation_run_id','validation_input_sha256',
        'validator_configuration_sha256','review_id','kind','subject_entity_id','object_entity_id',
        'relation_type','metric_id','raw_text','quantity','supports','context_supports','source_published_on'])
        AND observation ->> 'id'=regintel.candidate_stable_id('published-observation:'||candidate.id::TEXT)::TEXT
        AND observation ->> 'acceptance_audit_id'=regintel.candidate_stable_id('acceptance:'||
            (observation ->> 'id'))::TEXT
        AND observation ->> 'candidate_run_id'=owner.candidate_run_id::TEXT
        AND observation ->> 'parse_version_id'=owner.parse_version_id::TEXT
        AND observation ->> 'validation_run_id'=owner.id::TEXT
        AND observation ->> 'validation_input_sha256'=owner.input_sha256
        AND observation ->> 'validator_configuration_sha256'=owner.configuration_sha256
        AND observation -> 'quantity'=result -> 'quantity'
        AND observation -> 'context_supports'=result -> 'context_supports'
        AND observation -> 'supports'=draft -> 'supports', 'Accepted observation snapshot differs');
    FOREACH field IN ARRAY ARRAY['kind','subject_entity_id','object_entity_id','relation_type','metric_id','raw_text'] LOOP
        PERFORM regintel.publication_fail(observation -> field=to_jsonb(candidate) -> field,
            'Accepted observation must preserve its immutable candidate');
    END LOOP;
    PERFORM regintel.publication_fail(EXISTS (SELECT 1 FROM regintel.parse_versions p
        JOIN regintel.filing_versions f ON f.id=p.filing_version_id
        WHERE p.id=owner.parse_version_id AND f.id::TEXT=observation ->> 'filing_version_id'
        AND to_jsonb(f.published_on::TEXT) IS NOT DISTINCT FROM nullif(observation -> 'source_published_on','null'::JSONB)),
        'Observation source/date must match its immutable original');
    SELECT * INTO review FROM regintel.validation_reviews WHERE candidate_id=candidate.id;
    IF FOUND THEN
        PERFORM regintel.publication_fail(review.decision='APPROVE_FOR_PUBLICATION'
            AND observation ->> 'review_id'=review.id::TEXT
            AND acceptance -> 'original_review'=jsonb_build_object(
                'decision',convert_from(review.review_bytes,'UTF8')::JSONB,
                'reviewed_by',review.reviewed_by,'auth_version',review.auth_version)
            AND EXISTS (SELECT 1 FROM regintel.validation_runs r WHERE r.id=review.validation_run_id
                AND r.candidate_run_id=owner.candidate_run_id),
            'An existing final review cannot be ignored or relabelled');
    ELSE
        PERFORM regintel.publication_fail(result ->> 'state'='PASS'
            AND observation -> 'review_id'='null'::JSONB AND acceptance -> 'original_review'='null'::JSONB,
            'Extractive confirmation requires its original supported review');
    END IF;
    FOR span IN SELECT jsonb_array_elements(observation -> 'supports') LOOP
        PERFORM regintel.candidate_span(span,owner.parse_version_id);
    END LOOP;
END; $$;

CREATE FUNCTION regintel.publication_amendments(request JSONB, manifest JSONB, parent JSONB)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE link JSONB; effect JSONB; issuer JSONB; filing JSONB; old_filing JSONB; span JSONB;
        names TEXT[]; operation TEXT; wording TEXT; cue TEXT; scope TEXT[]; touched TEXT[]:='{}';
        item JSONB; child_parse UUID; old_keys JSONB; new_keys JSONB; supported_date TEXT;
BEGIN
    PERFORM regintel.publication_fail((SELECT count(DISTINCT decision -> 'proposal' ->> 'id')
        FROM jsonb_array_elements((manifest -> 'lineages')||(manifest -> 'effects')) decision)=
        jsonb_array_length(manifest -> 'lineages')+jsonb_array_length(manifest -> 'effects'),
        'Amendment decisions require distinct immutable identities');
    FOR link IN SELECT jsonb_array_elements(request -> 'lineages') LOOP
        PERFORM regintel.publication_fail(regintel.entity_json_keys(link,ARRAY['id','parent_filing_version_id',
            'child_filing_version_id','lineage_type','issuer_entity_id','parent_identity','child_identity',
            'parent_reference','review_note']) AND regintel.candidate_uuid(link -> 'id')
            AND regintel.validation_nonblank(link -> 'review_note')
            AND link -> 'parent_filing_version_id'<>link -> 'child_filing_version_id', 'Lineage scope is invalid');
        SELECT f INTO STRICT old_filing FROM jsonb_array_elements(manifest -> 'filings') f
            WHERE f -> 'filing_version_id'=link -> 'parent_filing_version_id';
        SELECT f INTO STRICT filing FROM jsonb_array_elements(manifest -> 'filings') f
            WHERE f -> 'filing_version_id'=link -> 'child_filing_version_id';
        SELECT convert_from(registration_bytes,'UTF8')::JSONB INTO STRICT issuer
            FROM regintel.entity_registrations WHERE id=(link ->> 'issuer_entity_id')::UUID;
        SELECT array_agg(name) INTO names FROM (
            SELECT lower(issuer ->> 'legal_name') AS name UNION ALL
            SELECT lower(a ->> 'name') FROM jsonb_array_elements(issuer -> 'aliases') a UNION ALL
            SELECT lower(i ->> 'value') FROM jsonb_array_elements(issuer -> 'identifiers') i) approved_names;
        PERFORM regintel.publication_fail(issuer ->> 'kind'='COMPANY'
            AND old_filing -> 'filing_id'<>filing -> 'filing_id'
            AND lower(link -> 'parent_identity' ->> 'quote')=ANY(names)
            AND lower(link -> 'child_identity' ->> 'quote')=ANY(names)
            AND ((link ->> 'lineage_type'='ADDENDUM_TO' AND filing ->> 'document_type'='ADDENDUM')
                OR (link ->> 'lineage_type'='CORRIGENDUM_TO' AND filing ->> 'document_type' IN ('CORRIGENDUM','ADDENDUM'))
                OR link ->> 'lineage_type'='AMENDS')
            AND EXISTS (SELECT 1 FROM regintel.filing_versions f WHERE f.id=(filing ->> 'filing_version_id')::UUID
                AND (f.declared_parent_filing_version_id IS NULL OR
                    f.declared_parent_filing_version_id=(old_filing ->> 'filing_version_id')::UUID)),
            'Lineage requires the matching approved issuer and explicit original parent');
    END LOOP;
    PERFORM regintel.publication_fail(NOT EXISTS (
        WITH RECURSIVE edges AS (SELECT l -> 'proposal' ->> 'parent_filing_version_id' AS source,
            l -> 'proposal' ->> 'child_filing_version_id' AS target FROM jsonb_array_elements(manifest -> 'lineages') l),
        reach(source,target) AS (SELECT source,target FROM edges UNION SELECT r.source,e.target
            FROM reach r JOIN edges e ON e.source=r.target)
        SELECT 1 FROM reach WHERE source=target), 'Lineage cannot contain a cycle');
    FOR effect IN SELECT jsonb_array_elements(request -> 'effects') LOOP
        operation:=effect ->> 'effect_type';
        SELECT l -> 'proposal' INTO STRICT link FROM jsonb_array_elements(manifest -> 'lineages') l
            WHERE l -> 'proposal' -> 'id'=effect -> 'lineage_id';
        SELECT f INTO STRICT filing FROM jsonb_array_elements(manifest -> 'filings') f
            WHERE f -> 'filing_version_id'=link -> 'child_filing_version_id';
        child_parse:=(filing ->> 'parse_version_id')::UUID;
        PERFORM regintel.publication_fail(regintel.entity_json_keys(effect,ARRAY['id','lineage_id','effect_type',
            'affected_observation_ids','new_candidate_ids','supports','effective_date','effective_date_support','review_note'])
            AND regintel.candidate_uuid(effect -> 'id') AND regintel.validation_nonblank(effect -> 'review_note')
            AND operation IN ('ADD','CORRECT','SUPPLEMENT','SUPERSEDE','REMOVE')
            AND jsonb_array_length(effect -> 'supports') BETWEEN 1 AND 16
            AND ((operation='ADD' AND jsonb_array_length(effect -> 'affected_observation_ids')=0
                AND jsonb_array_length(effect -> 'new_candidate_ids')>0)
                OR (operation='REMOVE' AND jsonb_array_length(effect -> 'affected_observation_ids')>0
                    AND jsonb_array_length(effect -> 'new_candidate_ids')=0)
                OR (operation IN ('CORRECT','SUPPLEMENT','SUPERSEDE') AND jsonb_array_length(effect -> 'affected_observation_ids')>0
                    AND jsonb_array_length(effect -> 'new_candidate_ids')>0)), 'Effect operation and scope differ');
        SELECT coalesce(array_agg(id #>> '{}'),'{}') INTO scope FROM jsonb_array_elements(effect -> 'affected_observation_ids') id;
        PERFORM regintel.publication_fail(NOT scope&&touched AND NOT EXISTS (
            SELECT 1 FROM unnest(scope) id WHERE NOT coalesce(parent -> 'active_observation_ids','[]'::JSONB) @> to_jsonb(id)),
            'Effects require distinct active named parent observations');
        touched:=touched||scope;
        FOR item IN SELECT jsonb_array_elements(effect -> 'affected_observation_ids') LOOP
            PERFORM regintel.publication_fail(EXISTS(SELECT 1 FROM jsonb_array_elements(parent -> 'observations') o
                WHERE o -> 'id'=item AND o -> 'filing_version_id'=link -> 'parent_filing_version_id'), 'Effect addresses another filing');
        END LOOP;
        FOR item IN SELECT jsonb_array_elements(effect -> 'new_candidate_ids') LOOP
            PERFORM regintel.publication_fail(EXISTS(SELECT 1 FROM jsonb_array_elements(manifest -> 'new_acceptances') a
                WHERE a -> 'observation' -> 'candidate_id'=item AND
                    a -> 'observation' -> 'filing_version_id'=link -> 'child_filing_version_id'), 'New effect evidence belongs to another filing');
        END LOOP;
        wording:='';
        FOR span IN SELECT jsonb_array_elements(effect -> 'supports') LOOP
            PERFORM regintel.candidate_span(span,child_parse);
            wording:=wording||' '||lower(span ->> 'quote');
        END LOOP;
        cue:=CASE operation WHEN 'ADD' THEN '\m(add(ed|ition|itional)?|include[ds]?)\M'
            WHEN 'CORRECT' THEN '\m(correct(ed|ion)?|amend(ed|ment)?|revis(ed|ion))\M'
            WHEN 'SUPPLEMENT' THEN '\m(supplement(ed|al|ation)?|addition(al)?|also)\M'
            WHEN 'SUPERSEDE' THEN '\m(supersed(e[ds]?|ing)|replac(e[ds]?|ement)|substitut(ed|ion))\M'
            ELSE '\m(remov(ed|al)|delet(ed|ion)|omitted|withdrawn)\M' END;
        PERFORM regintel.publication_fail(wording~cue AND wording!~'\m(not|never|propos(e[ds]?|ing)|may|might)\M',
            'Source wording must explicitly support the reviewed effect');
        PERFORM regintel.publication_fail(regintel.validation_date(effect -> 'effective_date',TRUE)
            AND (effect -> 'effective_date'='null'::JSONB)=(effect -> 'effective_date_support'='null'::JSONB), 'Effect date requires support');
        IF effect -> 'effective_date'<>'null'::JSONB THEN
            span:=effect -> 'effective_date_support';
            PERFORM regintel.candidate_span(span,child_parse);
            supported_date:=lower(btrim(span ->> 'quote'));
            PERFORM regintel.publication_fail(EXISTS (SELECT 1 FROM jsonb_array_elements(effect -> 'supports') s
                WHERE s -> 'evidence_id'=span -> 'evidence_id' AND (s ->> 'start')::BIGINT<=(span ->> 'start')::BIGINT
                    AND (s ->> 'end')::BIGINT>=(span ->> 'end')::BIGINT)
                AND supported_date=ANY(ARRAY[effect ->> 'effective_date',
                    lower(to_char((effect ->> 'effective_date')::DATE,'FMDD FMMonth YYYY')),
                    lower(to_char((effect ->> 'effective_date')::DATE,'FMMonth FMDD, YYYY')),
                    lower(to_char((effect ->> 'effective_date')::DATE,'FMMonth FMDD YYYY')),
                    lower(to_char((effect ->> 'effective_date')::DATE,'FMDD Mon YYYY'))]), 'Effective date differs from exact source support');
        END IF;
        IF operation IN ('CORRECT','SUPERSEDE') THEN
            SELECT jsonb_agg(key ORDER BY key) INTO old_keys FROM (SELECT DISTINCT jsonb_build_array(
                o -> 'kind',o -> 'subject_entity_id',o -> 'metric_id',o -> 'relation_type',o -> 'object_entity_id') AS key
                FROM jsonb_array_elements(parent -> 'observations') o WHERE o ->> 'id'=ANY(scope)) keys;
            SELECT jsonb_agg(key ORDER BY key) INTO new_keys FROM (SELECT DISTINCT jsonb_build_array(
                o -> 'kind',o -> 'subject_entity_id',o -> 'metric_id',o -> 'relation_type',o -> 'object_entity_id') AS key
                FROM jsonb_array_elements(manifest -> 'observations') o WHERE EXISTS (
                    SELECT 1 FROM jsonb_array_elements(effect -> 'new_candidate_ids') id WHERE o -> 'candidate_id'=id)) keys;
            PERFORM regintel.publication_fail(old_keys=new_keys,'Replacement disclosure identities must match');
        END IF;
    END LOOP;
END; $$;

CREATE FUNCTION regintel.validate_publication_build() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE request JSONB; manifest JSONB; configuration JSONB; parent JSONB; item JSONB;
        selected JSONB; expected JSONB; source RECORD; previous JSONB; active_ids TEXT[];
        requested_ids TEXT[]; actual_ids TEXT[];
BEGIN
    PERFORM regintel.entity_admin(NEW.approved_by, NEW.auth_version);
    NEW.creation_transaction := txid_current();
    request := convert_from(NEW.request_bytes,'UTF8')::JSONB;
    manifest := convert_from(NEW.manifest_bytes,'UTF8')::JSONB;
    configuration := manifest -> 'configuration';
    PERFORM regintel.publication_fail(
        convert_from(NEW.request_bytes,'UTF8')=regintel.candidate_canonical_json(request)
        AND encode(sha256(NEW.request_bytes),'hex')=NEW.request_sha256
        AND convert_from(NEW.manifest_bytes,'UTF8')=regintel.candidate_canonical_json(manifest)
        AND encode(sha256(NEW.manifest_bytes),'hex')=NEW.manifest_sha256
        AND regintel.entity_json_keys(request,ARRAY['idempotency_key','parent_corpus_version_id','selections','lineages','effects'])
        AND regintel.entity_json_keys(manifest,ARRAY['id','parent_corpus_version_id','request_sha256',
            'configuration','approved_by','approved_auth_version','filings','observations','new_acceptances',
            'lineages','effects','active_observation_ids','unresolved_parent_filing_version_ids'])
        AND request ->> 'idempotency_key'=NEW.idempotency_key::TEXT
        AND manifest ->> 'id'=NEW.id::TEXT AND manifest ->> 'request_sha256'=NEW.request_sha256
        AND manifest ->> 'approved_by'=NEW.approved_by::TEXT
        AND manifest -> 'approved_auth_version'=to_jsonb(NEW.auth_version)
        AND manifest -> 'parent_corpus_version_id'=request -> 'parent_corpus_version_id'
        AND NEW.id=regintel.candidate_stable_id('corpus:'||NEW.idempotency_key::TEXT||':'||NEW.request_sha256
            ||':'||encode(sha256(convert_to(regintel.candidate_canonical_json(configuration),'UTF8')),'hex')),
        'Publication requires a complete canonical approved manifest');
    PERFORM regintel.publication_fail(regintel.entity_json_keys(configuration,ARRAY['version','code_sha256',
        'validator_configuration_sha256','embedding_manifest_sha256','embedding_model','embedding_revision',
        'embedding_dimensions','max_embedding_tokens','chunk_target_tokens','onnxruntime_version',
        'tokenizers_version','neo4j_driver_version'])
        AND configuration ->> 'version'='1.0.0'
        AND configuration ->> 'code_sha256' ~ '^[0-9a-f]{64}$'
        AND configuration ->> 'validator_configuration_sha256' ~ '^[0-9a-f]{64}$'
        AND configuration ->> 'embedding_manifest_sha256' ~ '^[0-9a-f]{64}$'
        AND configuration ->> 'embedding_model'='BAAI/bge-small-en-v1.5'
        AND configuration ->> 'embedding_revision'='5c38ec7c405ec4b44b94cc5a9bb96e735b38267a'
        AND configuration -> 'embedding_dimensions'='384'::JSONB
        AND configuration -> 'max_embedding_tokens'='512'::JSONB
        AND configuration -> 'chunk_target_tokens'='450'::JSONB
        AND configuration ->> 'onnxruntime_version'='1.30.0'
        AND configuration ->> 'tokenizers_version'='0.23.2'
        AND configuration ->> 'neo4j_driver_version'='6.4.0', 'Publication configuration differs');
    IF request ->> 'parent_corpus_version_id' IS NOT NULL THEN
        SELECT regintel.publication_manifest(corpus_version_id) INTO STRICT parent
            FROM regintel.publication_commits WHERE corpus_version_id=(request ->> 'parent_corpus_version_id')::UUID;
    END IF;
    PERFORM regintel.publication_fail(request ->> 'parent_corpus_version_id' IS NOT DISTINCT FROM
        (SELECT corpus_version_id::TEXT FROM regintel.publication_head), 'Publication parent is not the explicit head');
    FOREACH actual_ids SLICE 1 IN ARRAY ARRAY[ARRAY['selections','100'],ARRAY['lineages','100'],ARRAY['effects','100']] LOOP
        PERFORM regintel.publication_fail(jsonb_typeof(request -> actual_ids[1])='array'
            AND jsonb_array_length(request -> actual_ids[1])<=actual_ids[2]::INTEGER, 'Publication request exceeds bounds');
    END LOOP;
    PERFORM regintel.publication_fail(jsonb_typeof(manifest -> 'observations')='array'
        AND jsonb_array_length(manifest -> 'observations')<=10000
        AND jsonb_typeof(manifest -> 'new_acceptances')='array'
        AND jsonb_array_length(manifest -> 'new_acceptances')=jsonb_array_length(request -> 'selections')
        AND jsonb_array_length(manifest -> 'observations')=coalesce(jsonb_array_length(parent -> 'observations'),0)
            +jsonb_array_length(manifest -> 'new_acceptances')
        AND (SELECT count(DISTINCT o ->> 'id') FROM jsonb_array_elements(manifest -> 'observations') o)
            =jsonb_array_length(manifest -> 'observations'), 'Publication observations must be complete and distinct');
    FOR item IN SELECT jsonb_array_elements(coalesce(parent -> 'observations','[]'::JSONB)) LOOP
        PERFORM regintel.publication_fail(manifest -> 'observations' @> jsonb_build_array(item), 'Historical observations cannot change');
    END LOOP;
    FOR item IN SELECT jsonb_array_elements(manifest -> 'new_acceptances') LOOP
        selected := item -> 'observation';
        PERFORM regintel.publication_snapshot(item,configuration);
        PERFORM regintel.publication_fail(selected ->> 'first_corpus_version_id'=NEW.id::TEXT
            AND manifest -> 'observations' @> jsonb_build_array(selected)
            AND EXISTS (SELECT 1 FROM jsonb_array_elements(request -> 'selections') s
                WHERE regintel.entity_json_keys(s,ARRAY['candidate_run_id','candidate_id','review_id'])
                    AND s -> 'candidate_id'=selected -> 'candidate_id'
                    AND s -> 'candidate_run_id'=selected -> 'candidate_run_id'
                    AND s -> 'review_id'=selected -> 'review_id'), 'Selected acceptance membership differs');
    END LOOP;
    FOR item IN SELECT jsonb_array_elements(manifest -> 'filings') LOOP
        SELECT p.id AS parse_version_id,p.filing_version_id,f.filing_id,f.document_type,
            f.published_on::TEXT AS published_on,b.sha256 AS source_sha256 INTO STRICT source
            FROM regintel.parse_versions p JOIN regintel.filing_versions f ON f.id=p.filing_version_id
            JOIN regintel.source_blobs b ON b.id=p.source_blob_id WHERE p.id=(item ->> 'parse_version_id')::UUID;
        PERFORM regintel.publication_fail(item=to_jsonb(source), 'Filing snapshot differs from its immutable source');
    END LOOP;
    FOR item IN SELECT jsonb_array_elements(manifest -> 'observations') LOOP
        PERFORM regintel.publication_fail(EXISTS (SELECT 1 FROM jsonb_array_elements(manifest -> 'filings') f
            WHERE f -> 'parse_version_id'=item -> 'parse_version_id'
                AND f -> 'filing_version_id'=item -> 'filing_version_id'), 'Observation filing membership differs');
    END LOOP;
    -- Application recomputation handles semantic scope. SQL independently binds all
    -- reviewed decisions, immutable history, exact sources and the resulting active set.
    FOR item IN SELECT jsonb_array_elements(coalesce(parent -> 'lineages','[]'::JSONB)) LOOP
        PERFORM regintel.publication_fail(manifest -> 'lineages' @> jsonb_build_array(item), 'Lineage history cannot change');
    END LOOP;
    FOR item IN SELECT jsonb_array_elements(coalesce(parent -> 'effects','[]'::JSONB)) LOOP
        PERFORM regintel.publication_fail(manifest -> 'effects' @> jsonb_build_array(item), 'Effect history cannot change');
    END LOOP;
    PERFORM regintel.publication_fail(jsonb_array_length(manifest -> 'lineages')=
        coalesce(jsonb_array_length(parent -> 'lineages'),0)+jsonb_array_length(request -> 'lineages')
        AND jsonb_array_length(manifest -> 'effects')=coalesce(jsonb_array_length(parent -> 'effects'),0)
            +jsonb_array_length(request -> 'effects'), 'Amendment decision counts differ');
    FOR item IN SELECT jsonb_array_elements(request -> 'lineages') LOOP
        expected := jsonb_build_object('proposal',item,'approved_in_corpus_version_id',NEW.id,
            'reviewed_by',NEW.approved_by,'auth_version',NEW.auth_version);
        PERFORM regintel.publication_fail(manifest -> 'lineages' @> jsonb_build_array(expected), 'Lineage approval snapshot differs');
        PERFORM regintel.candidate_span(item -> 'parent_identity', (SELECT id FROM regintel.parse_versions
            WHERE filing_version_id=(item ->> 'parent_filing_version_id')::UUID
                AND id::TEXT IN (SELECT f ->> 'parse_version_id' FROM jsonb_array_elements(manifest -> 'filings') f)));
        FOR selected IN SELECT value FROM jsonb_each(item) WHERE key IN ('child_identity','parent_reference') LOOP
            PERFORM regintel.candidate_span(selected, (SELECT id FROM regintel.parse_versions
                WHERE filing_version_id=(item ->> 'child_filing_version_id')::UUID
                    AND id::TEXT IN (SELECT f ->> 'parse_version_id' FROM jsonb_array_elements(manifest -> 'filings') f)));
        END LOOP;
    END LOOP;
    SELECT coalesce(array_agg(entry #>> '{}'),'{}') INTO active_ids
        FROM jsonb_array_elements(coalesce(parent -> 'active_observation_ids','[]'::JSONB)) entry;
    FOR item IN SELECT jsonb_array_elements(request -> 'effects') LOOP
        SELECT proposal INTO STRICT previous FROM (
            SELECT l -> 'proposal' AS proposal FROM jsonb_array_elements(manifest -> 'lineages') l
                WHERE l -> 'proposal' ->> 'id'=item ->> 'lineage_id') linked;
        FOR selected IN SELECT jsonb_array_elements(item -> 'supports') LOOP
            PERFORM regintel.candidate_span(selected,(SELECT p.id FROM regintel.parse_versions p
                WHERE p.filing_version_id=(previous ->> 'child_filing_version_id')::UUID
                    AND p.id::TEXT IN (SELECT f ->> 'parse_version_id' FROM jsonb_array_elements(manifest -> 'filings') f)));
        END LOOP;
        SELECT coalesce(array_agg(o ->> 'id' ORDER BY position),'{}') INTO actual_ids FROM
            jsonb_array_elements(item -> 'new_candidate_ids') WITH ORDINALITY refs(candidate_id,position)
            JOIN LATERAL jsonb_array_elements(manifest -> 'observations') o
                ON o -> 'candidate_id'=refs.candidate_id
                AND o ->> 'first_corpus_version_id'=NEW.id::TEXT;
        expected := jsonb_build_object('proposal',item,'new_observation_ids',to_jsonb(actual_ids),
            'approved_in_corpus_version_id',NEW.id,'reviewed_by',NEW.approved_by,'auth_version',NEW.auth_version);
        PERFORM regintel.publication_fail(manifest -> 'effects' @> jsonb_build_array(expected)
            AND cardinality(actual_ids)=jsonb_array_length(item -> 'new_candidate_ids'), 'Effect scope snapshot differs');
        IF item ->> 'effect_type' IN ('CORRECT','SUPERSEDE','REMOVE') THEN
            SELECT coalesce(array_agg(id),'{}') INTO active_ids FROM unnest(active_ids) id
                WHERE id NOT IN (SELECT value #>> '{}' FROM jsonb_array_elements(item -> 'affected_observation_ids'));
        END IF;
    END LOOP;
    SELECT coalesce(array_agg(id ORDER BY id),'{}') INTO requested_ids FROM (
        SELECT unnest(active_ids) AS id UNION
        SELECT o -> 'observation' ->> 'id' FROM jsonb_array_elements(manifest -> 'new_acceptances') o) all_active;
    SELECT coalesce(array_agg(entry #>> '{}' ORDER BY entry #>> '{}'),'{}') INTO actual_ids
        FROM jsonb_array_elements(manifest -> 'active_observation_ids') entry;
    PERFORM regintel.publication_fail(actual_ids=requested_ids, 'Active observations must follow explicit scoped effects');
    PERFORM regintel.publication_amendments(request,manifest,parent);
    RETURN NEW;
END; $$;
CREATE TRIGGER publication_build_gate BEFORE INSERT ON regintel.publication_builds
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_publication_build();

CREATE FUNCTION regintel.validate_publication_projection() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE manifest JSONB; payload JSONB; row_payload JSONB; approved regintel.publication_builds;
        observation JSONB; support JSONB; parse_id UUID;
BEGIN
    SELECT * INTO STRICT approved FROM regintel.publication_builds WHERE id=NEW.corpus_version_id;
    manifest := convert_from(approved.manifest_bytes,'UTF8')::JSONB;
    IF TG_TABLE_NAME='publication_retrieval' THEN
        PERFORM regintel.entity_admin(NEW.prepared_by,NEW.auth_version);
        NEW.creation_transaction := txid_current();
        payload := convert_from(NEW.projection_bytes,'UTF8')::JSONB;
        PERFORM regintel.publication_fail(regintel.entity_json_keys(payload,ARRAY['version','corpus_version_id',
            'manifest_sha256','embedding_manifest_sha256','chunks'])
            AND encode(sha256(NEW.projection_bytes),'hex')=NEW.projection_sha256
            AND payload ->> 'version'='1.0.0' AND payload ->> 'corpus_version_id'=NEW.corpus_version_id::TEXT
            AND payload ->> 'manifest_sha256'=approved.manifest_sha256
            AND payload -> 'embedding_manifest_sha256'=manifest -> 'configuration' -> 'embedding_manifest_sha256'
            AND jsonb_typeof(payload -> 'chunks')='array'
            AND jsonb_array_length(payload -> 'chunks')=NEW.chunk_count
            AND (SELECT count(DISTINCT c ->> 'id') FROM jsonb_array_elements(payload -> 'chunks') c)=NEW.chunk_count,
            'Retrieval projection must bind one approved manifest');
        FOR observation IN SELECT jsonb_array_elements(manifest -> 'observations') LOOP
            FOR support IN SELECT jsonb_array_elements((observation -> 'supports') ||
                (SELECT coalesce(jsonb_agg(w -> 'span'),'[]'::JSONB)
                    FROM jsonb_array_elements(observation -> 'context_supports') w)) LOOP
                PERFORM regintel.publication_fail((SELECT range_agg(int8range(
                    (c -> 'support' ->> 'start')::BIGINT,(c -> 'support' ->> 'end')::BIGINT,'[)'))
                    @> int8range((support ->> 'start')::BIGINT,(support ->> 'end')::BIGINT,'[)')
                    FROM jsonb_array_elements(payload -> 'chunks') c
                    WHERE c -> 'observation_id'=observation -> 'id'
                        AND c -> 'support' -> 'evidence_id'=support -> 'evidence_id'),
                    'Retrieval projection must cover every complete approved support');
            END LOOP;
        END LOOP;
    ELSE
        SELECT convert_from(projection_bytes,'UTF8')::JSONB INTO STRICT payload
            FROM regintel.publication_retrieval WHERE corpus_version_id=NEW.corpus_version_id
                AND (creation_transaction=txid_current() OR EXISTS
                    (SELECT 1 FROM regintel.retrieval_rebuilds r WHERE r.corpus_version_id=NEW.corpus_version_id
                        AND r.creation_transaction=txid_current()));
        SELECT c INTO STRICT row_payload FROM jsonb_array_elements(payload -> 'chunks') c WHERE c ->> 'id'=NEW.id::TEXT;
        support := row_payload -> 'support';
        SELECT o INTO STRICT observation FROM jsonb_array_elements(manifest -> 'observations') o
            WHERE o ->> 'id'=NEW.observation_id::TEXT;
        parse_id := (observation ->> 'parse_version_id')::UUID;
        PERFORM regintel.candidate_span(support,parse_id);
        PERFORM regintel.publication_fail(regintel.entity_json_keys(row_payload,ARRAY['id','observation_id','support',
            'token_count','embedding','term_counts'])
            AND NEW.id=regintel.candidate_stable_id('chunk:'||NEW.corpus_version_id::TEXT||':'||NEW.observation_id::TEXT
                ||':'||NEW.evidence_id::TEXT||':'||NEW.start_offset::TEXT||':'||NEW.end_offset::TEXT)
            AND support ->> 'evidence_id'=NEW.evidence_id::TEXT AND support -> 'start'=to_jsonb(NEW.start_offset)
            AND support -> 'end'=to_jsonb(NEW.end_offset) AND support ->> 'quote'=NEW.quote
            AND row_payload ->> 'observation_id'=NEW.observation_id::TEXT
            AND row_payload -> 'token_count'=to_jsonb(NEW.token_count)
            AND row_payload -> 'term_counts'=NEW.term_counts
            AND NEW.embedding::REAL[]=ARRAY(SELECT (entry #>> '{}')::REAL
                FROM jsonb_array_elements(row_payload -> 'embedding') entry)
            AND EXISTS (SELECT 1 FROM jsonb_array_elements((observation -> 'supports') ||
                (SELECT coalesce(jsonb_agg(w -> 'span'),'[]'::JSONB)
                    FROM jsonb_array_elements(observation -> 'context_supports') w)) original
                WHERE original -> 'evidence_id'=support -> 'evidence_id'
                    AND (original ->> 'start')::BIGINT<=NEW.start_offset
                    AND (original ->> 'end')::BIGINT>=NEW.end_offset), 'Chunk projection must retain exact approved support');
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER publication_retrieval_gate BEFORE INSERT ON regintel.publication_retrieval
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_publication_projection();
CREATE TRIGGER retrieval_chunk_gate BEFORE INSERT ON regintel.retrieval_chunks
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_publication_projection();
CREATE FUNCTION regintel.complete_publication_retrieval() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM regintel.publication_fail(NEW.chunk_count=(SELECT count(*) FROM regintel.retrieval_chunks
        WHERE corpus_version_id=NEW.corpus_version_id), 'Retrieval projection must commit complete atomically');
    RETURN NULL;
END; $$;
CREATE CONSTRAINT TRIGGER publication_retrieval_complete AFTER INSERT ON regintel.publication_retrieval
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION regintel.complete_publication_retrieval();

CREATE FUNCTION regintel.validate_publication_receipt() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE approved regintel.publication_builds; payload JSONB;
BEGIN
    PERFORM regintel.entity_admin(NEW.prepared_by,NEW.auth_version);
    SELECT * INTO STRICT approved FROM regintel.publication_builds WHERE id=NEW.corpus_version_id;
    payload := convert_from(NEW.receipt_bytes,'UTF8')::JSONB;
    PERFORM regintel.publication_fail(regintel.entity_json_keys(payload,ARRAY['corpus_version_id',
        'manifest_sha256','namespace','graph_sha256','node_count','edge_count'])
        AND convert_from(NEW.receipt_bytes,'UTF8')=regintel.candidate_canonical_json(payload)
        AND encode(sha256(NEW.receipt_bytes),'hex')=NEW.receipt_sha256
        AND payload ->> 'corpus_version_id'=NEW.corpus_version_id::TEXT
        AND payload ->> 'manifest_sha256'=approved.manifest_sha256
        AND payload ->> 'namespace' ~ '^regintel(_test_[0-9a-f]{32})?$'
        AND payload ->> 'graph_sha256' ~ '^[0-9a-f]{64}$'
        AND (payload ->> 'node_count')::INTEGER>=0 AND (payload ->> 'edge_count')::INTEGER>=0,
        'Graph receipt must bind the approved version and bounded namespace');
    RETURN NEW;
END; $$;
CREATE TRIGGER publication_graph_receipt_gate BEFORE INSERT ON regintel.publication_graph_receipts
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_publication_receipt();

CREATE FUNCTION regintel.validate_publication_commit() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE approved regintel.publication_builds; manifest JSONB;
BEGIN
    PERFORM regintel.entity_admin(NEW.published_by,NEW.auth_version);
    NEW.creation_transaction := txid_current();
    SELECT * INTO STRICT approved FROM regintel.publication_builds WHERE id=NEW.corpus_version_id;
    manifest := convert_from(approved.manifest_bytes,'UTF8')::JSONB;
    PERFORM regintel.publication_fail(NEW.manifest_sha256=approved.manifest_sha256
        AND NEW.published_by=approved.approved_by AND NEW.auth_version=approved.auth_version
        AND NEW.parent_corpus_version_id::TEXT IS NOT DISTINCT FROM manifest ->> 'parent_corpus_version_id'
        AND NEW.parent_corpus_version_id IS NOT DISTINCT FROM (SELECT corpus_version_id FROM regintel.publication_head)
        AND EXISTS (SELECT 1 FROM regintel.publication_retrieval WHERE corpus_version_id=NEW.corpus_version_id
            AND projection_sha256=NEW.retrieval_sha256)
        AND EXISTS (SELECT 1 FROM regintel.publication_graph_receipts WHERE corpus_version_id=NEW.corpus_version_id
            AND receipt_sha256=NEW.graph_receipt_sha256)
        AND EXISTS (SELECT 1 FROM regintel.corpus_versions WHERE id=NEW.corpus_version_id AND state='BUILDING'),
        'Publication requires the approved actor, prepared projections and unchanged head');
    RETURN NEW;
END; $$;
CREATE TRIGGER publication_commit_gate BEFORE INSERT ON regintel.publication_commits
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_publication_commit();

CREATE FUNCTION regintel.require_publication_authority() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE manifest JSONB; observation JSONB; acceptance JSONB; owner RECORD; field TEXT;
        expected_context UUID; stored RECORD; quantity JSONB; corpus_id UUID;
BEGIN
    IF TG_TABLE_NAME='corpus_versions' THEN
        SELECT * INTO STRICT owner FROM regintel.publication_builds WHERE id=NEW.id
            AND creation_transaction=txid_current();
        manifest := convert_from(owner.manifest_bytes,'UTF8')::JSONB;
        PERFORM regintel.publication_fail(NEW.state='BUILDING'
            AND NEW.parent_corpus_version_id::TEXT IS NOT DISTINCT FROM manifest ->> 'parent_corpus_version_id'
            AND NEW.configuration_sha256=encode(sha256(convert_to(
                regintel.candidate_canonical_json(manifest -> 'configuration'),'UTF8')),'hex'), 'Unapproved corpus insertion');
        RETURN NEW;
    END IF;
    IF TG_TABLE_NAME='acceptance_audits' THEN
        SELECT b.manifest_bytes,c.published_by INTO STRICT owner FROM regintel.publication_commits c
            JOIN regintel.publication_builds b ON b.id=c.corpus_version_id WHERE c.creation_transaction=txid_current();
        manifest := convert_from(owner.manifest_bytes,'UTF8')::JSONB;
        SELECT a INTO STRICT acceptance FROM jsonb_array_elements(manifest -> 'new_acceptances') a
            WHERE a -> 'observation' ->> 'acceptance_audit_id'=NEW.id::TEXT;
        observation := acceptance -> 'observation';
        PERFORM regintel.publication_snapshot(acceptance,manifest -> 'configuration');
        PERFORM regintel.publication_fail(NEW.actor_user_id=owner.published_by
            AND NEW.candidate_id::TEXT=observation ->> 'candidate_id'
            AND NEW.parse_version_id::TEXT=observation ->> 'parse_version_id'
            AND NEW.validator_configuration_sha256=observation ->> 'validator_configuration_sha256', 'Acceptance audit differs');
        RETURN NEW;
    END IF;
    IF TG_TABLE_NAME='publication_observations' THEN corpus_id:=NEW.first_corpus_version_id;
    ELSE corpus_id:=NEW.corpus_version_id; END IF;
    SELECT b.manifest_bytes INTO STRICT owner FROM regintel.publication_commits c
        JOIN regintel.publication_builds b ON b.id=c.corpus_version_id
        WHERE c.corpus_version_id=corpus_id AND c.creation_transaction=txid_current();
    manifest := convert_from(owner.manifest_bytes,'UTF8')::JSONB;
    SELECT a -> 'observation' INTO STRICT observation FROM jsonb_array_elements(manifest -> 'new_acceptances') a
        WHERE a -> 'observation' ->> 'id'=NEW.id::TEXT;
    IF TG_TABLE_NAME='publication_observations' THEN
        PERFORM regintel.publication_fail(convert_from(NEW.observation_bytes,'UTF8')=
            regintel.candidate_canonical_json(observation)
            AND encode(sha256(NEW.observation_bytes),'hex')=NEW.observation_sha256
            AND NEW.candidate_id::TEXT=observation ->> 'candidate_id'
            AND NEW.normalized_value IS NOT DISTINCT FROM (observation -> 'quantity' ->> 'normalized_value')::NUMERIC,
            'Authoritative observation payload differs');
        RETURN NEW;
    END IF;
    FOREACH field IN ARRAY ARRAY['candidate_id','parse_version_id','acceptance_audit_id','subject_entity_id'] LOOP
        PERFORM regintel.publication_fail(to_jsonb(NEW) ->> field=observation ->> field, 'Observation identity differs');
    END LOOP;
    IF TG_TABLE_NAME='fact_observations' THEN
        PERFORM regintel.publication_fail(NEW.kind=observation ->> 'kind'
            AND NEW.metric_id::TEXT=observation ->> 'metric_id' AND NEW.raw_text=observation ->> 'raw_text', 'Fact fields differ');
    ELSE
        PERFORM regintel.publication_fail(observation ->> 'kind'='relation'
            AND NEW.object_entity_id::TEXT=observation ->> 'object_entity_id'
            AND NEW.relation_type=observation ->> 'relation_type', 'Directed relation fields differ');
    END IF;
    quantity := observation -> 'quantity';
    expected_context := CASE WHEN quantity='null'::JSONB THEN NULL ELSE
        regintel.candidate_stable_id('accepted-quantity:'||NEW.id::TEXT) END;
    PERFORM regintel.publication_fail(NEW.quantitative_context_id IS NOT DISTINCT FROM expected_context, 'Accepted numeric context differs');
    IF expected_context IS NOT NULL THEN
        SELECT * INTO STRICT stored FROM regintel.quantitative_contexts WHERE id=expected_context;
        PERFORM regintel.publication_fail(stored.parse_version_id=NEW.parse_version_id
            AND stored.normalized_value IS NOT DISTINCT FROM (quantity ->> 'normalized_value')::NUMERIC
            AND stored.raw_value=quantity ->> 'raw_value'
            AND stored.raw_unit IS NOT DISTINCT FROM quantity ->> 'raw_unit'
            AND stored.normalized_unit IS NOT DISTINCT FROM quantity ->> 'normalized_unit'
            AND stored.raw_currency IS NOT DISTINCT FROM quantity ->> 'raw_currency'
            AND stored.currency IS NOT DISTINCT FROM quantity ->> 'currency'
            AND stored.period_kind=quantity -> 'period' ->> 'kind'
            AND stored.start_date::TEXT IS NOT DISTINCT FROM quantity -> 'period' ->> 'start_date'
            AND stored.end_date::TEXT IS NOT DISTINCT FROM quantity -> 'period' ->> 'end_date'
            AND stored.instant_date::TEXT IS NOT DISTINCT FROM quantity -> 'period' ->> 'instant_date'
            AND stored.raw_period_label IS NOT DISTINCT FROM quantity -> 'period' ->> 'raw_label'
            AND stored.basis=quantity ->> 'basis'
            AND stored.raw_basis_label IS NOT DISTINCT FROM quantity ->> 'raw_basis_label'
            AND stored.denominator IS NOT DISTINCT FROM quantity ->> 'denominator'
            AND stored.stake_kind IS NOT DISTINCT FROM quantity ->> 'stake_kind'
            AND stored.ownership_date::TEXT IS NOT DISTINCT FROM quantity ->> 'ownership_date'
            AND (SELECT coalesce(jsonb_agg(evidence_id::TEXT ORDER BY evidence_id),'[]'::JSONB)
                FROM regintel.quantitative_context_evidence WHERE context_id=expected_context)=
                    (SELECT jsonb_agg(id ORDER BY id) FROM jsonb_array_elements(quantity -> 'evidence_ids') id),
            'Accepted quantity must retain its complete exact validated Decimal context');
    END IF;
    RETURN NEW;
EXCEPTION WHEN no_data_found OR too_many_rows THEN
    RAISE EXCEPTION 'Authoritative inserts require a matching approved publication transaction'
        USING ERRCODE='23514';
END; $$;
DO $$ DECLARE target TEXT; BEGIN
    FOREACH target IN ARRAY ARRAY['corpus_versions','acceptance_audits','fact_observations','relation_observations'] LOOP
        EXECUTE format('DROP TRIGGER later_authority_gate ON regintel.%I',target);
        EXECUTE format('CREATE TRIGGER publication_authority_gate BEFORE INSERT ON regintel.%I '
            'FOR EACH ROW EXECUTE FUNCTION regintel.require_publication_authority()',target);
    END LOOP;
END; $$;
CREATE TRIGGER publication_observation_gate BEFORE INSERT ON regintel.publication_observations
    FOR EACH ROW EXECUTE FUNCTION regintel.require_publication_authority();

CREATE FUNCTION regintel.update_publication_state() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' THEN PERFORM regintel.publication_fail(FALSE,'Published history cannot be deleted'); END IF;
    IF TG_TABLE_NAME='corpus_versions' THEN
        PERFORM regintel.publication_fail(OLD.state='BUILDING' AND NEW.state='PUBLISHED'
            AND to_jsonb(OLD)-'state'=to_jsonb(NEW)-'state'
            AND EXISTS (SELECT 1 FROM regintel.publication_commits WHERE corpus_version_id=NEW.id
                AND creation_transaction=txid_current()), 'Only an atomic publication can seal a corpus');
    ELSE
        PERFORM regintel.publication_fail(EXISTS (SELECT 1 FROM regintel.publication_commits c
            JOIN regintel.corpus_versions v ON v.id=c.corpus_version_id AND v.state='PUBLISHED'
            WHERE c.corpus_version_id=NEW.corpus_version_id AND c.creation_transaction=txid_current()
                AND c.parent_corpus_version_id IS NOT DISTINCT FROM
                    (SELECT corpus_version_id FROM regintel.publication_head)),
            'Published head must follow the approved parent');
    END IF;
    RETURN NEW;
END; $$;
DROP TRIGGER immutable_rows ON regintel.corpus_versions;
CREATE TRIGGER controlled_publication_state BEFORE UPDATE OR DELETE ON regintel.corpus_versions
    FOR EACH ROW EXECUTE FUNCTION regintel.update_publication_state();
CREATE TRIGGER controlled_publication_head BEFORE INSERT OR UPDATE OR DELETE ON regintel.publication_head
    FOR EACH ROW EXECUTE FUNCTION regintel.update_publication_state();
CREATE FUNCTION regintel.complete_publication_commit() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE manifest JSONB; observation JSONB;
BEGIN
    manifest := regintel.publication_manifest(NEW.corpus_version_id);
    PERFORM regintel.publication_fail(EXISTS (SELECT 1 FROM regintel.corpus_versions
        WHERE id=NEW.corpus_version_id AND state='PUBLISHED') AND EXISTS (SELECT 1 FROM regintel.publication_head
        WHERE corpus_version_id=NEW.corpus_version_id), 'Publication head and state must commit atomically');
    FOR observation IN SELECT a -> 'observation' FROM jsonb_array_elements(manifest -> 'new_acceptances') a LOOP
        PERFORM regintel.publication_fail(EXISTS (SELECT 1 FROM regintel.publication_observations
            WHERE id=(observation ->> 'id')::UUID) AND EXISTS (SELECT 1 FROM regintel.acceptance_audits
            WHERE id=(observation ->> 'acceptance_audit_id')::UUID)
            AND (CASE WHEN observation ->> 'kind'='relation' THEN EXISTS
                (SELECT 1 FROM regintel.relation_observations WHERE id=(observation ->> 'id')::UUID)
                ELSE EXISTS (SELECT 1 FROM regintel.fact_observations WHERE id=(observation ->> 'id')::UUID) END),
            'Published authority must commit every approved observation and audit');
    END LOOP;
    RETURN NULL;
END; $$;
CREATE CONSTRAINT TRIGGER publication_commit_complete AFTER INSERT ON regintel.publication_commits
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION regintel.complete_publication_commit();
DO $$ DECLARE target TEXT; BEGIN
    FOREACH target IN ARRAY ARRAY['publication_builds','publication_retrieval','retrieval_chunks',
        'publication_graph_receipts','publication_commits','publication_observations'] LOOP
        EXECUTE format('CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.%I '
            'FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation()',target);
        EXECUTE format('CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.%I '
            'FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation()',target);
    END LOOP;
END; $$;
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.publication_head
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE FUNCTION regintel.control_retrieval_rebuild() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE' AND EXISTS (SELECT 1 FROM regintel.retrieval_rebuilds
        WHERE corpus_version_id=OLD.corpus_version_id AND creation_transaction=txid_current()) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Retrieval rows require an audited atomic rebuild' USING ERRCODE='23514';
END; $$;
DROP TRIGGER immutable_rows ON regintel.retrieval_chunks;
CREATE TRIGGER controlled_retrieval_rebuild BEFORE UPDATE OR DELETE ON regintel.retrieval_chunks
    FOR EACH ROW EXECUTE FUNCTION regintel.control_retrieval_rebuild();
CREATE FUNCTION regintel.complete_retrieval_rebuild() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM regintel.publication_fail((SELECT chunk_count FROM regintel.publication_retrieval
        WHERE corpus_version_id=NEW.corpus_version_id)=(SELECT count(*) FROM regintel.retrieval_chunks
        WHERE corpus_version_id=NEW.corpus_version_id), 'Rebuilt retrieval projection must be complete atomically');
    RETURN NULL;
END; $$;
CREATE CONSTRAINT TRIGGER retrieval_rebuild_complete AFTER INSERT ON regintel.retrieval_rebuilds
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION regintel.complete_retrieval_rebuild();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.retrieval_rebuilds
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.retrieval_rebuilds
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

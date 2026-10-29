-- Native numerical proposals join the existing atomic corpus/head transaction.
-- Immutable legacy manifests/observations remain readable without rewriting bytes.
ALTER TABLE regintel.publication_observations
    DROP CONSTRAINT publication_observations_candidate_id_fkey;

CREATE TABLE regintel.native_publication_audits (
    id regintel.canonical_id PRIMARY KEY,
    observation_id regintel.canonical_id NOT NULL UNIQUE,
    candidate_id regintel.canonical_id NOT NULL UNIQUE REFERENCES regintel.numerical_candidates(id),
    acceptance_id regintel.canonical_id NOT NULL REFERENCES regintel.numerical_acceptances(id),
    corpus_version_id regintel.canonical_id NOT NULL REFERENCES regintel.publication_commits(corpus_version_id),
    snapshot_bytes BYTEA NOT NULL CHECK (octet_length(snapshot_bytes) BETWEEN 1 AND 32000000),
    snapshot_sha256 regintel.sha256_hash NOT NULL,
    published_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version INTEGER NOT NULL CHECK (auth_version>0),
    published_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION regintel.native_publication_phrase(proof JSONB,role_name TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
    SELECT string_agg(w#>>'{evidence,span,quote}',' ' ORDER BY pi,wi)
    FROM jsonb_array_elements(proof->'phrases') WITH ORDINALITY p(phrase,pi),
         jsonb_array_elements(phrase->'words') WITH ORDINALITY word(w,wi)
    WHERE phrase->>'role'=role_name;
$$;

CREATE FUNCTION regintel.native_publication_snapshot(snapshot JSONB) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE observation JSONB; accepted JSONB; prepared JSONB; proposed JSONB; proof JSONB;
    decision JSONB; retained JSONB; quantity JSONB; supports JSONB; packet JSONB; span JSONB;
    candidate regintel.numerical_candidates; acceptance regintel.numerical_acceptances;
BEGIN
    observation:=snapshot->'observation';
    SELECT * INTO STRICT candidate FROM regintel.numerical_candidates WHERE id=(observation->>'candidate_id')::uuid;
    SELECT n.* INTO STRICT acceptance FROM regintel.numerical_acceptances n
        WHERE n.id=(observation->>'native_acceptance_id')::uuid AND n.candidate_id=candidate.id AND n.decision='ACCEPT';
    prepared:=convert_from(candidate.preparation_bytes,'UTF8')::jsonb;
    proposed:=prepared->'proposed_input'; proof:=proposed->'proof';
    decision:=convert_from(acceptance.record_bytes,'UTF8')::jsonb;
    accepted:=jsonb_build_object('record',decision,'candidate',jsonb_build_object(
        'record',convert_from(candidate.record_bytes,'UTF8')::jsonb,'preparation',prepared));
    SELECT convert_from(input_bytes,'UTF8')::jsonb INTO STRICT packet
        FROM regintel.bound_numerical_gate_runs WHERE id=candidate.gate_run_id;
    PERFORM regintel.publication_fail(regintel.entity_json_keys(snapshot,ARRAY['kind','observation','accepted','fresh_preparation'])
        AND snapshot->>'kind'='NATIVE_NUMERICAL' AND snapshot->'accepted'=accepted
        AND snapshot->'fresh_preparation'=prepared AND prepared->>'state'='READY_FOR_ADAPTER'
        AND decision->>'state'='ACCEPTED_UNPUBLISHED'
        AND decision->'checks'=prepared->'checks'
        AND NOT EXISTS(SELECT FROM jsonb_array_elements(prepared->'checks') c WHERE c->>'state'<>'PASS')
        AND NOT EXISTS(SELECT FROM regintel.candidates WHERE id=candidate.id),
        'Native publication requires the exact immutable accepted proposal and fresh checks');
    SELECT jsonb_agg(s ORDER BY s->>'evidence_id') INTO supports FROM (
        SELECT DISTINCT jsonb_build_object('evidence_id',w#>'{evidence,id}','start',0,
            'end',w#>'{evidence,span,end}','quote',w#>'{evidence,span,quote}') AS s
        FROM jsonb_array_elements(proof->'phrases') p,
             jsonb_array_elements(p->'words') w) exact_words;
    retained:=proposed->'quantity';
    quantity:=jsonb_build_object('raw_value',retained->'raw_value','normalized_value',retained->'normalized_value',
        'raw_unit',regintel.native_publication_phrase(proof,'unit_header'),'normalized_unit',retained->'normalized_unit',
        'raw_currency',substring(regintel.native_publication_phrase(proof,'unit_header') FROM '(?i)(INR|USD|₹|Rs\.)'),
        'currency',retained->'currency','period',retained->'period',
        'basis',retained->'basis','raw_basis_label',regintel.native_publication_phrase(proof,'basis_context'),
        'denominator',NULL,'stake_kind',NULL,'ownership_date',NULL,'evidence_ids',proposed#>'{gate,evidence_ids}');
    PERFORM regintel.publication_fail(regintel.entity_json_keys(observation,ARRAY[
        'id','acceptance_audit_id','first_corpus_version_id','candidate_id','candidate_run_id',
        'parse_version_id','filing_version_id','validation_run_id','validation_input_sha256',
        'validator_configuration_sha256','review_id','kind','subject_entity_id','object_entity_id',
        'relation_type','metric_id','raw_text','quantity','supports','context_supports','source_published_on',
        'schema_version','native_acceptance_id','proof'])
        AND observation->>'schema_version'='native-numerical-observation-1'
        AND observation->>'id'=regintel.candidate_stable_id('published-observation:'||candidate.id::text)::text
        AND observation->>'acceptance_audit_id'=regintel.candidate_stable_id('acceptance:'||(observation->>'id'))::text
        AND observation->>'candidate_run_id'=candidate.gate_run_id::text
        AND observation->>'parse_version_id'=candidate.parse_version_id::text
        AND observation->'filing_version_id'=proof->'filing_version_id'
        AND observation->>'validation_run_id'=acceptance.id::text
        AND observation->'validation_input_sha256'=prepared->'gate_input_sha256'
        AND observation->>'validator_configuration_sha256'=acceptance.configuration_sha256
        AND observation->>'review_id'=acceptance.id::text
        AND observation->>'kind'='numeric_fact'
        AND observation->'subject_entity_id'=proposed->'subject_entity_id'
        AND observation->'object_entity_id'='null'::jsonb AND observation->'relation_type'='null'::jsonb
        AND observation->'metric_id'=proposed#>'{metric,id}'
        AND observation->'raw_text'=retained->'raw_value'
        AND observation->'quantity'=quantity AND observation->'supports'=supports
        AND observation->'context_supports'='[]'::jsonb AND observation->'proof'=proof,
        'Native published quantity, proof, source or run identity differs');
    PERFORM regintel.publication_fail(EXISTS(SELECT FROM regintel.filing_versions f
        WHERE f.id=(proof->>'filing_version_id')::uuid AND to_jsonb(f.published_on::text)
            IS NOT DISTINCT FROM nullif(observation->'source_published_on','null'::jsonb)),
        'Native publication retains the actual immutable source date');
    PERFORM regintel.publication_fail((SELECT count(*) FROM regintel.entity_registrations)=
        (packet#>>'{current_context,registry,revision}')::bigint
        AND EXISTS(SELECT FROM regintel.entity_registrations e
            JOIN jsonb_array_elements(packet#>'{current_context,registry,entities}') item
                ON e.id=(item->>'id')::uuid AND convert_from(e.registration_bytes,'UTF8')::jsonb=item
            WHERE e.id=(proposed->>'subject_entity_id')::uuid)
        AND EXISTS(SELECT FROM regintel.metric_definitions m WHERE m.id=(proposed#>>'{metric,id}')::uuid
            AND convert_from(m.definition_bytes,'UTF8')::jsonb=proposed->'metric')
        AND EXISTS(SELECT FROM regintel.numeric_metric_policies p WHERE p.id=(proposed#>>'{policy,id}')::uuid
            AND convert_from(p.policy_bytes,'UTF8')::jsonb=proposed->'policy'),
        'Native publication cannot bypass changed approval context');
    FOR span IN SELECT jsonb_array_elements(supports) LOOP
        PERFORM regintel.candidate_span(span,candidate.parse_version_id);
    END LOOP;
EXCEPTION WHEN no_data_found OR too_many_rows THEN
    RAISE EXCEPTION 'Native publication requires exact stored source membership' USING ERRCODE='23514';
END;
$$;

ALTER FUNCTION regintel.publication_snapshot(JSONB,JSONB) RENAME TO publication_legacy_snapshot;
CREATE FUNCTION regintel.publication_snapshot(acceptance JSONB,configuration JSONB)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    IF acceptance->>'kind'='NATIVE_NUMERICAL' THEN
        PERFORM regintel.native_publication_snapshot(acceptance);
    ELSE
        PERFORM regintel.publication_legacy_snapshot(acceptance,configuration);
    END IF;
END;
$$;

CREATE FUNCTION regintel.guard_native_publication_audit() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE manifest JSONB; snapshot JSONB; observation JSONB; actor UUID;
BEGIN
    PERFORM regintel.entity_admin(NEW.published_by,NEW.auth_version);
    SELECT regintel.publication_manifest(c.corpus_version_id),c.published_by INTO STRICT manifest,actor
        FROM regintel.publication_commits c WHERE c.corpus_version_id=NEW.corpus_version_id
        AND c.creation_transaction=txid_current();
    SELECT a INTO STRICT snapshot FROM jsonb_array_elements(manifest->'new_acceptances') a
        WHERE a#>>'{observation,id}'=NEW.observation_id::text AND a->>'kind'='NATIVE_NUMERICAL';
    observation:=snapshot->'observation';
    PERFORM regintel.native_publication_snapshot(snapshot);
    PERFORM regintel.publication_fail(NEW.published_by=actor
        AND convert_from(NEW.snapshot_bytes,'UTF8')=regintel.candidate_canonical_json(snapshot)
        AND encode(sha256(NEW.snapshot_bytes),'hex')=NEW.snapshot_sha256
        AND NEW.id::text=observation->>'acceptance_audit_id'
        AND NEW.candidate_id::text=observation->>'candidate_id'
        AND NEW.acceptance_id::text=observation->>'native_acceptance_id'
        AND NEW.corpus_version_id::text=observation->>'first_corpus_version_id',
        'Native audit must be part of the exact approved publication transaction');
    NEW.published_at:=clock_timestamp(); RETURN NEW;
EXCEPTION WHEN no_data_found OR too_many_rows THEN
    RAISE EXCEPTION 'Native audit requires an approved publication transaction' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER native_publication_audit_guard BEFORE INSERT ON regintel.native_publication_audits
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_native_publication_audit();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.native_publication_audits
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.native_publication_audits
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

CREATE OR REPLACE FUNCTION regintel.complete_publication_commit() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE manifest JSONB; observation JSONB;
BEGIN
    manifest:=regintel.publication_manifest(NEW.corpus_version_id);
    PERFORM regintel.publication_fail(EXISTS(SELECT FROM regintel.corpus_versions WHERE id=NEW.corpus_version_id AND state='PUBLISHED')
        AND EXISTS(SELECT FROM regintel.publication_head WHERE corpus_version_id=NEW.corpus_version_id),
        'Publication head and state must commit atomically');
    FOR observation IN SELECT a->'observation' FROM jsonb_array_elements(manifest->'new_acceptances') a LOOP
        PERFORM regintel.publication_fail(EXISTS(SELECT FROM regintel.publication_observations WHERE id=(observation->>'id')::uuid)
            AND CASE WHEN observation->>'schema_version'='native-numerical-observation-1' THEN EXISTS(
                SELECT FROM regintel.native_publication_audits WHERE id=(observation->>'acceptance_audit_id')::uuid
                    AND observation_id=(observation->>'id')::uuid AND corpus_version_id=NEW.corpus_version_id)
            ELSE EXISTS(SELECT FROM regintel.acceptance_audits WHERE id=(observation->>'acceptance_audit_id')::uuid)
                AND CASE WHEN observation->>'kind'='relation' THEN EXISTS(SELECT FROM regintel.relation_observations WHERE id=(observation->>'id')::uuid)
                ELSE EXISTS(SELECT FROM regintel.fact_observations WHERE id=(observation->>'id')::uuid) END END,
            'Publication must atomically commit each native or legacy observation and audit');
    END LOOP;
    RETURN NULL;
END;
$$;

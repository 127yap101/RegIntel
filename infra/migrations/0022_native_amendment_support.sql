-- Ordered native amendment support preserves every original span and sealed position.
-- Reconstructed text is used only for deterministic inspection, never stored as a quote.
CREATE FUNCTION regintel.publication_sentence_end(value TEXT) RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE AS $$
    WITH normal AS (SELECT rtrim(regexp_replace(value,'[[:space:]]+$',''), $q$"'”’)]$q$) AS terminal)
    SELECT coalesce(terminal ~ '[.!?]$' AND lower(terminal) <> ALL
        (ARRAY['rs.','mr.','mrs.','dr.','no.','nos.','ltd.','co.','e.g.','i.e.']),FALSE) FROM normal;
$$;

CREATE FUNCTION regintel.publication_native_word(span JSONB,expected_parse UUID)
RETURNS JSONB LANGUAGE plpgsql STABLE AS $$
DECLARE original RECORD; block JSONB; previous JSONB; word_index BIGINT; matches INTEGER;
BEGIN
    PERFORM regintel.candidate_span(span,expected_parse);
    SELECT e.*,convert_from(a.artifact_bytes,'UTF8')::JSONB AS artifact,
        convert_from(a.configuration_bytes,'UTF8')::JSONB AS configuration INTO STRICT original
        FROM regintel.evidence e JOIN regintel.parse_artifacts a ON a.parse_version_id=e.parse_version_id
        WHERE e.id=(span ->> 'evidence_id')::UUID AND e.parse_version_id=expected_parse;
    IF original.configuration ->> 'schema_version' IS DISTINCT FROM '1.1.0'
        OR original.configuration ->> 'adapter_name' IS DISTINCT FROM 'regintel-native-context'
        OR original.artifact #>> '{provenance,adapter_name}' IS DISTINCT FROM 'regintel-native-context' THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO matches FROM jsonb_array_elements(original.artifact -> 'blocks') b
        WHERE b ->> 'id'=original.block_id::TEXT;
    PERFORM regintel.publication_fail(matches=1,'Amendment support needs one sealed original block');
    SELECT b INTO STRICT block FROM jsonb_array_elements(original.artifact -> 'blocks') b
        WHERE b ->> 'id'=original.block_id::TEXT;
    IF block ->> 'source_ref' IS DISTINCT FROM
            'page/'||(block ->> 'page_index')||'/text-cell/'||(block ->> 'source_cell_index') THEN
        RETURN NULL;
    END IF;
    word_index:=(block ->> 'source_cell_index')::BIGINT;
    SELECT count(*) INTO matches FROM jsonb_array_elements(original.artifact -> 'blocks') b
        WHERE b ->> 'page_id'=block ->> 'page_id' AND b -> 'source_cell_index'=block -> 'source_cell_index'
            AND b ->> 'source_ref'='page/'||(b ->> 'page_index')||'/text-cell/'||(b ->> 'source_cell_index');
    PERFORM regintel.publication_fail(matches=1,'Native original-word positions must be unambiguous');
    SELECT count(*) INTO matches FROM jsonb_array_elements(original.artifact -> 'blocks') b
        WHERE b ->> 'page_id'=block ->> 'page_id' AND (b ->> 'source_cell_index')::BIGINT=word_index-1
            AND b ->> 'source_ref'='page/'||(b ->> 'page_index')||'/text-cell/'||(b ->> 'source_cell_index');
    PERFORM regintel.publication_fail(matches<=1,'Native predecessor position must be unambiguous');
    SELECT b INTO previous FROM jsonb_array_elements(original.artifact -> 'blocks') b
        WHERE b ->> 'page_id'=block ->> 'page_id' AND (b ->> 'source_cell_index')::BIGINT=word_index-1
            AND b ->> 'source_ref'='page/'||(b ->> 'page_index')||'/text-cell/'||(b ->> 'source_cell_index');
    RETURN jsonb_build_object('page_id',original.page_id,'index',word_index,
        'previous',CASE WHEN previous -> 'from_ocr'='false'::JSONB THEN previous -> 'orig' ELSE NULL END,
        'whole',block -> 'from_ocr'='false'::JSONB AND block ->> 'orig'=original.quote
            AND block ->> 'page_id'=original.page_id::TEXT
            AND original.start_offset=0 AND original.end_offset=char_length(original.quote)
            AND (span ->> 'start')::BIGINT=0 AND (span ->> 'end')::BIGINT=original.end_offset);
END; $$;

CREATE FUNCTION regintel.publication_support_text(support JSONB,expected_parse UUID,statement BOOLEAN DEFAULT FALSE)
RETURNS TEXT LANGUAGE plpgsql STABLE AS $$
DECLARE span JSONB; position JSONB; first_position JSONB; last_span JSONB; counter INTEGER:=0;
        inspection_text TEXT:=''; original RECORD; before_text TEXT; after_text TEXT;
BEGIN
    IF support ? 'schema_version' THEN
        PERFORM regintel.publication_fail(regintel.entity_json_keys(support,
            ARRAY['schema_version','parse_version_id','spans'])
            AND support ->> 'schema_version'='native-amendment-words-1'
            AND regintel.candidate_uuid(support -> 'parse_version_id')
            AND support ->> 'parse_version_id'=expected_parse::TEXT
            AND jsonb_typeof(support -> 'spans')='array'
            AND jsonb_array_length(support -> 'spans') BETWEEN 1 AND 128,
            'Native amendment support requires its selected parse and bounded words');
        PERFORM regintel.publication_fail((SELECT count(DISTINCT s ->> 'evidence_id')
            FROM jsonb_array_elements(support -> 'spans') s)=jsonb_array_length(support -> 'spans'),
            'Native amendment words must retain distinct source identities');
        FOR span IN SELECT jsonb_array_elements(support -> 'spans') LOOP
            position:=regintel.publication_native_word(span,expected_parse);
            PERFORM regintel.publication_fail(position IS NOT NULL AND position -> 'whole'='true'::JSONB,
                'Native amendment words require complete exact original spans');
            IF counter=0 THEN first_position:=position; END IF;
            PERFORM regintel.publication_fail(position -> 'page_id'=first_position -> 'page_id'
                AND (position ->> 'index')::BIGINT=(first_position ->> 'index')::BIGINT+counter,
                'Native amendment words cannot skip context or change order/page');
            inspection_text:=inspection_text||CASE WHEN counter=0 THEN '' ELSE ' ' END||(span ->> 'quote');
            counter:=counter+1; last_span:=span;
        END LOOP;
        PERFORM regintel.publication_fail(char_length(inspection_text)<=20127,
            'Native amendment words exceed their exact text budget');
        PERFORM regintel.publication_fail((SELECT sum(char_length(s ->> 'quote'))
            FROM jsonb_array_elements(support -> 'spans') s)<=20000,
            'Native amendment words exceed their source text budget');
        IF statement THEN
            PERFORM regintel.publication_fail(((first_position ->> 'index')::BIGINT=0
                OR regintel.publication_sentence_end(first_position ->> 'previous'))
                AND regintel.publication_sentence_end(last_span ->> 'quote'),
                'Native effect support needs complete sentence boundaries');
        END IF;
        RETURN inspection_text;
    END IF;
    PERFORM regintel.candidate_span(support,expected_parse);
    IF statement THEN
        position:=regintel.publication_native_word(support,expected_parse);
        IF position IS NOT NULL THEN
            PERFORM regintel.publication_fail(position -> 'whole'='true'::JSONB
                AND ((position ->> 'index')::BIGINT=0
                    OR regintel.publication_sentence_end(position ->> 'previous'))
                AND regintel.publication_sentence_end(support ->> 'quote'),
                'An isolated native word cannot conceal effect context');
        ELSE
            SELECT e.* INTO STRICT original FROM regintel.evidence e
                WHERE e.id=(support ->> 'evidence_id')::UUID AND e.parse_version_id=expected_parse;
            before_text:=regexp_replace(left(original.quote,
                ((support ->> 'start')::BIGINT-original.start_offset)::INTEGER),'[[:space:]]+$','');
            after_text:=substr(original.quote,((support ->> 'end')::BIGINT-original.start_offset+1)::INTEGER);
            PERFORM regintel.publication_fail((before_text='' OR regintel.publication_sentence_end(
                regexp_replace(before_text,'^.*[[:space:]]','')))
                AND (regexp_replace(after_text,'[[:space:]]','','g')='' OR (regintel.publication_sentence_end(support ->> 'quote')
                    AND after_text ~ '^[[:space:]]')), 'Effect support cannot omit its sentence context');
        END IF;
    END IF;
    RETURN support ->> 'quote';
END; $$;

CREATE FUNCTION regintel.publication_support_contains(whole JSONB,part JSONB)
RETURNS BOOLEAN LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE outside JSONB; inside JSONB; start_at INTEGER; offset_at INTEGER; matched BOOLEAN;
BEGIN
    outside:=CASE WHEN whole ? 'schema_version' THEN whole -> 'spans' ELSE jsonb_build_array(whole) END;
    IF part ? 'schema_version' THEN
        IF NOT whole ? 'schema_version' OR whole -> 'parse_version_id'<>part -> 'parse_version_id' THEN RETURN FALSE; END IF;
        inside:=part -> 'spans';
        FOR start_at IN 0..jsonb_array_length(outside)-1 LOOP
            matched:=TRUE;
            FOR offset_at IN 0..jsonb_array_length(inside)-1 LOOP
                IF outside -> (start_at+offset_at) IS DISTINCT FROM inside -> offset_at THEN matched:=FALSE; EXIT; END IF;
            END LOOP;
            IF matched THEN RETURN TRUE; END IF;
        END LOOP;
        RETURN FALSE;
    END IF;
    RETURN EXISTS (SELECT 1 FROM jsonb_array_elements(outside) s
        WHERE s -> 'evidence_id'=part -> 'evidence_id'
            AND (s ->> 'start')::BIGINT<=(part ->> 'start')::BIGINT
            AND (s ->> 'end')::BIGINT>=(part ->> 'end')::BIGINT);
END; $$;

-- Existing operation, history, ownership and active-set checks retained.
CREATE OR REPLACE FUNCTION regintel.publication_amendments(request JSONB, manifest JSONB, parent JSONB)
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
            AND lower(regintel.publication_support_text(link -> 'parent_identity',(old_filing ->> 'parse_version_id')::UUID))=ANY(names)
            AND lower(regintel.publication_support_text(link -> 'child_identity',(filing ->> 'parse_version_id')::UUID))=ANY(names)
            AND ((link ->> 'lineage_type'='ADDENDUM_TO' AND filing ->> 'document_type'='ADDENDUM')
                OR (link ->> 'lineage_type'='CORRIGENDUM_TO' AND filing ->> 'document_type' IN ('CORRIGENDUM','ADDENDUM'))
                OR link ->> 'lineage_type'='AMENDS')
            AND EXISTS (SELECT 1 FROM regintel.filing_versions f WHERE f.id=(filing ->> 'filing_version_id')::UUID
                AND (f.declared_parent_filing_version_id IS NULL OR
                    f.declared_parent_filing_version_id=(old_filing ->> 'filing_version_id')::UUID)),
            'Lineage requires the matching approved issuer and explicit original parent');
        PERFORM regintel.publication_fail(EXISTS (SELECT 1 FROM unnest(CASE old_filing ->> 'document_type'
            WHEN 'DRHP' THEN ARRAY['draft red herring prospectus','drhp']
            WHEN 'RHP' THEN ARRAY['red herring prospectus','rhp'] WHEN 'PROSPECTUS' THEN ARRAY['prospectus']
            WHEN 'ADDENDUM' THEN ARRAY['addendum'] ELSE ARRAY['corrigendum'] END) label
            WHERE position(label in lower(regintel.publication_support_text(link -> 'parent_reference',
                (filing ->> 'parse_version_id')::UUID)))>0),'Child source must explicitly identify its reviewed parent document');
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
            wording:=wording||' '||lower(regintel.publication_support_text(span,child_parse,TRUE));
        END LOOP;
        cue:=CASE operation WHEN 'ADD' THEN '\m(add(ed|ition|itional)?|include[ds]?)\M'
            WHEN 'CORRECT' THEN '\m(correct(ed|ion)?|amend(ed|ment)?|revis(ed|ion))\M'
            WHEN 'SUPPLEMENT' THEN '\m(supplement(ed|al|ation)?|addition(al)?|also)\M'
            WHEN 'SUPERSEDE' THEN '\m(supersed(e[ds]?|ing)|replac(e[ds]?|ement)|substitut(ed|ion))\M'
            ELSE '\m(remov(ed|al)|delet(ed|ion)|omitted|withdrawn)\M' END;
        PERFORM regintel.publication_fail(wording~cue AND wording!~'\m(not|never|no|propos(e[ds]?|ing)|may|might|could|would|expects?|expected|intends?|intended|plans?|planned|if|unless|subject to|conditional|provided|except)\M',
            'Source wording must explicitly support the reviewed effect');
        PERFORM regintel.publication_fail(regintel.validation_date(effect -> 'effective_date',TRUE)
            AND (effect -> 'effective_date'='null'::JSONB)=(effect -> 'effective_date_support'='null'::JSONB), 'Effect date requires support');
        IF effect -> 'effective_date'<>'null'::JSONB THEN
            span:=effect -> 'effective_date_support';
            supported_date:=lower(regexp_replace(btrim(regintel.publication_support_text(span,child_parse)),'[.]$',''));
            PERFORM regintel.publication_fail(EXISTS (SELECT 1 FROM jsonb_array_elements(effect -> 'supports') s
                WHERE regintel.publication_support_contains(s,span))
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

-- Existing build guard retained; only amendment support calls are extended.
CREATE OR REPLACE FUNCTION regintel.validate_publication_build() RETURNS TRIGGER LANGUAGE plpgsql AS $$
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
        PERFORM regintel.publication_support_text(item -> 'parent_identity', (SELECT id FROM regintel.parse_versions
            WHERE filing_version_id=(item ->> 'parent_filing_version_id')::UUID
                AND id::TEXT IN (SELECT f ->> 'parse_version_id' FROM jsonb_array_elements(manifest -> 'filings') f)));
        FOR selected IN SELECT value FROM jsonb_each(item) WHERE key IN ('child_identity','parent_reference') LOOP
            PERFORM regintel.publication_support_text(selected, (SELECT id FROM regintel.parse_versions
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
            PERFORM regintel.publication_support_text(selected,(SELECT p.id FROM regintel.parse_versions p
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

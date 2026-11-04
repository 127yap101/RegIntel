-- Versioned company identity support retains each exact native word separately.
-- Legacy registration JSON/guard and every historical row remain unchanged.
CREATE FUNCTION regintel.entity_native_words(support JSONB) RETURNS TEXT
LANGUAGE plpgsql STABLE AS $$
DECLARE span JSONB; actual JSONB; first_position JSONB; counter INTEGER:=0;
        inspection TEXT:=''; total INTEGER:=0; selected UUID;
BEGIN
    IF NOT regintel.entity_json_keys(support,ARRAY['schema_version','parse_version_id','spans'])
        OR support ->> 'schema_version' IS DISTINCT FROM 'native-entity-words-1'
        OR NOT regintel.candidate_uuid(support -> 'parse_version_id')
        OR jsonb_typeof(support -> 'spans') IS DISTINCT FROM 'array'
        OR jsonb_array_length(support -> 'spans') NOT BETWEEN 1 AND 128
        OR (SELECT count(DISTINCT item ->> 'evidence_id')
            FROM jsonb_array_elements(support -> 'spans') item)
            IS DISTINCT FROM jsonb_array_length(support -> 'spans') THEN
        RAISE EXCEPTION 'Native entity support requires explicit bounded original words'
            USING ERRCODE='23514';
    END IF;
    selected:=(support ->> 'parse_version_id')::UUID;
    FOR span IN SELECT jsonb_array_elements(support -> 'spans') LOOP
        PERFORM regintel.entity_anchor(span,selected);
        actual:=regintel.publication_native_word(span,selected);
        IF actual IS NULL OR actual -> 'whole' IS DISTINCT FROM 'true'::JSONB THEN
            RAISE EXCEPTION 'Native entity support requires whole sealed native words'
                USING ERRCODE='23514';
        END IF;
        IF counter=0 THEN first_position:=actual; END IF;
        IF actual -> 'page_id' IS DISTINCT FROM first_position -> 'page_id'
            OR (actual ->> 'index')::BIGINT IS DISTINCT FROM
                (first_position ->> 'index')::BIGINT+counter
            OR btrim(span ->> 'quote')='' THEN
            RAISE EXCEPTION 'Native entity support cannot omit/reorder words or change source page'
                USING ERRCODE='23514';
        END IF;
        total:=total+char_length(span ->> 'quote');
        inspection:=inspection||CASE WHEN counter=0 THEN '' ELSE ' ' END||(span ->> 'quote');
        counter:=counter+1;
    END LOOP;
    IF total>2048 THEN
        RAISE EXCEPTION 'Native identity support exceeds its text budget' USING ERRCODE='23514';
    END IF;
    RETURN inspection;
END; $$;

CREATE FUNCTION regintel.validate_native_company_registration() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
DECLARE payload JSONB; name_support JSONB; heading JSONB; identifier JSONB;
        company_name TEXT; identity_text TEXT; tail TEXT;
BEGIN
    PERFORM pg_advisory_xact_lock(5928237198818004551);
    PERFORM regintel.entity_admin(NEW.registered_by,NEW.auth_version);
    payload:=convert_from(NEW.registration_bytes,'UTF8')::JSONB;
    IF NOT regintel.entity_json_keys(payload,ARRAY['schema_version','id','kind','legal_name',
            'legal_name_support','issuer_header','aliases','identifiers','review_note'])
        OR payload ->> 'schema_version' IS DISTINCT FROM 'native-company-registration-1'
        OR encode(sha256(NEW.registration_bytes),'hex') IS DISTINCT FROM NEW.registration_sha256
        OR payload ->> 'id' IS DISTINCT FROM NEW.id::TEXT
        OR payload ->> 'kind' IS DISTINCT FROM 'COMPANY'
        OR jsonb_typeof(payload -> 'legal_name') IS DISTINCT FROM 'string'
        OR char_length(payload ->> 'legal_name') NOT BETWEEN 1 AND 256
        OR payload ->> 'legal_name' !~ '[[:alnum:]]'
        OR jsonb_typeof(payload -> 'aliases') IS DISTINCT FROM 'array'
        OR jsonb_array_length(payload -> 'aliases')<>0
        OR jsonb_typeof(payload -> 'identifiers') IS DISTINCT FROM 'array'
        OR jsonb_array_length(payload -> 'identifiers')<>1
        OR jsonb_typeof(payload -> 'review_note') IS DISTINCT FROM 'string'
        OR char_length(payload ->> 'review_note') NOT BETWEEN 1 AND 2000
        OR payload ->> 'review_note' ~ '^[[:space:]]*$' THEN
        RAISE EXCEPTION 'Native company registration requires an explicit bounded reviewed profile'
            USING ERRCODE='23514';
    END IF;
    name_support:=payload -> 'legal_name_support'; heading:=payload -> 'issuer_header';
    identifier:=payload -> 'identifiers' -> 0;
    company_name:=regintel.entity_native_words(name_support);
    identity_text:=regintel.entity_native_words(heading);
    IF NOT regintel.entity_json_keys(identifier,ARRAY['kind','value','support'])
        OR identifier ->> 'kind' IS DISTINCT FROM 'CIN'
        OR NOT regintel.valid_entity_identifier('CIN',identifier ->> 'value')
        OR identifier ->> 'value' IS DISTINCT FROM identifier -> 'support' ->> 'quote'
        OR name_support ->> 'parse_version_id' IS DISTINCT FROM heading ->> 'parse_version_id'
        OR company_name IS DISTINCT FROM payload ->> 'legal_name'
        OR heading -> 'spans' -> -1 IS DISTINCT FROM identifier -> 'support'
        OR jsonb_array_length(name_support -> 'spans')>=jsonb_array_length(heading -> 'spans') THEN
        RAISE EXCEPTION 'Native company name/CIN must retain their exact common heading'
            USING ERRCODE='23514';
    END IF;
    IF EXISTS(SELECT FROM jsonb_array_elements(name_support -> 'spans') WITH ORDINALITY item(value,ordinal)
        WHERE item.value IS DISTINCT FROM heading -> 'spans' -> (item.ordinal::INTEGER-1)) THEN
        RAISE EXCEPTION 'Native company name must be the original heading prefix' USING ERRCODE='23514';
    END IF;
    -- Use source text only for inspection: never store it as a combined source quotation.
    IF left(identity_text,char_length(company_name)+1) IS DISTINCT FROM company_name||' ' THEN
        RAISE EXCEPTION 'Native identity heading must start with its exact company name' USING ERRCODE='23514';
    END IF;
    tail:=substr(identity_text,char_length(company_name)+2);
    IF lower(tail COLLATE "C") IS DISTINCT FROM lower(('CORPORATE IDENTITY NUMBER: '||(identifier ->> 'value')) COLLATE "C")
        AND lower(tail COLLATE "C") IS DISTINCT FROM lower(('CIN: '||(identifier ->> 'value')) COLLATE "C") THEN
        RAISE EXCEPTION 'Native identity needs its complete explicit CIN heading' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END; $$;

DROP TRIGGER entity_registration_gate ON regintel.entity_registrations;
CREATE TRIGGER entity_registration_gate BEFORE INSERT ON regintel.entity_registrations
    FOR EACH ROW WHEN ((convert_from(NEW.registration_bytes,'UTF8')::JSONB ->> 'schema_version')
        IS DISTINCT FROM 'native-company-registration-1')
    EXECUTE FUNCTION regintel.validate_entity_registration();
CREATE TRIGGER native_company_registration_gate BEFORE INSERT ON regintel.entity_registrations
    FOR EACH ROW WHEN ((convert_from(NEW.registration_bytes,'UTF8')::JSONB ->> 'schema_version')
        = 'native-company-registration-1')
    EXECUTE FUNCTION regintel.validate_native_company_registration();

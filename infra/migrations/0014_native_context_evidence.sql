-- Native complete-source words plus explicitly scoped contextual evidence.
-- Legacy formats/guards remain selected for all existing sidecars.
ALTER TABLE regintel.parse_artifacts ADD COLUMN format_version TEXT NOT NULL DEFAULT '1.0.0'
    CHECK (format_version IN ('1.0.0','1.1.0'));
DROP TRIGGER validate_parse_artifact ON regintel.parse_artifacts;
CREATE TRIGGER validate_parse_artifact BEFORE INSERT ON regintel.parse_artifacts
    FOR EACH ROW WHEN (NEW.format_version='1.0.0')
    EXECUTE FUNCTION regintel.validate_parse_artifact();

CREATE TABLE regintel.native_parse_manifests (
    parse_version_id regintel.canonical_id PRIMARY KEY REFERENCES regintel.parse_versions(id),
    job_id regintel.canonical_id NOT NULL UNIQUE REFERENCES regintel.filing_jobs(id),
    manifest_bytes BYTEA NOT NULL CHECK (octet_length(manifest_bytes) BETWEEN 1 AND 2097152),
    manifest_sha256 regintel.sha256_hash NOT NULL,
    native_configuration_sha256 regintel.sha256_hash NOT NULL
);
CREATE TABLE regintel.native_parse_source_pages (
    parse_version_id regintel.canonical_id NOT NULL REFERENCES regintel.native_parse_manifests(parse_version_id),
    page_index regintel.safe_index NOT NULL CHECK (page_index < 2000),
    page_bytes BYTEA NOT NULL CHECK (octet_length(page_bytes) BETWEEN 1 AND 4194304),
    page_sha256 regintel.sha256_hash NOT NULL,
    word_count INTEGER NOT NULL CHECK (word_count BETWEEN 0 AND 20000),
    PRIMARY KEY (parse_version_id,page_index),
    FOREIGN KEY (parse_version_id,page_index) REFERENCES regintel.pages(parse_version_id,page_index)
);
CREATE TABLE regintel.native_parse_context_captures (
    parse_version_id regintel.canonical_id NOT NULL REFERENCES regintel.native_parse_manifests(parse_version_id),
    capture_id regintel.canonical_id NOT NULL REFERENCES regintel.numerical_page_captures(id),
    page_index regintel.safe_index NOT NULL CHECK (page_index < 2000),
    PRIMARY KEY (parse_version_id,page_index),
    UNIQUE (parse_version_id,capture_id),
    FOREIGN KEY (parse_version_id,page_index) REFERENCES regintel.pages(parse_version_id,page_index)
);
CREATE TABLE regintel.native_parse_table_sources (
    parse_version_id regintel.canonical_id NOT NULL,
    artifact_table_id regintel.canonical_id NOT NULL,
    capture_id regintel.canonical_id NOT NULL,
    PRIMARY KEY (parse_version_id,artifact_table_id),
    FOREIGN KEY (parse_version_id,capture_id)
        REFERENCES regintel.native_parse_context_captures(parse_version_id,capture_id)
);

CREATE FUNCTION regintel.guard_native_parse_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner RECORD; payload JSONB;
BEGIN
    SELECT p.*,s.sha256 AS source_sha FROM regintel.parse_versions p
        JOIN regintel.source_blobs s ON s.id=p.source_blob_id
        WHERE p.id=NEW.parse_version_id INTO owner;
    IF NOT FOUND OR owner.creation_transaction<>txid_current()
       OR owner.adapter_name<>'regintel-native-context' OR owner.adapter_version<>'1.0.0' THEN
        RAISE EXCEPTION 'Native source records belong to their parse creation transaction';
    END IF;
    IF TG_TABLE_NAME='native_parse_manifests' THEN
        payload:=convert_from(NEW.manifest_bytes,'UTF8')::jsonb;
        IF encode(sha256(NEW.manifest_bytes),'hex') IS DISTINCT FROM NEW.manifest_sha256
           OR payload->>'schema_version' IS DISTINCT FROM 'native-source-bank-1'
           OR payload->>'scope' IS DISTINCT FROM 'ALL_ORIGINAL_NATIVE_WORDS'
           OR payload->>'source_sha256' IS DISTINCT FROM owner.source_sha
           OR payload->'acceptance_eligible' IS DISTINCT FROM 'false'::jsonb
           OR jsonb_typeof(payload->'pages') IS DISTINCT FROM 'array'
           OR jsonb_array_length(payload->'pages') IS DISTINCT FROM owner.page_count
           OR (payload->>'source_page_count')::bigint IS DISTINCT FROM owner.page_count
           OR NOT EXISTS (SELECT FROM regintel.filing_jobs j WHERE j.id=NEW.job_id
               AND j.state='RUNNING' AND j.filing_version_id=owner.filing_version_id
               AND j.source_blob_id=owner.source_blob_id
               AND j.configuration_sha256=owner.configuration_sha256) THEN
            RAISE EXCEPTION 'Native manifest differs from the source job';
        END IF;
    ELSIF TG_TABLE_NAME='native_parse_source_pages' THEN
        payload:=convert_from(NEW.page_bytes,'UTF8')::jsonb;
        IF encode(sha256(NEW.page_bytes),'hex') IS DISTINCT FROM NEW.page_sha256
           OR payload->>'schema_version' IS DISTINCT FROM 'native-source-page-1'
           OR payload->>'source_sha256' IS DISTINCT FROM owner.source_sha
           OR jsonb_typeof(payload->'page_index') IS DISTINCT FROM 'number'
           OR (payload->>'page_index')::bigint IS DISTINCT FROM NEW.page_index
           OR jsonb_typeof(payload->'words') IS DISTINCT FROM 'array'
           OR jsonb_array_length(payload->'words') IS DISTINCT FROM NEW.word_count
           OR EXISTS (SELECT FROM jsonb_array_elements(payload->'words') WITH ORDINALITY w(item,n)
               WHERE jsonb_typeof(item->'index') IS DISTINCT FROM 'number'
               OR (item->>'index')::bigint<>n-1
               OR item->'from_ocr' IS DISTINCT FROM 'false'::jsonb
               OR item#>>'{raw_rectangle,coord_origin}' IS DISTINCT FROM 'BOTTOMLEFT'
               OR item#>>'{raw_rectangle,coordinate_frame}' IS DISTINCT FROM 'DOCLING_PAGE') THEN
            RAISE EXCEPTION 'Native page data differs from its receipt';
        END IF;
    ELSIF TG_TABLE_NAME='native_parse_context_captures' THEN
        IF NOT EXISTS (SELECT FROM regintel.numerical_page_captures c
            WHERE c.id=NEW.capture_id AND c.filing_version_id=owner.filing_version_id
            AND c.source_blob_id=owner.source_blob_id
            AND (convert_from(c.prepared_bytes,'UTF8')::jsonb->>'page_index')::bigint=NEW.page_index) THEN
            RAISE EXCEPTION 'Context capture differs from the original native source';
        END IF;
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'Native source membership is invalid' USING ERRCODE='23514';
END;
$$;

CREATE TRIGGER native_insert_guard BEFORE INSERT ON regintel.native_parse_manifests
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_native_parse_insert();
CREATE TRIGGER native_insert_guard BEFORE INSERT ON regintel.native_parse_source_pages
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_native_parse_insert();
CREATE TRIGGER native_insert_guard BEFORE INSERT ON regintel.native_parse_context_captures
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_native_parse_insert();
CREATE TRIGGER native_insert_guard BEFORE INSERT ON regintel.native_parse_table_sources
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_native_parse_insert();

CREATE FUNCTION regintel.validate_native_parse_artifact() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner RECORD; artifact JSONB; configuration JSONB;
BEGIN
    SELECT p.*,j.state AS job_state,j.configuration_sha256 AS job_configuration,
        v.filing_id,s.sha256 AS source_sha,b.native_configuration_sha256
        INTO owner FROM regintel.parse_versions p
        JOIN regintel.filing_jobs j ON j.id=NEW.job_id AND j.filing_version_id=p.filing_version_id
            AND j.source_blob_id=p.source_blob_id
        JOIN regintel.filing_versions v ON v.id=p.filing_version_id
        JOIN regintel.source_blobs s ON s.id=p.source_blob_id
        JOIN regintel.native_parse_manifests b ON b.parse_version_id=p.id AND b.job_id=j.id
        WHERE p.id=NEW.parse_version_id;
    artifact:=convert_from(NEW.artifact_bytes,'UTF8')::jsonb;
    configuration:=convert_from(NEW.configuration_bytes,'UTF8')::jsonb;
    IF NOT FOUND OR owner.creation_transaction<>txid_current() OR owner.job_state<>'RUNNING'
       OR owner.adapter_name<>'regintel-native-context' OR owner.adapter_version<>'1.0.0'
       OR owner.configuration_sha256 IS DISTINCT FROM owner.job_configuration
       OR encode(sha256(NEW.artifact_bytes),'hex') IS DISTINCT FROM owner.artifact_sha256
       OR encode(sha256(NEW.configuration_bytes),'hex') IS DISTINCT FROM owner.configuration_sha256
       OR artifact->>'schema_version' IS DISTINCT FROM '1.0.0'
       OR artifact->>'id' IS DISTINCT FROM owner.id::text
       OR artifact->>'filing_id' IS DISTINCT FROM owner.filing_id::text
       OR artifact->>'filing_version_id' IS DISTINCT FROM owner.filing_version_id::text
       OR artifact->>'source_blob_id' IS DISTINCT FROM owner.source_blob_id::text
       OR artifact->>'source_sha256' IS DISTINCT FROM owner.source_sha
       OR artifact#>>'{provenance,adapter_name}' IS DISTINCT FROM owner.adapter_name::text
       OR artifact#>>'{provenance,adapter_version}' IS DISTINCT FROM owner.adapter_version::text
       OR artifact#>>'{provenance,backend_name}' IS DISTINCT FROM 'DoclingPdfParser'
       OR artifact#>>'{provenance,backend_version}' IS DISTINCT FROM '7.22.1'
       OR configuration->>'schema_version' IS DISTINCT FROM '1.1.0'
       OR configuration->>'adapter_name' IS DISTINCT FROM owner.adapter_name::text
       OR configuration->>'adapter_version' IS DISTINCT FROM owner.adapter_version::text
       OR configuration->>'native_coverage' IS DISTINCT FROM 'ALL_ORIGINAL_PAGES'
       OR configuration->>'evidence_coverage' IS DISTINCT FROM 'EXPLICIT_CONTEXT_PAGES'
       OR configuration->>'native_configuration_sha256' IS DISTINCT FROM owner.native_configuration_sha256
       OR artifact#>>'{provenance,configuration_sha256}' IS DISTINCT FROM configuration->>'sdk_configuration_sha256'
       OR artifact#>>'{provenance,adapter_code_sha256}' IS DISTINCT FROM configuration->>'adapter_code_sha256'
       OR artifact#>>'{provenance,backend_code_sha256}' IS DISTINCT FROM configuration->>'backend_code_sha256'
       OR artifact#>>'{provenance,coordinate_frame}' IS DISTINCT FROM configuration->>'coordinate_frame'
       OR artifact#>>'{provenance,package_manifest_sha256}' IS DISTINCT FROM configuration->>'package_manifest_sha256'
       OR artifact#>>'{provenance,model_manifest_sha256}' IS DISTINCT FROM configuration->>'model_manifest_sha256'
       OR configuration#>>'{native_source_configuration,capture_code_sha256}' IS DISTINCT FROM configuration->>'sdk_code_sha256'
       OR configuration->>'coordinate_frame' IS DISTINCT FROM 'CROP_ROTATED_TOP_LEFT'
       OR jsonb_typeof(configuration->'evidence_page_indices') IS DISTINCT FROM 'array'
       OR jsonb_array_length(configuration->'evidence_page_indices') NOT BETWEEN 1 AND 32 THEN
        RAISE EXCEPTION 'Native artifact differs from its job and versioned stage configuration';
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'Native artifact membership is invalid' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER validate_native_parse_artifact BEFORE INSERT ON regintel.parse_artifacts
    FOR EACH ROW WHEN (NEW.format_version='1.1.0')
    EXECUTE FUNCTION regintel.validate_native_parse_artifact();

CREATE FUNCTION regintel.require_complete_native_result(parse_id UUID, trigger_job UUID)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE result RECORD; artifact JSONB; configuration JSONB; manifest JSONB;
BEGIN
    SELECT p.*,j.id AS job_id,j.state AS job_state,j.parse_version_id AS job_parse,j.page_count AS job_pages,
        a.artifact_bytes,a.configuration_bytes,b.manifest_bytes
        INTO result FROM regintel.parse_versions p
        JOIN regintel.parse_artifacts a ON a.parse_version_id=p.id AND a.format_version='1.1.0'
        JOIN regintel.filing_jobs j ON j.id=a.job_id
        JOIN regintel.native_parse_manifests b ON b.parse_version_id=p.id AND b.job_id=j.id
        WHERE p.id=parse_id;
    IF NOT FOUND OR result.job_state<>'PARSED' OR result.job_parse IS DISTINCT FROM parse_id
       OR result.job_id IS DISTINCT FROM trigger_job OR result.job_pages IS DISTINCT FROM result.page_count
       OR result.creation_transaction<>txid_current() OR result.table_count<>0 OR result.cell_count<>0 THEN
        RAISE EXCEPTION 'Native result must be complete and atomic';
    END IF;
    artifact:=convert_from(result.artifact_bytes,'UTF8')::jsonb;
    configuration:=convert_from(result.configuration_bytes,'UTF8')::jsonb;
    manifest:=convert_from(result.manifest_bytes,'UTF8')::jsonb;
    IF (SELECT count(*) FROM regintel.native_parse_source_pages WHERE parse_version_id=parse_id)<>result.page_count
       OR jsonb_array_length(artifact->'pages')<>result.page_count
       OR (SELECT count(*) FROM regintel.pages WHERE parse_version_id=parse_id)<>result.page_count
       OR EXISTS (SELECT FROM jsonb_array_elements(manifest->'pages') WITH ORDINALITY p(item,n)
           LEFT JOIN regintel.native_parse_source_pages s ON s.parse_version_id=parse_id AND s.page_index=n-1
           WHERE (item->>'page_index')::bigint<>n-1 OR s.page_index IS NULL
           OR item->>'sha256' IS DISTINCT FROM s.page_sha256
           OR (item->>'word_count')::bigint IS DISTINCT FROM s.word_count
           OR (item->>'byte_size')::bigint IS DISTINCT FROM octet_length(s.page_bytes))
       OR EXISTS (SELECT FROM regintel.native_parse_source_pages s WHERE s.parse_version_id=parse_id
           AND convert_from(s.page_bytes,'UTF8')::jsonb->'page_geometry' IS DISTINCT FROM
               (artifact->'pages'->s.page_index::integer)->'geometry')
       OR EXISTS (SELECT FROM regintel.pages p WHERE p.parse_version_id=parse_id AND (
           p.id::text IS DISTINCT FROM artifact->'pages'->p.page_index::integer->>'id'
           OR jsonb_build_object('width',p.width,'height',p.height,
               'media_box',jsonb_build_object('x0',p.media_x0,'y0',p.media_y0,'x1',p.media_x1,'y1',p.media_y1),
               'crop_box',jsonb_build_object('x0',p.crop_x0,'y0',p.crop_y0,'x1',p.crop_x1,'y1',p.crop_y1),
               'rotation',p.rotation,'coordinate_space',p.coordinate_space,'origin',p.origin)
           IS DISTINCT FROM artifact->'pages'->p.page_index::integer->'geometry'))
       OR EXISTS (
          (SELECT value::bigint FROM jsonb_array_elements_text(configuration->'evidence_page_indices')
           EXCEPT SELECT page_index FROM regintel.native_parse_context_captures WHERE parse_version_id=parse_id)
       ) OR EXISTS (
          (SELECT page_index FROM regintel.native_parse_context_captures WHERE parse_version_id=parse_id
           EXCEPT SELECT value::bigint FROM jsonb_array_elements_text(configuration->'evidence_page_indices'))
       ) OR EXISTS (SELECT FROM regintel.native_parse_context_captures r
           JOIN regintel.numerical_page_captures c ON c.id=r.capture_id WHERE r.parse_version_id=parse_id
           AND convert_from(c.prepared_bytes,'UTF8')::jsonb->>'sdk_configuration_sha256'
               IS DISTINCT FROM configuration->>'sdk_configuration_sha256') THEN
        RAISE EXCEPTION 'Native coverage, geometry or contextual membership differs';
    END IF;
    -- Materialized sets avoid repeatedly scanning complete JSON for each source word.
    IF EXISTS (WITH actual AS MATERIALIZED (
        SELECT b->>'id' AS id,b->>'page_id' AS page_id,(b->>'page_index')::bigint AS page_index,
            (b->>'source_cell_index')::bigint AS word_index,b->>'orig' AS orig,
            b#>'{provenance,0,raw_rectangle}' AS raw_rectangle,b#>'{boxes,0}' AS box
        FROM jsonb_array_elements(artifact->'blocks') b
    ), expected AS MATERIALIZED (
        SELECT r.page_index,(w->>'word_index')::bigint AS word_index,w->>'orig' AS orig,
            w->'raw_rectangle' AS raw_rectangle,w->'box' AS box
        FROM regintel.native_parse_context_captures r
        JOIN regintel.numerical_page_captures c ON c.id=r.capture_id
        CROSS JOIN LATERAL jsonb_array_elements(convert_from(c.prepared_bytes,'UTF8')::jsonb->'words') w
        WHERE r.parse_version_id=parse_id
    ) SELECT FROM (
       (SELECT page_index,word_index,orig,raw_rectangle,box FROM actual
        EXCEPT SELECT page_index,word_index,orig,raw_rectangle,box FROM expected)
       UNION ALL
       (SELECT page_index,word_index,orig,raw_rectangle,box FROM expected
        EXCEPT SELECT page_index,word_index,orig,raw_rectangle,box FROM actual)
    ) differences) OR result.block_count<>jsonb_array_length(artifact->'blocks')
       OR result.block_count<>(SELECT count(*) FROM regintel.blocks WHERE parse_version_id=parse_id)
       OR result.evidence_count<>result.block_count
       OR result.evidence_count<>(SELECT count(*) FROM regintel.evidence WHERE parse_version_id=parse_id)
       OR EXISTS (SELECT FROM jsonb_array_elements(artifact->'blocks') b WHERE
           NOT regintel.exact_artifact_block_eligible(b) OR b->'from_ocr' IS DISTINCT FROM 'false'::jsonb
           OR jsonb_array_length(b->'exact_spans')<>1
           OR b#>>'{exact_spans,0,block_id}' IS DISTINCT FROM b->>'id'
           OR (b#>>'{exact_spans,0,start}')::bigint<>0
           OR (b#>>'{exact_spans,0,end}')::bigint<>char_length(b->>'orig')
           OR b#>>'{exact_spans,0,quote}' IS DISTINCT FROM b->>'orig')
       OR EXISTS (SELECT FROM regintel.tables WHERE parse_version_id=parse_id)
       OR EXISTS (SELECT FROM regintel.cells WHERE parse_version_id=parse_id) THEN
        RAISE EXCEPTION 'Native projected words differ from original contextual support';
    END IF;
    IF EXISTS (WITH expected AS MATERIALIZED (
        SELECT b->>'id' AS id,b->>'page_id' AS page_id,b->>'orig' AS quote,b->'boxes' AS boxes
        FROM jsonb_array_elements(artifact->'blocks') b
    ), actual AS MATERIALIZED (
        SELECT e.block_id::text AS id,e.page_id::text AS page_id,e.quote,e.kind,e.start_offset,e.end_offset,
            e.box_count,b.text,(SELECT jsonb_agg(jsonb_build_object('x0',x0,'y0',y0,'x1',x1,'y1',y1)
            ORDER BY box_index) FROM regintel.evidence_boxes WHERE evidence_id=e.id) AS boxes
        FROM regintel.evidence e JOIN regintel.blocks b ON b.id=e.block_id WHERE e.parse_version_id=parse_id
    ) SELECT FROM expected x FULL JOIN actual a ON a.id=x.id
        WHERE a.id IS NULL OR x.id IS NULL OR a.page_id IS DISTINCT FROM x.page_id
        OR a.quote IS DISTINCT FROM x.quote OR a.text IS DISTINCT FROM x.quote
        OR a.kind<>'text' OR a.start_offset<>0 OR a.end_offset<>char_length(x.quote)
        OR a.box_count<>1 OR a.boxes IS DISTINCT FROM x.boxes)
       OR EXISTS (SELECT FROM regintel.evidence WHERE parse_version_id=parse_id GROUP BY block_id HAVING count(*)<>1)
       OR EXISTS (
          (SELECT b->>'id' FROM jsonb_array_elements(artifact->'tables') b
           EXCEPT SELECT artifact_table_id::text FROM regintel.native_parse_table_sources WHERE parse_version_id=parse_id)
       ) OR EXISTS (
          (SELECT artifact_table_id::text FROM regintel.native_parse_table_sources WHERE parse_version_id=parse_id
           EXCEPT SELECT b->>'id' FROM jsonb_array_elements(artifact->'tables') b)
       ) THEN RAISE EXCEPTION 'Native relational evidence must match the exact projected words';
    END IF;
END;
$$;

-- Append-only native source artifacts share the existing parse transaction.
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.native_parse_manifests
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.native_parse_source_pages
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.native_parse_context_captures
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.native_parse_table_sources
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.native_parse_manifests
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.native_parse_source_pages
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.native_parse_context_captures
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.native_parse_table_sources
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

-- Preserve the legacy branch verbatim; route only the explicit new sidecar format.
CREATE OR REPLACE FUNCTION regintel.require_complete_parse_result() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parse_id UUID; trigger_job UUID; result RECORD; artifact JSONB;
BEGIN
    parse_id := NEW.parse_version_id;
    IF TG_TABLE_NAME = 'filing_jobs' THEN trigger_job := NEW.id;
    ELSE trigger_job := NEW.job_id;
    END IF;
    IF EXISTS (SELECT FROM regintel.parse_artifacts a
        WHERE a.parse_version_id=parse_id AND a.format_version='1.1.0') THEN
        PERFORM regintel.require_complete_native_result(parse_id,trigger_job);
        RETURN NULL;
    END IF;
    SELECT p.*, j.id AS job_id, j.state AS job_state, j.parse_version_id AS job_parse,
        j.filing_version_id AS job_version, j.source_blob_id AS job_source,
        j.configuration_sha256 AS job_configuration, j.page_count AS job_pages,
        a.artifact_bytes INTO result
        FROM regintel.parse_versions p JOIN regintel.parse_artifacts a ON a.parse_version_id=p.id
        JOIN regintel.filing_jobs j ON j.id=a.job_id WHERE p.id=parse_id;
    IF NOT FOUND OR result.job_state <> 'PARSED' OR result.job_parse IS DISTINCT FROM parse_id
       OR result.job_id IS DISTINCT FROM trigger_job
       OR result.job_version IS DISTINCT FROM result.filing_version_id
       OR result.job_source IS DISTINCT FROM result.source_blob_id
       OR result.job_configuration IS DISTINCT FROM result.configuration_sha256
       OR result.job_pages IS DISTINCT FROM result.page_count
       OR result.creation_transaction <> txid_current() THEN
        RAISE EXCEPTION 'A parsed job needs its complete immutable matching result'
            USING ERRCODE = '23514';
    END IF;
    artifact := convert_from(result.artifact_bytes, 'UTF8')::jsonb;
    IF result.table_count <> 0 OR result.cell_count <> 0
       OR EXISTS (SELECT FROM regintel.tables WHERE parse_version_id=parse_id)
       OR EXISTS (SELECT FROM regintel.cells WHERE parse_version_id=parse_id)
       OR result.block_count <> (SELECT count(*) FROM jsonb_array_elements(artifact -> 'blocks') b
            WHERE jsonb_typeof(b -> 'orig')='string' AND jsonb_typeof(b -> 'page_id')='string')
       OR result.evidence_count <> (SELECT coalesce(sum(jsonb_array_length(b -> 'exact_spans')),0)
            FROM jsonb_array_elements(artifact -> 'blocks') b
            WHERE regintel.exact_artifact_block_eligible(b))
       OR EXISTS (SELECT FROM regintel.evidence WHERE parse_version_id=parse_id AND kind <> 'text') THEN
        RAISE EXCEPTION 'The relational projection must retain original text and exact support only'
            USING ERRCODE = '23514';
    END IF;
    -- Compare original page geometry and Unicode blocks in both directions; SDK
    -- processed tables and missing/mislocated original text remain in the sidecar.
    IF EXISTS (
        (SELECT p.id::text,p.page_index,p.width,p.height,p.media_x0,p.media_y0,p.media_x1,p.media_y1,
             p.crop_x0,p.crop_y0,p.crop_x1,p.crop_y1,p.rotation,p.coordinate_space,p.origin
         FROM regintel.pages p WHERE p.parse_version_id=parse_id
         EXCEPT
         SELECT b ->> 'id',(b ->> 'page_index')::bigint,(b #>> '{geometry,width}')::float8,
             (b #>> '{geometry,height}')::float8,(b #>> '{geometry,media_box,x0}')::float8,
             (b #>> '{geometry,media_box,y0}')::float8,(b #>> '{geometry,media_box,x1}')::float8,
             (b #>> '{geometry,media_box,y1}')::float8,(b #>> '{geometry,crop_box,x0}')::float8,
             (b #>> '{geometry,crop_box,y0}')::float8,(b #>> '{geometry,crop_box,x1}')::float8,
             (b #>> '{geometry,crop_box,y1}')::float8,(b #>> '{geometry,rotation}')::smallint,
             b #>> '{geometry,coordinate_space}',b #>> '{geometry,origin}'
         FROM jsonb_array_elements(artifact -> 'pages') b)
    ) OR EXISTS (
        SELECT FROM regintel.blocks r WHERE r.parse_version_id=parse_id AND NOT EXISTS (
            SELECT FROM jsonb_array_elements(artifact -> 'blocks') b
            WHERE b ->> 'id'=r.id::text AND b ->> 'page_id'=r.page_id::text AND b ->> 'orig'=r.text)
    ) OR EXISTS (
        SELECT FROM jsonb_array_elements(artifact -> 'blocks') b
        WHERE jsonb_typeof(b -> 'orig')='string' AND jsonb_typeof(b -> 'page_id')='string'
        AND NOT EXISTS (SELECT FROM regintel.blocks r WHERE r.parse_version_id=parse_id
            AND r.id::text=b ->> 'id' AND r.page_id::text=b ->> 'page_id' AND r.text=b ->> 'orig')
    ) THEN
        RAISE EXCEPTION 'Projection page geometry and original Unicode must match the artifact'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT FROM regintel.evidence e WHERE e.parse_version_id=parse_id AND NOT EXISTS (
            SELECT FROM jsonb_array_elements(artifact -> 'blocks') b
            CROSS JOIN LATERAL jsonb_array_elements(b -> 'exact_spans') span
            WHERE regintel.exact_artifact_block_eligible(b)
            AND b ->> 'id'=e.block_id::text AND b ->> 'page_id'=e.page_id::text
            AND span ->> 'block_id'=e.block_id::text
            AND (span ->> 'start')::bigint=e.start_offset AND (span ->> 'end')::bigint=e.end_offset
            AND span ->> 'quote'=e.quote
            AND b -> 'boxes'=(SELECT jsonb_agg(jsonb_build_object('x0',x0,'y0',y0,'x1',x1,'y1',y1)
                 ORDER BY box_index) FROM regintel.evidence_boxes WHERE evidence_id=e.id))
    ) OR EXISTS (
        SELECT FROM jsonb_array_elements(artifact -> 'blocks') b
        CROSS JOIN LATERAL jsonb_array_elements(b -> 'exact_spans') span
        WHERE regintel.exact_artifact_block_eligible(b) AND NOT EXISTS (
            SELECT FROM regintel.evidence e WHERE e.parse_version_id=parse_id
            AND e.block_id::text=b ->> 'id' AND e.start_offset=(span ->> 'start')::bigint
            AND e.end_offset=(span ->> 'end')::bigint AND e.quote=span ->> 'quote')
    ) OR EXISTS (
        SELECT FROM regintel.evidence WHERE parse_version_id=parse_id
        GROUP BY block_id,start_offset,end_offset,quote HAVING count(*) <> 1
    ) THEN
        RAISE EXCEPTION 'Every exact evidence span and box must match eligible original support'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'A parsed job needs its complete immutable matching projection'
        USING ERRCODE = '23514';
END;
$$;

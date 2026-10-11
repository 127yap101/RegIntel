-- M1.1 storage foundations only. M1B must supply acceptance/publication gates.
CREATE DOMAIN regintel.canonical_id AS UUID
    CHECK (VALUE::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$');
CREATE DOMAIN regintel.sha256_hash AS TEXT
    CHECK (VALUE ~ '^[0-9a-f]{64}$');
CREATE DOMAIN regintel.stored_label AS TEXT CHECK (char_length(VALUE) BETWEEN 1 AND 256);
CREATE DOMAIN regintel.stored_text AS TEXT CHECK (char_length(VALUE) <= 200000);
CREATE DOMAIN regintel.safe_index AS BIGINT CHECK (VALUE BETWEEN 0 AND 9007199254740991);
CREATE DOMAIN regintel.positive_safe_integer AS BIGINT
    CHECK (VALUE BETWEEN 1 AND 9007199254740991);
CREATE DOMAIN regintel.finite_coordinate AS DOUBLE PRECISION
    CHECK (VALUE NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8));

CREATE TABLE regintel.source_blobs (
    id regintel.canonical_id PRIMARY KEY,
    sha256 regintel.sha256_hash NOT NULL UNIQUE,
    byte_size regintel.positive_safe_integer NOT NULL,
    storage_key regintel.stored_label NOT NULL UNIQUE
        CHECK (storage_key = 'sha256/' || sha256 || '.pdf'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE regintel.filings (
    id regintel.canonical_id PRIMARY KEY,
    company_name_raw regintel.stored_label NOT NULL,
    company_entity_id regintel.canonical_id,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE regintel.filing_versions (
    id regintel.canonical_id PRIMARY KEY,
    filing_id regintel.canonical_id NOT NULL REFERENCES regintel.filings(id),
    source_blob_id regintel.canonical_id NOT NULL REFERENCES regintel.source_blobs(id),
    document_type TEXT NOT NULL
        CHECK (document_type IN ('DRHP', 'RHP', 'PROSPECTUS', 'ADDENDUM', 'CORRIGENDUM')),
    source_url TEXT CHECK (source_url IS NULL OR
        (char_length(source_url) BETWEEN 1 AND 4096
         AND source_url ~ '^https://[^/@#[:space:]]+(/[^#[:space:]]*)?$'
         AND source_url !~ '[[:cntrl:]]')),
    published_on DATE CHECK (published_on BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
    declared_parent_filing_version_id regintel.canonical_id REFERENCES regintel.filing_versions(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, source_blob_id),
    CHECK (declared_parent_filing_version_id IS DISTINCT FROM id)
);
CREATE TABLE regintel.parse_versions (
    id regintel.canonical_id PRIMARY KEY,
    filing_version_id regintel.canonical_id NOT NULL,
    source_blob_id regintel.canonical_id NOT NULL,
    adapter_name regintel.stored_label NOT NULL,
    adapter_version regintel.stored_label NOT NULL,
    configuration_sha256 regintel.sha256_hash NOT NULL,
    artifact_sha256 regintel.sha256_hash NOT NULL,
    page_count regintel.positive_safe_integer NOT NULL,
    block_count regintel.safe_index NOT NULL,
    table_count regintel.safe_index NOT NULL,
    cell_count regintel.safe_index NOT NULL,
    evidence_count regintel.safe_index NOT NULL,
    creation_transaction BIGINT NOT NULL DEFAULT txid_current(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (filing_version_id, source_blob_id)
        REFERENCES regintel.filing_versions(id, source_blob_id),
    UNIQUE (id, filing_version_id)
);
CREATE TABLE regintel.pages (
    id regintel.canonical_id PRIMARY KEY,
    parse_version_id regintel.canonical_id NOT NULL,
    filing_version_id regintel.canonical_id NOT NULL,
    page_index regintel.safe_index NOT NULL CHECK (page_index < 9007199254740991),
    width regintel.finite_coordinate NOT NULL CHECK (width > 0),
    height regintel.finite_coordinate NOT NULL CHECK (height > 0),
    media_x0 regintel.finite_coordinate NOT NULL,
    media_y0 regintel.finite_coordinate NOT NULL,
    media_x1 regintel.finite_coordinate NOT NULL,
    media_y1 regintel.finite_coordinate NOT NULL,
    crop_x0 regintel.finite_coordinate NOT NULL,
    crop_y0 regintel.finite_coordinate NOT NULL,
    crop_x1 regintel.finite_coordinate NOT NULL,
    crop_y1 regintel.finite_coordinate NOT NULL,
    rotation SMALLINT NOT NULL CHECK (rotation IN (0, 90, 180, 270)),
    coordinate_space TEXT NOT NULL DEFAULT 'UNROTATED_PDF_POINTS'
        CHECK (coordinate_space = 'UNROTATED_PDF_POINTS'),
    origin TEXT NOT NULL DEFAULT 'BOTTOM_LEFT' CHECK (origin = 'BOTTOM_LEFT'),
    FOREIGN KEY (parse_version_id, filing_version_id)
        REFERENCES regintel.parse_versions(id, filing_version_id),
    UNIQUE (parse_version_id, page_index),
    UNIQUE (id, parse_version_id),
    UNIQUE (id, parse_version_id, filing_version_id),
    CHECK (media_x1 > media_x0 AND media_y1 > media_y0),
    CHECK (crop_x1 > crop_x0 AND crop_y1 > crop_y0
        AND crop_x1 - crop_x0 < 'Infinity'::float8
        AND crop_y1 - crop_y0 < 'Infinity'::float8),
    CHECK (abs(width - (media_x1 - media_x0)) <= greatest(1e-9, 1e-12 * width)),
    CHECK (abs(height - (media_y1 - media_y0)) <= greatest(1e-9, 1e-12 * height))
);
CREATE TABLE regintel.blocks (
    id regintel.canonical_id PRIMARY KEY,
    parse_version_id regintel.canonical_id NOT NULL,
    page_id regintel.canonical_id NOT NULL,
    text regintel.stored_text NOT NULL,
    FOREIGN KEY (page_id, parse_version_id) REFERENCES regintel.pages(id, parse_version_id),
    UNIQUE (id, parse_version_id, page_id)
);
CREATE TABLE regintel.tables (
    id regintel.canonical_id PRIMARY KEY,
    parse_version_id regintel.canonical_id NOT NULL,
    first_page_id regintel.canonical_id NOT NULL,
    row_count regintel.positive_safe_integer NOT NULL,
    column_count regintel.positive_safe_integer NOT NULL,
    FOREIGN KEY (first_page_id, parse_version_id) REFERENCES regintel.pages(id, parse_version_id),
    UNIQUE (id, parse_version_id)
);
CREATE TABLE regintel.cells (
    id regintel.canonical_id PRIMARY KEY,
    parse_version_id regintel.canonical_id NOT NULL,
    table_id regintel.canonical_id NOT NULL,
    page_id regintel.canonical_id NOT NULL,
    row_index regintel.safe_index NOT NULL,
    column_index regintel.safe_index NOT NULL,
    row_span regintel.positive_safe_integer NOT NULL,
    column_span regintel.positive_safe_integer NOT NULL,
    raw_text regintel.stored_text NOT NULL,
    FOREIGN KEY (page_id, parse_version_id) REFERENCES regintel.pages(id, parse_version_id),
    FOREIGN KEY (table_id, parse_version_id) REFERENCES regintel.tables(id, parse_version_id),
    UNIQUE (id, parse_version_id, table_id),
    UNIQUE (id, parse_version_id, page_id),
    UNIQUE (table_id, row_index, column_index),
    CHECK (row_index + row_span <= 9007199254740991),
    CHECK (column_index + column_span <= 9007199254740991)
);
CREATE TABLE regintel.cell_context (
    cell_id regintel.canonical_id NOT NULL,
    parse_version_id regintel.canonical_id NOT NULL,
    table_id regintel.canonical_id NOT NULL,
    context_cell_id regintel.canonical_id NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('ROW_LABEL', 'PERIOD_COLUMN', 'UNIT_HEADER', 'BASIS_HEADER')),
    PRIMARY KEY (cell_id, context_cell_id, role),
    FOREIGN KEY (cell_id, parse_version_id, table_id)
        REFERENCES regintel.cells(id, parse_version_id, table_id),
    FOREIGN KEY (context_cell_id, parse_version_id, table_id)
        REFERENCES regintel.cells(id, parse_version_id, table_id)
);
CREATE TABLE regintel.evidence (
    id regintel.canonical_id PRIMARY KEY,
    parse_version_id regintel.canonical_id NOT NULL,
    filing_version_id regintel.canonical_id NOT NULL,
    page_id regintel.canonical_id NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('text', 'table_cell')),
    block_id regintel.canonical_id,
    start_offset regintel.safe_index,
    end_offset regintel.safe_index,
    quote regintel.stored_text,
    cell_id regintel.canonical_id,
    box_count regintel.positive_safe_integer NOT NULL DEFAULT 1 CHECK (box_count <= 10000),
    FOREIGN KEY (page_id, parse_version_id, filing_version_id)
        REFERENCES regintel.pages(id, parse_version_id, filing_version_id),
    FOREIGN KEY (block_id, parse_version_id, page_id)
        REFERENCES regintel.blocks(id, parse_version_id, page_id),
    FOREIGN KEY (cell_id, parse_version_id, page_id)
        REFERENCES regintel.cells(id, parse_version_id, page_id),
    UNIQUE (id, parse_version_id),
    CHECK (
        (kind = 'text' AND block_id IS NOT NULL AND start_offset IS NOT NULL
         AND end_offset IS NOT NULL AND end_offset > start_offset AND quote IS NOT NULL
         AND end_offset - start_offset = char_length(quote) AND cell_id IS NULL)
        OR (kind = 'table_cell' AND cell_id IS NOT NULL AND block_id IS NULL
            AND start_offset IS NULL AND end_offset IS NULL AND quote IS NULL)
    )
);
CREATE TABLE regintel.evidence_boxes (
    evidence_id regintel.canonical_id NOT NULL REFERENCES regintel.evidence(id),
    box_index regintel.safe_index NOT NULL,
    x0 regintel.finite_coordinate NOT NULL,
    y0 regintel.finite_coordinate NOT NULL,
    x1 regintel.finite_coordinate NOT NULL,
    y1 regintel.finite_coordinate NOT NULL,
    PRIMARY KEY (evidence_id, box_index),
    CHECK (x1 > x0 AND y1 > y0)
);
CREATE TABLE regintel.quantitative_contexts (
    id regintel.canonical_id PRIMARY KEY,
    parse_version_id regintel.canonical_id NOT NULL REFERENCES regintel.parse_versions(id),
    raw_value regintel.stored_text NOT NULL,
    normalized_value NUMERIC CHECK (normalized_value IS NULL OR
        normalized_value::text ~ '^-?(0|[1-9][0-9]{0,119})(\.[0-9]{1,120})?$'),
    raw_unit regintel.stored_text,
    normalized_unit regintel.stored_label,
    raw_currency regintel.stored_text,
    currency regintel.stored_label,
    period_kind TEXT NOT NULL CHECK (period_kind IN ('INSTANT', 'DURATION', 'UNKNOWN')),
    start_date DATE CHECK (start_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
    end_date DATE CHECK (end_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
    instant_date DATE CHECK (instant_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
    raw_period_label regintel.stored_text,
    basis TEXT NOT NULL CHECK (basis IN ('STANDALONE', 'CONSOLIDATED', 'UNKNOWN')),
    raw_basis_label regintel.stored_text,
    denominator regintel.stored_label,
    stake_kind regintel.stored_label,
    ownership_date DATE CHECK (ownership_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
    evidence_count regintel.positive_safe_integer NOT NULL DEFAULT 1 CHECK (evidence_count <= 10000),
    UNIQUE (id, parse_version_id),
    CHECK (
        (period_kind = 'INSTANT' AND start_date IS NULL AND end_date IS NULL)
        OR (period_kind = 'DURATION' AND instant_date IS NULL
            AND (start_date IS NULL OR end_date IS NULL OR start_date <= end_date))
        OR (period_kind = 'UNKNOWN' AND start_date IS NULL AND end_date IS NULL AND instant_date IS NULL)
    )
);
CREATE TABLE regintel.quantitative_context_evidence (
    context_id regintel.canonical_id NOT NULL,
    parse_version_id regintel.canonical_id NOT NULL,
    evidence_id regintel.canonical_id NOT NULL,
    PRIMARY KEY (context_id, evidence_id),
    FOREIGN KEY (context_id, parse_version_id)
        REFERENCES regintel.quantitative_contexts(id, parse_version_id),
    FOREIGN KEY (evidence_id, parse_version_id) REFERENCES regintel.evidence(id, parse_version_id)
);
CREATE TABLE regintel.candidates (
    id regintel.canonical_id PRIMARY KEY,
    parse_version_id regintel.canonical_id NOT NULL REFERENCES regintel.parse_versions(id),
    kind TEXT NOT NULL CHECK (kind IN ('numeric_fact', 'narrative_fact', 'relation')),
    state TEXT NOT NULL DEFAULT 'CANDIDATE' CHECK (state = 'CANDIDATE'),
    subject_entity_id regintel.canonical_id NOT NULL,
    object_entity_id regintel.canonical_id,
    metric_id regintel.canonical_id,
    relation_type TEXT CHECK (relation_type IN
        ('OWNS', 'PROMOTER_OF', 'SUBSIDIARY_OF', 'SUPPLIES_TO', 'AUDITS', 'LENDS_TO')),
    raw_text regintel.stored_text NOT NULL,
    quantitative_context_id regintel.canonical_id,
    evidence_count regintel.positive_safe_integer NOT NULL DEFAULT 1 CHECK (evidence_count <= 10000),
    FOREIGN KEY (quantitative_context_id, parse_version_id)
        REFERENCES regintel.quantitative_contexts(id, parse_version_id),
    UNIQUE (id, parse_version_id),
    CHECK ((kind = 'relation' AND object_entity_id IS NOT NULL AND relation_type IS NOT NULL
            AND metric_id IS NULL AND subject_entity_id <> object_entity_id)
        OR (kind IN ('numeric_fact', 'narrative_fact') AND metric_id IS NOT NULL
            AND object_entity_id IS NULL AND relation_type IS NULL)),
    CHECK (kind <> 'numeric_fact' OR quantitative_context_id IS NOT NULL)
);
CREATE TABLE regintel.candidate_evidence (
    candidate_id regintel.canonical_id NOT NULL,
    parse_version_id regintel.canonical_id NOT NULL,
    evidence_id regintel.canonical_id NOT NULL,
    PRIMARY KEY (candidate_id, evidence_id),
    FOREIGN KEY (candidate_id, parse_version_id) REFERENCES regintel.candidates(id, parse_version_id),
    FOREIGN KEY (evidence_id, parse_version_id) REFERENCES regintel.evidence(id, parse_version_id)
);
CREATE TABLE regintel.corpus_versions (
    id regintel.canonical_id PRIMARY KEY,
    parent_corpus_version_id regintel.canonical_id REFERENCES regintel.corpus_versions(id),
    state TEXT NOT NULL CHECK (state IN ('BUILDING', 'PUBLISHED')),
    configuration_sha256 regintel.sha256_hash NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (parent_corpus_version_id IS DISTINCT FROM id)
);
CREATE TABLE regintel.acceptance_audits (
    id regintel.canonical_id PRIMARY KEY,
    candidate_id regintel.canonical_id NOT NULL,
    parse_version_id regintel.canonical_id NOT NULL,
    actor_user_id UUID NOT NULL REFERENCES regintel.users(id),
    decision TEXT NOT NULL CHECK (decision = 'ACCEPTED'),
    validator_configuration_sha256 regintel.sha256_hash NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (candidate_id, parse_version_id) REFERENCES regintel.candidates(id, parse_version_id),
    UNIQUE (id, candidate_id, parse_version_id)
);
CREATE TABLE regintel.fact_observations (
    id regintel.canonical_id PRIMARY KEY,
    candidate_id regintel.canonical_id NOT NULL,
    parse_version_id regintel.canonical_id NOT NULL,
    acceptance_audit_id regintel.canonical_id NOT NULL,
    corpus_version_id regintel.canonical_id NOT NULL REFERENCES regintel.corpus_versions(id),
    kind TEXT NOT NULL CHECK (kind IN ('numeric_fact', 'narrative_fact')),
    subject_entity_id regintel.canonical_id NOT NULL,
    metric_id regintel.canonical_id NOT NULL,
    quantitative_context_id regintel.canonical_id,
    raw_text regintel.stored_text NOT NULL,
    FOREIGN KEY (acceptance_audit_id, candidate_id, parse_version_id)
        REFERENCES regintel.acceptance_audits(id, candidate_id, parse_version_id),
    FOREIGN KEY (quantitative_context_id, parse_version_id)
        REFERENCES regintel.quantitative_contexts(id, parse_version_id),
    CHECK (kind <> 'numeric_fact' OR quantitative_context_id IS NOT NULL)
);
CREATE TABLE regintel.relation_observations (
    id regintel.canonical_id PRIMARY KEY,
    candidate_id regintel.canonical_id NOT NULL,
    parse_version_id regintel.canonical_id NOT NULL,
    acceptance_audit_id regintel.canonical_id NOT NULL,
    corpus_version_id regintel.canonical_id NOT NULL REFERENCES regintel.corpus_versions(id),
    subject_entity_id regintel.canonical_id NOT NULL,
    object_entity_id regintel.canonical_id NOT NULL,
    relation_type TEXT NOT NULL CHECK (relation_type IN
        ('OWNS', 'PROMOTER_OF', 'SUBSIDIARY_OF', 'SUPPLIES_TO', 'AUDITS', 'LENDS_TO')),
    quantitative_context_id regintel.canonical_id,
    FOREIGN KEY (acceptance_audit_id, candidate_id, parse_version_id)
        REFERENCES regintel.acceptance_audits(id, candidate_id, parse_version_id),
    FOREIGN KEY (quantitative_context_id, parse_version_id)
        REFERENCES regintel.quantitative_contexts(id, parse_version_id),
    CHECK (subject_entity_id <> object_entity_id)
);

CREATE FUNCTION regintel.reject_immutable_mutation() RETURNS TRIGGER
LANGUAGE plpgsql AS $function$
BEGIN
    RAISE EXCEPTION 'Immutable ingestion records cannot be changed or removed'
        USING ERRCODE = '23514';
END;
$function$;
CREATE FUNCTION regintel.reject_premature_authority() RETURNS TRIGGER
LANGUAGE plpgsql AS $function$
BEGIN
    RAISE EXCEPTION 'Acceptance and corpus operations require the later M1B gates'
        USING ERRCODE = '23514';
END;
$function$;
CREATE FUNCTION regintel.initialize_parse_transaction() RETURNS TRIGGER
LANGUAGE plpgsql AS $function$
BEGIN
    -- The caller cannot forge the transaction in which a parse tree is writable.
    NEW.creation_transaction := txid_current();
    RETURN NEW;
END;
$function$;
CREATE TRIGGER initialize_parse_transaction BEFORE INSERT ON regintel.parse_versions
    FOR EACH ROW EXECUTE FUNCTION regintel.initialize_parse_transaction();
CREATE FUNCTION regintel.require_parse_creation_transaction() RETURNS TRIGGER
LANGUAGE plpgsql AS $function$
DECLARE parse_id UUID; source_transaction BIGINT;
BEGIN
    IF TG_TABLE_NAME = 'evidence_boxes' THEN
        SELECT parse_version_id INTO parse_id FROM regintel.evidence WHERE id = NEW.evidence_id;
    ELSE
        parse_id := NEW.parse_version_id;
    END IF;
    SELECT creation_transaction INTO source_transaction FROM regintel.parse_versions WHERE id = parse_id;
    IF FOUND AND source_transaction <> txid_current() THEN
        RAISE EXCEPTION 'A completed parse source tree cannot gain new source records'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
CREATE FUNCTION regintel.require_complete_parse_tree() RETURNS TRIGGER
LANGUAGE plpgsql AS $function$
BEGIN
    IF NEW.page_count <> (SELECT count(*) FROM regintel.pages WHERE parse_version_id = NEW.id)
       OR NEW.block_count <> (SELECT count(*) FROM regintel.blocks WHERE parse_version_id = NEW.id)
       OR NEW.table_count <> (SELECT count(*) FROM regintel.tables WHERE parse_version_id = NEW.id)
       OR NEW.cell_count <> (SELECT count(*) FROM regintel.cells WHERE parse_version_id = NEW.id)
       OR NEW.evidence_count <> (SELECT count(*) FROM regintel.evidence WHERE parse_version_id = NEW.id) THEN
        RAISE EXCEPTION 'A parse tree must be complete and match its declared artifact counts'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$function$;
CREATE CONSTRAINT TRIGGER complete_parse_tree AFTER INSERT ON regintel.parse_versions
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION regintel.require_complete_parse_tree();
CREATE FUNCTION regintel.validate_cell_extent() RETURNS TRIGGER
LANGUAGE plpgsql AS $function$
DECLARE source_table regintel.tables%ROWTYPE;
BEGIN
    SELECT * INTO source_table FROM regintel.tables
        WHERE id = NEW.table_id AND parse_version_id = NEW.parse_version_id;
    IF FOUND AND (NEW.row_index + NEW.row_span > source_table.row_count
                  OR NEW.column_index + NEW.column_span > source_table.column_count) THEN
        RAISE EXCEPTION 'Cell span exceeds its source table dimensions' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
CREATE TRIGGER validate_cell_extent BEFORE INSERT ON regintel.cells
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_cell_extent();

CREATE FUNCTION regintel.validate_exact_text_evidence() RETURNS TRIGGER
LANGUAGE plpgsql AS $function$
DECLARE block_text TEXT;
BEGIN
    IF NEW.kind = 'text' THEN
        SELECT text INTO block_text FROM regintel.blocks
            WHERE id = NEW.block_id AND parse_version_id = NEW.parse_version_id
                  AND page_id = NEW.page_id;
        IF FOUND AND NEW.end_offset > char_length(block_text) THEN
            RAISE EXCEPTION 'Evidence quote must exactly match its immutable source span'
                USING ERRCODE = '23514';
        END IF;
        IF FOUND AND substring(block_text FROM (NEW.start_offset + 1)::integer
                               FOR (NEW.end_offset - NEW.start_offset)::integer)
            IS DISTINCT FROM NEW.quote THEN
            RAISE EXCEPTION 'Evidence quote must exactly match its immutable source span'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$function$;
CREATE TRIGGER validate_exact_text_evidence BEFORE INSERT ON regintel.evidence
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_exact_text_evidence();

CREATE FUNCTION regintel.validate_evidence_box() RETURNS TRIGGER
LANGUAGE plpgsql AS $function$
DECLARE source_record RECORD;
BEGIN
    SELECT e.box_count, p.media_x0, p.media_y0, p.media_x1, p.media_y1
        INTO source_record FROM regintel.evidence e
        JOIN regintel.pages p ON p.id = e.page_id AND p.parse_version_id = e.parse_version_id
        WHERE e.id = NEW.evidence_id;
    IF FOUND AND (NEW.box_index >= source_record.box_count
        OR NEW.x0 < source_record.media_x0 - 1e-7 OR NEW.y0 < source_record.media_y0 - 1e-7
        OR NEW.x1 > source_record.media_x1 + 1e-7 OR NEW.y1 > source_record.media_y1 + 1e-7) THEN
        RAISE EXCEPTION 'Evidence box must occupy its declared source page and slot'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$function$;
CREATE TRIGGER validate_evidence_box BEFORE INSERT ON regintel.evidence_boxes
    FOR EACH ROW EXECUTE FUNCTION regintel.validate_evidence_box();

CREATE FUNCTION regintel.require_complete_support() RETURNS TRIGGER
LANGUAGE plpgsql AS $function$
DECLARE owner_id UUID; expected BIGINT; actual BIGINT;
BEGIN
    IF TG_TABLE_NAME IN ('evidence', 'evidence_boxes') THEN
        IF TG_TABLE_NAME = 'evidence' THEN owner_id := NEW.id;
        ELSE owner_id := NEW.evidence_id;
        END IF;
        SELECT box_count INTO expected FROM regintel.evidence WHERE id = owner_id;
        SELECT count(*) INTO actual FROM regintel.evidence_boxes WHERE evidence_id = owner_id;
    ELSIF TG_TABLE_NAME IN ('quantitative_contexts', 'quantitative_context_evidence') THEN
        IF TG_TABLE_NAME = 'quantitative_contexts' THEN owner_id := NEW.id;
        ELSE owner_id := NEW.context_id;
        END IF;
        SELECT evidence_count INTO expected FROM regintel.quantitative_contexts WHERE id = owner_id;
        SELECT count(*) INTO actual FROM regintel.quantitative_context_evidence WHERE context_id = owner_id;
    ELSE
        IF TG_TABLE_NAME = 'candidates' THEN owner_id := NEW.id;
        ELSE owner_id := NEW.candidate_id;
        END IF;
        SELECT evidence_count INTO expected FROM regintel.candidates WHERE id = owner_id;
        SELECT count(*) INTO actual FROM regintel.candidate_evidence WHERE candidate_id = owner_id;
    END IF;
    IF expected IS DISTINCT FROM actual THEN
        RAISE EXCEPTION 'Immutable support must be complete and match its declared count'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$function$;

DO $block$
DECLARE target TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY[
        'source_blobs', 'filings', 'filing_versions', 'parse_versions', 'pages', 'blocks',
        'tables', 'cells', 'cell_context', 'evidence', 'evidence_boxes', 'quantitative_contexts',
        'quantitative_context_evidence', 'candidates', 'candidate_evidence', 'corpus_versions',
        'acceptance_audits', 'fact_observations', 'relation_observations'
    ] LOOP
        EXECUTE format('CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.%I '
            'FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation()', target);
        EXECUTE format('CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.%I '
            'FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation()', target);
    END LOOP;
    FOREACH target IN ARRAY ARRAY[
        'corpus_versions', 'acceptance_audits', 'fact_observations', 'relation_observations'
    ] LOOP
        EXECUTE format('CREATE TRIGGER later_authority_gate BEFORE INSERT ON regintel.%I '
            'FOR EACH ROW EXECUTE FUNCTION regintel.reject_premature_authority()', target);
    END LOOP;
    FOREACH target IN ARRAY ARRAY[
        'evidence', 'evidence_boxes', 'quantitative_contexts', 'quantitative_context_evidence',
        'candidates', 'candidate_evidence'
    ] LOOP
        EXECUTE format('CREATE CONSTRAINT TRIGGER complete_support AFTER INSERT ON regintel.%I '
            'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW '
            'EXECUTE FUNCTION regintel.require_complete_support()', target);
    END LOOP;
    FOREACH target IN ARRAY ARRAY[
        'pages', 'blocks', 'tables', 'cells', 'cell_context', 'evidence', 'evidence_boxes'
    ] LOOP
        -- Membership and exact-span checks run first; the insert still rolls back
        -- if its completed parse belongs to an earlier transaction.
        EXECUTE format('CREATE TRIGGER parse_tree_insert_gate AFTER INSERT ON regintel.%I '
            'FOR EACH ROW EXECUTE FUNCTION regintel.require_parse_creation_transaction()', target);
    END LOOP;
END;
$block$;

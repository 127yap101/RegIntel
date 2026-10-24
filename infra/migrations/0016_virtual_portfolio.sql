-- M4 whole-share INR simulator: fixed opening credit, zero fees, immutable outcomes.
CREATE TABLE regintel.portfolio_accounts (
    id regintel.canonical_id PRIMARY KEY,
    owner_id UUID NOT NULL UNIQUE REFERENCES regintel.users(id),
    opening_cash NUMERIC(16,2) NOT NULL CHECK (opening_cash=100000.00),
    auth_version BIGINT NOT NULL CHECK (auth_version>0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE regintel.portfolio_quote_snapshots (
    id regintel.canonical_id PRIMARY KEY,
    quote_bytes BYTEA NOT NULL CHECK (octet_length(quote_bytes) BETWEEN 1 AND 4096),
    quote_sha256 regintel.sha256_hash NOT NULL,
    company_id regintel.canonical_id NOT NULL,
    price NUMERIC(16,2) NOT NULL CHECK (price>0),
    stored_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version BIGINT NOT NULL CHECK (auth_version>0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE regintel.portfolio_orders (
    id regintel.canonical_id PRIMARY KEY,
    account_id regintel.canonical_id NOT NULL REFERENCES regintel.portfolio_accounts(id),
    sequence INTEGER NOT NULL CHECK (sequence BETWEEN 1 AND 1000000),
    request_id regintel.canonical_id NOT NULL,
    company_id regintel.canonical_id NOT NULL,
    request_bytes BYTEA NOT NULL CHECK (octet_length(request_bytes) BETWEEN 1 AND 2048),
    request_sha256 regintel.sha256_hash NOT NULL,
    entry_bytes BYTEA NOT NULL CHECK (octet_length(entry_bytes) BETWEEN 1 AND 32768),
    entry_sha256 regintel.sha256_hash NOT NULL,
    quote_id regintel.canonical_id REFERENCES regintel.portfolio_quote_snapshots(id),
    state TEXT NOT NULL CHECK (state IN ('EXECUTED','REJECTED')),
    cash_delta NUMERIC(16,2) NOT NULL,
    quantity_delta INTEGER NOT NULL CHECK (quantity_delta BETWEEN -1000000 AND 1000000),
    cash_after NUMERIC(16,2) NOT NULL CHECK (cash_after>=0),
    submitted_by UUID NOT NULL REFERENCES regintel.users(id),
    auth_version BIGINT NOT NULL CHECK (auth_version>0),
    committed_at TIMESTAMPTZ NOT NULL,
    UNIQUE(account_id,sequence), UNIQUE(account_id,request_id)
);

CREATE FUNCTION regintel.guard_virtual_account() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM regintel.users WHERE id=NEW.owner_id AND is_active AND auth_version=NEW.auth_version FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'A current virtual-account owner is required' USING ERRCODE='23514'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER virtual_account_guard BEFORE INSERT ON regintel.portfolio_accounts
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_virtual_account();

CREATE FUNCTION regintel.guard_virtual_quote() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE data JSONB;
BEGIN
    data:=convert_from(NEW.quote_bytes,'UTF8')::jsonb;
    PERFORM 1 FROM regintel.users WHERE id=NEW.stored_by AND is_active AND auth_version=NEW.auth_version FOR SHARE;
    IF NOT FOUND OR encode(sha256(NEW.quote_bytes),'hex') IS DISTINCT FROM NEW.quote_sha256
       OR data->>'id' IS DISTINCT FROM NEW.id::text
       OR data->>'company_id' IS DISTINCT FROM NEW.company_id::text
       OR data->>'currency' IS DISTINCT FROM 'INR'
       OR jsonb_typeof(data->'observed_at') IS DISTINCT FROM 'string'
       OR jsonb_typeof(data->'expires_at') IS DISTINCT FROM 'string'
       OR (data->>'quote_version_id')::regintel.canonical_id IS NULL
       OR (data->>'price')::numeric IS DISTINCT FROM NEW.price
       OR (data->>'observed_at')::timestamptz >= (data->>'expires_at')::timestamptz
       OR data->>'source_kind' NOT IN ('REVIEWED_DATASET','ENGINEERING_FIXTURE')
       OR jsonb_typeof(data->'source_kind') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'Virtual quote snapshot differs from its exact server input';
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'Virtual quote snapshot membership is invalid' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER virtual_quote_guard BEFORE INSERT ON regintel.portfolio_quote_snapshots
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_virtual_quote();

CREATE FUNCTION regintel.guard_virtual_order() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE account RECORD; request JSONB; entry JSONB; quote JSONB; current_cash NUMERIC;
    owned BIGINT; orders BIGINT; next_quantity BIGINT; holdings_count BIGINT;
    quantity BIGINT; side TEXT; expected_reason TEXT; expected_cash_delta NUMERIC;
    expected_quantity_delta BIGINT; before_holdings JSONB; after_holdings JSONB;
BEGIN
    SELECT * INTO account FROM regintel.portfolio_accounts WHERE id=NEW.account_id FOR UPDATE;
    IF NOT FOUND OR account.owner_id<>NEW.submitted_by THEN RAISE EXCEPTION 'Virtual account owner differs'; END IF;
    PERFORM 1 FROM regintel.users WHERE id=NEW.submitted_by AND is_active AND auth_version=NEW.auth_version FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Current owner required for virtual orders'; END IF;
    request:=convert_from(NEW.request_bytes,'UTF8')::jsonb;
    entry:=convert_from(NEW.entry_bytes,'UTF8')::jsonb;
    SELECT account.opening_cash+coalesce(sum(o.cash_delta),0),count(o.id)
        INTO current_cash,orders FROM regintel.portfolio_orders o WHERE o.account_id=NEW.account_id;
    SELECT coalesce(sum(o.quantity_delta),0) INTO owned FROM regintel.portfolio_orders o
        WHERE o.account_id=NEW.account_id AND o.company_id=NEW.company_id;
    SELECT coalesce(jsonb_agg(jsonb_build_object('company_id',p.company_id::text,'quantity',p.quantity)
        ORDER BY p.company_id),'[]'::jsonb),count(*) INTO before_holdings,holdings_count
        FROM (SELECT o.company_id,sum(o.quantity_delta) AS quantity FROM regintel.portfolio_orders o
            WHERE o.account_id=NEW.account_id GROUP BY o.company_id HAVING sum(o.quantity_delta)>0) p;
    IF encode(sha256(NEW.request_bytes),'hex') IS DISTINCT FROM NEW.request_sha256
       OR encode(sha256(NEW.entry_bytes),'hex') IS DISTINCT FROM NEW.entry_sha256
       OR request->>'request_id' IS DISTINCT FROM NEW.request_id::text
       OR request->>'company_id' IS DISTINCT FROM NEW.company_id::text
       OR jsonb_typeof(request->'corpus_version_id') IS DISTINCT FROM 'string'
       OR entry->>'id' IS DISTINCT FROM NEW.id::text OR entry->'request' IS DISTINCT FROM request
       OR (entry->>'sequence')::bigint IS DISTINCT FROM NEW.sequence
       OR NEW.sequence<>orders+1 OR entry#>>'{evaluation,state}' IS DISTINCT FROM NEW.state
       OR (entry->>'committed_at')::timestamptz IS DISTINCT FROM NEW.committed_at
       OR entry#>>'{evaluation,before,currency}' IS DISTINCT FROM 'INR'
       OR (entry#>>'{evaluation,before,cash}')::numeric IS DISTINCT FROM current_cash
       OR entry#>'{evaluation,before,holdings}' IS DISTINCT FROM before_holdings THEN
        RAISE EXCEPTION 'Virtual request or prior state differs from its immutable ledger';
    END IF;
    quantity:=(request->>'quantity')::bigint; side:=request->>'side';
    IF quantity IS NULL OR quantity NOT BETWEEN 1 AND 1000000 OR side IS NULL OR side NOT IN ('BUY','SELL')
       OR jsonb_typeof(request->'quantity') IS DISTINCT FROM 'number' THEN
        RAISE EXCEPTION 'Virtual orders require bounded positive whole shares';
    END IF;
    IF NEW.quote_id IS NOT NULL THEN
        SELECT convert_from(q.quote_bytes,'UTF8')::jsonb INTO quote
            FROM regintel.portfolio_quote_snapshots q WHERE q.id=NEW.quote_id;
        IF NOT FOUND OR entry->'quote' IS DISTINCT FROM quote THEN RAISE EXCEPTION 'Virtual quote differs'; END IF;
    ELSIF entry->'quote' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'Missing virtual quote was invented';
    END IF;
    next_quantity:=owned+CASE WHEN side='BUY' THEN quantity ELSE -quantity END;
    expected_cash_delta:=CASE WHEN side='BUY' THEN -1 ELSE 1 END * (quote->>'price')::numeric * quantity;
    expected_reason:=CASE
        WHEN quote IS NULL THEN 'QUOTES_UNAVAILABLE'
        WHEN quote->>'company_id'<>NEW.company_id::text OR quote->>'currency'<>'INR' THEN 'WRONG_QUOTE'
        WHEN NEW.committed_at<(quote->>'observed_at')::timestamptz OR NEW.committed_at>=(quote->>'expires_at')::timestamptz THEN 'STALE_QUOTE'
        WHEN side='SELL' AND owned<quantity THEN 'INSUFFICIENT_HOLDINGS'
        WHEN next_quantity>1000000 OR (next_quantity>0 AND owned=0 AND holdings_count>=100) THEN 'HOLDING_LIMIT'
        WHEN current_cash+expected_cash_delta<0 THEN 'INSUFFICIENT_CASH'
        WHEN current_cash+expected_cash_delta>99999999999999.99 THEN 'OUT_OF_RANGE'
        ELSE 'FILLED' END;
    IF entry#>>'{evaluation,reason}' IS DISTINCT FROM expected_reason THEN RAISE EXCEPTION 'Virtual outcome reason differs'; END IF;
    IF expected_reason='FILLED' THEN
        expected_quantity_delta:=CASE WHEN side='BUY' THEN quantity ELSE -quantity END;
        IF NEW.state<>'EXECUTED' THEN RAISE EXCEPTION 'A valid virtual fill requires its exact outcome'; END IF;
    ELSE
        expected_cash_delta:=0; expected_quantity_delta:=0;
        IF NEW.state<>'REJECTED' THEN RAISE EXCEPTION 'An invalid virtual order must be rejected'; END IF;
    END IF;
    SELECT coalesce(jsonb_agg(jsonb_build_object('company_id',p.company_id::text,'quantity',p.quantity)
        ORDER BY p.company_id),'[]'::jsonb) INTO after_holdings FROM (
        SELECT x.company_id,sum(x.quantity) AS quantity FROM (
            SELECT o.company_id,o.quantity_delta AS quantity FROM regintel.portfolio_orders o WHERE o.account_id=NEW.account_id
            UNION ALL SELECT NEW.company_id,expected_quantity_delta
        ) x GROUP BY x.company_id HAVING sum(x.quantity)>0
    ) p;
    IF NEW.cash_delta IS DISTINCT FROM expected_cash_delta OR NEW.quantity_delta IS DISTINCT FROM expected_quantity_delta
       OR NEW.cash_after IS DISTINCT FROM current_cash+expected_cash_delta
       OR (entry#>>'{evaluation,cash_delta}')::numeric IS DISTINCT FROM expected_cash_delta
       OR (entry#>>'{evaluation,quantity_delta}')::bigint IS DISTINCT FROM expected_quantity_delta
       OR (entry#>>'{evaluation,after,cash}')::numeric IS DISTINCT FROM NEW.cash_after
       OR entry#>>'{evaluation,after,currency}' IS DISTINCT FROM 'INR'
       OR entry#>'{evaluation,after,holdings}' IS DISTINCT FROM after_holdings THEN
        RAISE EXCEPTION 'Virtual cash and holdings must conserve the exact committed ledger';
    END IF;
    RETURN NEW;
EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'Virtual order or ledger membership is invalid' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER virtual_order_guard BEFORE INSERT ON regintel.portfolio_orders
    FOR EACH ROW EXECUTE FUNCTION regintel.guard_virtual_order();

CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.portfolio_accounts
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.portfolio_quote_snapshots
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON regintel.portfolio_orders
    FOR EACH ROW EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.portfolio_accounts
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.portfolio_quote_snapshots
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON regintel.portfolio_orders
    FOR EACH STATEMENT EXECUTE FUNCTION regintel.reject_immutable_mutation();

CREATE TABLE regintel.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid()
        CHECK (id::text ~
            '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'),
    username TEXT COLLATE "C" NOT NULL UNIQUE
        CHECK (char_length(username) BETWEEN 3 AND 64
               AND username ~ '^[a-z][a-z0-9._-]{2,63}$'),
    password_hash TEXT NOT NULL CHECK (password_hash LIKE '$argon2id$v=19$%'),
    role TEXT NOT NULL CHECK (role IN ('admin', 'learner')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    auth_version INTEGER NOT NULL DEFAULT 1 CHECK (auth_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION regintel.version_account_update() RETURNS TRIGGER
LANGUAGE plpgsql AS $function$
BEGIN
    IF NEW.auth_version IS NULL OR NEW.auth_version < OLD.auth_version THEN
        RAISE EXCEPTION 'Account authentication version must not be null or decrease'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.password_hash IS DISTINCT FROM OLD.password_hash
       OR NEW.role IS DISTINCT FROM OLD.role
       OR NEW.is_active IS DISTINCT FROM OLD.is_active THEN
        NEW.auth_version := GREATEST(NEW.auth_version, OLD.auth_version + 1);
    END IF;
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$function$;

CREATE TRIGGER version_account_update
BEFORE UPDATE ON regintel.users
FOR EACH ROW EXECUTE FUNCTION regintel.version_account_update();

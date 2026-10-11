# M0.4 — Authentication implementation decisions

Date:2026-10-05 (Asia/Calcutta). Prerequisite/requirements analysis completed before implementation. This supplements unchanged final specifications; it is not the M0.5 shared-contract freeze.

Status: **complete and verified**. See PHASE_LOG for actual commands/fixes and backend/README for runnable operator commands.

## Requirements and prerequisites

Build M0.4 requires JWT application authentication and seeded admin/learner roles. Architecture makes PostgreSQL users/roles authoritative and keeps authorization in application code. M0.1–M0.3 passed first. Existing PostgreSQL, Neo4j and Redis are healthy; no installation or infrastructure replacement is needed. The deck gate applies before M1, not M0.4. Windows/M0 approvals persist.

Inspect/reuse current app factory, typed configuration, SCRAM local DB connection, transaction/checksum migration runner and isolated live test helper. Official Python3.12-compatible dependency versions/licenses were verified before installation: PyJWT2.15.1/MIT, pwdlib[argon2]0.3.1/MIT and python-multipart0.0.32/Apache-2.0. Sources/policy are recorded in dependency_versions. No new ORM, Redis client, browser feature, registration API, refresh-token system or business endpoint is required here.

## Recorded implementation decisions

- New0002 auth migration;0001 bytes/checksum remain immutable. Users have server-generated UUIDv4 IDs, unique normalized ASCII usernames (3–64 characters), Argon2id hashes, role admin|learner, active flag, positive auth_version and timestamps. Security-relevant DB changes invalidate tokens by incrementing auth_version.
- PostgreSQL generates IDs with gen_random_uuid() and enforces both version4 and the RFC variant on explicit IDs. Final0002 SHA256:c4b6a5f95f313e527182804ff2c0263f0661a41a3fd648038795930420f05291.
- POST /v1/auth/token uses the OAuth2 password form and returns its standard token response. GET /v1/auth/me returns safe account identity; GET /v1/auth/admin/me demonstrates actual admin authorization without adding M1 features. Existing health remains public and configuration-independent.
- Fixed HS256 allowlist; new project-local secret contains256 random bits. Require and strictly validate issuer, audience, UUIDv4 subject/JTI, integer issued/expiry timestamps and auth_version. Default lifetime1800 seconds, explicit bounded configuration; token lifetime must match selected configuration. Tokens carry no authoritative role: reload role/active/version from PostgreSQL on each request.
- Argon2id verification preserves password bytes. Bound passwords and tokens before expensive work; dummy verification for unknown usernames. Generic401/Bearer challenge for invalid authentication,403 for role denial and sanitized503 for unavailable configuration/DB. Auth validation responses omit input values and all auth responses prohibit caching.
- Explicit root .env holds existing database configuration; new ignored .env.auth holds new JWT/seeding configuration. No import-time secret loading. A native launcher explicitly loads selected files; the original liveness launcher can remain usable with protected routes failing closed.
- Exclusive auth-secret generation refuses overwrite. Seed both users in one serialized transaction; repetition preserves UUID/hash/role/active/version. Conflicting existing accounts cause safe rollback, never credential/role resets. No passwords/tokens printed, passed through CLI arguments or committed.
- Add POST to configured CORS methods for browser login, retaining origin restrictions and Bearer headers. Auth schema/envelope choices remain confined to M0.4; M0.5 owns broader contracts.

## Verification gate

Verify crypto/claims, valid/invalid credentials, role denial, immediate revocation, inactive/deleted users, no secret-bearing errors, configuration/DB failures and CORS. Live PostgreSQL tests must cover clean installation,0001→0002 upgrade, idempotent/concurrent seeding and conflict rollback. Preserve migration drift/history/atomicity/concurrency tests with updated expected versions. Then run strict lint/format/typing, default backend suite, live integration helper and the full foundation runner. Review code and synchronize state/log/continuation before advancing to M0.5.

Completed gate:74 default backend tests,58 live cases with test-DB cleanup, strict lint/format/typing, frontend18/browser3/build and full runner exit0. Local0002 application/repeat/status and both seed invocations/check exited0. Configured native API was tested on an ephemeral loopback port; both logins/identities/admin-role/cache behavior passed and only the owned process was stopped. Hosted CI/Linux/macOS/ARM64 execution remain unverified.

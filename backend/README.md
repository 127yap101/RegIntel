# Backend foundation database commands

The application starts without database settings. Database commands load only the
explicitly selected environment file; unrelated process database secrets do not
override it. Variable interpolation is disabled, so `${...}` cannot import ambient
process secrets into the selected file. Never print the root `.env` or connection URI.

Foundation commands require complete explicit URI credentials and a loopback target.
They set the effective address, port and password explicitly, disable SSL/GSS for this
local container connection, and refuse ambient libpq service selectors. They do not
obtain credentials from existing password/service files. Authentication requires
SCRAM-SHA-256 using libpq 16 or newer; trust/SSPI/GSS authentication cannot replace
the selected password. Remote deployment requires
its own reviewed connection configuration.

From the repository root, after infrastructure is healthy:

```powershell
.tools/uv/uv.exe run --project backend --locked --no-sync regintel-db status --env-file .env
.tools/uv/uv.exe run --project backend --locked --no-sync regintel-db migrate --env-file .env
.tools/uv/uv.exe run --project backend --locked --no-sync regintel-db check --env-file .env
```

The check command expects PostgreSQL 16.15 and pgvector 0.8.7. An intentional tested
pin change must update the version record and the explicit expected-version options.
The default SQL directory is `infra/migrations`; `--migrations-dir` overrides it.

SQL files must be consecutive `0001_descriptive_name.sql` UTF-8 files with LF
newlines. Applied names and raw-byte SHA-256 checksums are immutable. A transactional
advisory lock serializes runners, and each invocation applies all pending files in
one transaction. SQL runs through safely quoted PL/pgSQL dynamic execution, which
rejects transaction-control commands rather than allowing a script to commit early.
Migration SQL must not manage transactions itself. Unknown,
changed, missing or out-of-order applied migrations fail without rewriting history.

The preferred verified helper creates a fresh UUID-named local test database, runs
the integration selection, and removes only that newly created database. It never
overwrites an existing test database or forcibly disconnects other sessions:

```powershell
.tools/uv/uv.exe run --project backend --locked --no-sync python scripts/check-migrations.py
```

For manually provisioned test databases, integration tests require `REGINTEL_TEST_DATABASE_URL` to explicitly identify a
loopback database named `regintel_test_...`. They clear only the test database's
`regintel`/`regintel_meta` schemas and vector extension before and after each test.
Create that disposable database separately; these tests never create databases or
start services. Missing configuration fails rather than skipping.

```powershell
.tools/uv/uv.exe run --project backend --locked --no-sync pytest backend/tests -m integration
```

Default foundation pytest runs explicitly exclude the integration marker and remain
independent of Docker. An integration gate requires the separate command to pass.

The M0.3 phase adds `psycopg[binary]==3.3.6` for native PostgreSQL connectivity and
migrations; `uv.lock` pins its binary distribution and transitive dependencies.
The explicit environment-file parser is `python-dotenv==1.2.4` (BSD-3-Clause), already
resolved by the settings dependency and declared directly for this new import.
Psycopg and its binary distribution use LGPL-3.0-only. Preserve their license notices
and the bundled library notices when distributing dependencies. No ORM, connection
pool, graph/Redis client, parsing or model dependency is introduced here.

## M0.4 authentication

The auth dependency pins are PyJWT2.15.1 (MIT), pwdlib[argon2]0.3.1 (MIT) and
python-multipart0.0.32 (Apache-2.0). Argon2id uses64MiB,time3,parallelism4 with
random16-byte salts. The new0002 migration adds accounts and a DB trigger that
invalidates old JWTs on password/role/active changes. Preserve0001 and every applied
checksum; append migrations rather than modifying history.

First-time auth setup from the root (the existing database .env is reused):

```powershell
.tools/uv/uv.exe run --project backend --locked --no-sync python scripts/init-auth-env.py
.tools/uv/uv.exe run --project backend --locked --no-sync regintel-db migrate --env-file .env
.tools/uv/uv.exe run --project backend --locked --no-sync regintel-auth seed --env-file .env --auth-env-file .env.auth
.tools/uv/uv.exe run --project backend --locked --no-sync regintel-auth check --env-file .env --auth-env-file .env.auth
.tools/uv/uv.exe run --project backend --locked --no-sync regintel-api --env-file .env --auth-env-file .env.auth
```

The generator refuses an existing .env.auth. Keep that ignored file private; account
names are admin/learner, and generated passwords belong only in the local file.
Seed repetition preserves existing IDs/hashes/roles/active/version. A conflicting
existing account rolls back the entire seed; no reset/reactivation occurs. Windows
secret protection follows inherited NTFS ACLs, not a promise of Unix-only permissions.

The native API listens on127.0.0.1:8000 and disables access logging of request URLs.
POST /v1/auth/token takes OAuth2 form fields grant_type=password, username and
password and returns access_token/token_type/expires_in. Send the token via
Authorization: Bearer for GET /v1/auth/me; GET /v1/auth/admin/me requires admin.
Tokens last1800 seconds by default (explicit config60–3600), have fixed HS256,
issuer/audience and strictly validated UUID/timestamp/version claims. Roles come
from a fresh authoritative DB read, not JWT claims. All auth responses prohibit
caching; failures are generic401/Bearer,403 role denial, sanitized422 or503.
There is no registration/refresh-token endpoint or business feature in this phase.

The original uvicorn regintel.main:app command still runs public liveness without
reading auth/database files. Its auth routes fail closed503; use regintel-api for
configured authentication.

## M0.5 shared contracts

GET /v1/auth/me and GET /v1/auth/admin/me return `{data,meta}`. JSON API failures
return `{error:{code,message,details},meta}` with the original HTTP status. Metadata
contains a fresh server request UUID, contract version1.0.0 and explicit null
versions where no corpus/module version applies. X-Request-ID matches metadata.
OAuth2 token responses and liveness retain their protocol shapes; auth no-store,
Bearer challenges, Allow and CORS headers are preserved. Error responses omit
submitted values, dynamic field names and internal exception text.

Python contracts in `src/regintel/contracts/` define strict IDs, financial context,
exact Decimal-string serialization, evidence geometry, relations and amendment
references. They validate shape only; M1 still owns source membership, evidence
support, acceptance, lineage resolution and publication.

From the repository root, generate ignored frontend artifacts after editing Python
contracts, then verify drift without changing generated files:

```powershell
.tools/uv/uv.exe run --project backend --locked --no-sync python scripts/export-contracts.py
.tools/uv/uv.exe run --project backend --locked --no-sync python scripts/export-contracts.py --check
```

The curated source `contracts/parity-vectors.json` exercises the same wire payloads
through Pydantic and the actual frontend Ajv validator. Synthetic parity checks
are engineering verification, not real-filing extraction results.

## M0.6 synthetic fixtures

Frozen source recipes in `src/regintel/fixtures/sources.py` generate three invented
PDFs with six pages: a four-page base source, a one-page explicit corrigendum and a
one-page unresolved later conflict. They include native text, financial table and
merged-header context, separate cross-page evidence, negative raw media/crop
offsets, all four allowed rotations and a raster-only page without hidden text.
The manifest carries source recipes, SHA-256 hashes and authored M0.5 evidence.

The adversarial suite contains 31 cases: 29 structural payload cases and two mocked
provider events. It covers all 18 runtime-contract adversarial categories, with
positive examples and separate expected future gate outcomes. Backend Pydantic
and frontend runtime validation check the structural cases. Timeout/refusal events
are authored test data; they make no provider call.

Generate the PDF family and frontend case data from the repository root, then
check for missing or changed artifacts without rewriting them:

```powershell
.tools/uv/uv.exe run --project backend --locked --no-sync python scripts/generate-fixtures.py
.tools/uv/uv.exe run --project backend --locked --no-sync python scripts/export-fixture-cases.py
.tools/uv/uv.exe run --project backend --locked --no-sync python scripts/generate-fixtures.py --check
.tools/uv/uv.exe run --project backend --locked --no-sync python scripts/export-fixture-cases.py --check
```

PDFs and `manifest.json` belong only in ignored `artifacts/fixtures/`; frontend case
data is ignored at `frontend/src/contracts/fixtures.generated.json`. The PDF helper
creates missing files exclusively, preserves identical existing files and refuses
conflicting content, unexpected directory entries, alternate output paths and
links/junctions. It does not delete or replace existing artifacts. Both `--check`
commands detect drift without writing. Keep render-review images in a separate
ignored directory so they do not become unexpected fixture entries.

At M0.6 the backend lock resolved 47 packages. Its added development pins were
`reportlab==5.0.1`, `pypdf==6.19.0`, `pillow==12.3.0` and
`types-reportlab==5.0.0.20260911`; ReportLab's transitive
`charset-normalizer==3.5.2` is also locked. ReportLab generates PDFs, pypdf inspects
their structure and Pillow produces the raster page. The stubs support strict
mypy without suppressing ReportLab imports. At that phase these dependencies
added no runtime parsing, OCR or model service. M1.2 subsequently promotes the
same pypdf pin to runtime for original-PDF structure validation, as described below.

Repeated generation is verified on the tested Windows/Python environment; byte
parity across operating systems remains unverified. Evidence and transcriptions
are authored fixture expectations, not measured Docling/OCR results or research
gold data. Source membership, exact support/context gates, reviewed acceptance,
amendment resolution and publication remain future M1 work. On2026-10-06 the user
explicitly waived the presentation gate and approved the Linux worker placement;
the deck itself remains unverified.

## M1.2 upload/jobs — verification pending

The user authorized M1A and approved one non-root Linux Celery worker on the
existing Compose network. FastAPI and the frontend remain native Windows; the
worker reuses PostgreSQL/Redis, has no published port and mounts ignored
`data/uploads` read-only. Sources are retained as exact original bytes under
`sha256/<hash>.pdf`; neither original PDFs nor generated source artifacts belong
in Git.

The backend lock now resolves61 packages. Runtime pins are
`celery[redis]==5.6.3` and `pypdf==6.19.0`, both BSD-3-Clause. pypdf was promoted
from development use for bounded PDF structure/page/encryption checks. The
digest-pinned worker image build succeeded with43 production packages using
uv0.12.23 and Python3.12.15; the native API/tests use Python3.12.14. Live worker
delivery/restart and final M1.2 checks remain pending. Docling, OCR and model
packages/artifacts are not yet installed.

Run the configured native API from the repository root after existing services,
reviewed migrations and local accounts are ready:

```powershell
.tools/uv/uv.exe run --project backend --locked --no-sync regintel-api --env-file .env --auth-env-file .env.auth
```

This command initializes ignored source directories and listens only on
127.0.0.1:8000. In another terminal, explicitly build/start the approved worker;
the base infrastructure `up` command does not activate the ingestion profile:

```powershell
./scripts/compose.ps1 worker-build
./scripts/compose.ps1 worker-up
./scripts/compose.ps1 worker-status
./scripts/compose.ps1 worker-restart
./scripts/compose.ps1 worker-stop
```

The last two commands perform the named action when needed; they are not required
after every upload. Bash equivalents:

```bash
bash scripts/compose.sh worker-build
bash scripts/compose.sh worker-up
bash scripts/compose.sh worker-status
bash scripts/compose.sh worker-restart
bash scripts/compose.sh worker-stop
```

Build/start reuse the existing `.env`, named data volumes and Compose services;
no source credentials or expanded Compose environment should be printed.

Authenticate with `POST /v1/auth/token`, then send the administrator Bearer token
in the Authorization header. `POST /v1/filings` accepts a raw `application/pdf`
body with query metadata:

| Query field | Requirement |
|---|---|
| `company_name_raw` | Required raw company label; no canonical entity acceptance |
| `document_type` | Required: `DRHP`, `RHP`, `PROSPECTUS`, `ADDENDUM` or `CORRIGENDUM` |
| `source_url` | Optional HTTPS source URL without credentials/fragment |
| `published_on` | Optional supported ISO date; not a financial period/effective date |
| `declared_parent_filing_version_id` | Optional registered compatible parent; not a recorded amendment effect |

For example, send PDF bytes to
`/v1/filings?company_name_raw=Example%20Company&document_type=RHP` using
`Content-Type: application/pdf` and the authenticated header. Keep tokens out of
URLs and terminal output. Uploads are bounded by64MiB actual streamed bytes and
2000 pages. Successful submission returns202 with a `{data,meta}` job envelope;
repeat source/metadata/configuration returns the same job, while conflicting
metadata returns409. This is ingestion identity, not acceptance/publication.

Administrators read `GET /v1/filing-jobs/{job_id}` with the same Bearer header.
States are `QUEUED`, `RUNNING`, `SOURCE_VERIFIED` and `FAILED`. `SOURCE_VERIFIED`
means original hash/byte size/PDF structure were checked, not that Docling parsed
or accepted any fact. Response metadata retains the filing version, with parse
and corpus versions null at this stage. Error/job responses sanitize diagnostics
and prohibit caching.

PostgreSQL commits filing/job identity and dispatch intent before broker I/O.
Broker failure preserves an unsent intent. Replay through the existing Redis:

```powershell
.tools/uv/uv.exe run --project backend --locked --no-sync regintel-dispatch --env-file .env
```

Replay sends only canonical job IDs; duplicate deliveries consult authoritative
job state. Full checkpointed pipeline recovery belongs to M1.8. The optional
worker profile does not make the default Docker-free checks a live worker gate;
the separate disposable database checks and actual producer/worker acceptance
must pass before this phase is marked complete.

The Unix read-permission contract for public filing sources is0755 directories
and0644 PDF files so the fixed UID/GID10001 worker can read a native-user bind
mount. This contract is not yet enforced or tested; a restrictive umask can deny
access. Windows is the measured host target. Do not treat the Linux worker image
build as macOS, ARM64 or native-Linux API reproduction.

Primary references: [Psycopg package](https://pypi.org/project/psycopg/),
[installation and supported platforms](https://www.psycopg.org/psycopg3/docs/basic/install.html),
[transaction behavior](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
## M1.5 native entity setup

Native development/CI installs the locked `entities` extra (`uv sync --project backend --locked --extra entities`); both bootstrap scripts select it. It supplies spaCy3.8.16/RapidFuzz3.14.6 for the administrator entity endpoints. The parser worker selects only `parsing`, preserving its separate frozen package manifest. No pretrained NER model is required. See [M1.5 contracts and real proof](../docs/M1_5_ENTITY_RESOLUTION.md).

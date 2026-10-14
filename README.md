# RegIntel Finance

Evidence-Grounded Regulatory Filing Knowledge Graph & Financial Learning Platform.

A six-week capstone exploring **Amendment-Aware Evidence-Constrained Corporate Relation Extraction** for Indian public-issue filings, with comparison, financial learning and deterministic virtual portfolios.

## Start here

- `AGENTS.md`: operating contract, evidence rules and specification navigation.
- `CURRENT_STATE.md`: latest implementation/verification status and exact resume direction.
- [Run/check/sleep guide](docs/RUN_AND_CHECK.md): current app/API launch commands, saved proof, verification and safe pause/resume.
- `docs/README.md`: finalized specification index.
- `docs/IMPLEMENTATION_PLAN.md`: authorized phase sequence and acceptance gates.
- `docs/PHASE_LOG.md`: actual execution history and unresolved work.
- `docs/PREREQUISITES.md`: environment/setup requirements and approved decisions.

## Current scope

M0/M1A and M1.5–M1.7 are verified on the approved Windows/native API host. The controlled Premier source retains 878 exact evidence records, 40 entity mentions and one immutable conditional narrative proposal. M1.7 adds mandatory source/context/semantic checks, proposed Decimal interpretation, quarantine and immutable staged decisions. Candidates remain unaccepted; no financial observation or corpus is published. Migrations 1–8 are applied, with earlier bytes preserved.

Final local checks pass 1,691 backend tests with six disclosed Windows skips, 90 final live validation cases, 212 frontend tests and three Chromium tests, plus lint/types/build. The earlier full 398 database cases passed before the final currency/unit repair; the expanded final validation suite verifies that repair. These are engineering checks, not measured research effectiveness. See [validation/review scope](docs/M1_7_VALIDATION_REVIEW.md), [measured proof](data/validation-review-report.json), [current state](CURRENT_STATE.md) and [continuation prompt](docs/CONTINUATION_PROMPT.md).

M1.8 worker recovery is next. Amendment/publication, company/graph/review experiences and held-out evaluation remain unfinished. Provider boundaries use offline mocks; live Gemini transport/model selection and paid benchmarking remain pending. No dependency/env change or worker rebuild occurred. The historical parser image selects only `parsing`; native setup/CI selects `entities`. Original PDFs/models/credentials/database state stay out of Git.

For authenticated ingestion/evidence/entity/candidate/validation APIs, complete the documented local database/auth setup and run `regintel-api --env-file .env --auth-env-file .env.auth` from the configured backend environment. The plain uvicorn command below supplies process liveness only.

## Verified foundation commands

Use Node24.19.0 and pnpm11.19.0. From the repository root:

```powershell
.\scripts\bootstrap.ps1
.\scripts\run-checks.ps1
.\.tools\uv\uv.exe run --project backend --locked --no-sync uvicorn regintel.main:app --host 127.0.0.1 --port 8000
```

In another terminal: `pnpm --dir frontend dev`, then visit `http://127.0.0.1:5173`. Bootstrap installs pinned project-local dependencies/browsers; checks install nothing. The full check runner starts and stops its own servers, so leave ports8000/5173 free. Windows Playwright process cleanup requires normal local process permissions; this Codex sandbox needed an approved outside-sandbox verification run. Linux/macOS use the corresponding `.sh` scripts with the pinned uv installed first; Linux browser OS dependencies must be explicitly installed. Prior M1.6 hosted CI passed on Windows/Linux and Linux data infrastructure; the current source checkpoint requires its own hosted result, recorded in CURRENT_STATE.

With the existing Docker Desktop Linux engine running and the already generated ignored root `.env`, infrastructure checks use:

```powershell
.\scripts\compose.ps1 status
.\.tools\uv\uv.exe run --project backend --locked --no-sync regintel-db status --env-file .env
.\.tools\uv\uv.exe run --project backend --locked --no-sync python scripts/check-migrations.py
```

The helper owns and removes only a new disposable test database. See [infra/README.md](infra/README.md) for setup/restart checks. The final M0.6 runner passes319 backend tests,212 frontend tests and3 browser tests;58 live migration/auth cases passed separately at M0.5 closure. Container persistence was verified through an orderly restart. After an initial2026-10-06 socket startup failure, the user started Desktop and all services recovered; no runtime-directory change was performed.

Bootstrap generates the ignored JSON Schema and TypeScript declarations from the Python contract source. After changing that source, regenerate from the root:

```powershell
.\.tools\uv\uv.exe run --project backend --locked --no-sync python scripts/export-contracts.py
.\.tools\uv\uv.exe run --project backend --locked --no-sync python scripts/export-contracts.py --check
```

The check runner detects artifact drift without overwriting files. [Shared-contract decisions](docs/SHARED_CONTRACTS.md) describe exact decimal strings, evidence geometry, versions, relation directions and protocol exceptions.

Bootstrap also generates three labelled synthetic PDFs/six pages and a manifest under ignored `artifacts/fixtures`, then exports the31 authored fixture cases for frontend structural parity. To verify or regenerate them:

```powershell
.\.tools\uv\uv.exe run --project backend --locked --no-sync python scripts/generate-fixtures.py
.\.tools\uv\uv.exe run --project backend --locked --no-sync python scripts/export-fixture-cases.py
.\.tools\uv\uv.exe run --project backend --locked --no-sync python scripts/generate-fixtures.py --check
.\.tools\uv\uv.exe run --project backend --locked --no-sync python scripts/export-fixture-cases.py --check
```

PDF generation creates missing files and preserves identical files; it refuses changed or unexpected outputs and linked paths. Preserve/review existing generated files before regenerating after a recipe change. [Fixture scope and verification](docs/FIXTURES.md) separates current wire-shape checks from authored expectations for future evidence/context gates. These invented sources are engineering fixtures, with no real-filing performance claim.

Use the already generated private .env/.env.auth to run the configured native API:

```powershell
.\.tools\uv\uv.exe run --project backend --locked --no-sync regintel-api --env-file .env --auth-env-file .env.auth
```

[backend/README.md](backend/README.md) documents OAuth2 login, Bearer identity/admin access and seed commands. Accounts are seeded and repeat seeding preserves them. Auth settings are loaded explicitly; the original liveness command keeps protected routes closed503. There is no auth UI yet.

Never commit secrets, original filing PDFs, model caches or generated artifacts. PostgreSQL is authoritative; all graph/retrieval data derives from validated, versioned state.

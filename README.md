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

M0, M1A (1.1–1.4) and M1.5 entity resolution are verified on the approved Windows/native API baseline with the existing Linux parser worker. The controlled Premier source retains878 exact records; its immutable entity run has40mentions (6resolved,1review,33unresolved). Source-backed registry/review, replay, authentication and unchanged source/job/financial state are verified. Migration0006 is applied;0001–0005 remain frozen. Tests pass1116backend with six Windows skips,208live database,212frontend and3Chromium, plus lint/types/build. These are engineering checks, not research accuracy. No financial facts or corpus are accepted/published.

Next is M1.6 candidate extraction; later validation/amendment/publication, user-facing modules and evaluation remain unfinished. Native setup/CI selects the locked `entities` extra; the parser worker selects only `parsing`. Existing parser/table/OCR limits remain. Original PDFs/models/credentials/database state are not in Git. See [current state](CURRENT_STATE.md), [M1.5 setup/contracts](docs/M1_5_ENTITY_RESOLUTION.md), [measured entity proof](data/entity-validation-report.json) and [continuation prompt](docs/CONTINUATION_PROMPT.md).

The plain uvicorn command below provides liveness only. For authenticated ingestion/evidence/entity APIs, complete the documented local database/auth setup and run `regintel-api --env-file .env --auth-env-file .env.auth` from the configured backend environment.

## Verified foundation commands

Use Node24.19.0 and pnpm11.19.0. From the repository root:

```powershell
.\scripts\bootstrap.ps1
.\scripts\run-checks.ps1
.\.tools\uv\uv.exe run --project backend --locked --no-sync uvicorn regintel.main:app --host 127.0.0.1 --port 8000
```

In another terminal: `pnpm --dir frontend dev`, then visit `http://127.0.0.1:5173`. Bootstrap installs pinned project-local dependencies/browsers; checks install nothing. The full check runner starts and stops its own servers, so leave ports8000/5173 free. Windows Playwright process cleanup requires normal local process permissions; this Codex sandbox needed an approved outside-sandbox verification run. Linux/macOS use the corresponding `.sh` scripts with the pinned uv installed first; Linux browser OS dependencies must be explicitly installed. Hosted CI is configured but has not run.

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

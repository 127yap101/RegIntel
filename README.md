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

M0/M1A and bounded M1.5–M1.9 are verified on the approved Windows/native API
host and private Linux worker. The controlled Premier filing retains 878 exact
evidence records and now publishes one complete conditional narrative with its
original review and fresh validation. Source-backed lineage/scoped effects,
historical/active/as-of views, recoverable Neo4j/pgvector/lexical projections and
atomic PostgreSQL corpus publication are implemented. The real parent is absent,
so lineage stays unresolved/effects 0; its unknown publication date produces an
explicit unavailable as-of response. See the [publication record](docs/M1_9_PUBLICATION_PLAN.md),
[measured report](data/publication-validation-report.json) and [current state](CURRENT_STATE.md).

Exact-source hosted [CI38717087117](https://github.com/127yap101/RegIntel/actions/runs/38717087117)
passes Windows 1802/three skips and Ubuntu 1804/one skip,212 frontend/3 Chromium on
each, lint/types/build, and all 469 live database tests with fresh migrations 1–11,
auth and restart persistence. The long native database run records 468 passes/one
storage setup error; all 7 affected cases pass fresh retry. This is engineering
verification, not real amendment-pair or held-out research effectiveness.

Next is M1.10 published company/fact/graph APIs and exact source-page experience,
then retrieval/Q&A and admin/review UI. M2–M4/integration remain unfinished.
Live Gemini transport/model selection and paid benchmarking are pending.
Native setup/CI selects locked entities+publication extras. The private worker
retains its M1.8 parser/stage environments and has not been rebuilt for M1.9.
Original PDFs/models/credentials/database state remain out of Git. Use the
[self-contained continuation prompt](docs/CONTINUATION_PROMPT.md) to resume.

For authenticated ingestion/evidence/entity/candidate/validation APIs, complete the documented local database/auth setup and run `regintel-api --env-file .env --auth-env-file .env.auth` from the configured backend environment. The plain uvicorn command below supplies process liveness only.

## Verified foundation commands

Use Node24.19.0 and pnpm11.19.0. From the repository root:

```powershell
.\scripts\bootstrap.ps1
.\scripts\run-checks.ps1
.\.tools\uv\uv.exe run --project backend --locked --no-sync uvicorn regintel.main:app --host 127.0.0.1 --port 8000
```

In another terminal: `pnpm --dir frontend dev`, then visit `http://127.0.0.1:5173`. Bootstrap installs pinned project-local dependencies/browsers; checks install nothing. The full check runner starts and stops its own servers, so leave ports8000/5173 free. Windows Playwright process cleanup requires normal local process permissions; this Codex sandbox needed an approved outside-sandbox verification run. Linux/macOS use the corresponding `.sh` scripts with the pinned uv installed first; Linux browser OS dependencies must be explicitly installed. M1.7 source hosted CI passed on Windows/Linux and Linux data infrastructure, including the complete final 402 database tests; exact source/run details are recorded in CURRENT_STATE.

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

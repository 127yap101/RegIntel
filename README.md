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
host and private Linux worker. M1.10 now adds published company search, facts,
directed graph reads and a browser filing explorer with exact quoted support
and original PDF pages. Every read stays bound to the selected published corpus
and active/historical/as-of view. Sign in with an existing local learner or admin
account; see the [run/check guide](docs/RUN_AND_CHECK.md).

M1.11 adds authenticated published retrieval and extractive source answers:
dense, filtered dense, BM25/RRF hybrid and bounded graph expansion. Questions
stay pinned to the applied corpus/history/date view. Source links open the exact
original page, and numeric questions require deterministic accepted-value context.
See the [run/check guide](docs/RUN_AND_CHECK.md) to try the Premier offering question.

M1.12 adds an administrator workspace for filing upload/jobs, exact evidence,
quarantine and immutable review decisions, explicit publication drafts and
evidence-backed amendment forms. It works before a corpus is published and uses
the existing audited write APIs; failed mandatory gates cannot be overridden.
See the [run/check guide](docs/RUN_AND_CHECK.md).

Local verification passes 1932 backend/six Windows skips, six new disposable
PostgreSQL cases, 254 frontend unit tests and all 24 Chromium tests, plus
lint/types/build/static checks. The real administrator browser proof preserves
original saved data. Source `4114407` is pushed and
[exact-source GitHub CI](https://github.com/127yap101/RegIntel/actions/runs/38908935402) passes Windows/Linux foundation and Linux data infrastructure,
including the full database command, fresh migrations, authentication and restart
persistence. See [current state](CURRENT_STATE.md), the
[administrator plan](docs/M1_12_ADMIN_REVIEW_PLAN.md) and
[measured report](data/admin-review-validation-report.json).

The real corpus contains one complete conditional narrative, zero corporate
relations and an unresolved parent/effects 0. Its unknown publication date returns
explicit temporal unavailability. This is bounded engineering verification;
real amendment-pair and held-out research effectiveness remain unmeasured.

Bounded M1 implementation is complete. This `codex/m2-comparison` branch adds
the M2 comparison baseline: published profile/evidence integration, exact Decimal
unit scaling, explicit period/basis compatibility, baseline differences and
relative percentage differences with input provenance. Missing, conflicting or
unresolved context blocks arithmetic. Quotes remain explicitly unavailable by
user choice. Comparison baseline `921e6a6` passes
[Windows/Ubuntu and infrastructure CI](https://github.com/127yap101/RegIntel/actions/runs/39007655529).
The original M1 main checkout stays available for manual testing.
See the [M2 plan](docs/M2_IMPLEMENTATION_PLAN.md) and
[current state](CURRENT_STATE.md) for verification and remaining acceptance work.
The [M2 acceptance runner](docs/M2_ACCEPTANCE.md) checks independent expected
values, compatibility states and exact evidence IDs against a pinned published
corpus. Its current real-data plan reports incomplete coverage; it does not
substitute authored test success for real numerical acceptance. Acceptance
workflow source `1840e14` passes
[exact-source Windows/Linux and infrastructure CI](https://github.com/127yap101/RegIntel/actions/runs/39137183719).
The [numerical source-intake handoff](docs/M2_SOURCE_INTAKE.md) records inspected
seed-company filings and outstanding M1 evidence/context requirements; its
candidates are not accepted facts.
M2 acceptance, M3/M4/integration and real-corpus research evaluation remain unfinished.
Live Gemini transport/model selection and paid benchmarking are pending.
Native setup/CI selects locked entities+publication extras. The private worker
retains its M1.8 parser/stage environments and has not been rebuilt for M1.9/M1.10/M1.11/M1.12.
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

In another Windows terminal: `.\.tools\pnpm\pnpm.cmd --dir frontend dev`, then visit `http://127.0.0.1:5173`. Bootstrap installs pinned project-local dependencies/browsers; checks install nothing. The full check runner starts and stops its own servers, so leave ports8000/5173 free. Windows Playwright process cleanup requires normal local process permissions; this Codex sandbox needed an approved outside-sandbox verification run. Linux/macOS use the corresponding `.sh` scripts with the pinned uv installed first and `pnpm --dir frontend dev`; Linux browser OS dependencies must be explicitly installed. Exact-source hosted checks are recorded in CURRENT_STATE.

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

Bootstrap also generates the M1.10 output schemas/types with
`scripts/export-published-reads.py` and labelled authored read/browser fixtures
with `scripts/generate-read-fixtures.py`. Both support `--check` and are included
in the check runner; their generated output remains ignored.

Bootstrap also exports separate retrieval and administrator schema/types/authored
fixtures using `scripts/export-retrieval.py` and `scripts/export-admin.py`.
Both support `--check` and are included in both check runners and CI.

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

[backend/README.md](backend/README.md) documents OAuth2 login, Bearer identity/admin access and seed commands. Accounts are seeded and repeat seeding preserves them. Auth settings are loaded explicitly; the original liveness command keeps protected routes closed503. The browser offers separate published-explorer and administrator sign-ins.

Never commit secrets, original filing PDFs, model caches or generated artifacts. PostgreSQL is authoritative; all graph/retrieval data derives from validated, versioned state.

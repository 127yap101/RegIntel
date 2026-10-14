# Run, inspect and pause RegIntel

M0/M1A, entity resolution and the bounded candidate baseline are implemented.
The frontend currently shows foundation/status and API liveness. Ingestion,
exact evidence/PDFs, entity decisions and unaccepted candidate runs are available
through the backend API. Company/graph/review screens come later.

## Inspect the saved result without starting services

- [Current state](../CURRENT_STATE.md)
- [Measured evidence verification](../data/evidence-validation-report.json)
- [Measured entity verification](../data/entity-validation-report.json)
- [Measured candidate verification](../data/candidate-validation-report.json)
- [Source manifest](../data/manifest.json)
- Persisted CIN highlight: `D:/RegIntel/.cache/evidence-qa-7ce9c9a9d4404e6bae69c6b38385c682/cin-detail.png`

The real Premier job is `PARSED`, with one attempt, three source pages and 878
exact text evidence records. Known OCR/table/currency limitations are recorded;
these records do not constitute accepted financial facts or a published corpus.

## Run the installed app

Open Docker Desktop and wait for its Linux engine to run. These commands reuse
the installed toolchain and data services. Reading persisted records does not
require a parser worker build. New parsing/recovery work must follow the frozen
worker setup; the retained M1A image has not been rebuilt with later native code.

In PowerShell terminal 1:

```powershell
Set-Location D:\RegIntel
.\scripts\compose.ps1 up
.\backend\.venv\Scripts\regintel-api.exe --env-file .env --auth-env-file .env.auth
```

Leave that terminal running. In PowerShell terminal 2:

```powershell
Set-Location D:\RegIntel
.\.tools\pnpm\pnpm.cmd --dir frontend dev
```

Open:

- Frontend: <http://127.0.0.1:5173>
- API explorer: <http://127.0.0.1:8000/docs>
- Public process liveness: <http://127.0.0.1:8000/health/live>

In the API explorer, select **Authorize** and use the generated admin username
and password stored privately in `D:\RegIntel\.env.auth`. Leave optional client
credentials blank. The explorer obtains the bearer token using the configured
password flow. Use **Try it out** on:

- `GET /v1/filing-jobs/{job_id}` with `c81a8c48-2895-4c00-8d88-e45a99bd114e`.
- `GET /v1/evidence/{evidence_id}` with `a2491199-24e3-439f-bba6-3e380db8a28d`.
- `GET /v1/filing-versions/{filing_version_id}/source.pdf` with `295214b3-1c7a-44d4-8201-bf97a986a950`.
- `GET /v1/admin/entities/runs/{run_id}` with `407bc0fa-e97a-4d81-8c9f-126b682e83a7`.
- `GET /v1/admin/candidates/runs/{run_id}` with `6311f8bd-d49d-4fa8-b038-817205e73fff`.

Expected results: `PARSED`, an exact CIN quote with span/geometry/provenance, and
the original source PDF. Admin access is required; the learner role cannot read
these unpublished M1A sources. Keep generated credentials local.

## Check implementation

Read-only schema status (expected applied 1-7, nothing pending):

```powershell
Set-Location D:\RegIntel
.\backend\.venv\Scripts\regintel-db.exe status --env-file .env
```

To rerun verification when desired, first stop the manual API/frontend with
**Ctrl+C** so ports 8000/5173 are free:

```powershell
.\scripts\run-checks.ps1
.\backend\.venv\Scripts\python.exe scripts/check-migrations.py
```

The first runs backend/frontend/browser and static checks. The second requires
running Docker/PostgreSQL and creates/removes only its own disposable database.
Last measured results: 887 backend passes/six Windows skips, 138 live database
passes, 212 frontend passes and three browser passes. These have already passed;
there is no need to rerun them merely to resume the checkpoint.

## Pause before sleep or shutdown

Stop manual API/frontend terminals with **Ctrl+C** if you started them. From the
project PowerShell terminal, stop the worker before its data services:

```powershell
Set-Location D:\RegIntel
.\scripts\compose.ps1 worker-stop
.\scripts\compose.ps1 stop
```

These actions retain the named volumes, database/evidence, source files and
models. Then quit Docker Desktop and use Windows **Start > Power > Sleep** or
**Shut down**. Closing the lid depends on your Windows power setting; choosing
Sleep explicitly avoids assuming that setting. Local processes do not perform
work while the machine is asleep.

When you return, reopen this Codex chat/project and start Docker Desktop if
needed. The checkpoint is in CURRENT_STATE.md and CONTINUATION_PROMPT.md. Say
"Resume from the M1A checkpoint; help resolve Docker storage, then proceed to
M1B." No deck/worker approval needs repeating. Recover adequate space on Docker's
storage drive before a new large image build.

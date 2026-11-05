# Run the current M1–M4 application

Updated 5 November 2026. Use branch `codex/m2-comparison`. This guide covers
matching application code, database schema and source/model assets. A successful
launch does not approve filings, glossary drafts, prices or research results.

## Check configuration before starting

In a normally installed current checkout, use that installation's existing
environment files:

```powershell
.\backend\.venv\Scripts\regintel-api.exe --env-file .env --auth-env-file .env.auth --check
```

The command verifies the checkout's ordered migration names/hashes, parses the
selected authentication settings and verifies parser application-code identity.
It never applies migrations, seeds accounts, starts a server/container or writes
source evidence. Pending migrations stop both check and normal startup, with an
instruction to use the existing `regintel-db migrate --env-file ...` command in
the selected checkout. Unknown/changed history fails with secrets omitted.

`CONFIGURATION_VALIDATED` concerns configuration and schema only. It does not
verify account passwords, model inventory/inference, worker delivery, live
infrastructure or accepted content. Directory-presence fields mean presence
only. Use the existing `regintel-auth check` command separately to verify local
seeded accounts. No common/default password is supplied by Git.

By default, original PDFs live in the checkout's `data/uploads`, the parser
descriptor is `data/parser-runtime-config.json`, and the optional publication
model is `models/bge-small-en-v1.5`. An explicit `--asset-project <directory>`
selects those three locations in an existing installation. It never changes
Python imports or chooses credentials. Invalid assets fail without fallback.
The selected parser descriptor must match installed parser code. Native
numerical review additionally requires its own explicit, matching
`--numerical-runtime-file <descriptor>`; omission leaves that workflow disabled.

## This laptop: integration code with existing assets

The code checkout is `D:\RegIntel\.cache\worktrees\m2-comparison`; the existing
credentials, upload storage and models remain in `D:\RegIntel`. The original
database was upgraded to schema 23 after a verified backup and restore rehearsal.
See the [measured activation result](../data/local-runtime-activation-validation-report.json).
The older
`D:\RegIntel` code checkout is not the current four-module application. Its
historical schema-11 runtime probes must not be used as current-schema checks.

Open Docker Desktop and start the configured services if necessary:

```powershell
Set-Location D:\RegIntel
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\compose.ps1 up
```

In the API terminal, explicitly load current code and retain existing assets:

```powershell
Set-Location D:\RegIntel\.cache\worktrees\m2-comparison
$env:PYTHONPATH = 'D:\RegIntel\.cache\worktrees\m2-comparison\backend\src;D:\RegIntel\.cache\worktrees\m2-comparison'
$apiOptions = @(
  '--env-file', 'D:\RegIntel\.env',
  '--auth-env-file', 'D:\RegIntel\.env.auth',
  '--asset-project', 'D:\RegIntel',
  '--numerical-runtime-file', 'D:\RegIntel\.cache\worktrees\m2-comparison\data\parser-runtime-config.json'
)
& D:\RegIntel\backend\.venv\Scripts\regintel-api.exe @apiOptions --check
# Start only after the check succeeds and no API already owns port 8000.
& D:\RegIntel\backend\.venv\Scripts\regintel-api.exe @apiOptions
```

In a second terminal, start the frontend from the same current checkout:

```powershell
Set-Location D:\RegIntel\.cache\worktrees\m2-comparison
$env:PATH = "D:\RegIntel\.cache\worktrees\m2-comparison\.tools\node-v24.19.0-win-x64;$env:PATH"
& D:\RegIntel\.tools\pnpm\pnpm.cmd --dir frontend dev
```

Open <http://127.0.0.1:5173/>; API documentation is at
<http://127.0.0.1:8000/docs>. Use one API/frontend instance per port. An occupied
port requires identifying the existing process; launching another instance does
not replace it. If the agent has already left the current runtime running, use
that runtime directly. API liveness alone does not establish sign-in/data readiness.

New asynchronous ingestion/processing also needs the approved worker with
matching processing code, parser descriptor and source/model mounts. Viewing
persisted data and editing learning drafts do not require a new parse. See the
activation record for the selected worker image/lifecycle; never start a stale
worker merely to populate a screen. No new service or public port is introduced.

The 5 November activation selected the verified current image
`664596a1899d23bdf718bcf459dd13ba412646e690eec566408398072bd10bc4` as
`regintel-ingestion:local`. The preceding image remains tagged
`regintel-ingestion:before-runtime-20261104`. To restart this already-selected
worker with the original asset mounts after Docker stops:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\RegIntel\scripts\compose.ps1 worker-up
```

This command does not rebuild the image. A later processing-code change requires
a verified image built from the current integration checkout; building from the
older original `main` checkout would select old processing code. Worker health
was checked after activation, with no new ingestion task submitted.

## What to test

Sign in with this installation's existing local account. The learner explorer
should retain the original published conditional narrative and original PDF.
Numerical comparison still needs genuine accepted/published numerical inputs;
the current real inputs remain unresolved. The administrator numerical queue
shows only this database's actual retained checks, not IDs from disposable tests.

In Financial learning, an administrator can inspect the seven unreviewed starters
and save/review/publish content as separate actions. An empty reviewed glossary
is expected until genuine decisions are recorded. In Virtual portfolio, users
can create their own virtual account and inspect history. Quotes remain
unavailable, so submitted valid orders retain `QUOTES_UNAVAILABLE` and no cash
movement. No successful priced runtime trade or financial approval is implied.

Follow the [team acceptance checklist](TEAM_ACCEPTANCE_CHECKLIST.md),
[numerical workflow](NUMERICAL_ADMIN_WORKFLOW.md) and
[learning/portfolio guide](M3_M4_RUN_AND_TEST.md) for module-specific steps.

## Another computer

Follow [teammate setup](M1_TEAM_TESTING.md) using `codex/m2-comparison` and the
current [module setup](M3_M4_RUN_AND_TEST.md). Initialize new credentials only for
a genuinely new installation. A fresh clone contains neither the laptop's
database nor its PDFs, models, passwords or accepted corpus. Existing credentials
must match existing database volumes; regenerating secret files does not update
accounts. Keep private backup/source assets out of Git.

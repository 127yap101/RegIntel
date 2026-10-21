# M1 testing on another computer

GitHub supplies source code, locked dependency lists, schemas, specifications
and measured engineering reports. It does not supply another machine's accounts,
passwords, Docker volumes, PostgreSQL corpus, original PDFs or model files.
`http://127.0.0.1:5173` refers to the computer opening that address.

The commands below are for a teammate's own installation. Preserve the existing
M1 checkout and manual-testing database on Yash's laptop. Do not switch that
checkout to the M2 branch or apply M2 preparation migrations to its database.

## Install and initialize a teammate's Windows environment

For the M1 release, use `main` in a new clone. Development on M2 uses
`codex/m2-comparison` in its own checkout and database configuration.

```powershell
git clone --branch main https://github.com/127yap101/RegIntel.git
cd RegIntel
```

Install the documented prerequisites first: Docker Desktop with the Linux
engine, Node24.19.0 and pnpm11.19.0. The checked-in Windows bootstrap downloads
project-local uv0.12.23 and Python3.12.14, verifies the uv download checksum,
installs locked native entities/publication dependencies and frontend packages,
and generates the ignored schemas/test artifacts. It also installs the project's
Chromium test browser. Docling stays in the approved private Linux worker.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

Start Docker Desktop and wait for its engine. On a genuinely new installation,
initialize local credentials, infrastructure, database and accounts:

```powershell
if (-not (Test-Path .env)) {
    .\backend\.venv\Scripts\python.exe scripts/init-local-env.py
}
if (-not (Test-Path .env.auth)) {
    .\backend\.venv\Scripts\python.exe scripts/init-auth-env.py
}
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\compose.ps1 up
.\backend\.venv\Scripts\regintel-db.exe migrate --env-file .env
.\backend\.venv\Scripts\regintel-auth.exe seed --env-file .env --auth-env-file .env.auth
.\backend\.venv\Scripts\regintel-auth.exe check --env-file .env --auth-env-file .env.auth
```

The last command must report that authentication passed for both seeded roles.
Existing setup files must match that machine's existing Docker database and
accounts. Keep them when reusing an installation; generating different credentials
does not update an existing database or account. Seed conflicts require diagnosing
the mismatch, not deleting volumes or resetting accounts.

In terminal1, start the configured API:

```powershell
.\backend\.venv\Scripts\regintel-api.exe --env-file .env --auth-env-file .env.auth
```

In terminal2, from the same repository root:

```powershell
pnpm --dir frontend dev --host 127.0.0.1 --strictPort
```

Keep both terminals running. Open <http://127.0.0.1:5173/>. The generated
`.env.auth` contains this installation's `REGINTEL_SEED_LEARNER_PASSWORD` and
`REGINTEL_SEED_ADMIN_PASSWORD`; there is no shared default password.
Use `learner` in the published explorer or `admin` in Administrator workspace,
unless the local username settings were explicitly changed.

The PowerShell policy option applies only to the invoked process. Project scripts
do not require a system-wide execution-policy change. macOS/Linux have the
corresponding bootstrap/Compose `.sh` scripts and native `uv run --project backend`
entry points; use the documented platform prerequisites. Hosted Windows/Linux
engineering CI does not establish a complete real-data fresh-clone reproduction
on macOS/ARM or on every teammate's machine.

## What can be tested with a fresh database

Authentication, API liveness, the administrator workspace and empty work queues
can be checked after initialization. The administrator workspace operates before
the first corpus is published. API documentation is at
<http://127.0.0.1:8000/docs>; liveness alone does not prove sign-in or data readiness.

A fresh database has no reviewed published filings. The learner explorer loads
the published corpus immediately after authenticating, so it can report missing
published data even when the credentials are valid. `regintel-auth check` verifies
credentials independently of that corpus load.

Authored unit/browser/database scenarios are provided for engineering tests.
They do not populate the local real-filing corpus and must not be presented as
accepted real financial data. Use the existing [run/check guide](RUN_AND_CHECK.md)
for test commands and their port requirements.

## How to test the same filing demo

The repository does not currently include a one-command, populated Premier demo
import. The current local demonstration has one reviewed conditional narrative,
with no accepted numerical/relation positive or supported amendment pair.

To reproduce it, a teammate needs the controlled original sources and pinned
model assets, followed by the actual upload, parse, registry/metric setup,
extraction, validation, review and publication workflow. Source URLs, hashes and
recorded scope are described in the checked-in manifests/plans. Never fabricate
reviewer decisions or seed fake accepted facts to make a screen appear populated.
New processing also needs the documented model acquisition and private worker
build/start; viewing existing persisted data does not require a worker build.

A separately prepared data handoff must preserve authoritative PostgreSQL
observations, audits, corpus versions and matching source assets. Neo4j and
retrieval projections remain rebuildable from approved authoritative state.
Copying PDFs alone does not recreate accepted observations or a published corpus.
Keep passwords, auth settings and original PDFs out of Git.

For teammates who only need product testing, a shared test instance with the same
reviewed corpus and individual accounts would simplify access. It requires a
separate hosting/access setup; no shared or public deployment is supplied by the
current localhost development setup.

## Recognize common errors

| Message | Meaning and first check |
|---|---|
| “Sign-in failed. Check your username and password.” | The login endpoint returned401. Verify this machine's seeded account/password with `regintel-auth check`. |
| “Published data could not be loaded. Please retry.” | A request could not complete successfully. Check API reachability and the failing request; this message alone does not prove whether authentication succeeded. |
| “No matching resource is published in this view.” | The request returned404; check whether a corpus has actually been published. |
| Windows error10048 on port8000 | Another process already owns the API port. Use the running API or identify its owner before changing anything. |

The form clears its password field after each submitted attempt. Diagnose with
HTTP statuses and safe terminal errors; no password or token needs to be shared.

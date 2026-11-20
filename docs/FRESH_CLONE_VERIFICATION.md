# Fresh-clone engineering verification

19 November 2026. Tested source revision:
`8624aa624dcb05d5e12633f4b7eae76fdff76b82` on `codex/m2-comparison`.
The clone was downloaded from GitHub into a separate project-cache directory.
It used its own new `backend/.venv` and `frontend/node_modules`; application
imports were checked to resolve inside that clone.

Measured results: **17 unit tests, nine database tests and23 browser tests pass**,
along with all10 generators and the production build. Both owned databases were
removed and the clone's final source status is clean. The selected Chromium run
passed on its first attempt in3.5minutes. See
[the measured report](../data/fresh-clone-validation-report.json) for scopes,
limitations and private artifact hashes.

This was a Windows x64 reproduction with existing pinned tools, package caches,
Chromium and the already running project PostgreSQL service. It was not a blank
operating-system installation or a macOS test. No original credentials, database,
PDFs, models or accepted content were copied into the clone. A teammate starting
on a new computer should follow [setup](M1_TEAM_TESTING.md) and
[the current four-module run guide](M3_M4_RUN_AND_TEST.md).

## Repeat against the existing laptop infrastructure

Use a fresh destination and verify the exact source revision. The following paths
refer to this laptop's existing tools; they are not prerequisites at these exact
locations on another machine.

```powershell
$verifyRoot = Join-Path 'D:\RegIntel\.cache' ('repro-' + [guid]::NewGuid().ToString('N'))
git clone --single-branch --branch codex/m2-comparison https://github.com/127yap101/RegIntel.git $verifyRoot
Set-Location $verifyRoot
git checkout --detach 8624aa624dcb05d5e12633f4b7eae76fdff76b82

$env:UV_CACHE_DIR = 'D:\RegIntel\.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = 'D:\RegIntel\.tools\python'
$env:UV_PYTHON_DOWNLOADS = 'never'
& D:\RegIntel\.tools\uv\uv.exe sync --project backend --locked --offline `
  --python D:\RegIntel\.tools\python\cpython-3.12.14-windows-x86_64-none\python.exe `
  --extra entities --extra publication

$env:PATH = 'D:\RegIntel\.cache\worktrees\m2-comparison\.tools\node-v24.19.0-win-x64;D:\RegIntel\.tools\pnpm;' + $env:PATH
pnpm --dir frontend install --offline --frozen-lockfile --store-dir D:\RegIntel\.cache\pnpm-store
$env:PYTHONPATH = "$verifyRoot\backend\src;$verifyRoot"
```

`--offline` requires these exact locked packages to be present in the cache; it
does not prove a new machine can install without internet. The observed pnpm
sandbox attempt could not create its required store link; a retry with normal
host permissions succeeded. Do not disable checks or change system execution
policy to work around it. uv fell back from hardlinks to copying, with installation
still successful. The frontend reused285 cached packages, downloading zero.

Generate all ignored contracts and authored test assets from the clone's Python:

```powershell
New-Item -ItemType Directory -Path .cache/reproduction -Force | Out-Null
$generators = @(
  'export-contracts', 'export-published-reads', 'export-retrieval', 'export-admin',
  'export-analysis', 'export-learning-portfolio', 'generate-analysis-fixtures',
  'generate-read-fixtures', 'generate-fixtures', 'export-fixture-cases'
)
foreach ($generator in $generators) {
  & .\backend\.venv\Scripts\python.exe "scripts/$generator.py"
  if ($LASTEXITCODE -ne 0) { throw "Generator failed: $generator" }
}
pnpm --dir frontend build
```

Use the existing configuration by explicit path. The runner reads it without
copying or modifying it, rejects nonlocal/overridden targets, and creates/drops
only a new randomly named disposable database for each invocation. Do not run
new-installation secret initialization or Compose setup in this verification
clone. The original database is not the test target.

```powershell
.\backend\.venv\Scripts\python.exe scripts/check-migrations.py `
  --env-file D:\RegIntel\.env `
  --test-file backend/tests/integration/test_shared_module_corpus.py `
  --junit-report .cache/reproduction/shared-modules.xml
.\backend\.venv\Scripts\python.exe scripts/check-migrations.py `
  --env-file D:\RegIntel\.env `
  --test-file backend/tests/integration/test_portfolio_metrics_storage.py `
  --junit-report .cache/reproduction/metrics.xml
```

For the selected browser workflows, use the clone's Python and free loopback
ports; Playwright owns and shuts down its test servers. These browser cases use
explicitly authored HTTP fixtures, separate from the database integration cases.

```powershell
$env:REGINTEL_TEST_PYTHON = "$verifyRoot\backend\.venv\Scripts\python.exe"
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\RegIntel\.cache\ms-playwright'
$env:REGINTEL_TEST_API_PORT = '8117'
$env:REGINTEL_TEST_WEB_PORT = '5197'
node frontend/node_modules/@playwright/test/cli.js test `
  --config frontend/playwright.config.ts `
  frontend/tests/e2e/module-corpus.spec.ts `
  frontend/tests/e2e/learning-portfolio.spec.ts `
  --workers=1 --timeout=120000
git status --short
```

The 120-second case budget allows the initial cold Vite dependency transform;
no assertion or source gate is disabled. Check process exit codes before claiming
success. See the measured report linked from CURRENT_STATE.md for actual outcomes.

## What this proves and what remains

This checks installation from locked cached dependencies, regeneration from
source, production compilation and selected all-module contracts in a separate
checkout. The existing large frontend chunk warning remains. It is not the full
test suite or research evaluation, and authored results are not real filing data.

I.4 still needs a teammate's complete real-data setup/demo and handoff acceptance.
M1 source decisions, numerical publication and real M2 expected-result checks,
M3 content review, real amendment evaluation and a frozen held-out study remain
separate requirements. Runtime quotes remain unavailable by the user's decision;
successful priced orders in tests use labelled fixed-price fixtures only.

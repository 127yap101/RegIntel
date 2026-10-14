<#
.SYNOPSIS
Runs the installed foundation toolchain checks without installing dependencies.
.DESCRIPTION
Run setup and the locked dependency installs first. Browser tests start only the
localhost web servers configured by Playwright; no infrastructure is started.
.PARAMETER SkipBrowser
Explicitly omit the browser smoke test when Chromium has not been installed.
#>
[CmdletBinding()]
param([switch]$SkipBrowser)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$localUv = Join-Path $projectRoot '.tools/uv/uv.exe'

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    Write-Host ("Running: {0} {1}" -f $Executable, ($Arguments -join ' '))
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable"
    }
}

if (Test-Path -LiteralPath $localUv -PathType Leaf) {
    $uvExecutable = $localUv
} else {
    $uvCommand = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $uvCommand) {
        throw 'uv is missing. Complete the documented project toolchain setup first.'
    }
    $uvExecutable = $uvCommand.Source
}
$localPnpm = Join-Path $projectRoot '.tools/pnpm/pnpm.cmd'
$pnpmCommand = if (Test-Path -LiteralPath $localPnpm -PathType Leaf) {
    Get-Command $localPnpm -CommandType Application
} else {
    Get-Command pnpm -ErrorAction SilentlyContinue | Select-Object -First 1
}
$nodeCommand = Get-Command node -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -eq $pnpmCommand -or $null -eq $nodeCommand) {
    throw 'Node.js and pnpm must be installed before running foundation checks.'
}
if ((& $pnpmCommand.Source --version) -ne '11.19.0') {
    throw 'Expected the documented pnpm11.19.0; restore the project toolchain before checks.'
}

$requiredPaths = @('backend/uv.lock', 'backend/.venv', 'frontend/package.json', 'frontend/node_modules')
foreach ($relativePath in $requiredPaths) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $relativePath))) {
        throw "Missing $relativePath. Complete the documented locked dependency installs first."
    }
}

$savedEnvironment = @{}
$checkEnvironment = @{
    UV_CACHE_DIR = Join-Path $projectRoot '.cache/uv'
    UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.tools/python'
    UV_PYTHON_DOWNLOADS = 'never'
    PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot '.cache/ms-playwright'
    COREPACK_ENABLE_NETWORK = '0'
}
if (Test-Path -LiteralPath $localPnpm -PathType Leaf) {
    # Browser server subprocesses must resolve the same pinned project tool.
    $checkEnvironment['PATH'] = (Split-Path -Parent $localPnpm) + ';' + $env:PATH
}
foreach ($environmentName in $checkEnvironment.Keys) {
    $savedEnvironment[$environmentName] = [Environment]::GetEnvironmentVariable($environmentName, 'Process')
    [Environment]::SetEnvironmentVariable($environmentName, $checkEnvironment[$environmentName], 'Process')
}

Push-Location -LiteralPath $projectRoot
try {
    Invoke-CheckedCommand $uvExecutable @('--version')
    Invoke-CheckedCommand $nodeCommand.Source @('--version')
    Invoke-CheckedCommand $pnpmCommand.Source @('--version')
    Invoke-CheckedCommand $uvExecutable @('lock', '--project', 'backend', '--check', '--offline')
    $uvRun = @('run', '--project', 'backend', '--locked', '--no-sync', '--offline', '--no-python-downloads')
    Invoke-CheckedCommand $uvExecutable ($uvRun + @('python', 'scripts/export-contracts.py', '--check'))
    Invoke-CheckedCommand $uvExecutable ($uvRun + @('python', 'scripts/generate-fixtures.py', '--check'))
    Invoke-CheckedCommand $uvExecutable ($uvRun + @('python', 'scripts/export-fixture-cases.py', '--check'))
    $pythonCheckPaths = @('backend', 'scripts/init-local-env.py', 'scripts/init-auth-env.py', 'scripts/check-infra.py', 'scripts/check-migrations.py', 'scripts/check-ingestion-runtime.py', 'scripts/check-evidence-runtime.py', 'scripts/check-entity-runtime.py', 'scripts/check-candidate-runtime.py', 'scripts/export-contracts.py', 'scripts/generate-fixtures.py', 'scripts/export-fixture-cases.py', 'scripts/acquire-worker-libs.py', 'scripts/inspect-docling-source.py', 'scripts/render-parse-qa.py')
    Invoke-CheckedCommand $uvExecutable ($uvRun + @('ruff', 'check', '--config', 'backend/pyproject.toml') + $pythonCheckPaths)
    Invoke-CheckedCommand $uvExecutable ($uvRun + @('ruff', 'format', '--check', '--config', 'backend/pyproject.toml') + $pythonCheckPaths)
    Invoke-CheckedCommand $uvExecutable ($uvRun + @('mypy', '--config-file', 'backend/pyproject.toml', 'backend/src', 'scripts/init-local-env.py', 'scripts/init-auth-env.py', 'scripts/check-infra.py', 'scripts/check-migrations.py', 'scripts/check-ingestion-runtime.py', 'scripts/check-evidence-runtime.py', 'scripts/check-entity-runtime.py', 'scripts/check-candidate-runtime.py', 'scripts/export-contracts.py', 'scripts/generate-fixtures.py', 'scripts/export-fixture-cases.py', 'scripts/acquire-worker-libs.py', 'scripts/inspect-docling-source.py', 'scripts/render-parse-qa.py'))
    # Separate sandbox/user temporary directories; never delete a shared OS temp root.
    $pytestRunId = [Guid]::NewGuid().ToString('N')
    $pytestCacheRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot '.cache'))
    $pytestTempPath = [IO.Path]::GetFullPath((Join-Path $pytestCacheRoot "pytest-tmp-$pytestRunId"))
    $pytestCachePath = [IO.Path]::GetFullPath((Join-Path $pytestCacheRoot "pytest-cache-$pytestRunId"))
    if ((Split-Path -Parent $pytestTempPath) -ne $pytestCacheRoot -or (Test-Path -LiteralPath $pytestTempPath)) {
        throw 'Pytest temporary target is not a fresh project-cache path.'
    }
    Invoke-CheckedCommand $uvExecutable ($uvRun + @('pytest', 'backend/tests', '--basetemp', $pytestTempPath, '-o', "cache_dir=$pytestCachePath"))
    $pnpmFrontend = @('--dir', 'frontend', '--config.verify-deps-before-run=error')
    foreach ($checkName in @('lint', 'typecheck', 'test', 'build')) {
        Invoke-CheckedCommand $pnpmCommand.Source ($pnpmFrontend + @('run', $checkName))
    }
    if ($SkipBrowser) {
        Write-Host 'Browser smoke test explicitly skipped (-SkipBrowser).'
    } else {
        Invoke-CheckedCommand $pnpmCommand.Source ($pnpmFrontend + @('run', 'test:e2e'))
    }
    Write-Host 'Foundation checks passed.'
} finally {
    Pop-Location
    foreach ($environmentName in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($environmentName, $savedEnvironment[$environmentName], 'Process')
    }
}

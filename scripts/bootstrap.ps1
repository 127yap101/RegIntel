[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$uvVersion = '0.12.23'
$pythonVersion = '3.12.14'
$uvDirectory = Join-Path $repoRoot '.tools\uv'
$uvExecutable = Join-Path $uvDirectory 'uv.exe'
$env:UV_CACHE_DIR = Join-Path $repoRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repoRoot '.tools\python'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $repoRoot '.cache\ms-playwright'

function Invoke-Checked {
    param([string]$Executable, [string[]]$CommandArguments)
    & $Executable @CommandArguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Executable $CommandArguments" }
}

Push-Location $repoRoot
try {
    if (-not (Test-Path -LiteralPath $uvExecutable)) {
        $downloadDirectory = Join-Path $repoRoot '.tools\downloads'
        New-Item -ItemType Directory -Path $downloadDirectory -Force | Out-Null
        $archive = Join-Path $downloadDirectory "uv-$uvVersion-windows.zip"
        $releaseUrl = "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-x86_64-pc-windows-msvc.zip"
        Invoke-WebRequest -Uri $releaseUrl -OutFile $archive
        $checksumFile = "$archive.sha256"
        Invoke-WebRequest -Uri "$releaseUrl.sha256" -OutFile $checksumFile
        $expected = (Get-Content -LiteralPath $checksumFile).Split(' ')[0].Trim()
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) {
            throw 'uv download checksum mismatch'
        }
        Expand-Archive -LiteralPath $archive -DestinationPath $uvDirectory -Force
    }
    $actualUv = & $uvExecutable --version
    if ($actualUv -notmatch "^uv $([regex]::Escape($uvVersion))\b") { throw "Expected uv $uvVersion; found $actualUv" }
    $actualNode = & node --version
    if ($actualNode -ne 'v24.19.0') { throw "Expected Node 24.19.0; found $actualNode. Install the documented project version explicitly." }
    $actualPnpm = & pnpm --version
    if ($actualPnpm -ne '11.19.0') { throw "Expected pnpm 11.19.0; found $actualPnpm. Install the documented project version explicitly." }
    Invoke-Checked $uvExecutable @('python', 'install', $pythonVersion, '--no-bin', '--no-registry')
    Invoke-Checked $uvExecutable @('sync', '--project', 'backend', '--locked', '--extra', 'entities')
    Invoke-Checked $uvExecutable @('run', '--project', 'backend', '--locked', '--no-sync', 'python', 'scripts/export-contracts.py')
    Invoke-Checked $uvExecutable @('run', '--project', 'backend', '--locked', '--no-sync', 'python', 'scripts/generate-fixtures.py')
    Invoke-Checked $uvExecutable @('run', '--project', 'backend', '--locked', '--no-sync', 'python', 'scripts/export-fixture-cases.py')
    Invoke-Checked 'pnpm' @('--dir', 'frontend', 'install', '--frozen-lockfile', '--store-dir', (Join-Path $repoRoot '.cache/pnpm-store'))
    Invoke-Checked 'node' @((Join-Path $repoRoot 'frontend/node_modules/@playwright/test/cli.js'), 'install', 'chromium')
    Write-Output 'Foundation dependencies installed. Run scripts/run-checks.ps1 separately.'
} finally {
    Pop-Location
}

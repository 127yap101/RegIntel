<# Project infrastructure wrapper. Never prints expanded configuration or credentials. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('validate', 'pull', 'up', 'status', 'restart', 'stop', 'images', 'worker-build', 'worker-up', 'worker-status', 'worker-restart', 'worker-stop')]
    [string]$Action
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$dockerCommand = Get-Command docker -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
$dockerExecutable = if ($null -ne $dockerCommand) { $dockerCommand.Source } else {
    Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
}
if (-not (Test-Path -LiteralPath $dockerExecutable -PathType Leaf)) { throw 'Install/approve Docker Desktop explicitly; no installation is performed by this script.' }
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot '.env') -PathType Leaf)) { throw 'Generate .env with scripts/init-local-env.py first.' }
$dockerConfigDirectory = Join-Path $repoRoot '.cache/docker'
New-Item -ItemType Directory -Path $dockerConfigDirectory -Force | Out-Null
$dockerConfigPath = Join-Path $dockerConfigDirectory 'config.json'
$pluginDirectory = Join-Path (Split-Path -Parent (Split-Path -Parent $dockerExecutable)) 'cli-plugins'
if (-not (Test-Path -LiteralPath (Join-Path $pluginDirectory 'docker-compose.exe'))) {
    throw 'The Docker Desktop Compose plugin is missing. Verify the existing installation explicitly.'
}
if (-not (Test-Path -LiteralPath $dockerConfigPath) -or (Get-Content -LiteralPath $dockerConfigPath -Raw).Trim() -eq '{}') {
    $projectDockerConfig = @{ cliPluginsExtraDirs = @($pluginDirectory) } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText($dockerConfigPath, $projectDockerConfig)
}
# Use a project config without registry credentials and the explicit local Linux engine.
$dockerArguments = @('--config', $dockerConfigDirectory, '--host', 'npipe:////./pipe/dockerDesktopLinuxEngine', 'compose', '--env-file', (Join-Path $repoRoot '.env'), '-f', (Join-Path $repoRoot 'infra/compose.yaml'))
[string[]]$actionArguments = switch ($Action) {
    'worker-build' { @('--profile', 'ingestion', 'build', 'worker') }
    'worker-up' { @('--profile', 'ingestion', 'up', '-d', '--wait', '--wait-timeout', '180', 'worker') }
    'worker-status' { @('--profile', 'ingestion', 'ps', 'worker') }
    'worker-restart' { @('--profile', 'ingestion', 'restart', '--timeout', '30', 'worker') }
    'worker-stop' { @('--profile', 'ingestion', 'stop', '--timeout', '30', 'worker') }
    'validate' { @('config', '--quiet') }
    'pull' { @('pull') }
    'up' { @('up', '-d', '--wait', '--wait-timeout', '180') }
    'status' { @('ps') }
    'restart' { @('restart', '--timeout', '30') }
    'stop' { @('stop', '--timeout', '30') }
    'images' { @('images') }
}
& $dockerExecutable @dockerArguments @actionArguments
if ($LASTEXITCODE -ne 0) { throw "Docker Compose action $Action failed with exit $LASTEXITCODE" }

#Requires -Version 5.1
# Start Meridian for a controlled non-production LAN pilot session.
# Binds the Vite UI to an explicit LAN host, configures Django host/CSRF
# allowlists, and prints the access URL. Does NOT open firewall ports or
# publish services to the public internet.
#
# Usage:
#   .\scripts\start-pilot.ps1 -PilotHost 192.168.1.50
# Optional:
#   -BackendPort 8000 -FrontendPort 5173

param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^(\d{1,3}\.){3}\d{1,3}$|^[a-zA-Z0-9.-]+$')]
    [string]$PilotHost,

    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PilotHost -in @('0.0.0.0', '*', '::', 'localhost', '127.0.0.1')) {
    throw 'PilotHost must be an approved LAN address (not loopback or wildcard).'
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RepoRoot '.env'
$FrontendDir = Join-Path $RepoRoot 'frontend'
$BackendDir = Join-Path $RepoRoot 'backend'

$uvBin = Join-Path $env:USERPROFILE '.local\bin'
if (Test-Path $uvBin) { $env:Path = "$uvBin;$env:Path" }

if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*([^#=]+)=(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
        }
    }
}

$FrontendOrigin = "http://${PilotHost}:${FrontendPort}"
$env:DJANGO_SETTINGS_MODULE = 'config.settings.development'
# Pilot sessions keep password login and must not expose the E2E login_key path.
$env:ENABLE_DEV_LOGIN = 'false'
$env:ENABLE_PILOT_PASSWORD_LOGIN = 'true'
$env:VITE_ENABLE_PILOT_PASSWORD_LOGIN = 'true'
$env:VITE_ENABLE_DEV_LOGIN = 'false'
$env:DJANGO_ALLOWED_HOSTS = (@('localhost', '127.0.0.1', $PilotHost) -join ',')
$env:DJANGO_CSRF_TRUSTED_ORIGINS = (@(
        'http://localhost:5173',
        'http://127.0.0.1:5173',
        $FrontendOrigin
    ) -join ',')

Write-Host ''
Write-Host '=== Meridian pilot (non-production) ===' -ForegroundColor Cyan
Write-Host ("LAN UI:      {0}" -f $FrontendOrigin)
Write-Host ("API (local): http://127.0.0.1:{0}  (proxied by Vite)" -f $BackendPort)
Write-Host 'ALLOWED_HOSTS / CSRF origins updated for this session only.'
Write-Host 'This script does not open Windows Firewall or public ports.'
Write-Host 'Each participant must use a unique account (provision_pilot_user).'
Write-Host ''

$backend = Start-Process -PassThru -NoNewWindow -WorkingDirectory $BackendDir -FilePath 'uv' -ArgumentList @(
    'run', 'python', 'manage.py', 'runserver', "127.0.0.1:$BackendPort"
)
$frontend = Start-Process -PassThru -NoNewWindow -WorkingDirectory $FrontendDir -FilePath 'npm' -ArgumentList @(
    'run', 'dev', '--', '--host', $PilotHost, '--port', "$FrontendPort"
)

Write-Host ("Backend PID  {0}" -f $backend.Id)
Write-Host ("Frontend PID {0}" -f $frontend.Id)
Write-Host 'Press Ctrl+C in this window after stopping the child processes, or close their consoles.'

try {
    Wait-Process -Id $backend.Id, $frontend.Id
}
finally {
    foreach ($proc in @($backend, $frontend)) {
        if ($null -ne $proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

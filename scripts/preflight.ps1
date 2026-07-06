#Requires -Version 5.1
# Project Meridian environment preflight.
# Verifies every tool required to initialize, run, test and build the project.
# Any missing tool or unavailable Docker daemon is reported explicitly and
# causes a non-zero exit code. This failure is environment evidence and must
# not be bypassed.
# Kept ASCII-only so Windows PowerShell 5.1 parses it regardless of code page.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'
$LASTEXITCODE = 0

$failures = New-Object System.Collections.Generic.List[string]

function Write-Pass([string]$name, [string]$detail) {
    Write-Host ("  [ OK ] {0}: {1}" -f $name, $detail) -ForegroundColor Green
}

function Write-Fail([string]$name, [string]$reason) {
    Write-Host ("  [FAIL] {0}: {1}" -f $name, $reason) -ForegroundColor Red
    $failures.Add(("{0}: {1}" -f $name, $reason))
}

function Test-ToolCommand([string]$name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host "Project Meridian preflight" -ForegroundColor Cyan
Write-Host "--------------------------"

# Git
if (Test-ToolCommand 'git') {
    Write-Pass 'Git' (git --version)
} else {
    Write-Fail 'Git' 'git not found on PATH'
}

# uv
$hasUv = Test-ToolCommand 'uv'
if ($hasUv) {
    Write-Pass 'uv' (uv --version)
} else {
    Write-Fail 'uv' 'uv not found on PATH (reopen terminal after install to refresh PATH)'
}

# Python 3.13 managed by uv
if ($hasUv) {
    $pyPath = (uv python find 3.13 2>&1)
    if ($LASTEXITCODE -eq 0 -and $pyPath) {
        Write-Pass 'Python 3.13' ($pyPath | Select-Object -First 1)
    } else {
        Write-Fail 'Python 3.13' 'uv-managed Python 3.13 not found; run: uv python install 3.13'
    }
} else {
    Write-Fail 'Python 3.13' 'cannot verify (uv missing)'
}

# Node.js 24 LTS
if (Test-ToolCommand 'node') {
    $nodeVersion = (node --version)
    if ($nodeVersion -match '^v24\.') {
        Write-Pass 'Node.js 24' $nodeVersion
    } else {
        Write-Fail 'Node.js 24' ("Node 24 LTS required, found {0}" -f $nodeVersion)
    }
} else {
    Write-Fail 'Node.js 24' 'node not found on PATH'
}

# npm
if (Test-ToolCommand 'npm.cmd') {
    Write-Pass 'npm' (npm.cmd --version)
} elseif (Test-ToolCommand 'npm') {
    Write-Pass 'npm' (npm --version)
} else {
    Write-Fail 'npm' 'npm not found on PATH'
}

# Docker CLI
$hasDocker = Test-ToolCommand 'docker'
if ($hasDocker) {
    Write-Pass 'Docker CLI' (docker --version)
} else {
    Write-Fail 'Docker CLI' 'docker not found on PATH'
}

# Docker Compose
if ($hasDocker) {
    $composeOut = (docker compose version 2>&1)
    if ($LASTEXITCODE -eq 0) {
        Write-Pass 'Docker Compose' ($composeOut | Select-Object -First 1)
    } else {
        Write-Fail 'Docker Compose' 'docker compose not available'
    }
} else {
    Write-Fail 'Docker Compose' 'cannot verify (Docker CLI missing)'
}

# Docker daemon must be running
if ($hasDocker) {
    $serverVersion = (docker version --format '{{.Server.Version}}' 2>&1)
    if ($LASTEXITCODE -eq 0 -and $serverVersion -and ($serverVersion -notmatch 'error|cannot|refused')) {
        Write-Pass 'Docker daemon' ("server {0}" -f $serverVersion)
    } else {
        Write-Fail 'Docker daemon' 'Docker Desktop is not running or daemon unavailable (start Docker Desktop)'
    }
} else {
    Write-Fail 'Docker daemon' 'cannot verify (Docker CLI missing)'
}

Write-Host ""
if ($failures.Count -gt 0) {
    Write-Host ("Preflight FAILED ({0}):" -f $failures.Count) -ForegroundColor Red
    foreach ($item in $failures) {
        Write-Host ("  - {0}" -f $item) -ForegroundColor Red
    }
    exit 1
}

Write-Host "Preflight passed. Environment is ready." -ForegroundColor Green
exit 0

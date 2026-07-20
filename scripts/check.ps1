#Requires -Version 5.1
# Project Meridian unified local quality gate.
# Runs the same checks that CI enforces and fails fast: the first failing step
# stops the run and the script exits with a non-zero code. Kept ASCII-only so
# Windows PowerShell 5.1 parses it regardless of code page.
#
# Prerequisite: local dependency services must be running
#   docker compose -f deploy/compose/compose.dev.yml --env-file .env up -d

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Compose = 'deploy/compose/compose.dev.yml'
$EnvFile = Join-Path $RepoRoot '.env'

# Make uv resolvable even if the current shell predates its install.
$uvBin = Join-Path $env:USERPROFILE '.local\bin'
if (Test-Path $uvBin) { $env:Path = "$uvBin;$env:Path" }

# Load .env so backend steps reach MySQL.
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*([^#=]+)=(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
        }
    }
}

$script:StepNo = 0

function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][scriptblock]$Action,
        [string]$WorkDir = $RepoRoot
    )
    $script:StepNo++
    Write-Host ""
    Write-Host ("=== [{0}] {1} ===" -f $script:StepNo, $Title) -ForegroundColor Cyan
    Push-Location $WorkDir
    try {
        & $Action
        if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {
            throw ("step failed (exit {0}): {1}" -f $LASTEXITCODE, $Title)
        }
    }
    finally {
        Pop-Location
    }
}

try {
    # 1. Environment preflight.
    Invoke-Native 'Environment preflight' {
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'preflight.ps1')
        if ($LASTEXITCODE -ne 0) { throw "preflight failed" }
    }

    # 2. Compose configuration validation.
    Invoke-Native 'Compose config validation' {
        docker compose -f $Compose --env-file $EnvFile config | Out-Null
    }

    # 3. Backend gates.
    $backend = Join-Path $RepoRoot 'backend'
    Invoke-Native 'Backend: lockfile' { uv lock --check } $backend
    Invoke-Native 'Backend: ruff check' { uv run ruff check . } $backend
    Invoke-Native 'Backend: ruff format check' { uv run ruff format --check . } $backend
    Invoke-Native 'Backend: mypy' { uv run mypy config apps } $backend
    Invoke-Native 'Backend: django check' {
        uv run python manage.py check --settings=config.settings.test
    } $backend
    Invoke-Native 'Backend: migration drift' {
        uv run python manage.py makemigrations --check --dry-run --settings=config.settings.test
    } $backend
    Invoke-Native 'Backend: pytest (MySQL)' { uv run pytest -q } $backend
    Invoke-Native 'Backend: OpenAPI drift' {
        $spectacularOutput = uv run python manage.py spectacular --file openapi/schema.yaml --validate --settings=config.settings.test 2>&1 | Out-String
        Write-Host $spectacularOutput
        if ($spectacularOutput -match 'Errors:\s+[1-9]\d*') {
            throw "OpenAPI schema generation reported errors"
        }
        git diff --exit-code -- openapi/schema.yaml
    } $backend

    # 4. Frontend gates.
    $frontend = Join-Path $RepoRoot 'frontend'
    Invoke-Native 'Frontend: npm ci' { npm.cmd ci } $frontend
    Invoke-Native 'Frontend: lint' { npm.cmd run lint } $frontend
    Invoke-Native 'Frontend: format check' { npm.cmd run format:check } $frontend
    Invoke-Native 'Frontend: typecheck' { npm.cmd run typecheck } $frontend
    Invoke-Native 'Frontend: unit tests' { npm.cmd run test:unit -- --run } $frontend
    Invoke-Native 'Frontend: build' { npm.cmd run build } $frontend
    Invoke-Native 'Frontend: contract type drift' {
        npm.cmd run api:generate
        git diff --exit-code -- src/api/generated/schema.d.ts
    } $frontend

    # 5. E2E: platform kernel + phase 2 opportunity-to-project (backend + frontend dev servers).
    $e2e = Join-Path $RepoRoot 'tests/e2e'
    Invoke-Native 'E2E: install deps' { npm.cmd ci } $e2e
    Invoke-Native 'E2E: Playwright browser' { npx playwright install chromium } $e2e
    Invoke-Native 'E2E: platform kernel, phase 2, and phase 3 product profile' {
        $env:CI = 'true'
        npx playwright test platform-kernel.spec.ts opportunity-to-project.spec.ts product-profile-migration.spec.ts development-first-launch.spec.ts
    } $e2e

    # 6. Docker image builds.
    Invoke-Native 'Docker: backend image' {
        docker build -t meridian-backend:ci backend
    }
    Invoke-Native 'Docker: frontend image' {
        docker build -f frontend/Dockerfile -t meridian-frontend:ci .
    }

    # 7. Legacy prototype reference scan (must find nothing).
    # Uses git grep for portability (Windows and Linux CI) and to honor
    # .gitignore, so node_modules/.venv/dist are skipped. --untracked also
    # covers new files not yet committed.
    Invoke-Native 'Legacy reference scan' {
        $patternFile = Join-Path $PSScriptRoot 'legacy-patterns.txt'
        git grep -I -F -n --untracked -f $patternFile -- `
            backend frontend deploy tests scripts ':(exclude)scripts/legacy-patterns.txt'
        if ($LASTEXITCODE -eq 0) {
            throw "legacy prototype references found"
        }
        # git grep exit code 1 means no matches -> success.
        $global:LASTEXITCODE = 0
    }
}
catch {
    Write-Host ""
    Write-Host ("CHECK FAILED: {0}" -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "All quality gates passed." -ForegroundColor Green
exit 0

param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

$pairs = @(
    @{
        Prd = 'docs/prd/00-product-lifecycle-master-prd.md'
        Trd = 'docs/trd/00-system-master-trd.md'
        Prefixes = @('GLB', 'NFR')
    },
    @{
        Prd = 'docs/prd/01-opportunity-case-project-prd.md'
        Trd = 'docs/trd/01-opportunity-case-project-trd.md'
        Prefixes = @('OPP')
    },
    @{
        Prd = 'docs/prd/02-product-profile-version-migration-prd.md'
        Trd = 'docs/trd/02-product-profile-version-migration-trd.md'
        Prefixes = @('PIM')
    },
    @{
        Prd = 'docs/prd/03-development-launch-execution-prd.md'
        Trd = 'docs/trd/03-development-launch-execution-trd.md'
        Prefixes = @('EXE')
    },
    @{
        Prd = 'docs/prd/04-operations-iteration-retirement-prd.md'
        Trd = 'docs/trd/04-operations-iteration-retirement-trd.md'
        Prefixes = @('OPS')
    },
    @{
        Prd = 'docs/prd/05-platform-permission-file-integration-prd.md'
        Trd = 'docs/trd/05-platform-permission-file-integration-trd.md'
        Prefixes = @('PLT')
    }
)

$issues = [System.Collections.Generic.List[string]]::new()
$allRequirementIds = [System.Collections.Generic.List[string]]::new()
$trdPaths = [System.Collections.Generic.List[string]]::new()
$rootPrefix = $Root.TrimEnd([char[]]@('\', '/'))

foreach ($pair in $pairs) {
    $prdPath = Join-Path $Root $pair.Prd
    $trdPath = Join-Path $Root $pair.Trd
    $trdPaths.Add($trdPath)

    if (-not (Test-Path -LiteralPath $prdPath)) {
        $issues.Add("Missing PRD: $($pair.Prd)")
        continue
    }
    if (-not (Test-Path -LiteralPath $trdPath)) {
        $issues.Add("Missing TRD: $($pair.Trd)")
        continue
    }

    $prdText = Get-Content -LiteralPath $prdPath -Raw -Encoding utf8
    $trdText = Get-Content -LiteralPath $trdPath -Raw -Encoding utf8
    $prefixPattern = ($pair.Prefixes | ForEach-Object { [regex]::Escape($_) }) -join '|'
    $idPattern = "(?m)^\| (($prefixPattern)-\d{3}) \|"
    $ids = [regex]::Matches($prdText, $idPattern) | ForEach-Object { $_.Groups[1].Value }

    if ($ids.Count -eq 0) {
        $issues.Add("No requirement IDs found in $($pair.Prd)")
    }

    foreach ($id in $ids) {
        $allRequirementIds.Add($id)
        $traceRowCount = [regex]::Matches(
            $trdText,
            "(?m)^\| $([regex]::Escape($id)) \|"
        ).Count
        if ($traceRowCount -ne 1) {
            $issues.Add("$id must have exactly one traceability row in $($pair.Trd), found $traceRowCount")
        }
    }

}

$duplicates = $allRequirementIds |
    Group-Object |
    Where-Object { $_.Count -gt 1 } |
    Select-Object -ExpandProperty Name

foreach ($duplicate in $duplicates) {
    $issues.Add("Duplicate requirement ID across PRDs: $duplicate")
}

foreach ($trdPath in $trdPaths) {
    $text = Get-Content -LiteralPath $trdPath -Raw -Encoding utf8
    $relative = $trdPath.Substring($rootPrefix.Length).TrimStart([char[]]@('\', '/'))

    if ($relative -notlike '*00-system-master-trd.md') {
        $sectionCount = [regex]::Matches($text, '(?m)^## \d+\.').Count
        if ($sectionCount -lt 15) {
            $issues.Add("Expected at least 15 numbered sections in $relative, found $sectionCount")
        }
    }

    if ([regex]::IsMatch($text, '\bTODO\b|\bTBD\b')) {
        $issues.Add("Placeholder found: $relative")
    }

    $references = [regex]::Matches(
        ($text -split '## 1\.')[0],
        '`([^`\r\n]+\.md)`'
    ) | ForEach-Object { $_.Groups[1].Value }

    foreach ($reference in $references) {
        $resolved = Join-Path (Split-Path -Parent $trdPath) $reference
        if (-not (Test-Path -LiteralPath $resolved)) {
            $issues.Add("Broken upstream reference '$reference': $relative")
        }
    }
}

$allTrdText = ($trdPaths | ForEach-Object {
    Get-Content -LiteralPath $_ -Raw -Encoding utf8
}) -join "`n"

$requiredGateCodes = @(
    'PROPOSAL_TO_CASE',
    'CASE_TO_PROJECT',
    'FIRST_LAUNCH',
    'PRODUCT_RETIREMENT'
)

foreach ($gateCode in $requiredGateCodes) {
    if (-not $allTrdText.Contains($gateCode)) {
        $issues.Add("Missing major stage gate code: $gateCode")
    }
}

if ($allTrdText.Contains('PASS_APPROVED')) {
    $issues.Add('Non-canonical stage gate code found: PASS_APPROVED')
}

if ($allRequirementIds.Count -ne 92) {
    $issues.Add("Expected 92 unique PRD/NFR requirements, found $($allRequirementIds.Count)")
}

$supportFiles = @(
    'docs/trd/README.md',
    'docs/trd/2026-06-30-trd-completeness-audit.md'
)

foreach ($supportFile in $supportFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $Root $supportFile))) {
        $issues.Add("Missing TRD support document: $supportFile")
    }
}

if ($issues.Count -gt 0) {
    Write-Host "TRD verification failed with $($issues.Count) issue(s):"
    $issues | ForEach-Object { Write-Host " - $_" }
    exit 1
}

Write-Host 'TRD verification passed.'
Write-Host "Documents: $($trdPaths.Count)"
Write-Host "Requirements traced: $($allRequirementIds.Count)"
Write-Host "Major stage gates: $($requiredGateCodes.Count)"

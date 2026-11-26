#Requires -Version 5.1
<#
.SYNOPSIS
  Aetrix V5.5 — operate the production backend on arm-free-1 from Windows.

.DESCRIPTION
  Wraps SSH/SCP so routine production work never needs a manual login. The SSH
  key is passphrase-protected, so ssh asks for the passphrase interactively; the
  passphrase is never stored by this script.

.EXAMPLES
  .\aetrix.ps1 status
  .\aetrix.ps1 health
  .\aetrix.ps1 deploy              # deploy committed HEAD (refuses a dirty tree)
  .\aetrix.ps1 deploy -AllowDirty  # deploy the working tree as <sha>-local
  .\aetrix.ps1 rollback
  .\aetrix.ps1 logs api 150
  .\aetrix.ps1 restart api
  .\aetrix.ps1 releases
  .\aetrix.ps1 version
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Command = 'help',
    [Parameter(Position = 1)][string]$Target = '',
    [Parameter(Position = 2)][int]$Lines = 100,
    [switch]$AllowDirty
)

$ErrorActionPreference = 'Stop'

$VmHost = 'ubuntu@139.185.60.57'
$SshKey = 'C:\Projects\AETRIX A1\arm-free-1'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot 'backend'
$WorkDir = Join-Path $env:TEMP 'aetrix-deploy'
$PublicApi = 'https://arm-free-1.tail06bb75.ts.net'

function Invoke-Ssh {
    param([string]$RemoteCommand)
    & ssh -i $SshKey -o IdentitiesOnly=yes -o ConnectTimeout=20 $VmHost $RemoteCommand
    if ($LASTEXITCODE -ne 0) { throw "remote command failed (exit $LASTEXITCODE): $RemoteCommand" }
}

function Send-RemoteScript {
    param([string]$LocalScript)
    $text = (Get-Content -Raw $LocalScript) -replace "`r`n", "`n"
    $text | & ssh -i $SshKey -o IdentitiesOnly=yes -o ConnectTimeout=20 $VmHost 'bash -s'
    if ($LASTEXITCODE -ne 0) { throw "remote script failed (exit $LASTEXITCODE)" }
}

function Get-ReleaseId {
    $sha = (& git -C $RepoRoot rev-parse --short HEAD).Trim()
    $dirty = (& git -C $RepoRoot status --porcelain backend) -ne $null -and
             ((& git -C $RepoRoot status --porcelain backend) | Measure-Object).Count -gt 0
    if ($dirty -and -not $AllowDirty) {
        throw "The backend working tree has uncommitted changes. Commit them, or pass -AllowDirty to deploy them as $sha-local."
    }
    if ($dirty) { return "$sha-local" }
    return $sha
}

function Build-Release {
    param([string]$ReleaseId)
    New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
    $tar = Join-Path $WorkDir "release-$ReleaseId.tar.gz"
    if (Test-Path $tar) { Remove-Item $tar -Force }

    if ($ReleaseId -like '*-local') {
        Push-Location $RepoRoot
        try {
            & tar -czf $tar `
                --exclude='backend/.venv' --exclude='__pycache__' --exclude='*.pyc' `
                --exclude='backend/.env' --exclude='.pytest_cache' `
                --exclude='backend/aetrix_engine.egg-info' --exclude='backend/tests' `
                --exclude='backend/data/documents' backend
            if ($LASTEXITCODE -ne 0) { throw 'tar failed' }
        } finally { Pop-Location }
    } else {
        & git -C $RepoRoot archive --format=tar.gz -o $tar HEAD backend
        if ($LASTEXITCODE -ne 0) { throw 'git archive failed' }
    }
    return $tar
}

function Assert-LocalChecks {
    $python = Join-Path $BackendDir '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { Write-Host '  (no venv; skipping local import check)' -ForegroundColor Yellow; return }
    Push-Location $BackendDir
    try {
        & $python -c "import app.main" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Backend does not import locally — refusing to deploy.' }
        Write-Host '  local import check: ok' -ForegroundColor Green
    } finally { Pop-Location }
}

function Deploy-Release {
    $releaseId = Get-ReleaseId
    Write-Host "release: $releaseId" -ForegroundColor Cyan
    Assert-LocalChecks

    $tar = Build-Release -ReleaseId $releaseId
    Write-Host ("artifact: {0:N0} KB" -f ((Get-Item $tar).Length / 1KB)) -ForegroundColor Cyan

    Invoke-Ssh 'mkdir -p /tmp/aetrix-bootstrap'
    & scp -q -i $SshKey -o IdentitiesOnly=yes $tar "${VmHost}:/tmp/aetrix-bootstrap/release.tar.gz"
    if ($LASTEXITCODE -ne 0) { throw 'scp failed' }

    $remote = Join-Path $WorkDir 'remote-deploy.sh'
    @"
#!/usr/bin/env bash
set -uo pipefail
RID=$releaseId
sudo -n /opt/aetrix/deploy/aetrix-deploy.sh install "`$RID" /tmp/aetrix-bootstrap/release.tar.gz || exit 1
sudo -n systemctl enable aetrix-api >/dev/null 2>&1
sudo -n /opt/aetrix/deploy/aetrix-deploy.sh activate "`$RID"
"@ | Set-Content -Encoding utf8 $remote

    Send-RemoteScript $remote
    Write-Host "deployed $releaseId" -ForegroundColor Green
}

switch ($Command.ToLower()) {
    'status'   { Invoke-Ssh 'sudo -n /opt/aetrix/deploy/aetrix-deploy.sh status' }
    'health'   { Invoke-Ssh "curl -sS --max-time 10 $PublicApi/health; echo; curl -sS --max-time 10 $PublicApi/ready; echo" }
    'version'  { Invoke-Ssh "cat /opt/aetrix/deploy/active 2>/dev/null; curl -sS --max-time 10 $PublicApi/version" }
    'releases' { Invoke-Ssh 'sudo -n /opt/aetrix/deploy/aetrix-deploy.sh releases' }
    'deploy'   { Deploy-Release }
    'update'   { Deploy-Release }
    'rollback' { Invoke-Ssh 'sudo -n /opt/aetrix/deploy/aetrix-deploy.sh rollback' }
    'restart'  {
        if ($Target -notin @('api', 'worker')) { throw 'usage: aetrix.ps1 restart api|worker' }
        Invoke-Ssh "sudo -n systemctl restart aetrix-$Target; sleep 4; systemctl is-active aetrix-$Target"
    }
    'logs'     {
        if ($Target -notin @('api', 'worker', 'nginx')) { throw 'usage: aetrix.ps1 logs api|worker|nginx [lines]' }
        if ($Target -eq 'nginx') { Invoke-Ssh "sudo -n tail -n $Lines /var/log/nginx/error.log" }
        else { Invoke-Ssh "sudo -n tail -n $Lines /opt/aetrix/shared/logs/$Target.log" }
    }
    default {
        Get-Help $PSCommandPath -Detailed | Out-String | Write-Host
    }
}

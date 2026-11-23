<#
.SYNOPSIS
    Starts the Sentinel AI security console (API + compiled dashboard).

.DESCRIPTION
    Creates/uses a local .venv, optionally installs dependencies and builds the
    React frontend, then launches uvicorn on http://127.0.0.1:8000/.

.PARAMETER Setup
    Create the virtual environment, install Python/npm dependencies and build
    the frontend.  Run this once on a fresh checkout.

.PARAMETER Build
    Rebuild only the frontend (useful after editing React/TypeScript files).

.PARAMETER Port
    HTTP port for the combined API + UI server.  Default: 8000.

.PARAMETER NoBrowser
    Do not open the browser automatically.

.EXAMPLE
    .\run.ps1 -Setup

.EXAMPLE
    .\run.ps1 -Build -Port 8080
#>
[CmdletBinding()]
param(
    [switch]$Setup,
    [switch]$Build,
    [switch]$NoBrowser,
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host ""
Write-Host "  Sentinel AI - Perimeter Control Center" -ForegroundColor Cyan
Write-Host "  --------------------------------------" -ForegroundColor DarkCyan
Write-Host ""

function Resolve-Python {
    param([string]$RootPath, [bool]$Install)
    $venv = Join-Path $RootPath ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    if ($Install) {
        Write-Host "[setup] Creating virtual environment in .venv ..." -ForegroundColor Yellow
        & python -m venv (Join-Path $RootPath ".venv")
        if (-not (Test-Path $venv)) { throw "Could not create .venv. Is Python 3.11+ on PATH?" }
        return $venv
    }
    $global = Get-Command python -ErrorAction SilentlyContinue
    if (-not $global) { throw "Python was not found. Install Python 3.11+ and re-run .\run.ps1 -Setup" }
    Write-Host "[info] No .venv found, using global Python: $($global.Source)" -ForegroundColor DarkYellow
    return $global.Source
}

$python = Resolve-Python -RootPath $Root -Install $Setup.IsPresent

if ($Setup) {
    Write-Host "[setup] Installing Python dependencies ..." -ForegroundColor Yellow
    & $python -m pip install --upgrade pip --disable-pip-version-check
    & $python -m pip install -r (Join-Path $Root "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

    Write-Host "[setup] Installing frontend dependencies ..." -ForegroundColor Yellow
    Push-Location (Join-Path $Root "frontend")
    try {
        cmd /c "npm install"
        if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
        cmd /c "npm run build"
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
    }
    finally {
        Pop-Location
    }
}
elseif ($Build) {
    Write-Host "[build] Compiling the dashboard ..." -ForegroundColor Yellow
    Push-Location (Join-Path $Root "frontend")
    try {
        cmd /c "npm run build"
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
    }
    finally {
        Pop-Location
    }
}

$distIndex = Join-Path $Root "frontend\dist\index.html"
if (-not (Test-Path $distIndex)) {
    Write-Host "[warn] frontend\dist is missing - the API will start without the UI." -ForegroundColor DarkYellow
    Write-Host "[warn] Run .\run.ps1 -Setup (or 'cd frontend; npm install; npm run build')." -ForegroundColor DarkYellow
}

$url = "http://${BindHost}:$Port/"
if (-not $NoBrowser) {
    Write-Host "[info] Opening $url in the default browser ..." -ForegroundColor DarkGray
    Start-Job -ScriptBlock {
        param($target)
        Start-Sleep -Seconds 5
        Start-Process $target
    } -ArgumentList $url | Out-Null
}

Write-Host ""
Write-Host "  API docs : http://${BindHost}:$Port/docs" -ForegroundColor Green
Write-Host "  Dashboard: $url" -ForegroundColor Green
Write-Host "  Logins   : admin/admin123, operator/operator123, viewer/viewer123" -ForegroundColor Green
Write-Host "  Stop     : Ctrl+C" -ForegroundColor DarkGray
Write-Host ""

& $python -m uvicorn backend.main:app --host $BindHost --port $Port

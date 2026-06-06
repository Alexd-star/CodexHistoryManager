$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$TargetExe = Join-Path $ProjectRoot "dist\CodexHistoryManager.exe"
$Running = Get-Process -Name "CodexHistoryManager" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $TargetExe }
if ($Running) {
    Write-Host "Build blocked: CodexHistoryManager.exe is running. Please close it and run this script again." -ForegroundColor Yellow
    exit 1
}

$Python311 = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
if (-not (Test-Path $Python311)) {
    $Python311 = (Get-Command python -ErrorAction Stop).Source
}

& $Python311 -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "CodexHistoryManager" `
    --icon "assets\codex_history_manager.ico" `
    --collect-all customtkinter `
    --collect-all darkdetect `
    --add-data "static;static" `
    --add-data "assets;assets" `
    --add-data "README.md;." `
    --add-data "VERSION;." `
    modern_app.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Build done: $TargetExe"

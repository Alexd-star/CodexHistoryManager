$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

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
    modern_app.py

Write-Host ""
Write-Host "Build done: $ProjectRoot\dist\CodexHistoryManager.exe"

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Version = (Get-Content -Path (Join-Path $ProjectRoot "VERSION") -Raw).Trim()
$ExePath = Join-Path $ProjectRoot "dist\CodexHistoryManager.exe"
$InstallerScript = Join-Path $ProjectRoot "installer\CodexHistoryManager.iss"
$SetupPath = Join-Path $ProjectRoot "dist\CodexHistoryManager-Setup-v$Version.exe"

if (-not (Test-Path $ExePath)) {
    Write-Host "CodexHistoryManager.exe not found. Building desktop EXE first..." -ForegroundColor Cyan
    & powershell -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "打包桌面版EXE.ps1")
}

$Candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
)
$Iscc = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    $Command = Get-Command iscc -ErrorAction SilentlyContinue
    if ($Command) {
        $Iscc = $Command.Source
    }
}

if (-not $Iscc) {
    Write-Host "Inno Setup compiler was not found." -ForegroundColor Yellow
    Write-Host "Install it, then run this script again:"
    Write-Host "  winget install --id JRSoftware.InnoSetup -e --silent"
    exit 1
}

& $Iscc "/DAppVersion=$Version" $InstallerScript
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup build failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path $SetupPath)) {
    throw "Installer was not generated: $SetupPath"
}

Write-Host ""
Write-Host "Installer build done: $SetupPath"

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

$Version = (Get-Content -Path (Join-Path $ProjectRoot "VERSION") -Raw).Trim()
$SetupPath = Join-Path $ProjectRoot "dist\CodexHistoryManager-Setup-v$Version.exe"
$Target = Join-Path $env:TEMP "CodexHistoryManager-install-test"

if (-not (Test-Path $SetupPath)) {
    throw "Installer not found: $SetupPath"
}

Remove-Item -Recurse -Force $Target -ErrorAction SilentlyContinue

$Install = Start-Process `
    -FilePath $SetupPath `
    -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=$Target", "/CURRENTUSER") `
    -Wait `
    -PassThru
if ($Install.ExitCode -ne 0) {
    throw "Installer exited with $($Install.ExitCode)"
}

$InstalledExe = Join-Path $Target "CodexHistoryManager.exe"
$Uninstaller = Join-Path $Target "unins000.exe"
if (-not (Test-Path $InstalledExe)) {
    throw "Installed EXE missing: $InstalledExe"
}
if (-not (Test-Path $Uninstaller)) {
    throw "Uninstaller missing: $Uninstaller"
}

$Uninstall = Start-Process `
    -FilePath $Uninstaller `
    -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") `
    -Wait `
    -PassThru
if ($Uninstall.ExitCode -ne 0) {
    throw "Uninstaller exited with $($Uninstall.ExitCode)"
}

Start-Sleep -Seconds 2
if (Test-Path $InstalledExe) {
    throw "Installed EXE still exists after uninstall: $InstalledExe"
}

Write-Host "[OK] installer install/uninstall smoke test passed"

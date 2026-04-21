# K2-Screws-Tilt bootstrap -- iex-compatible entrypoint.
#
# install.ps1 declares [CmdletBinding()] + param(), which PowerShell only
# accepts at the top of a script FILE. Invoke-Expression can't parse those
# in an expression block. This bootstrap is flat top-level code so
# `iwr | iex` works -- it downloads install.ps1 to a temp file and runs
# it as a real script.
#
# One-liner for users:
#
#   iwr -useb https://raw.githubusercontent.com/grant0013/K2-Screws-Tilt/main/bootstrap.ps1 | iex

$InstallUrl = "https://raw.githubusercontent.com/grant0013/K2-Screws-Tilt/main/install.ps1"
$TargetPath = Join-Path $env:TEMP "k2-screws-tilt-install.ps1"

Write-Host ""
Write-Host "[*] Downloading K2-Screws-Tilt installer..." -ForegroundColor Cyan
try {
    Invoke-WebRequest -UseBasicParsing -Uri $InstallUrl -OutFile $TargetPath -ErrorAction Stop
} catch {
    Write-Host "[x] Download failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Check your internet connection or open an issue:" -ForegroundColor Yellow
    Write-Host "  https://github.com/grant0013/K2-Screws-Tilt/issues" -ForegroundColor Yellow
    exit 1
}
Write-Host "[+] Saved to $TargetPath" -ForegroundColor Green
Write-Host "[*] Launching installer..." -ForegroundColor Cyan
Write-Host ""

# NOTE: deliberately no `exit` here -- iex evaluates this in the current
# shell scope, so exit would close the user's PowerShell window. Errors
# in the child script are caught below and paused for the user to read.
try {
    & $TargetPath
} catch {
    Write-Host ""
    Write-Host "[x] Installer crashed with an error:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Script location: $TargetPath" -ForegroundColor Yellow
    Write-Host "Stack trace:" -ForegroundColor Yellow
    Write-Host $_.ScriptStackTrace -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Paste the above into a GitHub issue:" -ForegroundColor Yellow
    Write-Host "  https://github.com/grant0013/K2-Screws-Tilt/issues" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Press Enter to close." -ForegroundColor Gray
    $null = Read-Host
}

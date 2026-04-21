# K2-Screws-Tilt PowerShell installer.
#
# Run from PowerShell (not cmd.exe). Recommended one-liner:
#
#   iwr -useb https://raw.githubusercontent.com/grant0013/K2-Screws-Tilt/main/bootstrap.ps1 | iex
#
# Or download this file and run locally:
#   .\install.ps1
#
# Optional parameters:
#   .\install.ps1 -PrinterHost 192.168.1.42
#   .\install.ps1 -PrinterHost 192.168.1.42 -Password mypass
#   .\install.ps1 -Revert

[CmdletBinding()]
param(
    [string]$PrinterHost = "",
    [string]$Password = "creality_2024",
    [switch]$Revert,
    [switch]$DryRun
)

# Do NOT set $ErrorActionPreference = "Stop" globally. Windows PowerShell 5.1
# raises NativeCommandError for any stderr from a native exe when that pref
# is Stop, which breaks normal Python probe calls. Use -ErrorAction Stop
# per-cmdlet where we genuinely want hard failure.
$InstallDir = Join-Path $env:USERPROFILE "K2-Screws-Tilt"
$BackupDir  = Join-Path $env:USERPROFILE "K2-Screws-Tilt\backups"
$RepoZipUrl = "https://github.com/grant0013/K2-Screws-Tilt/archive/refs/heads/main.zip"

function Write-Step($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[x] $msg" -ForegroundColor Red }

function Test-Python {
    foreach ($cmd in @("python", "py")) {
        try {
            $out = & $cmd --version 2>$null
            if ($LASTEXITCODE -eq 0 -and $out -match "Python\s+3\.") {
                return $cmd
            }
        } catch { continue }
    }
    return $null
}

function Test-Winget {
    try {
        $null = & winget --version 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Install-PythonViaWinget {
    Write-Step "Installing Python via winget (Python.Python.3.12)..."
    & winget install --exact --id Python.Python.3.12 `
        --scope user --silent `
        --accept-package-agreements --accept-source-agreements 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Err "winget Python install failed (exit $LASTEXITCODE)."
        return $false
    }
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $env:Path = $machinePath + ';' + $userPath
    Write-Ok "Python installed via winget; PATH refreshed."
    return $true
}

function Ensure-Python {
    $py = Test-Python
    if ($py) {
        Write-Ok "Python found: $py ($(& $py --version 2>&1))"
        return $py
    }
    Write-Warn "Python 3 not found on PATH."
    Write-Host ""
    if (Test-Winget) {
        Write-Host "winget is available. I can install Python 3.12 for you" -ForegroundColor Yellow
        Write-Host "(user-scoped, no admin needed)." -ForegroundColor Yellow
        Write-Host ""
        $yn = Read-Host "Install Python 3.12 via winget now? [Y/n]"
        if ($yn -ne "n") {
            if (Install-PythonViaWinget) {
                $py = Test-Python
                if ($py) {
                    Write-Ok "Python ready: $py"
                    return $py
                }
            }
        }
    }
    Write-Host "Manual install: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "IMPORTANT: tick 'Add Python to PATH' on the first screen." -ForegroundColor Yellow
    Write-Host ""
    $open = Read-Host "Open the Python download page now? [Y/n]"
    if ($open -ne "n") {
        Start-Process "https://www.python.org/downloads/"
    }
    exit 1
}

function Ensure-Paramiko($py) {
    Write-Step "Checking paramiko..."
    $check = & $py -c "import paramiko; print(paramiko.__version__)" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "paramiko present (version $check)"
        return
    }
    Write-Step "Installing paramiko (pip install --user)..."
    & $py -m pip install --user --quiet paramiko 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Err "pip install paramiko failed. Try manually:"
        Write-Err "  $py -m pip install --user paramiko"
        exit 1
    }
    Write-Ok "paramiko installed"
}

function Download-Repo {
    Write-Step "Downloading K2-Screws-Tilt from GitHub..."
    $tmpZip = Join-Path $env:TEMP "K2-Screws-Tilt-main.zip"
    Invoke-WebRequest -Uri $RepoZipUrl -OutFile $tmpZip -UseBasicParsing -ErrorAction Stop

    # Preserve backups dir across re-downloads.
    $preservedBackups = $null
    if (Test-Path $BackupDir) {
        $preservedBackups = Join-Path $env:TEMP "K2-Screws-Tilt-backups-preserve"
        if (Test-Path $preservedBackups) {
            Remove-Item -Recurse -Force $preservedBackups -ErrorAction Stop
        }
        Move-Item $BackupDir $preservedBackups -ErrorAction Stop
    }

    if (Test-Path $InstallDir) {
        Write-Step "Removing previous install at $InstallDir..."
        Remove-Item -Recurse -Force $InstallDir -ErrorAction Stop
    }

    Write-Step "Extracting to $InstallDir..."
    $tmpExtract = Join-Path $env:TEMP "K2-Screws-Tilt-extract"
    if (Test-Path $tmpExtract) { Remove-Item -Recurse -Force $tmpExtract -ErrorAction Stop }
    Expand-Archive -Path $tmpZip -DestinationPath $tmpExtract -ErrorAction Stop
    $inner = Get-ChildItem -Path $tmpExtract | Where-Object { $_.PSIsContainer } | Select-Object -First 1
    Move-Item $inner.FullName $InstallDir -ErrorAction Stop

    if ($preservedBackups) {
        New-Item -ItemType Directory -Path $BackupDir -Force -ErrorAction Stop | Out-Null
        Move-Item (Join-Path $preservedBackups "*") $BackupDir -ErrorAction Stop
        Remove-Item -Recurse -Force $preservedBackups -ErrorAction Stop
    }

    Remove-Item -Recurse -Force $tmpExtract, $tmpZip -ErrorAction SilentlyContinue
    Write-Ok "Repo ready at $InstallDir"
}

function Get-PrinterHost {
    if ($PrinterHost) { return $PrinterHost }
    Write-Host ""
    Write-Host "Find your printer's IP on the touchscreen:" -ForegroundColor Yellow
    Write-Host "  Settings -> Network -> IP Address (e.g. 192.168.1.170)" -ForegroundColor Yellow
    Write-Host ""
    do {
        $ip = Read-Host "Enter your printer's IP address"
        $ip = $ip.Trim()
    } while (-not ($ip -match "^\d{1,3}(\.\d{1,3}){3}$"))
    return $ip
}

function Run-Installer($py, [string[]]$extraArgs) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    $args = @("install_k2.py",
              "--host", $ip,
              "--password", $Password,
              "--local-backup-dir", $BackupDir)
    $args += $extraArgs
    if ($DryRun) { $args += "--dry-run" }

    $env:PYTHONIOENCODING = "utf-8"
    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

    Push-Location $InstallDir
    $rc = $null
    try {
        & $py @args 2>&1 | Out-Host
        $rc = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    return [int]$rc
}

function Detect-Install($py) {
    Write-Step "Checking printer state at $ip..."
    $detectArgs = @("install_k2.py",
                    "--host", $ip,
                    "--password", $Password,
                    "--detect")
    Push-Location $InstallDir
    try { $out = & $py @detectArgs 2>&1 | Out-String } finally { Pop-Location }
    $status = ($out -split "`n" | Where-Object { $_ -match "K2ST_STATUS=" } | Select-Object -First 1)
    $board  = ($out -split "`n" | Where-Object { $_ -match "K2ST_BOARD=" }  | Select-Object -First 1)
    if ($status -match "K2ST_STATUS=(\w+)") { $s = $Matches[1] } else { $s = "unknown" }
    if ($board  -match "K2ST_BOARD=(\w+)")  { $b = $Matches[1] } else { $b = "unknown" }
    return @{ Status = $s; Board = $b; RawOutput = $out }
}

function Show-Menu($detected) {
    Write-Host ""
    Write-Host "================================================" -ForegroundColor Cyan
    Write-Host " K2-Screws-Tilt is already installed." -ForegroundColor Cyan
    Write-Host " Board detected: $($detected.Board)" -ForegroundColor Cyan
    Write-Host "================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  [1] Update / reinstall (pulls latest from GitHub)"
    Write-Host "  [2] Revert (remove module, restore configs)"
    Write-Host "  [3] Exit without changes"
    Write-Host ""
    do {
        $choice = Read-Host "Choose [1-3]"
    } while ($choice -notin @("1", "2", "3"))
    return $choice
}

# --- main -------------------------------------------------------------------

Write-Host ""
Write-Host "=================================" -ForegroundColor Cyan
Write-Host " K2-Screws-Tilt PowerShell installer" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan
Write-Host ""

try {
    $py = Ensure-Python
    Ensure-Paramiko $py
    try {
        [Net.ServicePointManager]::SecurityProtocol =
            [Net.ServicePointManager]::SecurityProtocol -bor
            [Net.SecurityProtocolType]::Tls12
    } catch { }
    $ProgressPreference = 'SilentlyContinue'
    Download-Repo
} catch {
    Write-Host ""
    Write-Host "[x] Setup / download failed:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Yellow
    exit 1
}

$ip = Get-PrinterHost

if ($Revert) {
    Write-Step "Running revert against $ip..."
    $rc = Run-Installer $py @("--revert")
    exit $rc
}

$detected = Detect-Install $py
if ($detected.Status -eq "installed") {
    $choice = Show-Menu $detected
    switch ($choice) {
        "1" {
            Write-Step "Running update/reinstall against $ip..."
            $rc = Run-Installer $py @()
        }
        "2" {
            Write-Step "Running revert against $ip..."
            $rc = Run-Installer $py @("--revert")
        }
        "3" {
            Write-Ok "Exited without changes."
            exit 0
        }
    }
} elseif ($detected.Status -eq "fresh") {
    Write-Ok "No existing install detected. Board: $($detected.Board)"
    Write-Step "Running installer against $ip..."
    $rc = Run-Installer $py @()
} else {
    Write-Warn "Could not determine install state. Detect output:"
    Write-Host $detected.RawOutput
    $go = Read-Host "Proceed with install anyway? [y/N]"
    if ($go -ne "y") { exit 1 }
    $rc = Run-Installer $py @()
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
if ($rc -eq 0) {
    Write-Ok "K2-Screws-Tilt install complete."
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor White
    Write-Host "  1. Open Fluidd / Mainsail and enter this in the gcode console:" -ForegroundColor White
    Write-Host "       G28" -ForegroundColor Gray
    Write-Host "       SCREWS_TILT_CALCULATE" -ForegroundColor Gray
    Write-Host "  2. Klipper will probe each bed screw position and tell you" -ForegroundColor White
    Write-Host "     how many turns to adjust each screw by." -ForegroundColor White
    Write-Host "  3. Adjust your bed screws, re-run, repeat until all report" -ForegroundColor White
    Write-Host "     'adjusted' within your threshold." -ForegroundColor White
    Write-Host ""
    Write-Host "Local backups kept at: $BackupDir" -ForegroundColor Gray
    Write-Host "These survive printer firmware updates. Keep them safe." -ForegroundColor Gray
    Write-Host ""
    Write-Host "To revert later:" -ForegroundColor Gray
    Write-Host "  .\install.ps1 -PrinterHost $ip -Revert" -ForegroundColor Gray
} else {
    Write-Err "K2-Screws-Tilt install FAILED (exit code $rc)."
    Write-Host ""
    Write-Host "Scroll up for [x] / [!] lines. Open an issue with the full" -ForegroundColor Yellow
    Write-Host "terminal output:" -ForegroundColor Yellow
    Write-Host "  https://github.com/grant0013/K2-Screws-Tilt/issues" -ForegroundColor Yellow
}
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Enter to close this window." -ForegroundColor Gray
$null = Read-Host
exit $rc

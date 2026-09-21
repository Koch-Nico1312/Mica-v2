param(
    [switch]$NoUpdate,
    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"

# ── Paths ────────────────────────────────────────────────────────────────────
# Everything is derived from this script's own location, so the launcher behaves
# identically when it is double-clicked (working directory: C:\Windows\System32),
# started from a shortcut, or invoked from any shell in any directory.
$scriptPath = $MyInvocation.MyCommand.Path
if ([string]::IsNullOrEmpty($scriptPath)) { $scriptPath = $PSCommandPath }
if ([string]::IsNullOrEmpty($scriptPath)) { $scriptPath = $MyInvocation.MyCommand.Definition }

if (-not [string]::IsNullOrEmpty($scriptPath)) {
    $projectDir = Split-Path -Parent $scriptPath
} else {
    $projectDir = (Get-Location).Path
}
if ([string]::IsNullOrEmpty($projectDir)) { $projectDir = (Get-Location).Path }
$projectDir = (Resolve-Path -LiteralPath $projectDir).Path

$desktopDir       = Join-Path $projectDir "desktop"
$venvDir          = Join-Path $projectDir ".venv-local"
$pythonExe        = Join-Path $venvDir "Scripts\python.exe"
$requirementsLock = Join-Path $projectDir "requirements-phase0.lock"
$entryPoint       = Join-Path $desktopDir "local_main.py"
$newUiModule      = Join-Path $desktopDir "ui.py"
$newUiAsset       = Join-Path $desktopDir "assets\mica-orb-v2.png"
$uvInstallerUrl   = "https://astral.sh/uv/install.ps1"
# Must match the --python-version the lock file was compiled with (see header of
# requirements-phase0.lock), otherwise the pinned wheels may not fit.
$pythonVersion    = "3.13"

# Function to show progress bar
function Show-Progress {
    param(
        [string]$Activity,
        [string]$Status,
        [int]$PercentComplete
    )
    Write-Progress -Activity $Activity -Status $Status -PercentComplete $PercentComplete
}

# Rebuild $env:Path from the registry so a just-installed tool is usable without
# opening a new shell.  Both scopes are merged on purpose: replacing Path with
# the Machine value alone would silently drop everything installed per-user.
function Update-SessionPath {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $entries = @($machine, $user) | Where-Object { $_ } | ForEach-Object { $_.TrimEnd(";") }
    $env:Path = ($entries -join ";")

    # The uv installer drops uv.exe here and updates the user Path; add these
    # locations explicitly in case that update did not reach this session.
    foreach ($dir in @(
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:USERPROFILE ".cargo\bin")
    )) {
        if ((Test-Path -LiteralPath $dir) -and ($env:Path -notlike "*$dir*")) {
            $env:Path = "$dir;$env:Path"
        }
    }
}

# Returns the full path to uv.exe, or $null when uv is not installed yet.
function Resolve-Uv {
    $command = Get-Command "uv" -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    foreach ($candidate in @(
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe")
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

# Fetch and fast-forward the checked-out branch when that can be done without
# touching local work. A failed/offline update must never prevent MICA itself
# from starting, and the launcher never stashes, resets, or deletes user files.
function Update-MICA {
    if ($NoUpdate -or $env:MICA_SKIP_UPDATE -eq "1") {
        Write-Host "⏭️  Automatic update skipped." -ForegroundColor DarkGray
        return
    }

    $git = Get-Command "git" -ErrorAction SilentlyContinue
    if (-not $git -or -not (Test-Path -LiteralPath (Join-Path $projectDir ".git"))) {
        Write-Host "ℹ️  No Git checkout found; starting the installed version." -ForegroundColor Yellow
        return
    }

    Write-Host "🔄 Checking for MICA updates..." -ForegroundColor Cyan
    Push-Location -LiteralPath $projectDir
    try {
        $branchOutput = @(& $git.Source symbolic-ref --quiet --short HEAD 2>$null)
        $branchExit = $LASTEXITCODE
        $branch = $branchOutput | Select-Object -First 1
        if ($branchExit -ne 0 -or [string]::IsNullOrWhiteSpace($branch)) {
            Write-Host "ℹ️  Detached Git state; automatic update skipped." -ForegroundColor Yellow
            return
        }

        $upstreamOutput = @(& $git.Source rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>$null)
        $upstreamExit = $LASTEXITCODE
        $upstream = $upstreamOutput | Select-Object -First 1
        if ($upstreamExit -ne 0 -or [string]::IsNullOrWhiteSpace($upstream)) {
            Write-Host "ℹ️  Branch '$branch' has no upstream; automatic update skipped." -ForegroundColor Yellow
            return
        }

        & $git.Source fetch --quiet --prune
        if ($LASTEXITCODE -ne 0) {
            Write-Host "⚠️  Update server unavailable; starting the installed version." -ForegroundColor Yellow
            return
        }

        $localOutput = @(& $git.Source rev-parse HEAD 2>$null)
        $localExit = $LASTEXITCODE
        $localCommit = $localOutput | Select-Object -First 1
        $remoteOutput = @(& $git.Source rev-parse $upstream 2>$null)
        $remoteExit = $LASTEXITCODE
        $remoteCommit = $remoteOutput | Select-Object -First 1
        if ($localExit -ne 0 -or $remoteExit -ne 0 -or [string]::IsNullOrWhiteSpace($remoteCommit)) {
            Write-Host "⚠️  Upstream state could not be read; starting the installed version." -ForegroundColor Yellow
            return
        }
        if ($localCommit -eq $remoteCommit) {
            Write-Host "✅ MICA is already up to date." -ForegroundColor Green
            return
        }

        $dirty = @(& $git.Source status --porcelain --untracked-files=normal 2>$null)
        $dirtyExit = $LASTEXITCODE
        if ($dirtyExit -ne 0) {
            Write-Host "⚠️  Working tree state could not be checked; update skipped safely." -ForegroundColor Yellow
            return
        }
        if ($dirty) {
            Write-Host "⚠️  Local changes found; update skipped so nothing is overwritten." -ForegroundColor Yellow
            Write-Host "   Commit or save the changes, then start this file again." -ForegroundColor DarkGray
            return
        }

        & $git.Source merge-base --is-ancestor HEAD $upstream 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "⚠️  Local and remote history differ; automatic update skipped." -ForegroundColor Yellow
            return
        }

        & $git.Source pull --ff-only --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-Host "⚠️  Update failed; starting the previously installed version." -ForegroundColor Yellow
            return
        }
        Write-Host "✅ MICA updated successfully." -ForegroundColor Green
    }
    catch {
        Write-Host "⚠️  Update check failed: $_" -ForegroundColor Yellow
        Write-Host "   Starting the installed version." -ForegroundColor DarkGray
    }
    finally {
        Pop-Location
    }
}

# Function to install dependencies
function Install-Dependencies {
    Write-Host "🔧 Checking dependencies..." -ForegroundColor Cyan

    try {
        # Run the whole install inside the project directory: uv writes caches
        # and temporary files relative to the working directory, and the caller
        # may have started us from anywhere.
        Push-Location -LiteralPath $projectDir
        try {
            $uvPath = Resolve-Uv

            if (-not $uvPath) {
                Write-Host "📥 Installing uv package manager..." -ForegroundColor Cyan
                Show-Progress -Activity "Installing uv" -Status "Downloading uv installer..." -PercentComplete 10

                # Download into the system temp directory - never into the
                # current working directory, which may be read-only (System32)
                # or an unrelated folder.
                $installerPath = Join-Path ([System.IO.Path]::GetTempPath()) ("uv-install-" + [guid]::NewGuid().ToString("N") + ".ps1")
                try {
                    $download = @{ Uri = $uvInstallerUrl; OutFile = $installerPath }
                    if ($PSVersionTable.PSEdition -eq "Desktop") { $download["UseBasicParsing"] = $true }
                    Invoke-WebRequest @download

                    Show-Progress -Activity "Installing uv" -Status "Running uv installer..." -PercentComplete 30
                    # Bypass the execution policy for the installer: a freshly
                    # downloaded script carries the Mark-of-the-Web and would be
                    # refused under RemoteSigned.
                    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installerPath
                    if ($LASTEXITCODE -ne 0) { throw "The uv installer exited with code $LASTEXITCODE." }
                }
                finally {
                    if (Test-Path -LiteralPath $installerPath) { Remove-Item -LiteralPath $installerPath -Force }
                }

                Update-SessionPath
                $uvPath = Resolve-Uv
                if (-not $uvPath) { throw "uv was installed but uv.exe could not be located." }
                Show-Progress -Activity "Installing uv" -Status "uv installed successfully" -PercentComplete 50
            }

            if (-not (Test-Path -LiteralPath $pythonExe)) {
                Write-Host "⚠️  Local Python environment not found." -ForegroundColor Yellow
                Write-Host "🐍 Creating local Python environment..." -ForegroundColor Cyan
                Show-Progress -Activity "Setting up environment" -Status "Creating virtual environment..." -PercentComplete 60
                # --clear because uv refuses to touch an incomplete environment.
                & $uvPath venv $venvDir --python $pythonVersion --clear
                if ($LASTEXITCODE -ne 0) { throw "uv venv failed with exit code $LASTEXITCODE." }
                Show-Progress -Activity "Setting up environment" -Status "Virtual environment created" -PercentComplete 70
            }
            else {
                Write-Host "✅ Local Python environment found." -ForegroundColor Green
            }

            Write-Host "📦 Synchronizing Python dependencies..." -ForegroundColor Cyan
            Show-Progress -Activity "Installing dependencies" -Status "Syncing packages from lock file..." -PercentComplete 80
            # --python pins the target environment explicitly, so an activated or
            # otherwise discovered venv cannot hijack the install.
            & $uvPath pip sync --python $pythonExe $requirementsLock
            if ($LASTEXITCODE -ne 0) { throw "uv pip sync failed with exit code $LASTEXITCODE." }
            Show-Progress -Activity "Installing dependencies" -Status "Dependencies installed successfully" -PercentComplete 100
            Write-Progress -Activity "Installing dependencies" -Completed -PercentComplete 100

            if (-not (Test-Path -LiteralPath $pythonExe)) {
                throw "The virtual environment was created but $pythonExe is missing."
            }

            Write-Host ""
            Write-Host "✅ Installation and dependency update completed." -ForegroundColor Green
            Write-Host ""
        }
        finally {
            Pop-Location
        }
    }
    catch {
        Write-Host "❌ Error during installation: $_" -ForegroundColor Red
        Write-Host "   Please try running the script again or install dependencies manually." -ForegroundColor Yellow
        throw
    }
}

function Test-NewUI {
    foreach ($required in @($entryPoint, $newUiModule, $newUiAsset)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "The new MICA UI is incomplete. Missing file: $required"
        }
    }

    Push-Location -LiteralPath $desktopDir
    $oldQtPlatform = $env:QT_QPA_PLATFORM
    $oldPythonPath = $env:PYTHONPATH
    try {
        $env:QT_QPA_PLATFORM = "offscreen"
        $env:PYTHONPATH = "$desktopDir;$projectDir"
        & $pythonExe -c "import ui; assert getattr(ui, 'MICA_UI_GENERATION', 0) >= 2, 'legacy UI detected'"
        if ($LASTEXITCODE -ne 0) {
            throw "The new MICA UI validation failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        if ($null -eq $oldQtPlatform) {
            Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
        }
        else {
            $env:QT_QPA_PLATFORM = $oldQtPlatform
        }
        if ($null -eq $oldPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
        else {
            $env:PYTHONPATH = $oldPythonPath
        }
        Pop-Location
    }
    Write-Host "✅ New MICA UI verified." -ForegroundColor Green
}

# Function to start MICA Core
function Start-MICACore {
    Write-Host "🚀 Starting MICA Core..." -ForegroundColor Cyan
    Write-Host ""

    try {
        # MICA resolves its assets relative to the working directory.
        Set-Location -LiteralPath $desktopDir
        & $pythonExe $entryPoint
        if ($LASTEXITCODE -ne 0) {
            throw "MICA exited with code $LASTEXITCODE."
        }
    }
    catch {
        Write-Host "❌ Error starting MICA Core: $_" -ForegroundColor Red
        Write-Host "   Please check that all dependencies are installed correctly." -ForegroundColor Yellow
        throw
    }
}

# Main execution
try {
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "   MICA V2 - Installation & Launcher" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "   Project: $projectDir" -ForegroundColor DarkGray
    Write-Host ""

    # One double-click updates code and dependencies before starting the UI.
    Update-MICA
    Install-Dependencies
    Test-NewUI

    if (-not $SetupOnly) {
        Start-MICACore
    }
}
catch {
    Write-Host "❌ Fatal error: $_" -ForegroundColor Red
    Write-Host "   Press any key to exit..." -ForegroundColor Yellow
    # RawUI is unavailable in hosts without a console (redirected output, some
    # terminal integrations); without this guard the error message would be lost.
    try {
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
    catch {
        Start-Sleep -Seconds 5
    }
    exit 1
}

$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectDir ".venv-local\Scripts\python.exe"
$requirementsLock = Join-Path $projectDir "requirements-phase0.lock"
$uvExe = "uv"

# Function to show progress bar
function Show-Progress {
    param(
        [string]$Activity,
        [string]$Status,
        [int]$PercentComplete
    )
    Write-Progress -Activity $Activity -Status $Status -PercentComplete $PercentComplete
}

# Function to install dependencies
function Install-Dependencies {
    Write-Host "🔧 Checking dependencies..." -ForegroundColor Cyan
    
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        Write-Host "⚠️  WARNING: Local Python environment not found." -ForegroundColor Yellow
        Write-Host "📦 Installing dependencies - this may take several minutes..." -ForegroundColor Yellow
        Write-Host "   Please be patient, this is a one-time setup." -ForegroundColor Yellow
        Write-Host ""
        
        try {
            # Check if uv is installed
            $uvInstalled = Get-Command $uvExe -ErrorAction SilentlyContinue
            
            if (-not $uvInstalled) {
                Write-Host "📥 Installing uv package manager..." -ForegroundColor Cyan
                Show-Progress -Activity "Installing uv" -Status "Downloading uv installer..." -PercentComplete 10
                Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -OutFile "install.ps1"
                Show-Progress -Activity "Installing uv" -Status "Running uv installer..." -PercentComplete 30
                & ./install.ps1
                Remove-Item "install.ps1"
                Show-Progress -Activity "Installing uv" -Status "uv installed successfully" -PercentComplete 50
                $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
                $uvExe = "uv"
            }
            
            Write-Host "🐍 Creating local Python environment..." -ForegroundColor Cyan
            Show-Progress -Activity "Setting up environment" -Status "Creating virtual environment..." -PercentComplete 60
            & $uvExe venv ".venv-local" --python 3.12
            Show-Progress -Activity "Setting up environment" -Status "Virtual environment created" -PercentComplete 70
            
            Write-Host "📦 Installing Python dependencies..." -ForegroundColor Cyan
            Show-Progress -Activity "Installing dependencies" -Status "Syncing packages from lock file..." -PercentComplete 80
            & $uvExe pip sync --python $pythonExe $requirementsLock
            Show-Progress -Activity "Installing dependencies" -Status "Dependencies installed successfully" -PercentComplete 100
            Write-Progress -Activity "Installing dependencies" -Completed -PercentComplete 100
            
            Write-Host ""
            Write-Host "✅ Installation completed successfully!" -ForegroundColor Green
            Write-Host ""
        }
        catch {
            Write-Host "❌ Error during installation: $_" -ForegroundColor Red
            Write-Host "   Please try running the script again or install dependencies manually." -ForegroundColor Yellow
            throw
        }
    } else {
        Write-Host "✅ Local Python environment found at: $pythonExe" -ForegroundColor Green
        Write-Host "✅ Dependencies already installed." -ForegroundColor Green
        Write-Host ""
    }
}

# Function to start MICA Core
function Start-MICACore {
    Write-Host "🚀 Starting MICA Core..." -ForegroundColor Cyan
    Write-Host ""
    
    try {
        Set-Location -LiteralPath $projectDir
        & $pythonExe "local_main.py"
    }
    catch {
        Write-Host "❌ Error starting MICA Core: $_" -ForegroundColor Red
        Write-Host "   Please check that all dependencies are installed correctly." -ForegroundColor Yellow
    }
}

# Main execution
try {
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "   MICA V2 - Installation & Launcher" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
    
    # Install dependencies if needed
    Install-Dependencies
    
    # Start MICA
    Start-MICACore
}
catch {
    Write-Host "❌ Fatal error: $_" -ForegroundColor Red
    Write-Host "   Press any key to exit..." -ForegroundColor Yellow
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
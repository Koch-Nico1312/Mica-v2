$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectDir ".venv-local\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Lokale MICA-Umgebung fehlt: $pythonExe"
}

Set-Location -LiteralPath $projectDir
& $pythonExe "local_main.py"

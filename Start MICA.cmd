@echo off
setlocal
cd /d "%~dp0"
python -m desktop.start_mica
if errorlevel 1 pause
endlocal

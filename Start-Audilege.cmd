@echo off
setlocal
cd /d "%~dp0"
if exist AudilegeServer.exe (
  AudilegeServer.exe --bind 0.0.0.0 --open %*
  pause
  exit /b
)
where python.exe >nul 2>&1
if errorlevel 1 (
  echo Bitte Python 3.10 oder neuer installieren und zum PATH hinzufuegen.
  pause
  exit /b 1
)
python server.py --bind 0.0.0.0 --open %*
if errorlevel 1 pause

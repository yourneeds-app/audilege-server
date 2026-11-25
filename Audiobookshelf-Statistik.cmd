@echo off
setlocal
cd /d "%~dp0"
if exist AudilegeServer.exe (
  AudilegeServer.exe --abs-assistent
) else (
  python server.py --abs-assistent
)
pause

@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "%~dp0openmontage_studio.py"
) else (
  start "" pythonw "%~dp0openmontage_studio.py"
)
endlocal

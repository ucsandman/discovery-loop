@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" dashboard.py --open
) else (
  python dashboard.py --open
)

@echo off
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo Install uv first, then retry. See README.md.
  pause
  exit /b 1
)
uv run --locked --no-env-file python -m agent.launch %*
if errorlevel 1 pause

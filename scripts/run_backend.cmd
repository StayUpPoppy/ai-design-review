@echo off
setlocal
cd /d "%~dp0\.."
".venv\Scripts\python.exe" -m uvicorn ai_design_review.api:app --app-dir src --host 127.0.0.1 --port 8770

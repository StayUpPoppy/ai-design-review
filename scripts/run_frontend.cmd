@echo off
setlocal
cd /d "%~dp0\.."
".venv\Scripts\python.exe" -m http.server 5173 --bind 127.0.0.1 --directory frontend

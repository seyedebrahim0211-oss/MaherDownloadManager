@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1 || (echo Please install Python 3.12 first. & pause & exit /b 1)
if not exist .venv\Scripts\python.exe py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt || (pause & exit /b 1)
.venv\Scripts\pythonw.exe app.py

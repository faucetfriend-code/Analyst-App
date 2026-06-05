@echo off
REM Kills any existing instance on port 5051, then starts fresh
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :5051 ^| findstr LISTENING') do (
    taskkill /PID %%p /F >nul 2>&1
)
cd /d "%~dp0"
echo Starting Analyst App on http://localhost:5051
python app.py

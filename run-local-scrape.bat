@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
REM Scheduled entry point. Code history stays untouched; data uses snapshots.
REM Logs and 30-day rescue backups are kept under ignored logs/.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
python tools/local_scrape.py
exit /b %errorlevel%

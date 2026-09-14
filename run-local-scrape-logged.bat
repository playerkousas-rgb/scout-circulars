@echo off
chcp 65001 >nul
REM ============================================================
REM run-local-scrape-logged.bat - logging wrapper for run-local-scrape.bat
REM
REM Point Windows Task Scheduler at THIS file:
REM   Program/script : cmd.exe
REM   Add arguments  : /c "<repo>\run-local-scrape-logged.bat"
REM   Start in       : <repo>
REM
REM It calls run-local-scrape.bat unchanged, appends all stdout / stderr to
REM logs\scrape.log in this same folder, and writes a start line plus an end
REM line carrying the exit code - so a run that dies half way still leaves
REM evidence behind.
REM
REM logs\ is listed in .gitignore, so the log never dirties the working tree
REM and can never block the daily pull. The exit code is handed back to Task
REM Scheduler unchanged, so the task history still reports success/failure.
REM
REM KEEP THIS FILE PURE ASCII WITH CRLF LINE ENDINGS (see .gitattributes).
REM cmd reads a .bat through the console codepage. On a cp950 machine the
REM double-byte decoder drifts across UTF-8 CJK bytes and can swallow a line
REM break or the REM keyword itself, so comment text ends up running as
REM commands. That is exactly what happened on 2026-09-14:
REM     'xxxx' is not recognized as an internal or external command
REM for five fragments of this file's own comments. Pure ASCII removes the
REM whole class of failure.
REM ============================================================
setlocal
cd /d "%~dp0"

REM stdout gets redirected into a log file, and Windows would encode it as
REM cp950, so core.py / enrich.py die with a UnicodeEncodeError on the first
REM emoji or CJK character they print. Setting it here too means even an
REM older run-local-scrape.bat is covered.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "%~dp0logs" mkdir "%~dp0logs"
set "SC_LOG=%~dp0logs\scrape.log"

REM size-based rotation. A subroutine is used on purpose: testing a variable
REM and comparing it on the same line is a syntax error while that variable
REM is still undefined, and cmd is very picky about that.
for %%F in ("%SC_LOG%") do call :maybe_rotate "%%~zF"

echo ===== %date% %time% ===== run-local-scrape start >> "%SC_LOG%"
call run-local-scrape.bat >> "%SC_LOG%" 2>&1
set "SC_RC=%errorlevel%"
echo ===== %date% %time% ===== run-local-scrape end exit=%SC_RC% >> "%SC_LOG%"
exit /b %SC_RC%

:maybe_rotate
REM the argument is the size of scrape.log in bytes; empty means no file yet
if "%~1"=="" exit /b 0
if %~1 LSS 2000001 exit /b 0
if exist "%SC_LOG%.1" del /q "%SC_LOG%.1"
move /y "%SC_LOG%" "%SC_LOG%.1" >nul
exit /b 0

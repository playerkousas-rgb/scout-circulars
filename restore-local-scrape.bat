@echo off
chcp 65001 >nul
setlocal
REM ============================================================
REM restore-local-scrape.bat - one-shot local repair
REM
REM Original purpose: break the death loop left by an older
REM run-local-scrape.bat, which died between "git add" and "git commit"
REM and left staged files that blocked every later pull:
REM     error: cannot pull with rebase: Your index contains uncommitted
REM     changes.
REM Because the pull was blocked, the machine could never fetch the fixed
REM script - a self-sustaining loop.
REM
REM NOTE: run-local-scrape.bat now clears staged leftovers, stale locks and
REM half-finished rebases by itself at start-up, so this tool is mostly a
REM spare tyre. Keep it for the case where the main script cannot even start.
REM
REM Steps:
REM   0. confirm origin really is the scout-circulars repo (wrong-remote guard)
REM   1. unstage everything (working tree files are not touched)
REM   2. back up the three data files and both .bat files to logs\recovery\
REM   3. discard leftover half-written data files (already backed up; the next
REM      full crawl regenerates them)
REM   4. clear stale locks and half-finished rebase / merge / cherry-pick
REM   5. pull the latest from GitHub
REM   6. REPORT whether the .bat files differ from HEAD - never overwrite them
REM
REM Step 6 used to run "git checkout -- run-local-scrape*.bat". That was
REM removed on 2026-09-14 because it is dangerous: if main still carries an
REM older, broken copy of a .bat, that checkout silently replaces a locally
REM fixed file with the broken one. This script now only reports, and lets
REM you decide.
REM
REM Usage: double-click once from the repo root. No admin rights needed.
REM
REM KEEP THIS FILE PURE ASCII WITH CRLF LINE ENDINGS (see .gitattributes).
REM cmd reads a .bat through the console codepage; on a cp950 machine the
REM double-byte decoder drifts across UTF-8 CJK bytes and can swallow a line
REM break or the REM keyword, so comment text ends up running as commands.
REM ============================================================
cd /d "%~dp0"

echo [0/6] checking the origin remote...
git remote get-url origin 2>nul | findstr /i "scout-circulars" >nul
if errorlevel 1 goto wrong_remote
git remote get-url origin

echo [1/6] unstaging everything (git reset; working tree files untouched)...
git reset -q HEAD
if errorlevel 1 goto fail

echo [2/6] backing up data files and .bat files to logs\recovery\...
if not exist logs\recovery mkdir logs\recovery
set "STAMP="
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "STAMP=%%T"
if not defined STAMP set "STAMP=backup"
copy /y cache.json "logs\recovery\cache.json.%STAMP%" >nul 2>&1
copy /y enrich.json "logs\recovery\enrich.json.%STAMP%" >nul 2>&1
copy /y fingerprints.json "logs\recovery\fingerprints.json.%STAMP%" >nul 2>&1
copy /y run-local-scrape.bat "logs\recovery\run-local-scrape.bat.%STAMP%" >nul 2>&1
copy /y run-local-scrape-logged.bat "logs\recovery\run-local-scrape-logged.bat.%STAMP%" >nul 2>&1
echo     backed up as logs\recovery\*.%STAMP%

echo [3/6] discarding leftover half-written data files (backed up above)...
git reset -q HEAD -- cache.json enrich.json fingerprints.json
git checkout -- cache.json enrich.json fingerprints.json 2>nul

echo [4/6] clearing stale locks and half-finished rebase / merge...
if exist .git\index.lock del /f /q .git\index.lock
if exist .git\rebase-merge git rebase --abort
if exist .git\rebase-apply git rebase --abort
if exist .git\MERGE_HEAD git merge --abort
if exist .git\CHERRY_PICK_HEAD git cherry-pick --abort

echo [5/6] pulling the latest from GitHub...
REM --autostash so a locally fixed .bat cannot block the pull
git pull --rebase --autostash origin main
if errorlevel 1 goto fail

echo [6/6] comparing the .bat files against HEAD (report only, no overwrite)...
git diff --stat -- run-local-scrape.bat run-local-scrape-logged.bat
git status --porcelain -- run-local-scrape.bat run-local-scrape-logged.bat
echo     If the two lines above are empty, your .bat files match GitHub.
echo     If not, they differ on purpose (e.g. a fix not pushed yet).
echo     To take GitHub's copy: git checkout -- run-local-scrape-logged.bat
echo     - but ONLY after confirming that copy is correct.

echo.
echo -- current state --
git remote -v
git status --short
git log --oneline -1
echo.
echo Done.
echo   To verify now: double-click run-local-scrape-logged.bat
echo   (full re-crawl, takes a few minutes), or just wait for the 05:00 task.
exit /b 0

:wrong_remote
echo.
echo origin is not the scout-circulars repo - nothing was touched.
echo   Run: git remote -v
exit /b 1

:fail
echo.
echo Repair failed - see the git message above.
echo   Your data is backed up in logs\recovery\ so nothing is lost.
exit /b 1

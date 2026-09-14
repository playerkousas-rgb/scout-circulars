@echo off
chcp 65001 >nul
setlocal
REM ============================================================
REM restore-local-scrape.bat — 本機一次性修復（2026-09-14）
REM
REM 用途：修好舊版 run-local-scrape.bat 留低嘅死循環：
REM   「error: cannot pull with rebase: Your index contains
REM    uncommitted changes.」
REM 成因：舊版腳本喺「git add 之後、git commit 之前」死咗，留低 staged
REM   殘餘（cache.json／fingerprints.json 等）→ 之後每日 pull --rebase
REM   都俾擋住 → 永遠拉唔到 GitHub 嗰個已修好嘅新版腳本（死循環）。
REM
REM 呢個檔嘅步驟：
REM   0. 確認 origin 係 scout-circulars repo（防錯拉）
REM   1. 全部 unstage（git reset，工作區檔案一個字都唔郁）
REM   2. 先備份三個資料檔＋現有兩個 .bat 去 logs\recovery\
REM   3. 清走殘留未完嘅資料檔（已經備份過；之後全網巡邏會補返）
REM   4. 清走殘留 lock／半成品 rebase
REM   5. 由 GitHub 拉最新（包括修好嘅 run-local-scrape.bat）
REM   6. 兩個 .bat 還原返去 GitHub 版本（即 main 上嗰份）
REM
REM 用法：喺 repo 根目錄（即呢個檔所在目錄）double-click 行一次就得。
REM 行完之後可以 double-click run-local-scrape-logged.bat 即刻驗證
REM （會全網重新巡邏一次，要幾分鐘），或者等下次排程自動行。
REM 唔使 admin 權限。
REM ============================================================
cd /d "%~dp0"

echo [0/6] 確認 origin 遠端...
git remote get-url origin 2>nul | findstr /i "scout-circulars" >nul
if errorlevel 1 goto wrong_remote
git remote get-url origin

echo [1/6] Unstage 全部（git reset；工作區檔案本身唔郁）...
git reset -q HEAD
if errorlevel 1 goto fail

echo [2/6] 備份現有資料檔同 .bat 去 logs\recovery\...
if not exist logs\recovery mkdir logs\recovery
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss" 2^>nul') do set "STAMP=%%T"
if not defined STAMP set "STAMP=backup"
copy /y cache.json "logs\recovery\cache.json.%STAMP%" >nul 2>&1
copy /y enrich.json "logs\recovery\enrich.json.%STAMP%" >nul 2>&1
copy /y fingerprints.json "logs\recovery\fingerprints.json.%STAMP%" >nul 2>&1
copy /y run-local-scrape.bat "logs\recovery\run-local-scrape.bat.%STAMP%" >nul 2>&1
copy /y run-local-scrape-logged.bat "logs\recovery\run-local-scrape-logged.bat.%STAMP%" >nul 2>&1
echo     備份完成（logs\recovery\*.%STAMP%）

echo [3/6] 清走殘留未完嘅資料檔（已備份；之後全網巡邏會重新生成）...
git reset -q HEAD -- cache.json enrich.json fingerprints.json
git checkout -- cache.json enrich.json fingerprints.json 2>nul

echo [4/6] 清走殘留 lock／半成品 rebase...
if exist .git\index.lock del /f /q .git\index.lock
if exist .git\rebase-merge git rebase --abort
if exist .git\rebase-apply git rebase --abort
if exist .git\MERGE_HEAD git merge --abort
if exist .git\CHERRY_PICK_HEAD git cherry-pick --abort

echo [5/6] 由 GitHub 拉最新版本（包括修好嘅 run-local-scrape.bat）...
git pull --rebase origin main
if errorlevel 1 goto fail

echo [6/6] 兩個 .bat 還原返去 GitHub 版本...
git checkout -- run-local-scrape.bat run-local-scrape-logged.bat 2>nul

echo.
echo ── 而家狀態 ──
git remote -v
git status --short
git log --oneline -1
echo.
echo ✔ 修復完成。
echo   想即刻驗證：double-click run-local-scrape-logged.bat
echo   （全網重新巡邏一次，要幾分鐘；有增量先至會 push 上 Git）
echo   或者等下次 05:00 排程自動行，唔使再做任何嘢。
exit /b 0

:wrong_remote
echo.
echo ✘ origin 遠端唔係 scout-circulars repo，為安全起見唔郁任何嘢。
echo   請行 `git remote -v` 睇吓指向邊度。
exit /b 1

:fail
echo.
echo ✘ 修復失敗：睇上面嘅 git 錯誤訊息；或者將全部輸出＋logs\scrape.log 一齊俾開發者。
echo   （數據有備份喺 logs\recovery\，冇咗嘢。）
exit /b 1

@echo off
chcp 65001 >nul
setlocal

REM 強制 Python 在 Windows 背景／重定向至日誌檔時使用純 UTF-8 編碼（防止 cp950 編碼 Emoji 報錯）
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM 自動切換到本腳本所在資料夾
cd /d "%~dp0"

REM ── 1. 自動清除上次可能殘留的 Git 鎖或衝突 ──
if exist .git\index.lock del /f /q .git\index.lock
if exist .git\rebase-merge git rebase --abort >nul 2>&1
if exist .git\rebase-apply git rebase --abort >nul 2>&1

REM ── 2. 拉取 GitHub 最新進度 ──
echo [%date% %time%] 正在拉取 GitHub 最新進度…
git pull --rebase origin main
if errorlevel 1 goto failed

REM ── 3. 強制巡邏全部 49 個來源（補漏） ──
echo [%date% %time%] 正在執行本機來源巡邏（比對指紋補漏）…
python core.py --force
if errorlevel 1 goto failed

REM ── 4. 抽取新通告的文字內容 ──
echo [%date% %time%] 正在執行 PDF 增量內容抽取…
python enrich.py --verbose
if errorlevel 1 goto failed

REM ── 5. 檢查是否有新通告需提交 ──
echo [%date% %time%] 檢查是否有新通告需提交…
git add cache.json enrich.json fingerprints.json
git diff --cached --quiet
if not errorlevel 1 (
    echo [%date% %time%] 檢查完畢：所有來源已齊全（無遺漏新通告），毋須 Push。
    goto done
)

REM ── 6. 發現新通告，Commit 並 Push ──
echo [%date% %time%] 發現新通告！正在提交並 Push 上 GitHub…
git commit -m "🤖 Local backup scrape"
if errorlevel 1 goto failed

git push origin main
if errorlevel 1 goto failed

:done
echo [%date% %time%] 本機補漏順利完成！
exit /b 0

:failed
echo [%date% %time%] 發生錯誤，請檢查上方訊息！
exit /b 1

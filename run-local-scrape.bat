@echo off
chcp 65001 >nul
setlocal

REM 使用當前批次檔所在目錄，避免寫死 C:\Users\User 路徑造成 cd 失敗
cd /d "%~dp0"

REM ── 續跑／清場（2026-09-09 加）：上次 run 中途死咗會留低未 commit 嘅
REM    cache.json / enrich.json / fingerprints.json。dirty tree 會令之後每日
REM    git pull --rebase 被擋住（「一死永死」），所以起手先處理三條路：
REM      1) 上次結果完整（cache last_updated 係今日 + 三個檔都係合法 JSON）
REM         → 補 add + commit + pull --rebase + push，然後收工
REM      2) 上次結果過期／損毀 → git checkout 還原三個檔，再行下面原流程
REM      3) 三個檔冇未提交改動 → 直接行下面原流程
REM    順便清理上次可能留低嘅半成品 rebase，否則 git 會拒絕所有 pull。
if exist .git\rebase-merge git rebase --abort
if exist .git\rebase-apply git rebase --abort

git diff --quiet HEAD -- cache.json enrich.json fingerprints.json
if not errorlevel 1 goto resume_clean

echo [%date% %time%] 偵測到上次未完成嘅抓取結果：
git status --porcelain -- cache.json enrich.json fingerprints.json
echo [%date% %time%] 驗證上次結果係咪完整…
python check_cache_fresh.py cache.json
if errorlevel 1 goto resume_discard
python -c "import json;json.load(open('enrich.json',encoding='utf-8'));json.load(open('fingerprints.json',encoding='utf-8'))"
if errorlevel 1 goto resume_discard

echo [%date% %time%] 上次結果完整，補做 commit + push（續跑完成）
git add cache.json enrich.json fingerprints.json
git commit -m "🤖 Local backup scrape（續跑：補回上次未完成嘅結果）"
if errorlevel 1 goto failed
git fetch origin main
if errorlevel 1 goto failed
git show origin/main:cache.json | python check_cache_fresh.py --stdin
if not errorlevel 1 goto remote_won
git pull --rebase origin main
if errorlevel 1 goto rebase_conflict
git push origin main
if errorlevel 1 goto push_failed
goto done

:resume_discard
echo [%date% %time%] 上次結果過期或損毀，還原三個檔後照原本流程重跑
git checkout -- cache.json enrich.json fingerprints.json

:resume_clean
echo [%date% %time%] 更新 GitHub 最新資料
git pull --rebase origin main
if errorlevel 1 goto failed

REM ── 本機補漏抓取：有指紋快取防禦，未更新網站瞬間跳過，發現新通告才寫入入庫日期 ──
echo [%date% %time%] 執行本機來源抓取（比對指紋補漏）…
python core.py
if errorlevel 1 goto failed

echo [%date% %time%] 執行增量 PDF 內容處理…
python enrich.py --verbose
if errorlevel 1 goto failed

echo [%date% %time%] 檢查是否有新通告需提交…
git add cache.json enrich.json fingerprints.json
git diff --cached --quiet
if not errorlevel 1 (
    echo [%date% %time%] 沒有新通告，本機快取與 Git 保持一致，毋須 Push
    goto done
)

git commit -m "🤖 Local backup scrape"
if errorlevel 1 goto failed

REM ── 推送前最後檢查：Action 會唔會喺本機跑緊嗰陣先 push 咗？
git fetch origin main
if errorlevel 1 goto failed
git pull --rebase origin main
if errorlevel 1 goto rebase_conflict

git push origin main
if errorlevel 1 goto push_failed
goto done

:remote_won
echo [%date% %time%] Action 喺本機跑緊嗰陣已先完成，用返佢嗰份，棄置本機結果
git reset --hard origin/main
goto done

:push_failed
echo [%date% %time%] 直接 push 唔到，嘗試 rebase 後重試…
git pull --rebase origin main
if errorlevel 1 goto rebase_conflict
git push origin main
if errorlevel 1 goto failed
goto done

:rebase_conflict
git rebase --abort
echo [%date% %time%] rebase 有衝突，已還原；請人手處理後再跑
goto failed

:done
echo [%date% %time%] 完成
exit /b 0

:failed
echo [%date% %time%] 發生錯誤，請檢查上面訊息
exit /b 1

@echo off
chcp 65001 >nul
setlocal

cd /d "C:\Users\User\Documents\GitHub\scout-circulars"

echo [%date% %time%] 更新 GitHub 最新資料
git pull --rebase origin main
if errorlevel 1 goto failed

REM ── 本機係「後備」：GitHub Action 今朝已跑過（cache 已經係今日）就直接跳過，
REM    唔好同 Action 爭住寫同一份 cache.json。Action 跑先係必須的：
REM    notify.py 只會通知「HEAD 之後先出現」嘅通告，本機推先會令當日通知靜默丟失。
echo [%date% %time%] 檢查今日 GitHub Action 有無跑過…
python check_cache_fresh.py cache.json
if not errorlevel 1 goto fresh

echo [%date% %time%] 今日未更新，執行本機全部來源抓取
python core.py --force
if errorlevel 1 goto failed

echo [%date% %time%] 執行增量 PDF 內容處理
python enrich.py --verbose
if errorlevel 1 goto failed

echo [%date% %time%] 提交及上載更新
git add cache.json enrich.json fingerprints.json
git diff --cached --quiet
if not errorlevel 1 goto done

git commit -m "🤖 Local backup scrape"
if errorlevel 1 goto failed

REM ── 推送前最後檢查：Action 會唔會喺本機跑緊嗰陣先 push 咗？
REM    如果係，棄置本機結果（兩邊產出等價），唔好打 rebase 仗。
git fetch origin main
if errorlevel 1 goto failed
git show origin/main:cache.json | python check_cache_fresh.py --stdin
if not errorlevel 1 goto remote_won

git push origin main
if errorlevel 1 goto push_failed
goto done

:remote_won
echo [%date% %time%] Action 喺本機跑緊嗰陣已先完成，用返佢嗰份，棄置本機結果
git reset --hard origin/main
goto done

:push_failed
REM 對方郁過但唔係新 cache（例如有人同時 push 緊網站檔案）：rebase 後再試一次。
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

:fresh
echo [%date% %time%] 今日 GitHub Action 已跑過，本機跳過（後備毋須重複）
goto done

:done
echo [%date% %time%] 完成
exit /b 0

:failed
echo [%date% %time%] 發生錯誤，請檢查上面訊息
exit /b 1

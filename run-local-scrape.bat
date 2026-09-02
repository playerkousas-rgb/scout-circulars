@echo off
chcp 65001 >nul
setlocal

cd /d "C:\Users\User\Documents\GitHub\scout-circulars"

echo [%date% %time%] 更新 GitHub 最新資料
git pull --rebase origin main
if errorlevel 1 goto failed

echo [%date% %time%] 執行本機全部來源抓取
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

git push origin main
if errorlevel 1 goto failed

:done
echo [%date% %time%] 完成
exit /b 0

:failed
echo [%date% %time%] 發生錯誤，請檢查上面訊息
exit /b 1
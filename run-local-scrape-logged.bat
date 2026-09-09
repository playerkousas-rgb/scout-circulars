@echo off
REM ============================================================
REM run-local-scrape.bat 嘅記錄包裝（2026-09-09 加）
REM
REM 工作排程器請指去呢個檔（唔好再直接指 run-local-scrape.bat）：
REM   「動作/Actions」→「程式或指令碼」最尾改成 run-local-scrape-logged.bat
REM
REM 佢會原樣呼叫 run-local-scrape.bat，把所有 stdout / stderr append 落
REM logs\scrape.log（同本檔同一個資料夾，即 repo 根），並喺頭尾寫低開始時間
REM 同 exit code。日後本機 run 中途死咗都有口供可查。
REM
REM logs\ 已加入 .gitignore，唔會 commit；exit code 原樣回傳俾工作排程器，
REM 所以任務歷程紀錄嘅成功／失敗結果唔會變。
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "%~dp0logs" mkdir "%~dp0logs"
set "SC_LOG=%~dp0logs\scrape.log"

echo ===== %date% %time% ===== run-local-scrape start >> "%SC_LOG%"
call run-local-scrape.bat >> "%SC_LOG%" 2>&1
set "SC_RC=%errorlevel%"
echo ===== %date% %time% ===== run-local-scrape end exit=%SC_RC% >> "%SC_LOG%"
exit /b %SC_RC%

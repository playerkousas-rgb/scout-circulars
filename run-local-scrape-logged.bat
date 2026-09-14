@echo off
chcp 65001 >nul
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
REM
REM 2026-09-14 加咗兩樣嘢：
REM   * chcp 65001：log 本身係 UTF-8，行咗 chcp 之後喺 cmd 直接
REM     `type logs\scrape.log` 先唔會變亂碼。亂碼唔代表腳本壞，但真係會令人
REM     睇錯 log 入面發生咗乜（尤其係睇唔清邊一步失敗）。
REM   * log 過 2 MB 就轉名做 scrape.log.1，由零再計，唔會無限膨脹。
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "%~dp0logs" mkdir "%~dp0logs"
set "SC_LOG=%~dp0logs\scrape.log"

REM ── size-based rotation；檔案唔存在嘅時候 for 唔會 iterate，唔使特別判空
for %%F in ("%SC_LOG%") do call :maybe_rotate "%%~zF"

echo ===== %date% %time% ===== run-local-scrape start >> "%SC_LOG%"
call run-local-scrape.bat >> "%SC_LOG%" 2>&1
set "SC_RC=%errorlevel%"
echo ===== %date% %time% ===== run-local-scrape end exit=%SC_RC% >> "%SC_LOG%"
exit /b %SC_RC%

:maybe_rotate
REM %~1 = scrape.log 嘅 bytes（size）。
REM 用副程式係為咗避開 batch 行內提前展開（同一行寫 if defined X if %X% GTR ... 會喺
REM X 未設定時變語法錯誤）；順帶唔用多行括號 block，cmd 對呢樣嘢最挑剔。
if "%~1"=="" exit /b 0
if %~1 LSS 2000001 exit /b 0
if exist "%SC_LOG%.1" del /q "%SC_LOG%.1"
move /y "%SC_LOG%" "%SC_LOG%.1" >nul
exit /b 0

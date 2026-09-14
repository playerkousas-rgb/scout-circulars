@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"
if not exist logs mkdir logs

REM ── 編碼／殘留鎖（呢兩條 2026-09-11 本機已經加過，但一直留咗喺
REM    arena/01a0895d-scout-circulars 分支，從來冇 merge 入 main，所以部機每日 pull
REM    完就冇。而家併返入嚟）：
REM    * PYTHONUTF8／PYTHONIOENCODING：排程器行嘅時候 stdout 被 redirect 落 log 檔，
REM      Windows 會用 cp950 編碼，core.py／enrich.py 一打 emoji 或中文就 UnicodeEncodeError
REM      → 成個 run 死喺中途（好可能就是留低 staged 殘餘嘅元兇）。
REM    * .git\index.lock：上個 git 程序（殺 soft／VS Code／OneDrive 鎖檔）留低 lock，
REM      `git add`／`git commit` 會直接失敗，一樣係「死喺 add 之後、commit 之前」嘅來源。
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist .git\index.lock goto no_index_lock
echo [%date% %time%] 發現殘留 .git\index.lock（上個 git 程序未收尾），清走佢
del /f /q .git\index.lock
:no_index_lock

REM ── Git 身份自癒（2026-09-14 audit 加）：user.name／user.email 完全未設嘅話，
REM    所有自動 commit 必死，而 :failed → 自動重試會白行多一次全網巡邏。
REM    只寫 repo-local 身份（呢個 repo 自己嘅 .git\config）；你已有 global 身份
REM    嘅話呢步完全唔郁你嘅嘢。
for /f "delims=" %%I in ('git config user.email 2^>nul') do set "SC_EMAIL=%%I"
if not defined SC_EMAIL (
    git config user.name "scout-circulars-local"
    git config user.email "local@scout-circulars"
    echo [%date% %time%] 未設定 git 身份：已寫入 repo-local 後備身份（唔影響 global 設定）
)

REM ============================================================
REM 本機補漏抓取（Windows 工作排程器每日執行；建議用 run-local-scrape-logged.bat
REM 咁行，先至有 log 可攞）。
REM
REM ── 續跑／清場（2026-09-09 加）：上次 run 中途死咗會留低未 commit 嘅
REM    cache.json / enrich.json / fingerprints.json。dirty tree 會令之後每日
REM    git pull --rebase 被擋住（「一死永死」），所以起手先處理三條路：
REM      1) 上次結果完整（cache last_updated 係今日 + 三個檔都係合法 JSON）
REM         → 補 add + commit + pull --rebase + push，然後收工
REM      2) 上次結果過期／損毀 → 還原三個檔（連 index 一齊清），再行原流程
REM      3) 冇未提交改動 → 直接行原流程
REM    順便清理上次可能留低嘅半成品 rebase／merge，否則 git 會拒絕所有 pull。
REM
REM ── 2026-09-14 修正（本機連續多日 exit=1，log 係：
REM    「error: cannot pull with rebase: Your index contains uncommitted changes.」）
REM    成因：上次 run 死咗喺「git add 之後、git commit 之前」，index 留低咗暫存改動。
REM    舊版有兩個洞：
REM      (1) 判髒用 `git diff --quiet HEAD -- cache.json enrich.json fingerprints.json`，
REM          只覆蓋三個資料檔；其他檔（例如人手改咗 index.html 仲 staged）睇唔到。
REM      (2) 棄置分支用 `git checkout -- 嗰三個檔`：佢只係用 index 還原工作區，index
REM          本身照舊髒 → 之後每日 `git pull --rebase` 都俾擋死。
REM    對應修正：
REM      (a) 判髒改用 `git status --porcelain`（index + 工作區一齊睇）；
REM      (b) 棄置改成先 `git reset -q HEAD -- 嗰三個檔`（清 index），再 `git checkout` 還原工作區；
REM      (c) 所有 pull 加 `--autostash`，任何殘餘未提交改動都唔再擋住拉取；
REM      (d) rebase 衝突自動「GitHub 嗰份為準」，本機嗰份先留底喺
REM          logs\conflict-backup\ 同 backup/local-scrape 分支（舊版 abort 之後留低
REM          一個未 push 嘅本地 commit，之後每日都撞返同一個衝突）；
REM      (e) 有「已 commit 但未曾 push 出去」嘅本機補跑結果就即刻補推——否則
REM          notify.py（只通知「HEAD 之後先出現」嘅通告）會當日靜默冇通知；
REM      (f) 工作目錄由硬扣 C:\Users\User\... 改成 script 自身所屬資料夾（%~dp0）；
REM      (g) 本機由「今日 Action 跑過就跳過」改成「每次都重新檢查全網，有增量才 push」
REM          （見下面 :scrape 嘅註解 + check_local_gain.py）—— 即係還返
REM          arena/01a0895d 分支 2026-09-11 那個「來源巡邏」版本嘅原意，但改用內容
REM          比較而唔係「有任何 diff 就 push」，唔會每日製造只改 last_updated 嘅噪音 commit。
REM
REM      (h) 死咗之後先搶返嘢再執手尾：`:failed` 會先試「本次成果完整就先 commit（+push）」
REM          —— core.py 成功但 enrich.py／git 死咗，嗰啲新通告係補底成果，唔能够因為
REM          後面一步失敗就掉晒；跟住先清半成品 + 自動重試一次（SC_RETRY，淨係一次）。
REM      (i) `git pull` 失敗要分情況：rebase 衝突 → 處理；斷網／授權 → 唔准當死（:pull_fail
REM          → 照樣巡邏，成果留本地）。舊版係「GitHub 郁親 → 本機當日完全冇檢查」。
REM    ⚠️ 需 Git for Windows 2.27 或以上（先至有 `git pull --autostash`）。
REM ============================================================

REM ── 半成品 rebase／merge／cherry-pick 未清住，git 一律拒絕 pull
if exist .git\rebase-merge git rebase --abort
if exist .git\rebase-apply git rebase --abort
if exist .git\MERGE_HEAD git merge --abort
if exist .git\CHERRY_PICK_HEAD git cherry-pick --abort

REM ── 整個 index 先還原去 HEAD（淨係 unstage，工作區一個字都冇損）：
REM    一次過堵死兩條路——「index 有暫存改動 → pull --rebase 被擋」，
REM    同埋「本腳本嘅自動 commit 誤抱住你手頭 staged 緊嘅其他檔」。
git reset -q HEAD

REM ── 偵測上次留低嘅未提交改動（index + 工作區都要睇，唔好用 git diff HEAD）
set "SC_DIRTY="
for /f "delims=" %%L in ('git status --porcelain -- cache.json enrich.json fingerprints.json') do set "SC_DIRTY=1"
if not defined SC_DIRTY goto resume_clean

echo [%date% %time%] 偵測到上次未完成嘅抓取結果（可能已 staged 但冇 commit）：
git status --porcelain -- cache.json enrich.json fingerprints.json
echo [%date% %time%] 驗證上次結果係咪完整…
python check_cache_fresh.py cache.json
if errorlevel 1 goto resume_discard
python -c "import json;json.load(open('enrich.json',encoding='utf-8'));json.load(open('fingerprints.json',encoding='utf-8'))"
if errorlevel 1 goto resume_discard

echo [%date% %time%] 上次結果完整：睇吓有冇 GitHub 未有嘅新增通告，有先補做 commit + push
git add cache.json enrich.json fingerprints.json
git diff --cached --quiet
if not errorlevel 1 goto resume_discard
git fetch origin main
if errorlevel 1 goto failed
python check_local_gain.py origin/main
if not errorlevel 1 goto resume_committed
if errorlevel 2 goto resume_discard
echo [%date% %time%] 留低嘅結果冇額外發現：唔製造 commit，還原後照原流程再跑
goto resume_discard

:resume_committed
git commit -m "🤖 Local backup scrape（續跑：補回上次未完成嘅結果）"
if errorlevel 1 goto resume_commit_failed
git pull --rebase --autostash origin main
if errorlevel 1 goto rebase_conflict
git push origin main
if errorlevel 1 goto push_failed
goto done

:resume_commit_failed
echo [%date% %time%] git commit 失敗（通常係呢個 repo 冇設定 git config user.name／user.email）
git status --short
echo [%date% %time%] 棄置是次續跑結果，照原本流程重跑
goto resume_discard

:resume_discard
echo [%date% %time%] 上次結果過期或損毀：清走晒（index + 工作區）再照原本流程重跑
git reset -q HEAD -- cache.json enrich.json fingerprints.json
git checkout -- cache.json enrich.json fingerprints.json 2>nul
git status --porcelain -- cache.json enrich.json fingerprints.json

:resume_clean
echo [%date% %time%] 更新 GitHub 最新資料
set "SC_HEAD0="
for /f "delims=" %%H in ('git rev-parse -q --verify HEAD') do set "SC_HEAD0=%%H"
git pull --rebase --autostash origin main
if errorlevel 1 goto pull_fail

REM ── 自我更新保護：呢個腳本嘅來源就係佢自己 pull 落嚟嘅嗰個 repo。如果頭先嗰 pull
REM    改動咗 run-local-scrape*.bat 本身，cmd 係按 byte offset 慢慢讀 .bat 嘅 —— 繼續行
REM    落去會「半舊半新」甚至讀錯位（呢類就係最難睇嘅詭異失敗）。所以：發覺自己換咗
REM    就即刻收工（exit 0，唔算失敗），聽日嗰轉自然用新版行。
set "SC_SELFC="
if defined SC_HEAD0 for /f "delims=" %%F in ('git diff --name-only %SC_HEAD0% HEAD -- "run-local-scrape*.bat"') do set "SC_SELFC=1"
if defined SC_SELFC goto self_updated

:check_ahead
REM ── 補舊數：有冇「已 commit 但未曾 push 出去」嘅本機結果？
REM    （例如上日 push 之前斷線／停電。留咗喺本機唔單止網站冇更新，
REM     notify.py 又只會通知「HEAD 之後先出現」嘅通告，當日通知會靜默流失。）
set "SC_AHEAD="
for /f "delims=" %%N in ('git rev-list --count origin/main..HEAD') do set "SC_AHEAD=%%N"
if not defined SC_AHEAD goto after_ahead
if "%SC_AHEAD%"=="0" goto after_ahead
git log --format=%%s origin/main..HEAD | findstr /v /c:"Local backup scrape" >nul 2>&1
if not errorlevel 1 goto ahead_foreign
echo [%date% %time%] 本機有 %SC_AHEAD% 個未推送嘅補跑 commit，先補推…
git push origin main
if errorlevel 1 goto ahead_push_soft
goto after_ahead

REM 補推失败唔准升級成「今日完全冇檢查」：照樣落去巡邏來源，成果繼續留喺本地，
REM 之後任何一日返到網都會補推（notify 嗰邊有 7 日 rolling recovery，唔會漏通知）。
:ahead_push_soft
echo [%date% %time%] 補推失敗（GitHub 郁唔到／授權問題？）：本次照樣巡邏，成果留喺本地
goto after_ahead

:ahead_foreign
echo [%date% %time%] 本機有 %SC_AHEAD% 個未推送 commit，但入面有唔係本腳本做嘅改動，唔敢自動 push：
git log --oneline origin/main..HEAD
echo [%date% %time%] 自己決定要不要 `git push origin main`

:after_ahead
REM ── 2026-09-14 改：本機**每次**都重新檢查全網，唔再「GitHub 有今日份就收工」。
REM    舊版（2026-09-09 加）用 check_cache_fresh.py：Action 今朝 push 過 → 本機跳過。
REM    問題係本機嘅定位係後備補底：Action「成功但漏咗某個來源」嗰陣，唯有用本機
REM    自己跑過一次先發現到；用時間做準則會令後備好多日一次都冇檢查過。
REM    新準則係「內容」而唔係「時間」：永遠抓，之後用 check_local_gain.py 比較
REM    本機 cache vs origin/main ——
REM      有本機先至有嘅通告 → commit + push（06:00 嗰轉 notify 嘅 catch-up 會補發）
REM      冇額外發現        → 唔製造 commit，還原三個檔（唔會同 Action 打 rebase 仗）
:scrape
echo [%date% %time%] 本機重新檢查全部來源（唔理 cache 係咪今日）
python core.py --force
if errorlevel 1 goto failed

echo [%date% %time%] 執行增量 PDF 內容處理
python enrich.py --verbose
if errorlevel 1 goto failed

echo [%date% %time%] 檢查有冇 GitHub 未有嘅新增通告…
git add cache.json enrich.json fingerprints.json
git diff --cached --quiet
if not errorlevel 1 goto no_change

git fetch origin main
if errorlevel 1 goto failed
python check_local_gain.py origin/main
if not errorlevel 1 goto commit_and_push
if errorlevel 2 goto failed
echo [%date% %time%] 冇額外發現：唔 commit（兩邊等價），還原三個檔
goto discard_local

:commit_and_push
git commit -m "🤖 Local backup scrape"
if errorlevel 1 goto commit_failed
git push origin main
if errorlevel 1 goto push_failed
goto done

:no_change
echo [%date% %time%] 本機結果同現行 HEAD 完全一樣，冇嘢好提交
goto done

:discard_local
git reset -q HEAD -- cache.json enrich.json fingerprints.json
git checkout -- cache.json enrich.json fingerprints.json 2>nul
goto done

:commit_failed
echo [%date% %time%] git commit 失敗：檢查 `git config user.name` ／ `git config user.email`
git status --short
goto failed

:push_failed
REM 對方郁過但唔係新 cache（例如有人同時 push 緊網站檔案）：rebase 後再試一次。
echo [%date% %time%] 直接 push 唔到，嘗試 rebase 後重試…
git pull --rebase --autostash origin main
if errorlevel 1 goto rebase_conflict
git push origin main
if errorlevel 1 goto failed
goto done

:pull_fail
REM ── 頭先嗰個 pull 失敗，分兩種情況處理：
REM    (a) 有 rebase 進行中／衝突 → 一定要先處理乾淨（交俾 :rebase_conflict）
REM    (b) 淨係斷網／授權過期／GitHub 故障 → 唔准阻住今日補底：照樣巡邏來源，
REM        成果留喺本地 commit，聽日 05:00 個 ahead 守衛會自己補推。
REM        （舊版係一遇 pull 失敗就 exit 1，即係「GitHub 郁親 → 本機當日完全冇檢查」）
if exist .git\rebase-merge goto rebase_conflict
if exist .git\rebase-apply goto rebase_conflict
echo [%date% %time%] 更新 GitHub 失敗（多數係網絡／授權／GitHub 故障）：唔阻住本次巡邏
goto check_ahead

:rebase_conflict
if defined SC_CONFLICT_DONE goto rebase_second_time
REM 真係有 rebase 進行中先算「衝突」；其他 pull 錯誤（網絡、autostash 彈唔返…）唔亂改嘢。
if not exist .git\rebase-merge if not exist .git\rebase-apply goto rebase_not_conflict

echo [%date% %time%] rebase 衝突（多數係本機同 Action 各寫咗一份 cache）：先留底，改用 GitHub 嗰份
if not exist logs\conflict-backup mkdir logs\conflict-backup
git rebase --abort
REM abort 之後先 copy：衝突進行中嘅工作區有 merge 標記，copy 咗都係垃圾
git branch -f backup/local-scrape HEAD
set "SC_CONFLICT_DONE=1"
copy /y cache.json logs\conflict-backup\cache.json >nul 2>&1
copy /y enrich.json logs\conflict-backup\enrich.json >nul 2>&1
copy /y fingerprints.json logs\conflict-backup\fingerprints.json >nul 2>&1
echo [%date% %time%] 本機嗰份已留低喺 logs\conflict-backup\（同 backup/local-scrape 分支）
echo [%date% %time%] 想比對返：git checkout backup/local-scrape -- cache.json
git fetch origin main
if errorlevel 1 goto failed
REM hard reset 會連其他未提交嘅檔案一齊清走 —— 清之前留份口供喺 log，
REM 萬一有唔係腳本做嘅改動被清咗，睇得到係乜嘢。
git status --porcelain
git reset --hard origin/main
echo [%date% %time%] 已改用 GitHub 嗰份，繼續當日該做嘅檢查
goto scrape

:rebase_second_time
echo [%date% %time%] 今次係第二輪衝突，唔敢再自動處理；本機嗰份喺 logs\conflict-backup\
git status --short
goto failed

:self_updated
echo [%date% %time%] 頭先嗰 pull 更新咗本腳本自己（GitHub 就係佢嘅來源）：本次即刻收工，聽日 05:00 自然用新版行
exit /b 0

:rebase_not_conflict
echo [%date% %time%] git pull/push 失敗，但唔係 rebase 衝突（詳情見上面 git 訊息）
echo [%date% %time%] 如果上面話 unknown option／--autostash：你嘅 Git 太舊，更新去 Git for Windows 2.27 以上
git status --short
git log --oneline -1
echo [%date% %time%] 冇改動過任何嘢；處理好網絡／授權之後手動再跑一次本腳本即可
goto failed

:done
echo [%date% %time%] 完成
exit /b 0

:failed
echo [%date% %time%] 發生錯誤（上面有 git／Python 嘅原始訊息）

REM ── 步 1（2026-09-14 新增）：先搶返本次已經到手嘅成果，先至執手尾。
REM    典型情況：core.py 成功寫入咗新通告，但 enrich.py／git 嗰邊先至死 ——
REM    嗰啲通告係實實在在嘅補底成果，唔可以因為後面一步失敗就掉晒。
REM    安全欄：三個資料檔要 JSON 讀得開、同 check_local_gain 真係見到新增，
REM    先至 commit；冇增量／檔壞咗就唔Save（唔製造只改 last_updated 嘅噪音 commit）。
REM    push 唔到（斷網／授權）都冇所謂：成果已經喺本地 commit，聽日開波嘅
REM    ahead 守衛會自動補推。
git add cache.json enrich.json fingerprints.json 2>nul
git diff --cached --quiet
if not errorlevel 1 goto failed_scrub
echo [%date% %time%] 失敗之前本次已經改動咗資料檔：驗證吓完整唔完整，能救就救…
python -c "import json;json.load(open('cache.json',encoding='utf-8'));json.load(open('enrich.json',encoding='utf-8'));json.load(open('fingerprints.json',encoding='utf-8'))"
if errorlevel 1 goto failed_scrub
git fetch origin main 2>nul
python check_local_gain.py origin/main
if errorlevel 1 goto failed_scrub
git commit -m "🤖 Local backup scrape（自動搶救：本次成果完整，係後續步驟死咗）"
if errorlevel 1 goto failed_scrub
echo [%date% %time%] 本次成果已 commit（安全咗）；嘗試直接 push…
git push origin main
if errorlevel 1 echo [%date% %time%] push 暫時失敗：冇事，聽日開波會自動補推
goto failed_aftermath

REM ── 步 2：清走本次半成品（淨係三個資料檔，你手頭其他檔一個字都冇損），再重試一次。
REM    呢個先係「今日死＝聽日唔好死」：就算失敗原因係我哋未預见到嘅，
REM    第二次都唔會俾 index／半成品卡住。
:failed_scrub
git reset -q HEAD -- cache.json enrich.json fingerprints.json
git checkout -- cache.json enrich.json fingerprints.json 2>nul
if defined SC_RETRY goto failed_final
set "SC_RETRY=1"
echo [%date% %time%] 已清走本次半成品，自動重試一次（會再拉一次＋補推，並重新巡邏來源）
goto resume_clean

:failed_final
echo [%date% %time%] 重試之後仍然失敗：exit 1（repo 已還原 clean，聽日嗰轉唔會被今次拖累）
:failed_aftermath
git status --short
git log --oneline -1
echo [%date% %time%] 睇 log 請用 Notepad，或者：powershell -c "Get-Content -Encoding UTF8 logs\scrape.log -Tail 60"
exit /b 1

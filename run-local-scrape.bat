@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"
if not exist logs mkdir logs

REM ============================================================
REM run-local-scrape.bat - local daily backup scrape
REM (Windows Task Scheduler; point the task at run-local-scrape-logged.bat
REM  in this folder so the run is written to logs\scrape.log)
REM
REM CONTRACT - rewritten 2026-09-14, deliberately minimal:
REM   1. download the latest from GitHub
REM   2. core.py --force      full re-crawl of every source
REM   3. enrich.py            incremental PDF text extraction
REM   4. anything changed -> commit + push
REM That is all.
REM
REM BOTH GATES ARE GONE:
REM   * No freshness gate. The old "cache is already fresh today because the
REM     Action ran, so skip the local patrol" rule is removed. The local run
REM     always patrols every source.
REM   * No gain check. check_local_gain.py is no longer called from here.
REM     Any diff is committed and pushed. core.py writes a fresh
REM     last_updated on every single run, so a successful run always moves
REM     the website timestamp - and that moving timestamp is how the run is
REM     verified day to day.
REM
REM SELF-HEALING - whatever a crashed run left behind must not be able to
REM stop the next run. Before doing anything else this script clears:
REM   - .git\index.lock left by a killed git process
REM   - a half-finished rebase / merge / cherry-pick
REM   - staged leftovers. This was the 2026-09-14 death loop: a run died
REM     between "git add" and "git commit", the staged files blocked
REM     "git pull --rebase" with "cannot pull with rebase: Your index
REM     contains uncommitted changes", and every run after that died the
REM     same way - including the pull that would have fetched the fixed
REM     script.
REM Leftover data files are discarded rather than salvaged, because
REM core.py --force re-crawls every source from scratch and rediscovers
REM anything that mattered. Only cache.json / enrich.json /
REM fingerprints.json are ever touched: any other file you are editing is
REM left exactly as it is.
REM
REM Requires Git for Windows 2.27 or newer (for "git pull --autostash").
REM Keep this file pure ASCII with CRLF line endings (see .gitattributes).
REM ============================================================

REM -- stdout is redirected into a log file by the scheduler; without these
REM    Windows encodes it as cp950 and core.py / enrich.py die with a
REM    UnicodeEncodeError on the first emoji or CJK character they print.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

:run_from_top

REM -- [1] clear anything a dead run left behind -------------------------
if exist .git\index.lock del /f /q .git\index.lock
if exist .git\rebase-merge git rebase --abort
if exist .git\rebase-apply git rebase --abort
if exist .git\MERGE_HEAD git merge --abort
if exist .git\CHERRY_PICK_HEAD git cherry-pick --abort

REM -- [2] git identity: if it is unset every automatic commit fails ------
for /f "delims=" %%I in ('git config user.email 2^>nul') do set "SC_EMAIL=%%I"
if defined SC_EMAIL goto identity_ok
git config user.name "scout-circulars-local"
git config user.email "local@scout-circulars"
echo [%date% %time%] git identity was unset: wrote a repo-local fallback (your global config is untouched)
:identity_ok

REM -- [3] discard staged / dirty leftovers from a crashed run -----------
REM    "git reset -q HEAD" unstages the whole index but does not modify a
REM    single byte of the working tree, so it kills both failure modes at
REM    once: "staged changes block pull --rebase" and "the automatic commit
REM    below picks up unrelated files you had staged by hand".
git reset -q HEAD
git checkout -- cache.json enrich.json fingerprints.json 2>nul

REM -- [4] download the latest ------------------------------------------
set "SC_HEAD0="
for /f "delims=" %%H in ('git rev-parse -q --verify HEAD') do set "SC_HEAD0=%%H"
git pull --rebase --autostash origin main
if errorlevel 1 goto pull_fail

REM -- [5] self-update guard -------------------------------------------
REM    This script is pulled from the very repo it updates. cmd reads a .bat
REM    by byte offset, so if the pull replaced this file, carrying on would
REM    execute a half-old / half-new mix and read from the wrong offsets -
REM    the nastiest kind of failure to diagnose. Stop here instead; the next
REM    scheduled run picks up the new version by itself.
set "SC_SELFC="
if defined SC_HEAD0 for /f "delims=" %%F in ('git diff --name-only %SC_HEAD0% HEAD -- "run-local-scrape*.bat"') do set "SC_SELFC=1"
if defined SC_SELFC goto self_updated

REM -- [6] push local commits that were never pushed -------------------
REM    e.g. yesterday's run committed but lost the network before pushing.
REM    Left unpushed, the site does not update and notify.py (which only
REM    reports notices appearing after HEAD) silently drops that day.
set "SC_AHEAD="
for /f "delims=" %%N in ('git rev-list --count origin/main..HEAD') do set "SC_AHEAD=%%N"
if not defined SC_AHEAD goto after_ahead
if "%SC_AHEAD%"=="0" goto after_ahead
git log --format=%%s origin/main..HEAD | findstr /v /c:"Local backup scrape" >nul 2>&1
if not errorlevel 1 goto ahead_foreign
echo [%date% %time%] %SC_AHEAD% local commit(s) were never pushed: pushing them now
git push origin main
if errorlevel 1 echo [%date% %time%] push failed (offline / auth?): continuing anyway - the crawl still runs and tomorrow retries the push
goto after_ahead

:ahead_foreign
echo [%date% %time%] %SC_AHEAD% unpushed commit(s) contain changes this script did not make, so it will not push them for you:
git log --oneline origin/main..HEAD
echo [%date% %time%] run "git push origin main" yourself if you want them upstream

:after_ahead

:scrape
REM -- [7] full re-crawl, regardless of how fresh the cache already is ----
echo [%date% %time%] core.py --force : re-checking every source
python core.py --force
if errorlevel 1 goto failed

echo [%date% %time%] enrich.py : incremental PDF text extraction
python enrich.py --verbose
if errorlevel 1 goto failed

REM -- [8] commit + push whatever changed ------------------------------
git add cache.json enrich.json fingerprints.json
git diff --cached --quiet
if not errorlevel 1 goto no_change
git commit -m "Local backup scrape"
if errorlevel 1 goto commit_failed
git push origin main
if errorlevel 1 goto push_failed
goto done

REM ============================================================
REM handlers
REM ============================================================

:pull_fail
REM Two different situations, and they must not be treated the same:
REM   (a) a rebase actually in progress / conflicting -> clean it up below
REM   (b) plain network outage, expired credentials, GitHub down -> this
REM       must NOT cancel today's patrol. Crawl anyway, keep the result in a
REM       local commit, and step [6] pushes it on a later run.
REM       (The old behaviour was exit 1 on any pull failure, i.e. "GitHub
REM       hiccups -> the local machine checks nothing at all that day".)
if exist .git\rebase-merge goto rebase_conflict
if exist .git\rebase-apply goto rebase_conflict
echo [%date% %time%] could not update from GitHub (network / auth / GitHub down): running the crawl anyway
goto after_ahead

:rebase_conflict
if defined SC_CONFLICT_DONE goto rebase_second_time
REM Only a rebase that is really in progress counts as a conflict. Any other
REM pull error (network, autostash that would not pop, ...) changes nothing.
if not exist .git\rebase-merge if not exist .git\rebase-apply goto rebase_not_conflict

echo [%date% %time%] rebase conflict (local and the Action each wrote a cache): keeping the GitHub copy
if not exist logs\conflict-backup mkdir logs\conflict-backup
git rebase --abort
REM Copy only after the abort: during a conflict the working tree holds merge
REM markers, so a copy taken then would just be garbage.
git branch -f backup/local-scrape HEAD
set "SC_CONFLICT_DONE=1"
copy /y cache.json logs\conflict-backup\cache.json >nul 2>&1
copy /y enrich.json logs\conflict-backup\enrich.json >nul 2>&1
copy /y fingerprints.json logs\conflict-backup\fingerprints.json >nul 2>&1
echo [%date% %time%] your local copy is kept in logs\conflict-backup\ and on branch backup/local-scrape
echo [%date% %time%] to compare later: git checkout backup/local-scrape -- cache.json
git fetch origin main
if errorlevel 1 goto failed
REM The hard reset below also discards other uncommitted files, so leave a
REM record of what they were first.
git status --porcelain
git reset --hard origin/main
echo [%date% %time%] now on the GitHub copy; continuing with today's crawl
goto scrape

:rebase_second_time
echo [%date% %time%] second conflict in the same run: not auto-resolving again
echo [%date% %time%] your local copy is in logs\conflict-backup\ and on branch backup/local-scrape
git status --short
goto failed

:self_updated
echo [%date% %time%] that pull just replaced this script; stopping now so cmd does not read a half-updated file
echo [%date% %time%] the next scheduled run will use the new version
exit /b 0

:rebase_not_conflict
echo [%date% %time%] git failed, but it is not a rebase conflict (the git message is above)
echo [%date% %time%] if it says unknown option --autostash, your Git is too old: update to Git for Windows 2.27+
git status --short
git log --oneline -1
echo [%date% %time%] nothing was modified; fix the network / auth and run this script again
goto failed

:no_change
REM core.py rewrites last_updated on every run, so reaching here means it
REM exited 0 without touching cache.json. Nothing was pushed, which means
REM the website timestamp will not move today - that breaks the contract
REM this script exists to honour, so report it as a failure.
echo [%date% %time%] WARNING: core.py and enrich.py both exited 0 but cache.json did not change at all
echo [%date% %time%] last_updated should move on every run, so nothing was committed or pushed
echo [%date% %time%] check the core.py output above before relying on today's timestamp
exit /b 1

:commit_failed
echo [%date% %time%] git commit failed - check git config user.name / user.email
git status --short
goto failed

:push_failed
REM Someone else pushed in the meantime (e.g. the Action): rebase, retry once.
echo [%date% %time%] direct push rejected: rebasing onto GitHub and retrying once
git pull --rebase --autostash origin main
if errorlevel 1 goto rebase_conflict
git push origin main
if errorlevel 1 goto failed
goto done

:done
echo [%date% %time%] done
git log --oneline -1
exit /b 0

:failed
echo [%date% %time%] error (the original git / Python message is above)
REM Before cleaning up, try to keep what this run already produced. Typical
REM case: core.py found new notices, then enrich.py or git died - those
REM notices are a real result and must not be thrown away just because a
REM later step failed. Safety rail: all three data files must still parse as
REM JSON, and there must be an actual diff. A push failure here is fine: the
REM result is already committed locally and step [6] pushes it later.
python -c "import json;json.load(open('cache.json',encoding='utf-8'));json.load(open('enrich.json',encoding='utf-8'));json.load(open('fingerprints.json',encoding='utf-8'))"
if errorlevel 1 goto failed_scrub
git add cache.json enrich.json fingerprints.json
git diff --cached --quiet
if not errorlevel 1 goto failed_scrub
git commit -m "Local backup scrape (salvaged: a later step failed)"
if errorlevel 1 goto failed_scrub
echo [%date% %time%] salvaged this run's results into a commit; trying to push
git push origin main
if errorlevel 1 echo [%date% %time%] push failed for now: no problem, step [6] of the next run pushes it
goto failed_aftermath

:failed_scrub
REM Discard this run's half-finished work (only the three data files - any
REM other file of yours is untouched), then retry once. This is what makes
REM "died today" not imply "dies tomorrow": even if the cause was something
REM not anticipated here, the retry cannot be blocked by index or leftovers.
git reset -q HEAD -- cache.json enrich.json fingerprints.json
git checkout -- cache.json enrich.json fingerprints.json 2>nul
if defined SC_RETRY goto failed_final
set "SC_RETRY=1"
echo [%date% %time%] cleaned up this run's leftovers; retrying the whole run once
goto run_from_top

:failed_final
echo [%date% %time%] still failing after the retry: exit 1 (repo restored clean, so tomorrow is not dragged down by today)
:failed_aftermath
git status --short
git log --oneline -1
echo [%date% %time%] to read the log: notepad logs\scrape.log
exit /b 1

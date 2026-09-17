#!/usr/bin/env python3
"""
vercel_bundle_guard.py — 防止 Functions Storage 病源復發
========================================================
由 .github/workflows/vercel-bundle-guard.yml 每次 push / PR 跑。

背景：2026-09-17 Functions Storage 爆到 11.82GB / 10GB。病源係根目錄
requirements.txt 列住 playwright —— Vercel Python runtime 會把 **repo 根目錄**
嘅 requirements.txt / pyproject.toml / Pipfile pip install 入 **每一個**
api/*.py function bundle，而官方明言「There is no automatic tree-shaking for
Python」。playwright 解壓後 137MB，× 幾十個 retained deployment = 爆額。
而 api/ 其實係 100% 標準庫。

呢個 guard 檢查五樣嘢（任何一項失敗 → CI 紅，附修法）：

  1. api/*.py 只 import 標準庫 ＋ 自己嘅 local module（api.*）
  2. 冇任何「Vercel 會自動 pip install」嘅 manifest 漏網上載：
     requirements.txt / pyproject.toml / Pipfile / uv.lock / api/requirements.txt
     —— 存在就必須被 .vercelignore 擋住
  3. 根目錄 requirements.txt 如果列咗真嘢，就必須 **冇** 被 ignore
     （反之亦然：ignore 咗就唔准有真嘢）—— 防止「api/ 要裝但 Vercel 收唔到」
     呢種會 runtime 500 嘅半桶水狀態
  4. 上載去 Vercel 嘅總體積唔超 budget（預設 2 MB）
  5. vercel.json 入面 includeFiles 指到嘅檔案真係存在，而且冇被 .vercelignore
     擋走（擋走咗 includeFiles 會靜靜地搵唔到 → runtime 先炸）

全部檢查都係離線嘅，唔使 network、唔使 Vercel token，幾秒跑完。
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# Vercel Python runtime 會自動讀呢啲檔做依賴安裝（全部相對 project root）
MANIFESTS = [
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "uv.lock",
    "api/requirements.txt",
]

# 上載去 Vercel 嘅總體積 budget（bytes）。而家實測 ~1.2MB（.vercelignore 之後），
# 主要係 index.html 160KB + icons/*.png 712KB + icon.svg 68KB + api/ + catalog。
# 呢個 budget 係「靜態資產」嘅，同 function bundle 無關；超咗代表有人放咗大檔入部署。
UPLOAD_BUDGET_BYTES = int(os.environ.get("UPLOAD_BUDGET_BYTES", 2 * 1024 * 1024))

failures: list[str] = []
notes: list[str] = []


def fail(message: str) -> None:
    failures.append(message)
    print(f"::error::{message}")


def note(message: str) -> None:
    notes.append(message)
    print(message)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失敗：{result.stderr.strip()}")
    return result.stdout


def tracked_files() -> list[str]:
    return [line for line in git("ls-files").splitlines() if line]


def vercelignored_files(tracked: list[str]) -> set[str]:
    """用 git 自己嘅 matcher 模擬 .vercelignore（Vercel 都係用 gitignore 語法）。

    `git ls-files -c -i --exclude-from=<file>` 列嘅係「被忽略嗰啲」。
    """
    ignore_file = ROOT / ".vercelignore"
    if not ignore_file.exists():
        return set()
    out = git("ls-files", "-c", "-i", "--exclude-from=.vercelignore")
    ignored = {line for line in out.splitlines() if line}
    # 只保留真係 tracked 嘅（上面個命令唔會吐未 track 嘅，雙保險）
    return ignored & set(tracked)


def uploaded_files(tracked: list[str], ignored: set[str]) -> list[str]:
    return [path for path in tracked if path not in ignored]


def local_modules() -> set[str]:
    """repo 入面嘅 top-level module 名（api.*, core, enrich, ...）。

    api/ 只應該 import 標準庫同 api.* 自己人；但 push_common.py 用
    `from api.push_common import ...`，所以要認得 `api`。
    """
    names = {"api"}
    for path in ROOT.glob("*.py"):
        names.add(path.stem)
    return names


def check_api_imports() -> None:
    """1. api/*.py 只 import 標準庫 ＋ local module。"""
    api_dir = ROOT / "api"
    if not api_dir.is_dir():
        fail("api/ 目錄唔存在 —— 個站嘅 push function 冇咗？")
        return

    stdlib = set(sys.stdlib_module_names)
    allowed = stdlib | local_modules()
    offenders: dict[str, set[str]] = {}

    py_files = sorted(api_dir.glob("*.py"))
    if not py_files:
        fail("api/ 入面冇 .py 檔")
        return

    for path in py_files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            fail(f"{path.relative_to(ROOT)} parse 失敗：{exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                tops = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import → 一定係自己人
                    continue
                tops = [(node.module or "").split(".")[0]]
            else:
                continue
            for top in tops:
                if top and top not in allowed:
                    offenders.setdefault(str(path.relative_to(ROOT)), set()).add(top)

    if offenders:
        for path, modules in sorted(offenders.items()):
            fail(
                f"{path} import 咗第三方套件：{', '.join(sorted(modules))}。"
                f"Vercel 會把根目錄 requirements.txt pip install 入每個 function "
                f"bundle（冇 tree-shaking），所以呢度每加一個套件，每個 retained "
                f"deployment 都會脹 —— 2026-09-17 就係咁爆到 11.82GB。"
                f"如非必要請改返用標準庫；真係要用就同步改 requirements.txt "
                f"並由 .vercelignore 移除佢（guard 會一齊檢查）。"
            )
    else:
        note(f"✅ 檢查 1：api/ 嘅 {len(py_files)} 個檔全部只用標準庫／local module")


def parse_requirements(path: Path) -> list[str]:
    """抽返 requirements 檔入面真正嘅 requirement 行（撇除註解／空行／-r 等）。"""
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):  # -r / -e / --index-url …
            lines.append(line)
            continue
        lines.append(line)
    return lines


def check_manifests(tracked: list[str], ignored: set[str], uploaded: list[str]) -> None:
    """2 + 3. Vercel 會自動 pip install 嘅 manifest 唔准漏網上載。"""
    tracked_set = set(tracked)
    uploaded_set = set(uploaded)

    for manifest in MANIFESTS:
        path = ROOT / manifest
        exists_on_disk = path.is_file()
        is_tracked = manifest in tracked_set

        if not exists_on_disk and not is_tracked:
            continue  # 冇呢個檔 → 最理想

        is_uploaded = manifest in uploaded_set
        deps = parse_requirements(path) if exists_on_disk else []
        has_real_deps = bool(deps)

        if is_uploaded:
            fail(
                f"{manifest} 會上載去 Vercel（冇被 .vercelignore 擋住）。"
                f"Vercel Python runtime 會自動 pip install 佢入 **每一個** "
                f"api/*.py function bundle，而且冇 tree-shaking。"
                f"修法：把 `{manifest}` 加入 .vercelignore；如果個依賴係爬蟲／CI 用，"
                f"搬去 .github/requirements-*.txt（.github/ 唔會上載）。"
            )
            continue

        # 被 ignore 咗 —— 咁佢入面就唔應該有真嘢，否則 api/ 一旦 import 就會 runtime 炸
        if has_real_deps:
            fail(
                f"{manifest} 被 .vercelignore 擋住，但入面列咗 {len(deps)} 個依賴："
                f"{'、'.join(deps[:6])}{'…' if len(deps) > 6 else ''}。"
                f"呢啲依賴 Vercel 收唔到 → 如果 api/ 真係 import 佢就會 runtime 500。"
                f"修法：要嘛把依賴搬去 .github/requirements-*.txt（爬蟲／CI 用），"
                f"要嘛由 .vercelignore 移除 `{manifest}` 並接受每個 deployment 會脹。"
            )
        else:
            note(f"✅ 檢查 2/3：{manifest} 已被 .vercelignore 擋住，且冇列任何依賴")

    # 特別確認根目錄 requirements.txt 嘅狀態有被記錄清楚
    root_req = ROOT / "requirements.txt"
    if root_req.is_file() and "requirements.txt" not in ignored:
        fail("requirements.txt 唔喺 .vercelignore 入面（見上面）")
    elif root_req.is_file():
        note("✅ 檢查 2/3：requirements.txt 已 ignore（Vercel 收唔到，零 pip install）")


def check_upload_budget(uploaded: list[str]) -> None:
    """4. 上載去 Vercel 嘅總體積唔好超 budget。"""
    total = 0
    biggest: list[tuple[int, str]] = []
    for path in uploaded:
        full = ROOT / path
        if not full.is_file():
            continue
        size = full.stat().st_size
        total += size
        biggest.append((size, path))

    biggest.sort(reverse=True)
    over = total > UPLOAD_BUDGET_BYTES
    note(f"{'❌' if over else '✅'} 檢查 4：上載去 Vercel 嘅檔案 {len(uploaded)} 個，合共 "
         f"{total / 1024 / 1024:.2f} MB（budget {UPLOAD_BUDGET_BYTES / 1024 / 1024:.2f} MB）")
    if biggest:
        note("    最大五個：" + "、".join(
            f"{path} {size / 1024:.0f}KB" for size, path in biggest[:5]))

    if over:
        fail(
            f"上載去 Vercel 嘅總體積 {total / 1024 / 1024:.2f} MB 超過 budget "
            f"{UPLOAD_BUDGET_BYTES / 1024 / 1024:.2f} MB。每個 deployment 都會保留呢啲"
            f"靜態資產（Deployment Storage），而每日有 ~3 個 bot commit 開新 deployment。"
            f"修法：把大檔加入 .vercelignore（如果部署唔需要），或者搬走佢。"
            f"最大嗰幾個：{'、'.join(path for _, path in biggest[:5])}"
        )


def check_include_files(uploaded: list[str]) -> None:
    """5. vercel.json 嘅 includeFiles 指到嘅檔案要存在＋要上載到。"""
    config_path = ROOT / "vercel.json"
    if not config_path.is_file():
        note("ℹ️ 檢查 5：冇 vercel.json，跳過 includeFiles 檢查")
        return
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"vercel.json 唔係合法 JSON：{exc}")
        return

    uploaded_set = set(uploaded)
    functions = config.get("functions") or {}
    checked = 0
    for entry, options in functions.items():
        include = (options or {}).get("includeFiles")
        if not include:
            continue
        patterns = include if isinstance(include, list) else [include]
        for pattern in patterns:
            # includeFiles 支援 glob；呢度只驗證「字面路徑」嗰種（本 repo 用呢種）
            if any(char in pattern for char in "*?{["):
                matched = [p for p in uploaded_set if _glob_match(p, pattern)]
                if not matched:
                    fail(
                        f"vercel.json → functions.{entry}.includeFiles 嘅 `{pattern}` "
                        f"喺會上載嘅檔案入面搵唔到任何 match。includeFiles 搵唔到嘢係"
                        f"靜默失敗：build 照過，runtime 先 500。"
                    )
                checked += len(matched)
                continue
            if not (ROOT / pattern).exists():
                fail(f"vercel.json → functions.{entry}.includeFiles 指到 `{pattern}`，"
                     f"但 repo 入面冇呢個檔。")
            elif pattern not in uploaded_set:
                fail(
                    f"vercel.json → functions.{entry}.includeFiles 指到 `{pattern}`，"
                    f"但佢被 .vercelignore 擋走咗 → Vercel 收唔到，includeFiles 會"
                    f"靜默失敗（build 照過，function 一讀就 500）。"
                    f"修法：由 .vercelignore 移除 `{pattern}`。"
                )
            else:
                checked += 1
    if checked:
        note(f"✅ 檢查 5：includeFiles 指到嘅 {checked} 個檔案全部存在且會上載")


def _glob_match(path: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(path, pattern)


def main() -> int:
    print("=" * 68)
    print("Vercel function bundle guard —— 防止 Functions Storage 病源復發")
    print("=" * 68)

    tracked = tracked_files()
    if not tracked:
        print("::warning::git ls-files 冇結果（唔喺 git checkout 入面？）—— 跳過檢查")
        return 0

    ignored = vercelignored_files(tracked)
    uploaded = uploaded_files(tracked, ignored)
    note(f"tracked {len(tracked)} 個檔；.vercelignore 擋走 {len(ignored)} 個；"
         f"上載 {len(uploaded)} 個\n")

    check_api_imports()
    check_manifests(tracked, ignored, uploaded)
    check_upload_budget(uploaded)
    check_include_files(uploaded)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = ["## Vercel bundle guard", ""]
        if failures:
            lines += [f"❌ **{len(failures)} 個問題**：", ""]
            lines += [f"- {message}" for message in failures]
        else:
            lines += ["✅ 全部檢查通過。", ""]
        lines += ["```", *notes, "```"]
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass

    print()
    if failures:
        print(f"❌ {len(failures)} 個問題。Functions Storage 病源可能返咗嚟 —— 睇上面 ::error::。")
        return 1
    print("✅ 全部檢查通過：冇嘢會令 Vercel function bundle 脹返。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""一次性清理：修復被編碼誤判污染嘅通告標題（Cyrillic 亂碼 → 正確中文）。

背景
----
core.py 舊版 encoding_shield_response() 對「非 big5」來源一律用 requests 嘅
auto-detect（charset_normalizer）解碼，忽略 sources.json 嘅 encoding 設定。
當 auto-detect 將 UTF-8 中文誤判成西里爾文編碼（ptcp154/cp1251）時，
標題就變成「з¬¬дёҖеұҶйҰҷжёҜ…」呢類亂碼。

此 bug 已喺 core.py 修好（encoding 白名單：只接受中／英文編碼）。
呢支 script 負責清走已經寫入 cache.json / enrich.json 嘅污染資料。

還原方法
--------
亂碼字串係 UTF-8 位元組被當成 ptcp154 解碼嘅結果，所以逆向做
    s.encode('ptcp154').decode('utf-8')
即可還原。兩類 NFKC 正規化遺留要先行還原：
  - № (U+2116) → NFKC 變 "No"，要還原返單字元
  - … (U+2026) → NFKC 變 "..."，要還原返單字元
而 NBSP (0xA0, 亦係 CJK 三字節嘅 continuation byte) 被 NFKC 收做普通空格，
屬「不可逆」嘅損失，要用回溯法喺每個空格位試 0x20 / 0xA0 邊個至啱。

用法
----
    python fix_mojibake_titles.py --dry-run   # 只睇會改咩
    python fix_mojibake_titles.py             # 實際寫入 cache.json + enrich.json
"""
from __future__ import annotations

import argparse
import json
import re
from itertools import product
from pathlib import Path

BASE_DIR = Path(__file__).parent
CACHE_PATH = BASE_DIR / "cache.json"
ENRICH_PATH = BASE_DIR / "enrich.json"

_CYR_RE = re.compile(r"[\u0400-\u04FF\u0510-\u052F]")  # Cyrillic / 擴充

# 極少數標題混咗不可逆損失（漏字／尾部截斷），自動還原會差少少。
# 呢度人手核對後直接寫返正確標題（key = 亂碼，value = 正確標題）。
_MANUAL_FIXES = {
    # 「列」喺原始資料已經丟失（非編碼問題），補返
    "й«”й©—жҙ»еӢ•зі» – ж—Ҙжң¬жӣёи—қзІүеҪ©": "體驗活動系列 – 日本書藝粉彩",
    "й«”й©—жҙ»еӢ•зі» – йҠ...з·ҡиҠұ": "體驗活動系列 – 銅線花",
    # 尾部「驗」最後一個 byte 被 strip 走，補返
    "з«Ҙи»Қе...Ҳдҝ®з« иЁ“з·ҙзҸӯ – еҺҹйҮҺзғNoйЈӘй«”й©": "童軍先修章訓練班 – 原野烹飪體驗",
    "з«ҘзNo«зӨҫеҚҖдәҢйғЁжӣІ дNoӢ иҲҮзңҫеҢ—з«Ҙж·ұеәҰйҒҠ ж·ұиіҮз«Ҙи»Қж®өз« иҖғй©": "童繫社區二部曲 之 與眾北童深度遊 深資童軍段章考驗",
    "жүӢи—қз« (з·ҡиЈқйҮҳжӣё)е·ҘдҪңеқҠеҸҠиҖғй©": "手藝章 (線裝釘書) 工作坊及考驗",
    "з«Ҙи»ҚжүӢи—қз« (зҡ®е·Ҙ)е·ҘдҪңеқҠеҸҠиҖғй©": "童軍手藝章 (皮工) 工作坊及考驗",
}


def looks_garbled(s: str) -> bool:
    """含西里爾字母即係被誤判解碼嘅亂碼。"""
    return bool(s and _CYR_RE.search(s))


def _reverse_segment(seg: str) -> str | None:
    """逆向還原一段純亂碼（只有 ptcp154 非 ASCII 字元 + 空格）。

    空格喺 NFKC 後唔知原本係 ASCII 0x20 定 NBSP 0xA0（CJK continuation byte），
    用回溯法試晒每個空格嘅兩種可能，揀解到出嚟係乾淨中文嗰個。
    """
    n_spaces = seg.count(" ")
    if n_spaces > 8:  # 太多空格 = 過多歧義，放棄
        return None
    for combo in product((b"\x20", b"\xa0"), repeat=n_spaces):
        it = iter(combo)
        ba = bytearray()
        ok = True
        for ch in seg:
            if ch == " ":
                ba += next(it)
            else:
                try:
                    ba += ch.encode("ptcp154")
                except Exception:
                    ok = False
                    break
        if not ok:
            continue
        try:
            out = bytes(ba).decode("utf-8")
        except Exception:
            continue
        if _CYR_RE.search(out):
            continue
        if any("\u4e00" <= c <= "\u9fff" for c in out):
            return out
    return None


def fix_title(s: str) -> str | None:
    """把亂碼標題還原；失敗或唔係亂碼就回 None。"""
    if not looks_garbled(s):
        return None
    # 人手核對過嘅 edge case
    if s in _MANUAL_FIXES:
        return _MANUAL_FIXES[s]
    # 先還原 NFKC 可逆遺留（№→No、…→...）
    cand = s.replace("No", "\u2116").replace("...", "\u2026")
    return _reverse_segment(cand)


def iter_all_paths(obj, path=()):
    """遍歷 JSON 樹，yield (parent_container, key, value) 令喺原地改字串。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_all_paths(v, path + (k,))
            if isinstance(v, str):
                yield obj, k, v
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_all_paths(v, path + (i,))
            if isinstance(v, str):
                yield obj, i, v


def _fix_value(s: str) -> str:
    """fix_title，但 URL 值可能未經 normalize_text（NBSP 完好），直接逆向即可。"""
    return fix_title(s) or (s.encode("ptcp154").decode("utf-8") if looks_garbled(s) else "")


def fix_file(path: Path, dry_run: bool) -> int:
    if not path.exists():
        print(f"  ⏭️ 冇 {path.name}")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = 0

    # 1) 值
    for parent, key, value in iter_all_paths(data):
        fixed = _fix_value(value)
        if fixed and fixed != value:
            parent[key] = fixed
            changed += 1
            print(f"  [{path.name}] {value[:38]!r} → {fixed!r}")

    # 2) 鍵（enrich.json 以 URL 作 key，亂碼鍵要 re-key）
    def _rekey(obj):
        nonlocal changed
        if isinstance(obj, dict):
            for k in list(obj.keys()):
                new_key = None
                if isinstance(k, str) and looks_garbled(k):
                    new_key = _fix_value(k)
                    if new_key and new_key != k:
                        obj[new_key] = obj.pop(k)
                        changed += 1
                        print(f"  [{path.name}] KEY {k[:38]!r} → {new_key[:38]!r}")
                child = obj[new_key] if new_key else obj.get(k)
                if isinstance(child, (dict, list)):
                    _rekey(child)
        elif isinstance(obj, list):
            for v in obj:
                if isinstance(v, (dict, list)):
                    _rekey(v)

    _rekey(data)

    if changed and not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return changed


def main() -> None:
    ap = argparse.ArgumentParser(description="清理 Cyrillic 亂碼標題")
    ap.add_argument("--dry-run", action="store_true", help="只預覽，不寫入")
    args = ap.parse_args()

    total = 0
    for p in (CACHE_PATH, ENRICH_PATH):
        n = fix_file(p, args.dry_run)
        print(f"{p.name}: 修復 {n} 筆{'（dry-run，未寫入）' if args.dry_run else ''}")
        total += n
    print(f"\n共修復 {total} 筆")
    if args.dry_run:
        print("（dry-run 模式，冇改任何檔案；去掉 --dry-run 再跑先至寫入）")


if __name__ == "__main__":
    main()

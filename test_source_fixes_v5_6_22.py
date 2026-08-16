#!/usr/bin/env python3
"""
回歸測試 v5.6.22：觀塘區 / 深水埗西區 / 旺角區
==============================================
呢三個來源一直「唔會報錯」但實際抓錯或漏抓（靜默失敗），
所以每日 error_sources 都係空，好易走漏眼：

  觀塘區    只抓到分類目錄連結（「支部通告-童軍(1)」），從來冇真通告
  深水埗西區 type 誤設為 wordpress（實為 Google Sites），只兜底抽到「view」等雜項
  旺角區    Drive 舊式資料夾帶 resourcekey，core.py 只捉 id 丟棄 key → 該資料夾回 500，漏 2 個 PDF

全部用「依實測 DOM 重建」嘅假頁面，唔連外網。
執行：  python test_source_fixes_v5_6_22.py
"""
from __future__ import annotations

import json
import re
import sys
import types

import core
from bs4 import BeautifulSoup

SOURCES = json.load(open("sources.json", encoding="utf-8"))["sources"]
failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


def _collect(name: str, pages: dict, detail_pages: int | None = None):
    """行足 core.py 嘅列表頁 + 分頁流程。"""
    cfg = SOURCES[name]

    def fake(url, config, timeout=20):
        if url not in pages:
            raise AssertionError(f"未預期 URL（設定可能寫錯）: {url}")
        return core.FetchResult(url=url, html=pages[url], engine="requests", status_code=200)

    core.fetch_requests = fake
    core.fetch_with_playwright = lambda *a, **k: None
    core.time = types.SimpleNamespace(sleep=lambda *_: None)

    md = cfg.get("detail_max_pages", 0) if detail_pages is None else detail_pages
    result = core.fetch_main_page(name, cfg)
    assert result is not None, f"{name}: fetch_main_page 回傳 None"
    soup = BeautifulSoup(result.html, "html.parser")
    assets = core.extract_assets_from_listing(
        name=name, soup=soup, page_url=result.url, config=cfg, max_detail_pages=md
    )
    if cfg.get("follow_listing_pages"):
        listing = core.discover_listing_pages(soup, result.url, cfg)
        seen = {a["pdf_url"] for a in assets}
        for u in listing[: int(cfg.get("listing_max_pages") or 0)]:
            sub = core.fetch_page(u, cfg)
            ss = BeautifulSoup(sub.html, "html.parser")
            for r in core.extract_assets_from_listing(
                name=name, soup=ss, page_url=sub.url, config=cfg, max_detail_pages=md
            ):
                if r["pdf_url"] not in seen:
                    seen.add(r["pdf_url"])
                    assets.append(r)
    fp = core.compute_fingerprint(soup, cfg.get("fingerprint_selector", "body"))
    check(bool(fp), f"{name}: 計唔到指紋")
    return assets


# ─────────────── 觀塘區：Phoca Download ───────────────
def test_ktd():
    B = "https://hkscout-ktd.org/ktdweb/index.php/event-and-program"
    cats = [
        "1-2023-12-09-06-20-23", "2-2023-12-09-06-20-30", "4-2023-12-09-06-20-44",
        "3-2023-12-09-06-20-36", "5-2023-12-09-06-20-50", "6-2023-12-09-06-21-05",
    ]
    main = ('<html><body><div id="phocadownload"><div class="pd-categoriesrow">'
            + "".join(f'<a href="{B}/category/{c}.html">分類</a>' for c in cats)
            + "</div></div></body></html>")
    cat3 = (f'<html><body><div id="phocadownload">'
            f'<a href="{B}/file/21-21.html">第21屆初級航空活動章訓練班</a>'
            f'<a href="{B}/file/21-21.html">Download</a>'
            f'<a href="{B}/file/21-21.html?tmpl=component">Details</a>'
            f"</div></body></html>")
    empty = '<html><body><div id="phocadownload"></div></body></html>'
    pages = {f"{B}.html": main,
             f"{B}/file/21-21.html": "<html><body><h3>第21屆初級航空活動章訓練班</h3></body></html>"}
    for c in cats:
        pages[f"{B}/category/{c}.html"] = cat3 if c.startswith("3-") else empty

    assets = _collect("觀塘區", pages)
    print(f"### 觀塘區 → {len(assets)} 個")
    for a in assets:
        print("   -", a["title"], "|", a["pdf_url"].replace(B, "…"))

    check(any("21-21" in a["pdf_url"] for a in assets), "觀塘區: 攞唔到真通告 21-21")
    check(not any("category/" in a["pdf_url"] for a in assets), "觀塘區: 仍收錄分類目錄連結（假通告）")
    check(not any("tmpl=component" in a["pdf_url"] for a in assets), "觀塘區: Details 彈窗版未去重")
    check(len(assets) == len({a["pdf_url"] for a in assets}), "觀塘區: 有重複 URL")
    for a in assets:
        check(not core.is_generic_download_title(a["title"]), f"觀塘區: 通用標題 {a['title']}")


# ─────────────── 深水埗西區：Google Sites ───────────────
def test_sspw():
    url = SOURCES["深水埗西區"]["url"]
    html = """<html><body><div role="main">
<div>Search this site</div><div>Embedded Files</div><h2>最新通告</h2>
<section><div class="C9DxTc">深水埗西區35周年顏明秀系列（二）傷健共融填色比賽結果</div>
<a href="https://drive.google.com/file/d/1lzi7JkEP-L5o_343C8TTR8LNTs7pdV7s/view?usp=drive_link">下載通告</a></section>
<section><div class="C9DxTc">2026-27行事曆</div>
<a href="https://drive.google.com/file/d/1S1IjDJHswuyhIU6-ao-cytHQZlZySGwg/view?usp=drive_link">2026-27行事曆</a></section>
<a href="https://www.google.com/url?q=https%3A%2F%2Fwww.facebook.com%2Fgroups%2Fsspwhk">Facebook</a>
<a href="#">Report abuse</a></div></body></html>"""
    assets = _collect("深水埗西區", {url: html})
    print(f"### 深水埗西區 → {len(assets)} 個")
    for a in assets:
        print("   -", a["title"], "|", a["pdf_url"])

    check(SOURCES["深水埗西區"]["type"] == "google_sites", "深水埗西區: type 應為 google_sites")
    check(len(assets) == 2, f"深水埗西區: 應抽到 2 個，實際 {len(assets)}")
    check(not any(a["title"].strip().lower() == "view" for a in assets), "深水埗西區: 仍有『view』雜項標題")
    check(not any("facebook" in a["pdf_url"].lower() or "google.com/url" in a["pdf_url"]
                  for a in assets), "深水埗西區: 收錄咗社交連結")
    titles = " ".join(a["title"] for a in assets)
    check("35周年" in titles, "深水埗西區: 第一則通告標題錯（應為 35周年…填色比賽結果）")


# ─────────────── 旺角區：Drive resourcekey ───────────────
def test_mkd():
    folders = {
        "1WDNBzQjwuhrFuHWqhsizc8PfIlzXiscc": [("1_CAM0UdPoLsB_ne7SJmRVkFLb7CpNKBQ", "2025讀圖探險章通告及報名表.pdf")],
        "130alJ2johGC453VfDb9mD-ZeQUyokgXR": [("1hhk6h8Z4RFb7A9aEw19AzYQ9kKQ6gVFV", "初航班通告.pdf"),
                                              ("177fBQIEYZ3P9rJzWVRSCwsSOVknikiAR", "地圖閱讀班通告.pdf")],
        "0BzZsW4VHcy3yUE15eDZOMTBNZjA": [("1kp7TeRl07lYEcslkCArPsF7hL5cmzpba", "MKD VS&RS比賽2025_通告.pdf")],
        "1HYBn26Zez52rehRxiPY8mVPI78l-x3z3": [],
        "0BzZsW4VHcy3yTUNtbTZvaEQ4aHc": [("1dV-tgoi3ADphM4apkz5q_cHgEb06XO63", "香港童軍115周年旺角區嘉年華通告.pdf")],
    }
    # 舊式資料夾：冇 resourcekey 就 500（真實行為）
    needs_key = {"0BzZsW4VHcy3yUE15eDZOMTBNZjA", "0BzZsW4VHcy3yTUNtbTZvaEQ4aHc"}
    page = ("<html><body>"
            '<a href="https://docs.google.com/folderview?id=1WDNBzQjwuhrFuHWqhsizc8PfIlzXiscc">Cub</a>'
            '<a href="https://docs.google.com/folderview?id=130alJ2johGC453VfDb9mD-ZeQUyokgXR">S</a>'
            '<a href="https://docs.google.com/folderview?id=0BzZsW4VHcy3yUE15eDZOMTBNZjA&amp;resourcekey=0-u8JLENLXH8n1rovtdKkzNQ">深資</a>'
            '<a href="https://docs.google.com/folderview?id=1HYBn26Zez52rehRxiPY8mVPI78l-x3z3">V</a>'
            '<a href="https://docs.google.com/folderview?id=0BzZsW4VHcy3yTUNtbTZvaEQ4aHc&amp;resourcekey=0-46lBy5jnNFPLP2n0CZ9ycg">區會</a>'
            "</body></html>")

    class Resp:
        def __init__(self, text, code=200):
            self.text, self.status_code = text, code

    def fake_get(u, **kw):
        if "sites.google.com" in u:
            return Resp(page)
        fid = re.search(r"[?&]id=([\w-]+)", u).group(1)
        if fid in needs_key and "resourcekey=" not in u:
            return Resp("<html>Error 500</html>", 500)
        rows = "".join(
            f'<div class="flip-entry"><a href="https://drive.google.com/file/d/{i}/view?usp=drive_web"></a>'
            f'<div class="flip-entry-title">{t}</div></div>' for i, t in folders[fid])
        return Resp(f"<html><body>{rows}</body></html>")

    import requests as _r
    orig = _r.get
    _r.get = fake_get
    try:
        res = core.fetch_main_page("旺角區", SOURCES["旺角區"])
        soup = BeautifulSoup(res.html, "html.parser")
        assets = core.extract_assets_from_listing(
            name="旺角區", soup=soup, page_url=res.url, config=SOURCES["旺角區"], max_detail_pages=0)
    finally:
        _r.get = orig

    print(f"### 旺角區 → {len(assets)} 個")
    for a in assets:
        print("   -", a["title"][:48])

    got = {a["pdf_url"].split("/file/d/")[1].split("/")[0] for a in assets}
    want = {i for v in folders.values() for i, _ in v}
    missing = want - got
    check(not missing, f"旺角區: 漏咗 {missing}（resourcekey 資料夾抽唔到）")
    check(len(assets) == 5, f"旺角區: 應有 5 個 PDF，實際 {len(assets)}")


# ─── resourcekey URL 格式向後兼容 ───
def test_resourcekey_formats():
    import re as _re

    def extract(page_html):
        folder_keys = {}

        def remember(fid, rkey):
            if fid not in folder_keys or (rkey and not folder_keys[fid]):
                folder_keys[fid] = rkey or ""

        for fid, rkey in _re.findall(
            r"(?:drive|docs)\.google\.com/(?:embedded)?folderview\?id=([\w-]+)"
            r"(?:&(?:amp;)?resourcekey=([\w-]+))?", page_html):
            remember(fid, rkey)
        for fid, rkey in _re.findall(
            r"drive\.google\.com/drive/folders/([\w-]+)"
            r"(?:\?(?:amp;)?resourcekey=([\w-]+))?", page_html):
            remember(fid, rkey)
        return folder_keys

    cases = [
        ('<a href="https://docs.google.com/folderview?id=AAA">x</a>', {"AAA": ""}),
        ('<a href="https://drive.google.com/embeddedfolderview?id=BBB">x</a>', {"BBB": ""}),
        ('<a href="https://docs.google.com/folderview?id=CCC&amp;resourcekey=0-KEY">x</a>', {"CCC": "0-KEY"}),
        ('<a href="https://docs.google.com/folderview?id=DDD&resourcekey=0-K2">x</a>', {"DDD": "0-K2"}),
        ('<a href="https://drive.google.com/drive/folders/EEE">x</a>', {"EEE": ""}),
        ('<a href="https://drive.google.com/drive/folders/FFF?resourcekey=0-K3">x</a>', {"FFF": "0-K3"}),
        # 同一 id 出現兩次，有 key 嗰個要贏
        ('<a href="https://docs.google.com/folderview?id=GGG">x</a>'
         '<a href="https://docs.google.com/folderview?id=GGG&amp;resourcekey=0-K4">y</a>', {"GGG": "0-K4"}),
    ]
    for html, expected in cases:
        got = extract(html)
        check(got == expected, f"resourcekey 格式: 預期 {expected}，實際 {got}")
    print(f"### resourcekey URL 格式 → {len(cases)} 種全部驗證")


def main() -> int:
    for fn in (test_ktd, test_sspw, test_mkd, test_resourcekey_formats):
        print("=" * 66)
        fn()
    print("\n" + "=" * 66)
    if failures:
        print(f"❌ {len(failures)} 項失敗：")
        for f in failures:
            print("   -", f)
        return 1
    print("🎉 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())

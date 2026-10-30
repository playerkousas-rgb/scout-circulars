#!/usr/bin/env python3
"""回歸測試：九龍城區 ajax_fragment 抓取 + 「空殼唔可以寫入指紋」防呆。

背景（2026-10-30）
------------------
klcscout.hk/circular 由頭到尾都係一個空殼：inline JS 喺 document.ready 之後
```js
$.get("https://www.klcscout.hk/cportal/getdata.php", function(data){
    $('.pt').replaceWith(data);
});
```
先至把通告表格注入 `.pt`。Chromium 見唔到表格（jQuery 未 ready／AJAX 慢／被擋）時
頁面依然 HTTP 200 而且「render 成功」，於是：

  1. 指紋 = 空殼（每次都一樣）→ process_source 當「無變動」跳過
  2. 就算指紋有變，舊 code「抽出 0 個資產」照樣把空殼指紋寫入 fingerprints
  3. 兩條路都唔會出現在 error_sources → 靜靜咁漏通告

結果 2026-09-26 之後嘅通告（例如 2026-10-29「童軍露營訓練班 2027」）一直冇入庫。

本測試鎖住三件事：
  A. `ajax_fragment` 直接 GET getdata.php（伺服器端 HTML，唔使 JS）→ 抽到通告
  B. 片段失效（空／冇連結）→ fall through，唔會當成「成功但無內容」
  C. 抽出 0 個資產 → 保留舊指紋 + 標記 error（下輪重試，唔會永久跳過）

執行：python test_klc_fragment_2026_10_30.py
"""
import json
from pathlib import Path

import core
from bs4 import BeautifulSoup

FAILED = []


def check(desc, actual, expected):
    ok = actual == expected
    print(f"{'✅' if ok else '❌'} {desc}")
    if not ok:
        print(f"     預期 {expected!r}，實際 {actual!r}")
        FAILED.append(desc)


def check_true(desc, cond, detail=""):
    print(f"{'✅' if cond else '❌'} {desc}")
    if not cond:
        if detail:
            print(f"     {detail}")
        FAILED.append(desc)


# ── 真實片段結構（2026-10-30 由 https://www.klcscout.hk/cportal/getdata.php 取得）──
# 四欄：日期 | 標題 | 支部 | 連結（[通告] 直連 PDF，另有訓練綱要外鏈）
FRAGMENT = """
<div class="pt">
<table class="table">
  <tbody>
    <tr>
      <td>2026-10-29</td>
      <td>童軍露營訓練班 2027</td>
      <td>童軍支部</td>
      <td>
        <a href="https://www.klcscout.hk/cportal/uploads/童軍露營訓練班%202027_通告.pdf">[通告]</a>
        <a href="https://scoutsinfohub.org.hk/ScoutTrainingScheme/pdf-zh/Pursuit/Camper.pdf">[技能組訓練綱要]</a>
      </td>
    </tr>
    <tr>
      <td>2026-09-25</td>
      <td>童軍原野烹飪章（ 教導組及技能組） 訓練班</td>
      <td>童軍支部</td>
      <td>
        <a href="https://www.klcscout.hk/cportal/uploads/童軍原野烹飪章(技能組)訓練班_訓練班通告.pdf">[通告]</a>
        <a href="https://scoutsinfohub.org.hk/ScoutTrainingScheme/pdf-zh/Pursuit/BackwoodsCook.pdf">[訓練班內容]</a>
      </td>
    </tr>
  </tbody>
</table>
</div>
"""

# 空殼：即係 /circular 本身（只有導覽，冇通告）
SHELL = """
<nav><a href="/about-us">關於城區</a><a href="/circular">最新通告</a></nav>
<div class="pt"></div>
"""

CONFIG = json.loads(Path("sources.json").read_text(encoding="utf-8"))["sources"]["九龍城區"]


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"


class FakeSession:
    """只回應 fragment_url，記錄被要求過嘅網址。"""

    def __init__(self, body, status_code=200, exc=None):
        self.body = body
        self.status_code = status_code
        self.exc = exc
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        if self.exc:
            raise self.exc
        return FakeResponse(self.body, self.status_code)


print("── 1. sources.json 嘅九龍城區設定 ──")
check("type 係 ajax_fragment", CONFIG.get("type"), "ajax_fragment")
check("fragment_url 指向 getdata.php", CONFIG.get("fragment_url"),
      "https://www.klcscout.hk/cportal/getdata.php")
check("保留 Playwright 作 fallback", CONFIG.get("use_playwright"), True)
check("PW fallback 等表格連結（唔係 networkidle）", CONFIG.get("wait_strategy"), "selector")
check("PW wait_selector 係 PDF 連結欄", CONFIG.get("wait_selector"),
      'a[href*="cportal/uploads"]')

print("\n── 2. ajax_fragment 直接抓片段（唔經 JavaScript）──")
_orig_session = core.SESSION
fake = FakeSession(FRAGMENT)
core.SESSION = fake
try:
    result = core.fetch_main_page("九龍城區", CONFIG)
finally:
    pass
check_true("fetch_main_page 有結果", result is not None)
if result:
    check("engine 係 requests（冇開 Chromium）", result.engine, "requests")
    check("只請求咗片段網址", fake.requested == [CONFIG["fragment_url"]], True)
    soup = BeautifulSoup(result.html, "html.parser")
    check("片段入面有 2 個 PDF 連結", len(soup.select('a[href*="cportal/uploads"]')), 2)

print("\n── 3. 片段 → 通告記錄（標題唔可以係日期或者「通告」）──")
assets = core.extract_assets_from_listing(
    "九龍城區", soup, result.url, CONFIG, 12
) if result else []
by_url = {a["pdf_url"]: a["title"] for a in assets}
klc_pdf = "https://www.klcscout.hk/cportal/uploads/童軍露營訓練班%202027_通告.pdf"
check_true(f"抽到 2026-10-29 通告（{len(assets)} 筆）", klc_pdf in by_url,
           f"實際：{list(by_url)}")
check("新通告標題 = 童軍露營訓練班 2027", by_url.get(klc_pdf), "童軍露營訓練班 2027")
old_pdf = "https://www.klcscout.hk/cportal/uploads/童軍原野烹飪章(技能組)訓練班_訓練班通告.pdf"
check("舊通告標題保留", by_url.get(old_pdf), "童軍原野烹飪章( 教導組及技能組) 訓練班")
check_true("標題唔會變成日期",
           all(t and not t.startswith("2026-") for t in by_url.values()),
           f"實際：{by_url}")

print("\n── 4. 片段失效：要 fall through，唔可以當「成功但空」──")
core.SESSION = FakeSession(SHELL)
check("片段係空殼（冇 cportal/uploads）→ fetch_main_page 回 None（交由 PW fallback）",
      core.fetch_main_page("九龍城區", CONFIG), None)
core.SESSION = FakeSession("", status_code=500)
check("片段 HTTP 500 → fall through", core.fetch_main_page("九龍城區", CONFIG), None)
core.SESSION = FakeSession("", exc=RuntimeError("boom"))
check("片段連線失敗 → fall through", core.fetch_main_page("九龍城區", CONFIG), None)
core.SESSION = _orig_session

print("\n── 5. 抽出 0 個資產：保留舊指紋 + 標記 error ──")
# 舊 code：return new_fp（空殼指紋）＋ has_err=False → 下一輪「指紋相同」永久跳過
_orig_fetch = core.fetch_main_page
try:
    core.fetch_main_page = lambda name, cfg: core.FetchResult(
        url=cfg.get("url", ""), html=f"<html><body>{SHELL}</body></html>",
        engine="playwright", status_code=200,
    )
    old_fp = "feca600268901da715c7f2334667fe5b"
    new_recs, upd, fp, skip, engine, has_err = core.process_source(
        "九龍城區", CONFIG, {"九龍城區": old_fp}, set(), "2026-10-30"
    )
    check("冇新增記錄", new_recs, [])
    check("保留舊指紋（唔寫入空殼指紋）", fp, old_fp)
    check("標記為錯誤 → 出現在 error_sources", has_err, True)
    check("唔會當成「指紋相同」跳過", skip, False)
finally:
    core.fetch_main_page = _orig_fetch

print("\n" + ("✅ 全部通過" if not FAILED else f"❌ {len(FAILED)} 項失敗: {FAILED}"))
raise SystemExit(1 if FAILED else 0)

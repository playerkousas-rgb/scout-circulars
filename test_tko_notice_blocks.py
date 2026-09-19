#!/usr/bin/env python3
"""回歸測試 v5.6.23：將軍澳區 notice_card 結構化解析 + 指紋唔再對通告內容盲。

背景（2026-09-19 診斷）
----------------------
將軍澳區 (hkscout-tko.org/notice.php) 嘅下載掣唔係 anchor，而係
``<span class="pdfImg" data-id="206">``（站方 JS 跳 ``/notice/?nid=206``）。
後果有两个：

1. ``asset_link_selector: "a[href]"`` 睇唔到 → 30 筆通告 0 個附件，舊 regex 路徑
   唯有砌假 URL ``notice.php#slug``；但個頁只有 ``#top`` 同 8 個分類 anchor，
   所以 UI 㩒「開啟附件」永遠彈返列表頂。
2. ``fingerprint_selector: ".divContent, body"`` —— 两者都含 ``a[href]``
   （breadcrumb + 8 個分類連結 + 登入/聯絡我們/常見問題 + mailto），
   ``compute_fingerprint`` 因此行「只 hash anchor」分支；而通告卡一個 anchor 都冇，
   所以通告增減／改標題／過期，指紋一律唔變 → GitHub Actions 嘅 ``python core.py``
   （無 --force）日日 skip 呢個來源，只有本機 ``run-local-scrape.bat`` 嘅 --force 先巡到。

下面嘅 fixture 係 2026-09-19 由 W3C validator（out=xml&showsource=yes）攞到嘅
verbatim DOM 結構，唔係憑空砌嘅。

跑法（sandbox 冇 bs4/requests 就會自動 skip）::

    python -m pytest test_tko_notice_blocks.py -q
"""
from __future__ import annotations

import copy
import inspect
import json
import re
import sys
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

try:
    import bs4
    from bs4 import BeautifulSoup
except ImportError:
    bs4 = None
    BeautifulSoup = None

import core  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
SOURCES = json.loads((BASE_DIR / "sources.json").read_text(encoding="utf-8"))["sources"]
TKO_CFG = SOURCES["將軍澳區"]
PAGE_URL = TKO_CFG["url"]


class SimpleMonkeyPatch:
    """輕量 monkeypatch：冇安裝 pytest 時 standalone 執行用。"""

    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        old = getattr(target, name)
        self._undo.append((target, name, old))
        setattr(target, name, value)

    def undo(self):
        for target, name, old in reversed(self._undo):
            setattr(target, name, old)


def tko_cfg(**overrides):
    """真 config（連 sources.json 一齊測），預設唔跟內頁，等測試唔使等 sleep。"""
    cfg = copy.deepcopy(TKO_CFG)
    cfg["notice_detail_max_pages"] = 0  # 預設唔跟內頁；要測就由 overrides 開返
    cfg.update(overrides)
    return cfg


# ── verbatim 結構（簡化自 hkscout-tko.org/notice.php 2026-09-19 快照）──────────
# 保留晒關鍵特徵：
#   * .divContent 內嘅 breadcrumb <a href=''> 同 8 個分類 <a href="#spec"> …
#     （正正係呢啲 static chrome anchor 令舊指紋永遠唔變）
#   * 通告卡係 .divlink > .form-group，四欄：編號 / 標題 / 按鈕 / 期限
#   * 已過期通告嘅可見期限得 <span class="span_expired">已截止</span>，
#     原截止日只保留喺 whatsappImg[data-title]
#   * 未過期通告先有 <span class="span_deadline">截止: …</span>
#   * twitter/google share 掣係 HTML comment（內含 data-id，唔應該被選中）
FIXTURE = """
<html><body>
<div class="container-fluid">
 <div class="col-md-2 col-sm-3 col-xs-12 divMenu">
  <span class="0" data-link="news.php">最新消息</span>
 </div>
 <div class="col-md-10 col-sm-9 col-xs-12 divContent">
  <div class="col-xs-12">
   <span><a href='' target='_self'>活動及訓練</a> / 本區通告</span>
   <span><a href="./staff/login.php">登入</a> | <a href="./contact.php">聯絡我們</a></span>
   <div class="form-group">
    <div class="form-group subheader"><h4 class="col-sm-12 col-xs-12">本區通告</h4></div>
    <div class="form-group">
     <div class="col-xs-12"><a name="top"></a>
      <a href="#spec">特別通告</a> | <a href="#adm">行政通告</a> | <a href="#all">跨支部</a>
      | <a href="#gs">小童軍支部</a> | <a href="#cs">幼童軍支部</a> | <a href="#sc">童軍支部</a>
      | <a href="#vs">深資童軍支部</a> | <a href="#rs">樂行童軍支部</a>
     </div>
    </div>

    <a name="spec"></a><h4>特別通告 <i class='fa fa-chevron-circle-up' aria-hidden='true'></i></h4>
    <div class="divlink">
     <div class="form-group">
      <div class="col-md-2 col-sm-2 col-xs-12 div_expired">11-2025</div>
      <div class="col-md-5 col-sm-5 col-xs-12 div_expired">邁步未來領袖聯誼聚會 (深資童軍及樂行童軍邀請)</div>
      <div class="col-md-2 col-sm-2 col-xs-12 div_expired">
       <span class="pdfImg" data-id="190" title="下載"><i class="fa fa-file-pdf-o" aria-hidden="true"></i></span>
       <span class="whatsappImg" data-id="190" data-title="邁步未來領袖聯誼聚會 (深資童軍及樂行童軍邀請) (2025-11-27截止)" title="Share to Whatsapp"><i class="fa fa-whatsapp" aria-hidden="true"></i></span>
       <span class="fbImg" data-id="190" data-title="邁步未來領袖聯誼聚會 (深資童軍及樂行童軍邀請)(11-2025)" title="Share to Facebook"><i class="fa fa-facebook-square" aria-hidden="true"></i></span>
       <!--
       <span class="twitterImg" data-id="999" data-title="唔應該被選中" title="Share to Twitter"><i class="fa fa-twitter"></i></span>
       -->
      </div>
      <div class="col-md-3 col-sm-3 col-xs-12 div_expired">
       <span class="span_expired">已截止</span>
      </div>
     </div>
     <hr class="visible-xs" />
     <div class="form-group">
      <div class="col-md-2 col-sm-2 col-xs-12 div_expired">10-2025</div>
      <div class="col-md-5 col-sm-5 col-xs-12 div_expired">邁步未來領袖聯誼聚會</div>
      <div class="col-md-2 col-sm-2 col-xs-12 div_expired">
       <span class="pdfImg" data-id="189" title="下載"><i class="fa fa-file-pdf-o"></i></span>
       <span class="whatsappImg" data-id="189" data-title="邁步未來領袖聯誼聚會 (2025-11-20截止)" title="Share to Whatsapp"><i class="fa fa-whatsapp"></i></span>
       <span class="fbImg" data-id="189" data-title="邁步未來領袖聯誼聚會(10-2025)" title="Share to Facebook"><i class="fa fa-facebook-square"></i></span>
      </div>
      <div class="col-md-3 col-sm-3 col-xs-12 div_expired">
       <span class="span_expired">已截止</span>
      </div>
     </div>
     <hr class="visible-xs" />
    </div>

    <a name="adm"></a><h4>行政通告 <i class='fa fa-chevron-circle-up' aria-hidden='true'></i></h4>
    <div class="divlink">
     <div class="form-group">
      <div class="col-md-2 col-sm-2 col-xs-12 div_expired">06-2026</div>
      <div class="col-md-5 col-sm-5 col-xs-12 div_expired">第25屆區務委員會就職典禮暨積極公民同樂日</div>
      <div class="col-md-2 col-sm-2 col-xs-12 div_expired">
       <span class="pdfImg" data-id="206" title="下載"><i class="fa fa-file-pdf-o"></i></span>
       <span class="whatsappImg" data-id="206" data-title="第25屆區務委員會就職典禮暨積極公民同樂日 (2026-07-16截止)" title="Share to Whatsapp"><i class="fa fa-whatsapp"></i></span>
       <span class="fbImg" data-id="206" data-title="第25屆區務委員會就職典禮暨積極公民同樂日(06-2026)" title="Share to Facebook"><i class="fa fa-facebook-square"></i></span>
      </div>
      <div class="col-md-3 col-sm-3 col-xs-12 div_expired">
       <span class="span_expired">已截止</span>
      </div>
     </div>
    </div>

    <h4>活動與訓練通告</h4>
    <a name="cs"></a><h5>幼童軍支部 <i class='fa fa-chevron-circle-up' aria-hidden='true'></i></h5>
    <div class="divlink">
     <div class="form-group">
      <div class="col-md-2 col-sm-2 col-xs-12">09-2026<img src='images/new.gif' /></div>
      <div class="col-md-5 col-sm-5 col-xs-12">幼童軍活動 親子長洲偵探之旅</div>
      <div class="col-md-2 col-sm-2 col-xs-12">
       <span class="pdfImg" data-id="211" title="下載"><i class="fa fa-file-pdf-o"></i></span>
       <span class="whatsappImg" data-id="211" data-title="幼童軍活動 親子長洲偵探之旅 (2026-09-30截止)" title="Share to Whatsapp"><i class="fa fa-whatsapp"></i></span>
       <span class="fbImg" data-id="211" data-title="幼童軍活動 親子長洲偵探之旅(09-2026)" title="Share to Facebook"><i class="fa fa-facebook-square"></i></span>
      </div>
      <div class="col-md-3 col-sm-3 col-xs-12">
       <span class="span_deadline">截止: 2026-09-30</span>
      </div>
     </div>
    </div>

   </div>
  </div>
 </div>
</div>
</body></html>
"""


def soup_of(html: str = FIXTURE) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def parse(html: str = FIXTURE, **overrides):
    return core.parse_notice_card_blocks("將軍澳區", soup_of(html), PAGE_URL, tko_cfg(**overrides))


def by_nid(records, nid):
    hits = [r for r in records if f"nid={nid}" in r["pdf_url"]]
    assert len(hits) == 1, f"nid={nid} 應該啱啱好一笔，實際 {len(hits)}: {records}"
    return hits[0]


# ─── 1. 真 URL：唔再係砌出嚟嘅假 fragment ────────────────────────


def test_每張通告卡都解析到():
    records = parse()
    assert len(records) == 4, records


def test_url_係真內頁_nid_而唔係假_anchor():
    for r in parse():
        assert "notice.php#" not in r["pdf_url"], f"仲係假 URL: {r}"
        assert r["pdf_url"].startswith("https://hkscout-tko.org/notice/?nid="), r


def test_nid_對得上站方_data_id():
    records = parse()
    assert by_nid(records, 190)["title"].startswith("11-2025 特別通告 - 邁步未來領袖聯誼聚會")
    assert by_nid(records, 189)["title"].startswith("10-2025 特別通告 - 邁步未來領袖聯誼聚會")
    assert by_nid(records, 206)["title"].startswith("06-2026 行政通告 - 第25屆區務委員會就職典禮")
    assert by_nid(records, 211)["title"].startswith("09-2026 幼童軍支部 - 幼童軍活動 親子長洲偵探之旅")


def test_分類標題由_h5_h4_攞_而唔係_outer_h4():
    """幼童軍嗰則上面有 <h4>活動與訓練通告</h4> 同 <h5>幼童軍支部</h5>，要攞最近嗰個。"""
    assert "幼童軍支部" in by_nid(parse(), 211)["title"]
    assert "活動與訓練通告" not in by_nid(parse(), 211)["title"]


def test_commented_out_share_掣唔會被當成正文():
    """twitter/google 掣係 HTML comment，內含 data-id=999 —— 唔應該出現喺任何 record。"""
    for r in parse():
        assert "999" not in r["pdf_url"], r
        assert "唔應該被選中" not in r["title"], r


# ─── 2. 截止日：過期通告都要還原到 ────────────────────────────────


def test_已過期通告由_data_title_還原截止日():
    """畫面色水變「已截止」之後，可見嘅 deadline 就冇咗；data-title 仲留住原日期。"""
    records = parse()
    assert by_nid(records, 190)["title"].endswith("(截止: 2025-11-27)")
    assert by_nid(records, 189)["title"].endswith("(截止: 2025-11-20)")
    assert by_nid(records, 206)["title"].endswith("(截止: 2026-07-16)")


def test_未過期通告嘅截止日():
    assert by_nid(parse(), 211)["title"].endswith("(截止: 2026-09-30)")


def test_冇_data_title_時_回落去可見嘅_span_deadline():
    """站方哪天改咗 share 掣，都唔應該即刻失去 deadline。"""
    html = FIXTURE.replace(' data-title="幼童軍活動 親子長洲偵探之旅 (2026-09-30截止)"', "")
    assert by_nid(parse(html), 211)["title"].endswith("(截止: 2026-09-30)")


def test_標題格式同舊路徑一致():
    """舊 cache 嘅格式係 "{code} {heading} - {title} (截止: YYYY-MM-DD)"。

    格式唔變，先至可以靠 fix_tko_notice_urls.py 用 title 配對 re-key 而保留 captured_date。
    """
    r = by_nid(parse(), 206)
    assert r["title"] == "06-2026 行政通告 - 第25屆區務委員會就職典禮暨積極公民同樂日 (截止: 2026-07-16)"


# ─── 3. 指紋：呢個先係「Actions 日日 skip 將軍澳區」嘅根因 ──────────


def _expire(html: str) -> str:
    """模擬一則通告由「未截止」變「已截止」（站方最常見嘅每日一變）。"""
    return html.replace(
        '<span class="span_deadline">截止: 2026-09-30</span>',
        '<span class="span_expired">已截止</span>',
    )


def _remove_one(html: str) -> str:
    """模擬區會落架一則通告（2026-05 就試过一次過落架 7 則）。"""
    start = html.index('<a name="spec"></a>')
    end = html.index('<a name="adm"></a>')
    return html[:start] + html[end:]


def test_新指紋_divlink_對通告增減同過期敏感():
    cfg = TKO_CFG
    base = core.compute_fingerprint(soup_of(FIXTURE), cfg["fingerprint_selector"])
    assert cfg["fingerprint_selector"] == ".divlink", "呢個測試係釘住 sources.json 嘅設定"
    assert base, "指紋唔應該係空字串"
    assert core.compute_fingerprint(soup_of(_expire(FIXTURE)), ".divlink") != base, "過期應該要改變指紋"
    assert core.compute_fingerprint(soup_of(_remove_one(FIXTURE)), ".divlink") != base, "落架應該要改變指紋"


def test_舊指紋_divContent_body_對通告內容盲():
    """回歸釘：舊 selector 只 hash 到 static chrome anchor，所以永遠唔變。

    呢個就係點解 GitHub Actions（python core.py，無 --force）日日 skip 將軍澳區，
    只有本機 run-local-scrape.bat 嘅 --force 先至巡到。
    """
    old_selector = ".divContent, body"
    base = core.compute_fingerprint(soup_of(FIXTURE), old_selector)
    assert base
    assert core.compute_fingerprint(soup_of(_expire(FIXTURE)), old_selector) == base
    assert core.compute_fingerprint(soup_of(_remove_one(FIXTURE)), old_selector) == base


def test_divlink_內真係冇_anchor():
    """成個 bug 嘅前提：通告卡零 anchor → compute_fingerprint 行 text 分支。"""
    for el in soup_of().select(".divlink"):
        assert not el.select("a[href]"), el.get_text(" ", strip=True)[:60]


# ─── 4. dispatcher + fail-soft ──────────────────────────────────


def test_parse_text_notice_blocks_會_dispatch_去_card_parser():
    records = core.parse_text_notice_blocks(soup_of(), PAGE_URL, tko_cfg(), name="將軍澳區")
    assert records and all("notice.php#" not in r["pdf_url"] for r in records), records


def test_card_解析唔到時_回落去舊_regex_路徑():
    """站方再改版都唔應該由「有資料」變「零資料」。"""
    html = FIXTURE.replace('class="divlink"', 'class="divlink_renamed"')
    cfg = tko_cfg(text_notice_selector=[".divlink_renamed"])
    records = core.parse_text_notice_blocks(soup_of(html), PAGE_URL, cfg, name="將軍澳區")
    assert records, "回落路徑應該仲解析到通告"
    assert all(r["pdf_url"].startswith(PAGE_URL + "#") for r in records), records


def test_內頁攞唔到時_fail_soft_保留_nid_url(monkeypatch):
    """站方 block 抓取端 IP（/notice/?nid= 對 datacenter IP 回 500）時唔應該炸。"""
    monkeypatch.setattr(core, "fetch_detail_page", lambda *a, **k: None)
    monkeypatch.setattr(core.time, "sleep", lambda *_a, **_k: None)
    records = parse(notice_detail_max_pages=5)
    assert len(records) == 4
    assert all(r["pdf_url"].startswith("https://hkscout-tko.org/notice/?nid=") for r in records)


def test_內頁有_pdf_時_升級做真_pdf(monkeypatch):
    """呢個係成個 fix 嘅目的：pdf_url 變真 PDF，enrich.py 先至抽到參加資格／費用。"""
    seen = []

    def fake_fetch(name, detail_url, config):
        seen.append(detail_url)
        nid = detail_url.rsplit("nid=", 1)[-1]

        class _R:
            html = (
                f"<html><body><h1>通告 {nid}</h1>"
                f'<a href="/uploads/notice/{nid}.pdf">下載通告</a>'
                "</body></html>"
            )
            url = detail_url

        return _R()

    monkeypatch.setattr(core, "fetch_detail_page", fake_fetch)
    monkeypatch.setattr(core.time, "sleep", lambda *_a, **_k: None)
    records = parse(notice_detail_max_pages=5)

    assert sorted(u.rsplit("nid=", 1)[-1] for u in seen) == ["189", "190", "206", "211"], seen
    # 每張卡都要升級去自己嗰份 PDF，唔好張冠李戴
    got = {r["title"].split(" ", 1)[0]: r["pdf_url"] for r in records}
    assert got == {
        "11-2025": "https://hkscout-tko.org/uploads/notice/190.pdf",
        "10-2025": "https://hkscout-tko.org/uploads/notice/189.pdf",
        "06-2026": "https://hkscout-tko.org/uploads/notice/206.pdf",
        "09-2026": "https://hkscout-tko.org/uploads/notice/211.pdf",
    }, records
    # 標題唔應該被內頁標題蓋走：列表標題先有編號／分類／截止日
    pdf_rec = next(r for r in records if r["pdf_url"].endswith("/211.pdf"))
    assert pdf_rec["title"] == "09-2026 幼童軍支部 - 幼童軍活動 親子長洲偵探之旅 (截止: 2026-09-30)"
    # pdf_url 係真 PDF 之後 enrich.py 先會肯處理（enrich.py 只食 .pdf）
    assert all(core.is_download_url(r["pdf_url"]) for r in records), records


def test_notice_detail_max_pages_上限生效(monkeypatch):
    """防封：每日 --force 都唔應該無上限咁炸內頁。"""
    calls = []
    monkeypatch.setattr(
        core, "fetch_detail_page", lambda name, url, config: calls.append(url) or None
    )
    monkeypatch.setattr(core.time, "sleep", lambda *_a, **_k: None)
    parse(notice_detail_max_pages=2)
    assert len(calls) == 2, calls


def test_預設_0_上限就完全唔跟內頁(monkeypatch):
    calls = []
    monkeypatch.setattr(
        core, "fetch_detail_page", lambda name, url, config: calls.append(url) or None
    )
    parse()  # tko_cfg() 預設 notice_detail_max_pages=0
    assert calls == []


# ─── 5. 純 Python / regex 測試（免 bs4 依賴，任何環境皆可跑）──────────


def test_regex_編號欄():
    assert core.NOTICE_CARD_CODE_COL_RE.match("06-2026")
    assert core.NOTICE_CARD_CODE_COL_RE.match("11-2025")
    assert not core.NOTICE_CARD_CODE_COL_RE.match("06-2026 行政通告")
    assert not core.NOTICE_CARD_CODE_COL_RE.match("已截止")


def test_regex_data_title_截止日提取():
    raw1 = "第25屆區務委員會就職典禮暨積極公民同樂日 (2026-07-16截止)"
    m1 = core.NOTICE_CARD_DEADLINE_RE.search(raw1)
    assert m1 and m1.group(1) == "2026-07-16"
    assert raw1[: m1.start()].strip() == "第25屆區務委員會就職典禮暨積極公民同樂日"

    raw2 = "邁步未來領袖聯誼聚會 (深資童軍及樂行童軍邀請) (2025-11-27截止)"
    m2 = core.NOTICE_CARD_DEADLINE_RE.search(raw2)
    assert m2 and m2.group(1) == "2025-11-27"
    assert raw2[: m2.start()].strip() == "邁步未來領袖聯誼聚會 (深資童軍及樂行童軍邀請)"


def test_regex_facebook_share_編號提取():
    raw = "第25屆區務委員會就職典禮暨積極公民同樂日(06-2026)"
    m = core.NOTICE_CARD_CODE_TAIL_RE.search(raw)
    assert m and m.group(1) == "06-2026"


def test_sources_json_將軍澳區_config_設定完整():
    cfg = TKO_CFG
    assert cfg["fingerprint_selector"] == ".divlink", "指紋必須是 .divlink 以避免 static chrome 盲區"
    assert cfg["notice_card_selector"] == ".divlink .form-group"
    assert cfg["notice_id_selector"] == "[data-id]"
    assert cfg["notice_detail_url_template"] == "/notice/?nid={id}"
    assert cfg["notice_detail_max_pages"] == 30


def test_fix_script_title_key_配對邏輯():
    from fix_tko_notice_urls import title_key
    # 舊 cache 的標題（無截止日）
    old_title = "06-2026 行政通告 - 第25屆區務委員會就職典禮暨積極公民同樂日"
    # 新 parser 還原截止日後的標題
    new_title = "06-2026 行政通告 - 第25屆區務委員會就職典禮暨積極公民同樂日 (截止: 2026-07-16)"
    assert title_key(old_title) == title_key(new_title)


# ─── 主測試執行器（支援直接 python test_tko_notice_blocks.py 運行）────────


def main() -> int:
    all_tests = [
        (name, fn)
        for name, fn in globals().items()
        if name.startswith("test_") and callable(fn)
    ]
    bs4_tests = [t for t in all_tests if not t[0].startswith("test_regex_") and not t[0].startswith("test_sources_") and not t[0].startswith("test_fix_")]
    pure_tests = [t for t in all_tests if t not in bs4_tests]

    passed = 0
    failed = 0
    skipped = 0

    print("=" * 66)
    print(f"🧪 將軍澳區 v5.6.23 回歸測試集（共 {len(all_tests)} 個測試）")
    print("=" * 66)

    # 1. 跑純 Python 測試
    for name, fn in pure_tests:
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            failed += 1

    # 2. 跑 BeautifulSoup DOM 測試
    if BeautifulSoup is None:
        print(f"\n  ⚠️  當前環境缺少 BeautifulSoup (bs4)，略過 {len(bs4_tests)} 項 DOM 測試。")
        print("     提示：可在有 bs4 的環境（如本機執行 run-local-scrape.bat 的 Python）運行：")
        print("         python test_tko_notice_blocks.py")
        skipped = len(bs4_tests)
    else:
        for name, fn in bs4_tests:
            sig = inspect.signature(fn)
            mp = SimpleMonkeyPatch()
            try:
                if "monkeypatch" in sig.parameters:
                    fn(mp)
                else:
                    fn()
                print(f"  ✅ {name}")
                passed += 1
            except Exception as e:
                print(f"  ❌ {name}: {e}")
                failed += 1
            finally:
                mp.undo()

    print("=" * 66)
    print(f"測試結果：通過 {passed} 項 / 失敗 {failed} 項 / 略過 {skipped} 項")
    if failed:
        return 1
    print("🎉 通過！")
    return 0


if __name__ == "__main__":
    sys.exit(main())

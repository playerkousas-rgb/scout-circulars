#!/usr/bin/env python3
"""回歸測試 v5.6.24：內頁 meta refresh 跳轉 + 「記錄只增不減」嘅 cache 紀律。

背景（2026-09-19 診斷）
----------------------
將軍澳區嘅通告內頁 ``https://hkscout-tko.org/notice/?nid=207`` 係一個「空殼」：
``<body>`` 完全空，冇 ``<a>``、冇 ``<iframe>``、冇 ``<embed>``，只有古典 HTML
自動跳轉::

    <meta http-equiv="refresh"
          content="0; url=https://hkscout-tko.org/notice/2026/prog_207.pdf">

兩個連鎖後果：

1. ``core.py`` 嘅 ``extract_detail_assets`` 只搵 ``a[href]`` / ``iframe`` /
   ``embed`` / ``object``，見到空 body 就回空 list →
   ``fetch_detail_page`` 當「內頁冇嘢」→ fail-soft 保留
   ``https://hkscout-tko.org/notice/?nid=207`` 當成 PDF 網址寫入 cache.json；
2. ``enrich.py``（``collect_targets``）嚴格要求網址以 ``.pdf`` 結尾，見到
   ``?nid=207`` 直接繼續（略過）→ enrich.json 完全冇將軍澳區嘅資料。

仲有第三個後果要一齊處理：URL 由 placeholder 變真 PDF 之後，cache 嘅唯一鍵
``(source_site, pdf_url)`` 亦變 → 舊 placeholder 會被當成另一則通告留低
（同一則通告喺 UI 出現兩次），而真 PDF 嗰筆 ``captured_date`` 係今日 →
notify.py 會把 29 筆舊通告當「新通告」重推。
``core.collapse_notice_placeholders`` 就係收起舊 placeholder、過繼最早
``captured_date``（captured_date 嘅語義係「幾時第一次見到」）。

跑法::

    python -m pytest test_meta_refresh_detail.py -q
    python test_meta_refresh_detail.py     # 冇 pytest 都得（缺 bs4 時自動略過 DOM 測試）
"""
from __future__ import annotations

import copy
import inspect
import json
import sys
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import core  # noqa: E402

SOURCES = json.loads((BASE_DIR / "sources.json").read_text(encoding="utf-8"))["sources"]
TKO_CFG = SOURCES["將軍澳區"]

# 同一份 TKO 列表 fixture（test_tko_notice_blocks.py 內嘅 verbatim DOM 結構），
# 借過嚟測「通告卡 → 內頁 meta refresh → 真 PDF」成條鏈。
try:
    from test_tko_notice_blocks import (
        FIXTURE as TKO_LISTING_FIXTURE,
        SimpleMonkeyPatch,
        soup_of as tko_soup,
    )
except Exception:  # pragma: no cover
    TKO_LISTING_FIXTURE = ""
    SimpleMonkeyPatch = None
    tko_soup = None

TKO_PAGE_URL = TKO_CFG["url"]
TKO_PDF_207 = "https://hkscout-tko.org/notice/2026/prog_207.pdf"
TKO_DETAIL_207 = "https://hkscout-tko.org/notice/?nid=207"

# 2026-09-19 現場攞到嘅內頁結構：<head> 有 meta refresh，<body> 完全空。
EMPTY_SHELL_207 = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>09-2026 小童軍支部 - 小童軍活動 親子長洲偵探之旅</title>
<meta http-equiv="refresh" content="0; url={TKO_PDF_207}">
</head>
<body>
</body>
</html>
"""


def needs_bs4(fn):
    """標記 DOM 測試：standalone 執行器喺缺 bs4 嘅環境會略過。"""
    fn._needs_bs4 = True
    return fn


def tko_cfg(**overrides):
    cfg = copy.deepcopy(TKO_CFG)
    cfg["notice_detail_max_pages"] = 0
    cfg.update(overrides)
    return cfg


def fetch_result(html: str, url: str):
    return core.FetchResult(url=url, html=html, engine="requests", status_code=200)


# ─── 1. meta refresh 目標解析（純字串，任何環境可跑）─────────────────


def test_meta_refresh_基本寫法():
    assert core.extract_meta_refresh_target(f"0; url={TKO_PDF_207}") == TKO_PDF_207
    assert core.extract_meta_refresh_target(f"0;url={TKO_PDF_207}") == TKO_PDF_207


def test_meta_refresh_引號大細寫同空格():
    # 站方／CDN 改少少寫法都唔應該失效
    assert core.extract_meta_refresh_target(f"0; URL = '{TKO_PDF_207}'") == TKO_PDF_207
    assert core.extract_meta_refresh_target(f'0;url="{TKO_PDF_207}"') == TKO_PDF_207
    assert core.extract_meta_refresh_target(f"0; url={TKO_PDF_207} ;") == TKO_PDF_207
    assert core.extract_meta_refresh_target(f"url={TKO_PDF_207}") == TKO_PDF_207


def test_meta_refresh_唔靠_split_分號_唔會斬爛_url():
    """舊式寫法用 split(";") 會把 query 內嘅分號斬開 —— 呢度要原汁原味。"""
    target = "https://hkscout-tko.org/notice/2026/prog_207.pdf?a=1;b=2"
    assert core.extract_meta_refresh_target(f"0; url={target}") == target


def test_meta_refresh_認唔出就回空():
    assert core.extract_meta_refresh_target("5") == ""
    assert core.extract_meta_refresh_target("") == ""
    assert core.extract_meta_refresh_target(None) == ""
    assert core.extract_meta_refresh_target("0; refresh") == ""


# ─── 2. placeholder 判別（唔好誤掉 page-fallback 來源嘅真內頁）────────


def test_placeholder_認得出將軍澳區內頁_url():
    assert core.is_notice_placeholder_url(TKO_DETAIL_207, TKO_CFG) is True
    assert core.is_notice_placeholder_url("https://hkscout-tko.org/notice/?nid=190", TKO_CFG) is True


def test_placeholder_真檔案唔算():
    assert core.is_notice_placeholder_url(TKO_PDF_207, TKO_CFG) is False


def test_placeholder_冇_template_嘅來源一律唔算():
    """灣仔區、大埔北區等：內頁 URL 就係佢哋嘅正式記錄，唔可以被當 placeholder。"""
    for name in ("灣仔區", "大埔北區", "觀塘區"):
        cfg = SOURCES.get(name) or {}
        url = (cfg.get("url") or "https://example.org") + "/some-article"
        assert core.is_notice_placeholder_url(url, cfg) is False, name
    assert core.is_notice_placeholder_url(TKO_DETAIL_207, {}) is False


def test_placeholder_template_冇_id_就唔認():
    assert core.notice_detail_template_regex({}) is None
    assert core.notice_detail_template_regex({"notice_detail_url_template": "/notice/{slug}"}) is None


# ─── 3. 記錄只增不減：同一張卡可以有兩筆，一筆都唔會被收起 ──────────
#
# 原則（2026-09-19 使用者定案）：我哋要嘅係「全」。GitHub Actions 掃到、本機掃到、
# 一時掃到一時掃唔到 —— 每個時刻見到嘅都係真，cache 照收。用戶見到多一張一樣嘅卡
# （一張跳內頁、一張直連 PDF）無傷大雅；站方唔統一伺服器，唔應該由我哋去掩蓋。


TITLE_206 = "06-2026 行政通告 - 第25屆區務委員會就職典禮暨積極公民同樂日 (截止: 2026-07-16)"


def row(url, date, title=None, source="將軍澳區"):
    title = TITLE_206 if title is None else title
    return {"source_site": source, "region": "東九龍地域",
            "pdf_url": url, "title": title, "captured_date": date}


def test_cache_collapse_機制已經唔存在():
    """釘死：core.py 唔應該再有任何「收起／取代記錄」嘅函數。

    曾幾何時呢度有 collapse_superseded_placeholders；佢會令同一張卡嘅舊 URL
    記錄消失。使用者明確要求「多一筆唔緊要，我哋要全」，所以拆走咗。
    """
    names = [n for n in dir(core) if "collapse" in n.lower()]
    assert names == [], f"唔應該再有收起記錄嘅函數: {names}"
    for needle in ("superseded_placeholders", "known_detail_files", "_notice_detail_files"):
        assert needle not in Path(core.__file__).read_text(encoding="utf-8"), needle


def test_同一張卡兩筆都留_包括內頁_URL_同真檔案():
    """一時掃到真檔案、一時只掃到內頁 URL → 兩筆都係真，兩筆都要留。"""
    placeholder = row("https://hkscout-tko.org/notice/?nid=206", "2026-09-19")
    resolved = row("https://hkscout-tko.org/notice/2026/prog_206.pdf", "2026-06-30")
    assert core.build_grouped_cache([placeholder, resolved], SOURCES, "2026-09-19")["data"]["將軍澳區"], "兩筆都要出"
    data = core.build_grouped_cache([placeholder, resolved], SOURCES, "2026-09-19")
    entries = data["data"]["將軍澳區"]
    assert len(entries) == 2, entries
    assert {e["pdf_url"] for e in entries} == {
        "https://hkscout-tko.org/notice/?nid=206",
        "https://hkscout-tko.org/notice/2026/prog_206.pdf",
    }
    # captured_date 一個字都唔准改
    assert {e["captured_date"] for e in entries} == {"2026-09-19", "2026-06-30"}


def test_同名通告_唔同年份_兩筆都留():
    """2026 同 2027 各有一個「消防訓練班」：來源一樣、名一樣、只有 PDF 唔同。

    標題唔係身份 —— 兩則都要當新通告照收。就算連 PDF 名都一樣，只要
    (source_site, pdf_url) 唔同，就係兩筆登記，兩筆都留。
    """
    y2026 = row("https://hkscout-tko.org/notice/2026/prog_100.pdf", "2026-03-01",
                title="消防訓練班 (截止: 2026-03-01)")
    y2027 = row("https://hkscout-tko.org/notice/2027/prog_200.pdf", "2027-03-01",
                title="消防訓練班 (截止: 2027-03-01)")
    entries = core.build_grouped_cache([y2026, y2027], SOURCES, "2027-03-01")["data"]["將軍澳區"]
    assert len(entries) == 2, entries


def test_同一標題跨來源_幾個地方登記嘅通告_全部保留():
    """內容一樣但喺唔同地方（區／地域／總會）登記 = 幾筆唔同嘅登記，一筆都唔會動。

    呢個係核心原則：我哋收嘅係「邊個幾時喺邊度刊出」，唔係「內容去重」。
    """
    title = "09-2026 童軍支部 - 童軍消防(服務組)專章訓練班 (截止: 2026-09-30)"
    same_pdf = "https://www.scout.org.hk/article_attach/99999/PT20.pdf"
    scenario = [
        row(same_pdf, "2026-09-19", title=title, source="深旺區"),
        row(same_pdf, "2026-09-19", title=title, source="新界地域"),
        row(same_pdf, "2026-09-19", title=title, source="總會"),
        row("https://hkscout-tko.org/notice/?nid=207", "2026-06-30", title=title),
    ]
    out = core.build_grouped_cache(copy.deepcopy(scenario), SOURCES, "2026-09-19")
    cross = out["data"]["深旺區"] + out["data"]["新界地域"] + out["data"]["總會"]
    assert len(cross) == 3, cross
    assert {r["pdf_url"] for r in cross} == {same_pdf}
    assert len(out["data"]["將軍澳區"]) == 1


def test_來源隔離_同名同_PDF_但唔同來源_永遠唔會合併():
    """cache 唯一鍵係 (source_site, pdf_url)：來源唔同 = 兩筆，即使 URL 一樣。"""
    same_pdf = "https://www.scout.org.hk/article_attach/99999/PT20.pdf"
    a = row(same_pdf, "2026-09-19", title="同一份通告", source="深旺區")
    b = row(same_pdf, "2026-09-19", title="同一份通告", source="總會")
    out = core.build_grouped_cache([a, b], SOURCES, "2026-09-19")
    assert len(out["data"]["深旺區"]) == 1
    assert len(out["data"]["總會"]) == 1


def test_現有_cache_一筆都唔應該被動():
    """真 cache.json 4828 筆：build_grouped_cache 重跑一次，一筆都唔可以少。"""
    cache_path = BASE_DIR / "cache.json"
    if not cache_path.exists():
        return
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    records = cache.get("notices") or []
    rebuilt = core.build_grouped_cache(copy.deepcopy(records), SOURCES, cache.get("last_updated") or "")
    total_before = sum(len(v) for v in cache.get("data", {}).values() if isinstance(v, list))
    total_after = sum(len(v) for v in rebuilt.get("data", {}).values() if isinstance(v, list))
    assert total_after == total_before, (total_after, total_before)


# ─── 4. 空殼內頁 → extract_detail_assets 抽到真 PDF（DOM）────────────


@needs_bs4
def test_dom_空_body_加_meta_refresh_抽到真_pdf():
    soup = BeautifulSoup(EMPTY_SHELL_207, "html.parser")
    records = core.extract_detail_assets(soup, TKO_DETAIL_207, tko_cfg())
    assert [r["pdf_url"] for r in records] == [TKO_PDF_207], records
    # 標題由內頁 <title> 嚟（卡嘅標題喺 parse_notice_card_blocks 內會被保留）
    assert "親子長洲偵探之旅" in records[0]["title"]
    assert core.is_download_url(records[0]["pdf_url"]), "enrich.py 只食得落 .pdf／可下載網址"


@needs_bs4
def test_dom_冇_meta_refresh_嘅空殼_仍然係零附件():
    """釘住舊行為：呢個就係「抽唔到資料」嘅現場。"""
    html = EMPTY_SHELL_207.replace('content="0; url=' + TKO_PDF_207 + '"', 'content="0; url=/notice.php"')
    soup = BeautifulSoup(html, "html.parser")
    assert core.extract_detail_assets(soup, TKO_DETAIL_207, tko_cfg()) == []


@needs_bs4
def test_dom_meta_refresh_指向另一個_html_唔會當成附件():
    html = EMPTY_SHELL_207.replace(TKO_PDF_207, "https://hkscout-tko.org/notice.php")
    soup = BeautifulSoup(html, "html.parser")
    assert core.extract_detail_assets(soup, TKO_DETAIL_207, tko_cfg()) == []


@needs_bs4
def test_dom_meta_refresh_相對路徑同引號():
    html = EMPTY_SHELL_207.replace(
        'content="0; url=' + TKO_PDF_207 + '"',
        "content=\"0; url='/notice/2026/prog_207.pdf'\"",
    )
    soup = BeautifulSoup(html, "html.parser")
    records = core.extract_detail_assets(soup, TKO_DETAIL_207, tko_cfg())
    assert [r["pdf_url"] for r in records] == [TKO_PDF_207], records


@needs_bs4
def test_dom_iframe_唔會被_meta_refresh_冚走():
    """兩種寫法並存時兩個都要抽到（唔好因為新 code 而少咗附件）。"""
    html = EMPTY_SHELL_207.replace(
        "<body>\n</body>",
        f'<body><iframe src="{TKO_PDF_207}?from=iframe"></iframe></body>',
    )
    soup = BeautifulSoup(html, "html.parser")
    urls = [r["pdf_url"] for r in core.extract_detail_assets(soup, TKO_DETAIL_207, tko_cfg())]
    assert urls == [f"{TKO_PDF_207}?from=iframe", TKO_PDF_207], urls


# ─── 5. 成條鏈：列表卡 → 內頁 meta refresh → 真 PDF（DOM）────────────


@needs_bs4
def test_dom_fetch_detail_page_唔會再當空殼係_冇嘢(monkeypatch):
    """fetch_detail_page 嘅關卡係 extract_detail_assets 有冇結果 —— 呢度係舊 bug 嘅門口。"""
    monkeypatch.setattr(
        core, "fetch_requests",
        lambda url, config, timeout=20: fetch_result(EMPTY_SHELL_207, TKO_DETAIL_207),
    )
    result = core.fetch_detail_page("將軍澳區", TKO_DETAIL_207, tko_cfg())
    assert result is not None
    assert TKO_PDF_207 in result.html


@needs_bs4
def test_dom_通告卡跟內頁_meta_refresh_升級做真_pdf(monkeypatch):
    """現場情況：區會內頁用 meta refresh 跳去 prog_<nid>.pdf。

    卡嘅標題要保留（列表標題先有編號／分類／截止日），URL 就要變真 PDF。
    """
    if not TKO_LISTING_FIXTURE:
        return  # 借唔到 fixture（例如單獨散佈）就略過

    def fake_fetch(url, config, timeout=20):
        nid = url.rsplit("nid=", 1)[-1]
        html = EMPTY_SHELL_207.replace(
            TKO_PDF_207, f"https://hkscout-tko.org/notice/2026/prog_{nid}.pdf"
        )
        return fetch_result(html, url)

    monkeypatch.setattr(core, "fetch_requests", fake_fetch)
    monkeypatch.setattr(core.time, "sleep", lambda *_a, **_k: None)

    records = core.parse_notice_card_blocks(
        "將軍澳區", tko_soup(TKO_LISTING_FIXTURE), TKO_PAGE_URL,
        tko_cfg(notice_detail_max_pages=5),
    )
    by_nid = {r["title"].split(" ", 1)[0]: r for r in records}
    assert by_nid["09-2026"]["pdf_url"] == "https://hkscout-tko.org/notice/2026/prog_211.pdf"
    assert by_nid["06-2026"]["pdf_url"] == "https://hkscout-tko.org/notice/2026/prog_206.pdf"
    # 標題唔應該被內頁標題蓋走
    assert by_nid["09-2026"]["title"].endswith("(截止: 2026-09-30)")
    assert all(core.is_download_url(r["pdf_url"]) for r in records), records


@needs_bs4
def test_dom_連唔上內頁時_照樣出內頁_URL_記錄(monkeypatch):
    """跟唔到內頁唔會消失：卡照出（內頁 URL），等下次再試，兩筆都留。"""
    if not TKO_LISTING_FIXTURE:
        return
    monkeypatch.setattr(core, "fetch_detail_page", lambda name, url, config: None)
    monkeypatch.setattr(core.time, "sleep", lambda *_a, **_k: None)
    records = core.parse_notice_card_blocks(
        "將軍澳區", tko_soup(TKO_LISTING_FIXTURE), TKO_PAGE_URL,
        tko_cfg(notice_detail_max_pages=5),
    )
    assert len(records) == 4, records
    assert all("?nid=" in r["pdf_url"] for r in records), records


# ─── 6. enrich.py 嘅守門條件（呢個係「enrich.json 完全冇變」嘅第 2 個原因）──


def test_升級後嘅_url_過得到_enrich_嘅_pdf_守門():
    """enrich.py collect_targets 只收 .pdf（或 Google Drive）；placeholder 一定被略過。"""
    assert TKO_PDF_207.lower().endswith(".pdf")
    assert not TKO_DETAIL_207.lower().endswith(".pdf")


# ─── 主測試執行器（支援直接 python test_meta_refresh_detail.py 運行）────────


def main() -> int:
    all_tests = [
        (name, fn)
        for name, fn in globals().items()
        if name.startswith("test_") and callable(fn)
    ]
    dom_tests = [t for t in all_tests if getattr(t[1], "_needs_bs4", False)]
    pure_tests = [t for t in all_tests if t not in dom_tests]

    passed = failed = skipped = 0
    print("=" * 66)
    print(f"🧪 v5.6.24 內頁 meta refresh 回歸測試集（共 {len(all_tests)} 個測試）")
    print("=" * 66)

    def run(name, fn):
        nonlocal passed, failed
        mp = SimpleMonkeyPatch() if SimpleMonkeyPatch else None
        try:
            if mp is not None and "monkeypatch" in inspect.signature(fn).parameters:
                fn(mp)
            else:
                fn()
            print(f"  ✅ {name}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ {name}: {e}")
            failed += 1
        finally:
            if mp is not None:
                mp.undo()

    for name, fn in pure_tests:
        run(name, fn)

    if BeautifulSoup is None:
        print(f"\n  ⚠️  當前環境缺少 BeautifulSoup (bs4)，略過 {len(dom_tests)} 項 DOM 測試。")
        print("     提示：喺有 bs4 嘅環境（本機 run-local-scrape.bat 嘅 Python）可跑：")
        print("         python test_meta_refresh_detail.py")
        skipped = len(dom_tests)
    else:
        for name, fn in dom_tests:
            run(name, fn)

    print("=" * 66)
    print(f"測試結果：通過 {passed} 項 / 失敗 {failed} 項 / 略過 {skipped} 項")
    if failed:
        return 1
    print("🎉 通過！")
    return 0


if __name__ == "__main__":
    sys.exit(main())

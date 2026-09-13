#!/usr/bin/env python3
"""回歸測試：屯門東區標題唔可以誤配到隔壁通告。

2026-09-13 事故：
  今日新通告 TME_A_26_03.pdf 實際係
    「2027年功績獎勵及感謝狀提名 - 區會提名截止日期」通告
  但 cache 標題被寫成「深資童軍消防訓練班」通告
  （嗰個先至係 TME_V_26_02.pdf）。

根因：
  1. clean_title() 用 substring 濾「截止日期」，真標題被整句丟棄
  2. infer_listing_title() 落到 page-level title_selector，偷咗下一列嘅標題

執行：python test_tme_title_mismatch.py
"""
from __future__ import annotations

import json
import sys

import core
from bs4 import BeautifulSoup

FAILED: list[str] = []

TME_CFG = json.load(open("sources.json", encoding="utf-8"))["sources"]["屯門東區"]

MERIT_TITLE = "「2027年功績獎勵及感謝狀提名 - 區會提名截止日期」通告"
FIRE_TITLE = "「深資童軍消防訓練班」通告"
MERIT_URL = "https://www.tmescout.org.hk/file/notice/TME_A_26_03.pdf"
FIRE_URL = "https://www.tmescout.org.hk/file/notice/TME_V_26_02.pdf"
SCOUT_FIRE_URL = "https://www.tmescout.org.hk/file/notice/TME_S_26_04.pdf"


def check(cond: bool, msg: str) -> None:
    print(f"{'✅' if cond else '❌'} {msg}")
    if not cond:
        FAILED.append(msg)


TME_HTML = f"""<html><head><meta charset="big5"></head><body>
<h2>教學資源平台</h2>
<table>
<tr><th>支部</th><th>教材名稱</th><th>適用對象</th><th>下載</th></tr>
<tr>
  <td>幼童軍</td>
  <td>TME_幼童軍會員章考核紀錄冊</td>
  <td>本區幼童軍支部成員及領袖</td>
  <td><a href="notice/TME_會員章考核紀錄冊.pdf">(pdf格式)</a></td>
</tr>
</table>
<h2>通告</h2>
<table>
<tr><th>日期</th><th>通告名稱</th><th>單位/支部</th><th>下載</th></tr>
<tr>
  <td>2026年9月14日</td>
  <td>{MERIT_TITLE}</td>
  <td></td>
  <td><a href="notice/TME_A_26_03.pdf">(pdf格式)</a></td>
</tr>
<tr>
  <td>2026年9月1日</td>
  <td>{FIRE_TITLE}</td>
  <td>已完成深資童軍肩章之深資童軍成員</td>
  <td><a href="notice/TME_V_26_02.pdf">(pdf格式)</a></td>
</tr>
<tr>
  <td>2026年9月1日</td>
  <td>「童軍消防訓練班」通告</td>
  <td>年滿12歲及已宣誓並持有效童軍成員編號之童軍支部成員</td>
  <td><a href="notice/TME_S_26_04.pdf">(pdf格式)</a></td>
</tr>
<tr>
  <td>2025年9月1日</td>
  <td>「2026年功績獎勵及感謝狀提名--區會提名截止日期」通告</td>
  <td>本區各旅旅長</td>
  <td><a href="notice/TME_A_25_08.pdf">(pdf格式)</a></td>
</tr>
</table>
</body></html>
"""


def test_clean_title_keeps_deadline_in_name():
    print("── 1. clean_title 唔可以因為提到截止日期就丟棄 ──")
    got = core.clean_title(MERIT_TITLE, TME_CFG)
    check(got == MERIT_TITLE, f"功績獎勵標題保留（實際 {got!r}）")
    last_year = "「2026年功績獎勵及感謝狀提名--區會提名截止日期」通告"
    got2 = core.clean_title(last_year, TME_CFG)
    check(got2 == last_year, f"舊年同類標題保留（實際 {got2!r}）")
    check(core.clean_title("截止日期", TME_CFG) is None, "純欄位標題「截止日期」仍然丟棄")
    check(core.clean_title("通告日期", TME_CFG) is None, "純欄位標題「通告日期」仍然丟棄")
    check(core.clean_title("活動/訓練班名稱", TME_CFG) is None, "純欄位標題「活動/訓練班名稱」仍然丟棄")
    check(core.clean_title(FIRE_TITLE, TME_CFG) == FIRE_TITLE, "消防訓練班標題不受影響")


def test_extract_does_not_swap_pdfs():
    print("\n── 2. 列表抽取：每條 PDF 配自己嗰行嘅標題 ──")
    soup = BeautifulSoup(TME_HTML, "html.parser")
    assets = core.extract_assets_from_listing(
        name="屯門東區",
        soup=soup,
        page_url="https://www.tmescout.org.hk/file/memo.htm",
        config=TME_CFG,
        max_detail_pages=0,
    )
    by_url = {a["pdf_url"]: a["title"] for a in assets}
    for a in assets:
        print(f"   {a['title'][:40]} | {a['pdf_url'].rsplit('/', 1)[-1]}")

    check(by_url.get(MERIT_URL) == MERIT_TITLE,
          f"TME_A_26_03 應為功績獎勵（實際 {by_url.get(MERIT_URL)!r}）")
    check(by_url.get(FIRE_URL) == FIRE_TITLE,
          f"TME_V_26_02 應為深資消防（實際 {by_url.get(FIRE_URL)!r}）")
    check(by_url.get(SCOUT_FIRE_URL) == "「童軍消防訓練班」通告",
          "TME_S_26_04 應為童軍消防")
    last_year_url = "https://www.tmescout.org.hk/file/notice/TME_A_25_08.pdf"
    check(by_url.get(last_year_url) == "「2026年功績獎勵及感謝狀提名--區會提名截止日期」通告",
          f"TME_A_25_08 唔可以再變成「本區各旅旅長」（實際 {by_url.get(last_year_url)!r}）")
    check(by_url.get(MERIT_URL) != FIRE_TITLE, "新通告唔可以偷消防訓練班標題")


def test_infer_stays_in_row():
    print("\n── 3. infer_listing_title 只可以用本列文字 ──")
    soup = BeautifulSoup(TME_HTML, "html.parser")
    merit_a = soup.select_one('a[href$="TME_A_26_03.pdf"]')
    fire_a = soup.select_one('a[href$="TME_V_26_02.pdf"]')
    merit_title = core.infer_listing_title(merit_a, soup, TME_CFG)
    fire_title = core.infer_listing_title(fire_a, soup, TME_CFG)
    check(merit_title == MERIT_TITLE, f"本列推斷功績獎勵（實際 {merit_title!r}）")
    check(fire_title == FIRE_TITLE, f"本列推斷消防訓練班（實際 {fire_title!r}）")
    check(merit_title != fire_title, "兩條通告標題必須唔同")


def main() -> int:
    test_clean_title_keeps_deadline_in_name()
    test_extract_does_not_swap_pdfs()
    test_infer_stays_in_row()
    print()
    if FAILED:
        print(f"❌ {len(FAILED)} 項失敗")
        return 1
    print("🎉 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())

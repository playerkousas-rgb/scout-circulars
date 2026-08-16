#!/usr/bin/env python3
"""
回歸測試：港島西區 / 慈雲山區（group.scout.org.hk）
====================================================
背景：呢兩個來源原本用 WP REST API (`/wp-json`) 抓取，但站方由 2026-08-12 起
針對性封鎖 wp-json（同網域嘅深旺區普通 HTML 一直正常，可作對照），
令 core.py 每日把兩者標成 error。v5.6.21 改為直接抓普通 HTML 頁。

本測試用「依實測 DOM 重建」嘅假頁面驗證設定，唔會連外網。

執行：  python test_group_scout_sources.py
"""
import json
import types
import sys

import core
from bs4 import BeautifulSoup

SOURCES = json.load(open("sources.json", encoding="utf-8"))["sources"]

# ── 依實測重建：https://group.scout.org.hk/hkw/circular/ 年度索引頁 ──
HKW_INDEX = """<html><body><table><tbody>
<tr><td><a href="https://group.scout.org.hk/hkw/circular2026/">2026年</a></td></tr>
<tr><td><a href="https://group.scout.org.hk/hkw/circular2025/">2025年</a></td></tr>
<tr><td><a href="https://group.scout.org.hk/hkw/circular/circular2023/">2023年</a></td></tr>
</tbody></table></body></html>"""


def _hkw_year(year: str) -> str:
    return f"""<html><body><table>
<thead><tr><th>日期</th><th>通告名稱</th></tr></thead><tbody>
<tr><td>{year}年7月10日</td><td><a href="https://group.scout.org.hk/hkw/wp-content/uploads/{year}/07/HKW{year}VCIR005.pdf">游泳測試</a></td></tr>
<tr><td>{year}年5月15日</td><td><a href="https://group.scout.org.hk/hkw/wp-content/uploads/{year}/06/HKW{year}SCIR004.pdf">童軍專章考驗日—手藝章(技能組)及體育章(技能組)</a></td></tr>
<tr><td>{year}年1月20日</td><td><a href="https://group.scout.org.hk/hkw/wp-content/uploads/{year}/01/HKW{year}SCIR001.pdf">第583屆童軍領導才訓練班</a></td></tr>
</tbody></table></body></html>"""


# ── 依實測重建：https://group.scout.org.hk/tws/ 主頁（WP 標準：每篇 post 一個 <article>）──
_TWS_BASE = "https://group.scout.org.hk/tws/wp-content/uploads/"


def _tws_post(title: str, pdf: str, with_heading: bool = True) -> str:
    heading = f'<h2 class="entry-title">{title}</h2>' if with_heading else ""
    return (
        f'<article class="post"><header>{heading}</header>'
        f'<div class="entry-content"><div class="wp-block-file">'
        f'<a href="{pdf}">{title}</a>'
        f'<a href="{pdf}" class="wp-block-file__button">Download</a></div>'
        f"<p>詳情如下：日期 2026 年 7 月 12 日，地點慈雲山聖文德天主教小學，費用全免。</p>"
        f"</div></article>"
    )


TWS_P1 = (
    '<html><body><main class="site-main">'
    + _tws_post("第 50 屆慈雲山區區務委員會就職典禮 暨 中國文化", _TWS_BASE + "2026/06/TWS-5292-26-abc.pdf")
    + _tws_post("更新區會網址及聯絡電郵通告", _TWS_BASE + "2026/05/TWS-585-26-xyz.pdf")
    + _tws_post("慈雲山區 65 周年紀念 – 禾田喜山親子日營", _TWS_BASE + "2026/05/PT1006_26.pdf")
    + "</main></body></html>"
)
# PT996 呢篇實際上冇獨立標題，連結文字得個編號 —— 最易令標題被鄰近內文/隔離篇污染
TWS_P2 = (
    '<html><body><main class="site-main">'
    + _tws_post("小童軍親子競技比賽（小童軍支部）", _TWS_BASE + "2026/05/PT1001_2026.pdf")
    + _tws_post("PT996", _TWS_BASE + "2026/03/PT996.pdf", with_heading=False)
    + "</main></body></html>"
)

PAGES = {
    "https://group.scout.org.hk/hkw/circular/": HKW_INDEX,
    "https://group.scout.org.hk/hkw/circular2026/": _hkw_year("2026"),
    "https://group.scout.org.hk/hkw/circular2025/": _hkw_year("2025"),
    "https://group.scout.org.hk/hkw/circular/circular2023/": _hkw_year("2023"),
    "https://group.scout.org.hk/tws/": TWS_P1,
    "https://group.scout.org.hk/tws/page/2/": TWS_P2,
}


def _install_fakes():
    def fake_fetch(url, config, timeout=20):
        html = PAGES.get(url)
        if html is None:
            raise AssertionError(f"未預期嘅 URL（設定可能寫錯）: {url}")
        return core.FetchResult(url=url, html=html, engine="requests", status_code=200)

    def no_pw(*a, **k):
        raise AssertionError("唔應該用到 Playwright：呢兩個來源係純 server-render HTML")

    core.fetch_requests = fake_fetch
    core.fetch_with_playwright = no_pw
    core.time = types.SimpleNamespace(sleep=lambda *_: None)


def collect(name: str):
    """行足 core.py process_source 嘅抓取 + 分頁流程。"""
    cfg = SOURCES[name]
    result = core.fetch_main_page(name, cfg)
    assert result is not None, f"{name}: fetch_main_page 回傳 None"
    soup = BeautifulSoup(result.html, "html.parser")
    assets = core.extract_assets_from_listing(
        name=name, soup=soup, page_url=result.url, config=cfg, max_detail_pages=0
    )
    if cfg.get("follow_listing_pages"):
        pages = core.discover_listing_pages(soup, result.url, cfg)
        limit = int(cfg.get("listing_max_pages") or len(pages) or 0)
        seen = {a["pdf_url"] for a in assets}
        for url in pages[:limit]:
            sub = core.fetch_page(url, cfg)
            sub_soup = BeautifulSoup(sub.html, "html.parser")
            for rec in core.extract_assets_from_listing(
                name=name, soup=sub_soup, page_url=sub.url, config=cfg, max_detail_pages=0
            ):
                if rec["pdf_url"] not in seen:
                    seen.add(rec["pdf_url"])
                    assets.append(rec)
    # 指紋要計得出，否則每日都會當「有變動」重抓
    fp = core.compute_fingerprint(soup, cfg.get("fingerprint_selector", "body"))
    assert fp, f"{name}: 計唔到指紋（fingerprint_selector 無 match）"
    return assets


def main() -> int:
    _install_fakes()
    failures = []

    for name in ("港島西區", "慈雲山區"):
        cfg = SOURCES[name]
        print("=" * 66)
        print(f"### {name}")

        # 唔應該再用 wordpress_api（wp-json 被站方封鎖）
        if cfg.get("type") == "wordpress_api":
            failures.append(f"{name}: 仍然係 wordpress_api，但該站 /wp-json 被封鎖")
        # fallback_urls 對呢兩個嚟講係無用設定（WP API 已唔再係主路徑）
        if cfg.get("fallback_urls"):
            failures.append(f"{name}: 仲留住無用嘅 fallback_urls")

        assets = collect(name)
        print(f"  抽到 {len(assets)} 個資產")
        for a in assets:
            print(f"     - {a['title']}  |  {a['pdf_url'].split('/')[-1]}")

        if not assets:
            failures.append(f"{name}: 抽唔到任何資產")
        if not all(a["pdf_url"].lower().endswith(".pdf") for a in assets):
            failures.append(f"{name}: 有非 PDF 連結混入")
        # 標題唔可以係 "下載"/"Download" 之類
        for a in assets:
            if core.is_generic_download_title(a["title"]):
                failures.append(f"{name}: 標題係通用下載字樣 -> {a['title']}")
        # 標題唔可以夾雜內文（曾出現：整段「詳情如下…」被當標題）
        for a in assets:
            if any(bad in a["title"] for bad in ("詳情如下", "報名方法", "截止日期", "費用全免")):
                failures.append(f"{name}: 標題夾雜內文 -> {a['title']}")
        # 每個 PDF 唯一
        urls = [a["pdf_url"] for a in assets]
        if len(urls) != len(set(urls)):
            failures.append(f"{name}: 有重複 PDF URL")

    # 針對性檢查
    hkw = collect("港島西區")
    if not any("HKW2026" in a["pdf_url"] for a in hkw):
        failures.append("港島西區: 攞唔到 2026 年度通告")
    if not any("HKW2025" in a["pdf_url"] for a in hkw):
        failures.append("港島西區: 年度索引頁冇跟入舊年度（follow_listing_pages 失效）")

    tws = collect("慈雲山區")
    if not any("PT1001" in a["pdf_url"] for a in tws):
        failures.append("慈雲山區: 攞唔到第 2 頁通告（分頁失效）")
    # PT996 篇冇獨立標題，唔可以錯抄隔離篇 post 嘅標題
    pt996 = [a for a in tws if "PT996" in a["pdf_url"]]
    if pt996 and "小童軍親子競技" in pt996[0]["title"]:
        failures.append(f"慈雲山區: PT996 錯抄咗隔離篇標題 -> {pt996[0]['title']}")

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

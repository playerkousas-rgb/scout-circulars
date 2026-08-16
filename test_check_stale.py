#!/usr/bin/env python3
"""
test_check_stale.py — 驗證靜默失敗偵測邏輯
執行：python test_check_stale.py
"""
from __future__ import annotations
import datetime, sys
from check_stale import analyse

TODAY = datetime.date(2026, 8, 16)
fails: list[str] = []


def chk(cond, msg):
    if not cond:
        fails.append(msg)


def mk(sources, expected_empty=None, errors=None):
    return {"data": sources,
            "_meta": {"expected_empty_sources": expected_empty or [],
                      "last_run": {"error_sources": errors or []}}}


def item(title, url, date):
    return {"title": title, "pdf_url": url, "captured_date": date}


# ── 1. 主準則：90 日門檻 ──
rep = analyse(mk({
    "久無更新區": [item("通告A", "https://x/a.pdf", "2026-03-01")],   # 168 日
    "剛更新區":  [item("通告B", "https://x/b.pdf", "2026-08-10")],   # 6 日
}), 90, TODAY)
stale = {r["source"] for r in rep["stale"]}
chk("久無更新區" in stale, "90日門檻：應 flag 久無更新嘅來源")
chk("剛更新區" not in stale, "90日門檻：唔應 flag 啱啱更新嘅來源")

# ── 2. 重點：數量多寡唔應該影響判斷 ──
rep = analyse(mk({
    "得1張但啱更新": [item("通告", "https://x/a.pdf", "2026-08-15")],
    "有500張但停咗": [item(f"通告{i}", f"https://x/{i}.pdf", "2026-01-01")
                  for i in range(500)],
}), 90, TODAY)
stale = {r["source"] for r in rep["stale"]}
chk("得1張但啱更新" not in stale, "數量少但正常更新 → 唔應 flag（舊『<5筆』規則會誤報）")
chk("有500張但停咗" in stale, "數量多但停止更新 → 應 flag（舊『<5筆』規則永遠捉唔到）")

# ── 3. 站方清舊通告：剩返幾張但持續有新 → 唔應 flag ──
rep = analyse(mk({
    "定期清舊區": [item("最新通告", "https://x/new.pdf", "2026-08-12"),
                item("次新通告", "https://x/n2.pdf", "2026-07-20")],
}), 90, TODAY)
chk(not rep["stale"], "站方定期清舊通告（剩2張但持續更新）→ 唔應 flag")
chk(not rep["suspicious"], "同上：標題正常就唔應標可疑")

# ── 4. 輔助準則：抓到垃圾（90日門檻嘅盲點）──
rep = analyse(mk({
    "抓到分類目錄": [item("1 支部通告-童軍", "https://x/p.html#1-支部通告", "2026-08-07"),
                 item("1 支部通告-幼童軍", "https://x/p.html#1-支部通告", "2026-08-07")],
    "抓到view雜項": [item("view", "https://drive.google.com/file/d/A/view", "2026-08-03"),
                 item("view", "https://drive.google.com/file/d/B/view", "2026-08-03")],
}), 90, TODAY)
sus = {r["source"] for r in rep["suspicious"]}
chk("抓到分類目錄" in sus, "應捉到『分類目錄當通告』（觀塘區當日情況）")
chk("抓到view雜項" in sus, "應捉到『view』雜項標題（深水埗西區當日情況）")
chk(not rep["stale"], "呢兩個 captured_date 好新，唔應歸類為過期")

# ── 5. 誤報防護：錨點式通告係正常設計 ──
rep = analyse(mk({
    "錨點通告區": [item("06-2026 行政通告 - 第25屆區務委員會就職典禮",
                    "https://hkscout-tko.org/notice.php#行政通告-06-2026", "2026-07-01"),
                item("12-2024 特別通告 - 未來童夢熱血狂歡2025",
                    "https://hkscout-tko.org/notice.php#特別通告-12-2024", "2026-06-20")],
}), 90, TODAY)
chk(not rep["suspicious"],
    "將軍澳區式錨點通告（標題有真內容）唔應誤報 —— URL 有 # 唔代表壞")

# ── 6. expected_empty 要跳過 ──
rep = analyse(mk({"西貢區": []}, expected_empty=["西貢區"]), 90, TODAY)
chk(not rep["empty"] and not rep["stale"], "expected_empty 來源應完全跳過")

# ── 7. 完全冇資料要分開報 ──
rep = analyse(mk({"空空區": []}), 90, TODAY)
chk([r["source"] for r in rep["empty"]] == ["空空區"], "冇資料來源應歸類 empty")

# ── 8. 新鮮度六欄：互斥且窮盡 ──
rep = analyse(mk({
    "今日更新": [item("通告", "https://x/a.pdf", "2026-08-16")],
    "五日前":   [item("通告", "https://x/b.pdf", "2026-08-11")],
    "十日前":   [item("通告", "https://x/c.pdf", "2026-08-06")],
    "廿五日前": [item("通告", "https://x/d.pdf", "2026-07-22")],
    "六十日前": [item("通告", "https://x/e.pdf", "2026-06-17")],
    "半年前":   [item("通告", "https://x/f.pdf", "2026-02-16")],
}), 90, TODAY)
fresh = rep["freshness"]
chk(sum(fresh.values()) == rep["total_sources"] == 6,
    f"六欄總和必須等於來源總數（實際 {sum(fresh.values())} vs {rep['total_sources']}）")
chk(fresh["今天"] == 1 and fresh["7 天內"] == 1 and fresh["14 天內"] == 1
    and fresh["1 個月內"] == 1 and fresh["3 個月內"] == 1 and fresh["超過 3 個月"] == 1,
    f"六欄分配唔正確：{fresh}")

print("═" * 60)
if fails:
    print(f"❌ {len(fails)} 項失敗：")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("🎉 全部通過（8 組情境）")

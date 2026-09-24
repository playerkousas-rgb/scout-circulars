#!/usr/bin/env python3
"""AI 底圖 × 真通告內容 —— 出圖試範（layout 參數同用戶腳本一致）。

底圖：story-bases/<款>.webp（9 張 AI 無字底圖，1080×1920）
內容：cache.json + enrich.json 嘅真通告（title／截止／地點／費用／對象）
圖層：分類 pill（左上）→ 真區徽（右上）→ 標題（TITLE_AREAS 座標）→ 資料一條 → 來源＋credit

自動處理（避免字撞花紋）：
  標題區平均亮度 >135 → 深字；<90 → 白字；中間調 → 字後面加柔邊底板

用法：
  python3 tools/render_story_bases_demo.py [--out DIR] [--stub]
需要：pip install pillow；中文字體（STORY_FONT 或 ~/.cache/fonts/NotoSansTC_900Black.ttf）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
ROOT = Path(__file__).resolve().parent.parent
BASES = ROOT / "story-bases"

FONT_CANDIDATES = [
    os.environ.get("STORY_FONT", ""),
    str(Path.home() / ".cache/fonts/NotoSansTC_900Black.ttf"),
    str(Path.home() / ".cache/fonts/NotoSansTC_700Bold.ttf"),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansHK-Bold.otf",
    "C:/Windows/Fonts/msjhbd.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]
_FONT: str | None = None


def load_font(size: int, bold: bool = True):
    global _FONT
    if _FONT is None:
        for p in FONT_CANDIDATES:
            if p and Path(p).exists():
                try:
                    ImageFont.truetype(p, 12)
                    _FONT = p
                    break
                except OSError:
                    continue
        if _FONT is None:
            raise SystemExit("❌ 搵唔到中文字體。export STORY_FONT=/path/to/CJK-Bold.ttf")
    return ImageFont.truetype(_FONT, size)


# ── 用戶腳本嘅 layout 參數（原封不動） ─────────────────────────────
TITLE_AREAS = {
    "train_blue": (60, 420, 1020, 1180, "left", "#111111", 78),
    "train_orange": (60, 400, 1020, 1100, "left", "#111111", 78),
    "train_green": (80, 380, 1000, 980, "left", "#FFFFFF", 72),
    "activity_army": (60, 820, 1020, 1180, "left", "#FFFFFF", 66),
    "service_wanted": (140, 400, 940, 820, "center", "#3D1E00", 58),
    "competition_gold_black": (60, 420, 1020, 1000, "center", "#FFFFFF", 74),
    "unc_scope": (60, 380, 1020, 900, "center", "#FFFFFF", 70),
    "unc_topsecret": (80, 520, 1000, 920, "left", "#111111", 60),
    "unc_glitch": (60, 400, 1020, 900, "center", "#FFFFFF", 70),
}
PILL_COLORS = {
    "train_blue": "#0066FF", "train_orange": "#FF5E00", "train_green": "#00C950",
    "competition_gold_black": "#FFD60A", "activity_army": "#A6FF00", "service_wanted": "#3D1E00",
    "unc_scope": "#FF1E1E", "unc_topsecret": "#8B0000", "unc_glitch": "#00FFF0",
}
DARK_PILL_FG = {"competition_gold_black", "activity_army", "unc_glitch"}
CATEGORY_TO_POOL = {
    "training": ["train_blue", "train_orange", "train_green"],
    "competition": ["competition_gold_black"],
    "activity": ["activity_army"],
    "service": ["service_wanted"],
    "other": ["unc_scope", "unc_topsecret", "unc_glitch"],
}
CATEGORY_LABEL = {"training": "訓練", "competition": "比賽", "activity": "活動",
                  "service": "服務", "other": "通告"}
DEFAULT_STUBS = [
    ({"title": "童軍射擊精英比賽2026 — 全港公開組", "category": "competition",
      "deadline": "2026-11-15", "region": "香港童軍中心", "fee": "$80",
      "url": "https://scout.org.hk/comp", "audience": "16-24歲", "source_site": "總會"}),
    ({"title": "童軍領袖野外求生及領導才能訓練班（深資支部）", "category": "training",
      "deadline": "2026-10-30", "region": "大棠渡假村", "url": "https://scout.org.hk/1",
      "audience": "深資童軍", "source_site": "新界地域"}),
    ({"title": "全港童軍大露營暨武林大會2026 — 技能大比拼", "category": "activity",
      "region": "大棠渡假村", "url": "https://scout.org.hk/wulin", "source_site": "港島地域"}),
    ({"title": "九龍地域週年獎勵頒獎典禮暨晚宴", "category": "activity",
      "region": "九龍塘", "url": "https://scout.org.hk/award", "audience": "各級領袖",
      "source_site": "九龍地域"}),
    ({"title": "2026社區服務義工招募 — 為榮譽而服務", "category": "service", "fee": "免費",
      "region": "全港各區", "url": "https://scout.org.hk/service", "source_site": "筲箕灣區"}),
]


def safe_get(item, keys):
    for k in keys:
        v = item.get(k)
        if v and str(v).strip() and str(v).strip() not in ["-", "待定", "無", "/", "N/A", "null"]:
            return str(v).strip()
    return None


def pick_template(cat_raw, url):
    cat = cat_raw if cat_raw in CATEGORY_TO_POOL else "other"
    pool = CATEGORY_TO_POOL[cat]
    h = int(hashlib.md5(url.encode()).hexdigest(), 16)
    return cat, pool[h % len(pool)]


def wrap_cjk(draw, text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        test = cur + ch
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def load_base(tmpl):
    """底圖：WebP 優先（repo 細），PNG／JPG 都食。"""
    for ext in (".webp", ".png", ".jpg"):
        p = BASES / f"{tmpl}{ext}"
        if p.exists():
            return Image.open(p).convert("RGB").resize((W, H), Image.LANCZOS)
    return None


def zone_stats(img, area):
    """標題區 (平均亮度, 標準差)。標準差大＝底圖好多花紋，字一定要有底板墊住。"""
    from PIL import ImageStat
    x0, y0, x1, y1 = area[:4]
    strip = img.crop((x0, y0, x1, y1)).convert("L").resize((48, 48))
    st = ImageStat.Stat(strip)
    return st.mean[0], st.stddev[0]


def soft_plate(img, area, dark_plate, feather=56, alpha=214):
    """花紋底：字後面加半透明柔邊底板（唔會洗白底圖，仍然見到質感）。"""
    x0, y0, x1, y1 = area[:4]
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([x0 + 26, y0 + 26, x1 - 26, y1 - 26], radius=40, fill=alpha)
    m = m.filter(ImageFilter.GaussianBlur(feather))
    layer = Image.new("RGB", img.size, (10, 12, 16) if dark_plate else (252, 252, 250))
    return Image.composite(layer, img, m)


def draw_title(draw, text, area, color, tmpl=""):
    """標題。字級同 app（posterFitTitle）一致：96→84→72→64→56→48，
    行高 1.3×，最多 4 行（同 app 一樣，唔會忽然變 5 行）。"""
    x0, y0, x1, y1, align, _cfg, _base = area
    max_w = x1 - x0
    text = text.replace("\n", " ").strip()
    max_h = y1 - y0
    fallback = None
    for size in (96, 84, 72, 64, 56, 48):
        font = load_font(size, True)
        lines = wrap_cjk(draw, text, font, max_w)
        lh = round(size * 1.3)
        block = dict(size=size, lines=lines, lh=lh, height=(len(lines) - 1) * lh + size)
        if block["height"] <= max_h and not lines[-1].endswith("…") and len(lines) <= 4:
            fallback = block
            break
        fallback = fallback or block
    font = load_font(fallback["size"], True)
    lines, lh = fallback["lines"], fallback["lh"]
    total_h = fallback["height"]
    y = y0 + (max_h - total_h) // 2
    for line in lines:
        if line != lines[-1] and y + lh > y1:
            break
        wtxt = draw.textbbox((0, 0), line, font=font)[2]
        x = x0 + (max_w - wtxt) // 2 if align == "center" else x0
        if tmpl in ("service_wanted", "unc_topsecret"):
            stroke = "#F2E4C8" if tmpl == "service_wanted" else "#FFFFFF"
        else:
            stroke = "#FFFFFF" if color == "#111111" else "#000000"
        draw.text((x, y), line, font=font, fill=color, stroke_width=5, stroke_fill=stroke)
        y += lh


def draw_pill(draw, text, bg, fg, xy=(56, 68), size=30):
    """分類標籤。用 glyph 實際 bbox（唔係 (0,0) 起點）居中，
    否則中文字會有 bearing 令字貼邊／出界。"""
    font = load_font(size, True)
    bbox = draw.textbbox((0, 0), text, font=font)
    gw, gh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x = max(18, round(size * 0.62))
    pad_y = max(12, round(size * 0.42))
    w, h = gw + pad_x * 2, gh + pad_y * 2
    x, y = xy
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=bg)
    draw.text((x + pad_x - bbox[0], y + pad_y - bbox[1]), text, font=font, fill=fg)
    return w, h


# ── 真區徽（取代假 LOGO 虛線圈） ────────────────────────────────
_ORGS: dict | None = None
_BCACHE: dict = {}


def badge_for(item):
    global _ORGS
    if _ORGS is None:
        try:
            _ORGS = json.loads((ROOT / "icons/orgs/orgs.json").read_text(encoding="utf-8"))
        except Exception:
            _ORGS = {"orgs": {}}
    table = _ORGS.get("orgs") or {}
    ent = table.get(str(item.get("source_site") or "").strip())
    chain = []
    if ent and ent.get("icon256"):
        chain.append(ent["icon256"])
    if ent and ent.get("fallback") and table.get(ent["fallback"], {}).get("icon256"):
        chain.append(table[ent["fallback"]]["icon256"])
    if table.get("總會", {}).get("icon256"):
        chain.append(table["總會"]["icon256"])
    for icon in chain:
        if icon not in _BCACHE:
            try:
                raw = Image.open(ROOT / icon.replace(".avif", ".png")).convert("RGBA")
                raw.thumbnail((170, 170))
                _BCACHE[icon] = raw
            except OSError:
                _BCACHE[icon] = None
        if _BCACHE[icon] is not None:
            return _BCACHE[icon]
    return None


def paste_badge(img, badge, xy=(844, 68), size=176):
    """真區徽，唔加白框。只貼區／地域／總會 LOGO。"""
    if badge is None:
        return
    x, y = xy
    sc = min(size / badge.width, size / badge.height)
    bw, bh = max(1, round(badge.width * sc)), max(1, round(badge.height * sc))
    b2 = badge.resize((bw, bh), Image.LANCZOS)
    img.paste(b2, (x + (size - bw) // 2, y + (size - bh) // 2), b2)


def draw_footer(draw, item, tmpl):
    infos = []
    d = safe_get(item, ["deadline", "截止", "cutoff", "截止日期"])
    l = safe_get(item, ["location", "地點", "venue"]) or safe_get(item, ["region"])
    f = safe_get(item, ["fee", "費用", "cost"])
    t = safe_get(item, ["target", "對象"]) or safe_get(item, ["audience"])
    if d:
        infos.append(d[:14])
    if l:
        infos.append(l[:12])
    if f:
        infos.append(f[:10])
    if t:
        infos.append(t[:10])
    if infos:
        txt = " • ".join(infos[:3])
        if len(txt) > 36:
            txt = txt[:33] + "…"
        font = load_font(20, True)
        tw = draw.textbbox((0, 0), txt, font=font)[2]
        draw.rounded_rectangle([48, 1320, 48 + tw + 40, 1368], radius=20, fill=(255, 255, 255, 235))
        draw.text((68, 1328), txt, font=font, fill="#111111")
    url = safe_get(item, ["url", "來源網址", "source", "link"]) or ""
    if url and len(url) > 38:
        url = url[:35] + "..."
    col = "#CCCCCC" if tmpl in ["competition_gold_black", "activity_army", "unc_scope",
                                "unc_glitch", "train_green"] else "#666666"
    if url:
        draw.text((56, 1840), f"來源: {url}", font=load_font(14, False), fill=col)
    draw.text((56, 1864), "經 通告圖書館整理 @noscout.system", font=load_font(12, False), fill=col)


def load_items():
    """真通告優先：cache.json ＋ enrich.json join。冇就用 stub。"""
    try:
        cache = json.loads((ROOT / "cache.json").read_text(encoding="utf-8"))
        enrich = json.loads((ROOT / "enrich.json").read_text(encoding="utf-8"))
    except Exception:
        return [dict(x) for x in DEFAULT_STUBS]
    out = []
    for section, arr in (cache.get("data") or {}).items():
        if not isinstance(arr, list) or "Scout System" in section:
            continue
        for it in arr:
            if not isinstance(it, dict) or not it.get("title"):
                continue
            ex = enrich.get(it.get("pdf_url")) or enrich.get(it.get("url")) or {}
            cats = ex.get("categories") if isinstance(ex.get("categories"), list) else []
            cat = "other"
            for c in cats:
                if isinstance(c, dict) and c.get("id") in ("training", "service", "activity", "competition"):
                    cat = c["id"]
                    break
            out.append({
                "title": it.get("title"), "url": it.get("url") or it.get("pdf_url") or "",
                "source_site": it.get("source_site") or section, "region": it.get("region") or section,
                "date": str(it.get("date") or "")[:10], "category": cat,
                "deadline": str(ex.get("deadline") or "")[:10], "fee": ex.get("fee") or "",
                "audience": ex.get("audience") or "",
            })
    out.sort(key=lambda x: (x["date"] or "", x["title"]), reverse=True)
    picked, seen = [], set()
    for want in ["training", "competition", "activity", "service", "other"]:
        for it in out:
            if it["category"] == want and it["title"] not in seen:
                picked.append(it)
                seen.add(it["title"])
                break
    for it in out:
        if len(picked) >= 12:
            break
        if it["title"] not in seen:
            picked.append(it)
            seen.add(it["title"])
    return picked or [dict(x) for x in DEFAULT_STUBS]


def render_one(item, tmpl, out_path, force_color=None):
    img = load_base(tmpl)
    if img is None:
        img = Image.new("RGB", (W, H), "#111111")
    area = TITLE_AREAS.get(tmpl, (80, 400, 1000, 1000, "center", "#FFFFFF", 64))
    luma, sd = zone_stats(img, area)
    cfg_color = area[5]
    cfg_is_light = cfg_color.upper() in ("#FFFFFF", "#FFF", "#E8D8B0")
    if force_color:
        color = force_color
    elif luma > 150:
        color = "#FFFFFF" if (cfg_is_light and sd < 32) else ("#111111" if not cfg_is_light or True else "#111111")
        color = cfg_color if (not cfg_is_light and sd < 32) else "#111111"
    elif luma < 95:
        color = "#FFFFFF"
    else:
        color = "#111111" if luma > 122 else "#FFFFFF"
    # 底圖花紋勁（標準差大）→ 一定要底板；純色乾淨底就唔加（保留質感）
    if not force_color and sd >= 38:
        img = soft_plate(img, area, dark_plate=(color == "#FFFFFF"),
                         alpha=170 if luma > 150 else 214)
    draw = ImageDraw.Draw(img, "RGBA")
    draw_title(draw, item.get("title") or "未命名通告", area, color, tmpl)
    cat = item.get("category") if item.get("category") in CATEGORY_TO_POOL else "other"
    fg = "#000000" if tmpl in DARK_PILL_FG else ("#E8D8B0" if tmpl == "service_wanted" else "#FFFFFF")
    draw_pill(draw, CATEGORY_LABEL.get(cat, "通告"), PILL_COLORS.get(tmpl, "#333"), fg, xy=(60, 80), size=32)
    paste_badge(img, badge_for(item), xy=(844, 68))
    draw_footer(draw, item, tmpl)
    img.save(out_path, optimize=True)
    return luma, sd, color


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI 底圖 × 真通告：出圖試範")
    ap.add_argument("--out", default=str(BASES / "demo"))
    ap.add_argument("--stub", action="store_true", help="用示範資料（唔讀 cache.json）")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    items = [dict(x) for x in DEFAULT_STUBS] if args.stub else load_items()
    print(f"試範出圖：{len(items)} 條通告 × 9 款底圖（字色自動探測）")

    made = {}
    for tmpl in TITLE_AREAS:
        item = None
        for it in items:
            _c, t = pick_template(it.get("category") or "other", it.get("url") or it["title"])
            if t == tmpl:
                item = it
                break
        if item is None:
            item = items[made.get("_i", 0) % len(items)]
        made["_i"] = made.get("_i", 0) + 1
        out = out_dir / f"{tmpl}.jpg"
        luma, sd, color = render_one(item, tmpl, out)
        print(f"  ✓ {out.name:26s} 亮度 {luma:5.1f} 雜亂 {sd:5.1f} → {color} ｜ {item['title'][:26]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

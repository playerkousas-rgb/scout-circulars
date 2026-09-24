#!/usr/bin/env python3
"""Story 出圖：Pillow 模板，食 story-queue.json 出 1080×1920 PNG + JPEG。

PNG 供 Stories branch／通告專屬頁顯示；JPEG 供 Instagram Graph API（只接受 JPEG）。
預設輸出 queue 內全部齊料通告，不設張數上限。

由「NoScout 9 款概念」正式移植，執正咗嘅位：
  - 資料真源：story_queue.py 已 join 好 cache.json + enrich.json
    （deadline/audience/fee/category），唔通再中文 key 亂猜；
  - category 用我哋五分類（training/service/activity/competition/other），
    「小工具」也唔會入 queue，唔使喺度 skip；
  - Logo 唔係吉 placeholder：直貼 icons/orgs 嘅真區徽
    （PNG 版，fallback 鏈：區 → 地域 → 總會）；
  - 中文要靠 Noto Sans CJK（workflow 會 apt install fonts-noto-cjk）；
  - 底部有 credit（同 app poster 同款），唔係「NoScout.System」。

每日 15:30 HKT 自動流程會將 JPEG 經 Instagram Graph API 發佈；API 發佈唔支援
link sticker。PNG 仍供通告專屬頁及手動 Story Drafts 流程重用。

需要：pip install pillow 'qrcode[pil]'。CLI：--queue story-queue.json --out output
產物：output/<today>/NN_<template>_<hash>.png/.jpg + manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
ROOT = Path(__file__).resolve().parent.parent
story_attachment_url = None
story_slogan = None


def _load_story_helpers():
    """Load queue helpers only for rendering; copied --build-index runs on stories branch."""
    global story_attachment_url, story_slogan
    if callable(story_attachment_url) and callable(story_slogan):
        return
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from story_queue import story_attachment_url as _attachment_url, story_slogan as _story_slogan
    story_attachment_url, story_slogan = _attachment_url, _story_slogan


CREDIT = "經 通告圖書館整理 @noscout.system"  # 同 index.html POSTER_CREDIT 一致

# ── 字體 ──────────────────────────────────────────────────────────
FONT_CANDIDATES = [
    os.environ.get("STORY_FONT", ""),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansHK-Bold.ttf",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/msjhbd.ttc",          # Windows 微軟正黑體 Bold
    "/System/Library/Fonts/PingFang.ttc",    # macOS
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    global _FONT_RESOLVED
    if _FONT_RESOLVED is not None:
        return ImageFont.truetype(_FONT_RESOLVED, size)
    for p in FONT_CANDIDATES:
        if p and Path(p).exists():
            try:
                ImageFont.truetype(p, 12)
                _FONT_RESOLVED = p
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    raise SystemExit(
        "❌ 搵唔到中文字體（搵過 STORY_FONT＋Ubuntu Noto CJK＋msjhbd＋PingFang）。\n"
        "   冇字體出圖只會出豆腐格，所以寧願 fail。Ubuntu 請 `sudo apt-get install fonts-noto-cjk`；"
        "   或者 `export STORY_FONT=/path/to/CJK-Bold.ttf`。")


_FONT_RESOLVED: str | None = None


def text_w(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return draw.textlength(text, font=font)


import re as _re

_TOKEN_SPLIT = _re.compile(r"([A-Za-z0-9%$./_+@#-]+)")


def _tokens(text: str) -> list[str]:
    """切成唔可以斷嘅單位：連續 ASCII 字母/數字係一粒（年份、HK$50 唔准斷），
    其他（CJK、標點）逐字一粒。"""
    out: list[str] = []
    for part in _TOKEN_SPLIT.split(text):
        if not part:
            continue
        if _TOKEN_SPLIT.fullmatch(part):
            out.append(part)
        else:
            out.extend(part)
    return out


def wrap_cjk(draw: ImageDraw.ImageDraw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    """逐粒斷行（CJK 逐字、ASCII 詞唔斷），最多 max_lines 行，尾行截住加省略號。"""
    text = " ".join(str(text or "").split()) or "未命名通告"
    lines: list[str] = []
    cur = ""
    for tok in _tokens(text):
        if text_w(draw, cur + tok, font) <= max_w or not cur:
            cur += tok
        else:
            lines.append(cur)
            cur = tok.lstrip()
            if len(lines) == max_lines:
                break
    else:
        if cur:
            lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    consumed = sum(len(x) for x in lines)
    if consumed < len(text.replace(" ", "")):
        last = lines[-1]
        while last and text_w(draw, last + "…", font) > max_w:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines[:max_lines]


def draw_title_block(draw, title: str, color: str, zone: tuple[int, int, int, int],
                     outline: str | None = None, align: str = "center"):
    """標題自動縮 size + 逐字斷行 + 喺 zone(左,上,右,下) 垂直置中。"""
    x0, y0, x1, y1 = zone
    max_w = x1 - x0
    for size in (92, 78, 64, 52):
        font = _font(size)
        lines = wrap_cjk(draw, title, font, max_w, 4)
        if not (len(lines) == 4 and lines[-1].endswith("…") and size > 52):
            break
    lh = int(size * 1.3)
    total = lh * len(lines)
    y = y0 + max(0, (y1 - y0 - total) // 2)
    for line in lines:
        tw = text_w(draw, line, font)
        x = x0 + (max_w - tw) / 2 if align == "center" else x0
        if outline:
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                draw.text((x + dx, y + dy), line, fill=outline, font=font)
        draw.text((x, y), line, fill=color, font=font)
        y += lh


def draw_pill(draw, text, xy, bg, fg="#FFFFFF"):
    x, y = xy
    font = _font(32)
    tw = text_w(draw, text, font)
    th = 40
    pad_x, pad_y = 28, 10
    draw.rounded_rectangle([x, y, x + tw + pad_x * 2, y + th + pad_y * 2], radius=22, fill=bg)
    draw.text((x + pad_x, y + pad_y - 2), text, fill=fg, font=font)


# ── 區徽：icons/orgs 真徽（PNG 版），fallback：區 → 地域 → 總會 ──
_ORGS: dict | None = None
_BADGE_CACHE: dict[str, Image.Image | None] = {}


def load_orgs(path: Path) -> dict:
    global _ORGS
    if _ORGS is None:
        try:
            _ORGS = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _ORGS = {"orgs": {}}
    return _ORGS


def _badge_png_path(icon256: str) -> Path:
    rel = icon256.replace(".avif", ".png")
    return ROOT / rel


def badge_for(item: dict, orgs: dict) -> Image.Image | None:
    """拎到就 148×148 contain 嘅 RGBA 徽；真係冇就 None（模板靜靜略過）。"""
    name = str(item.get("source_site") or "").strip()
    table = orgs.get("orgs") or {}
    ent = table.get(name)
    chain = []
    if ent and ent.get("icon256"):
        chain.append(ent["icon256"])
    if ent and ent.get("fallback") and table.get(ent["fallback"], {}).get("icon256"):
        chain.append(table[ent["fallback"]]["icon256"])
    if table.get("總會", {}).get("icon256"):
        chain.append(table["總會"]["icon256"])
    for icon in chain:
        if icon in _BADGE_CACHE:
            img = _BADGE_CACHE[icon]
        else:
            p = _badge_png_path(icon)
            try:
                raw = Image.open(p).convert("RGBA")
                raw.thumbnail((148, 148))
                img = raw
            except OSError:
                img = None
            _BADGE_CACHE[icon] = img
        if img is not None:
            return img
    return None


def paste_badge(img: Image.Image, badge: Image.Image | None):
    if not badge:
        return
    tile = Image.new("RGBA", (184, 184), (255, 255, 255, 242))
    mask = Image.new("L", (184, 184), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, 184, 184], radius=34, fill=255)
    img.paste(tile, (W - 236, 68), mask)
    img.paste(badge, (W - 236 + (184 - badge.width) // 2, 68 + (184 - badge.height) // 2), badge)


def draw_story_cta(img: Image.Image, draw: ImageDraw.ImageDraw, item: dict, accent: str):
    """Add the category's encouragement and a scan-friendly QR to the original attachment."""
    _load_story_helpers()
    attachment_url = story_attachment_url(item)
    if not attachment_url:
        raise ValueError("Story QR requires the original attachment URL")
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(attachment_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#111111", back_color="#FFFFFF").get_image().convert("RGB")
    qr_size = 250
    qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.NEAREST)

    panel = [60, 1090, 1020, 1372]
    draw.rounded_rectangle(panel, radius=24, fill=(255, 255, 255, 246), outline=accent, width=3)
    draw.rounded_rectangle([60, panel[1], 82, panel[3]], radius=10, fill=accent)

    slogan = story_slogan(item)
    text_x, max_width = 108, 620
    for size in (46, 42, 38, 34):
        font = _font(size)
        lines = wrap_cjk(draw, slogan, font, max_width, 2)
        if len(lines) < 2 or not lines[-1].endswith("…"):
            break
    line_height = int(size * 1.25)
    text_height = line_height * len(lines)
    text_y = panel[1] + max(0, (panel[3] - panel[1] - text_height) // 2)
    for line in lines:
        draw.text((text_x, text_y), line, fill="#111111", font=font)
        text_y += line_height

    qr_x, qr_y = 770, 1094
    img.paste(qr_img, (qr_x, qr_y))
    qr_label = "掃碼開原文附件"
    qr_font = _font(20)
    label_width = text_w(draw, qr_label, qr_font)
    draw.text((qr_x + (qr_size - label_width) / 2, 1345), qr_label, fill="#333333", font=qr_font)


def draw_bottom(draw, item: dict, accent: str, dark: bool, img: Image.Image):
    """QR／鼓勵字句 callout + 實數據卡：截止／對象／費用／頒佈。"""
    draw_story_cta(img, draw, item, accent)
    rows = [
        ("截止", item.get("deadline") or "詳情見內文"),
        ("對象", item.get("audience") or "見通告"),
        ("費用", item.get("fee") or "見通告"),
        ("頒佈", item.get("date") or "—"),
    ]
    y = 1380
    fl, fv = _font(26), _font(30)
    for label, val in rows:
        val = str(val)
        if len(val) > 18:
            val = val[:17] + "…"
        draw.rounded_rectangle([60, y, 1020, y + 92], radius=18, fill=(255, 255, 255, 235))
        draw.text((86, y + 14), label, fill="#666666", font=fl)
        draw.text((86, y + 46), val,
                  fill=accent if label == "截止" and val != "詳情見內文" else "#111111",
                  font=fv)
        y += 108
    foot = f"{item.get('source_site', '')} ・ {item.get('region', '')}".strip(" ・")
    foot_c = "#9AA7BD" if dark else "#6B7280"
    credit_c = "#7C89A3" if dark else "#9CA3AF"
    draw.text((60, 1800), foot, fill=foot_c, font=_font(22))
    draw.text((60, 1834), CREDIT, fill=credit_c, font=_font(22))


# ── 12 款模板 ─────────────────────────────────────────────────────
def t_train(color_hex):
    def render(item, img, draw, badge):
        draw.rectangle([0, 0, W, H], fill="#FFFFFF")
        draw.polygon([(0, 760), (W, 540), (W, 1320), (0, 1560)], fill=color_hex)
        draw_pill(draw, "訓練", (60, 80), color_hex)
        paste_badge(img, badge)
        draw_title_block(draw, item.get("title", ""), "#111111", (70, 480, 1010, 1080))
        draw_bottom(draw, item, color_hex, False, img)
    return render


def t_competition_gold(item, img, draw, badge):
    draw.rectangle([0, 0, W, H], fill="#0A0A0A")
    draw.rectangle([30, 30, W - 30, H - 30], outline="#FFD700", width=4)
    draw_pill(draw, "比賽", (60, 80), "#FFD700", "#000000")
    paste_badge(img, badge)
    draw_title_block(draw, item.get("title", ""), "#FFD700", (80, 500, 1000, 1080), outline="#000000")
    draw.rectangle([60, 1288, 1020, 1296], fill="#FFD700")
    draw_bottom(draw, item, "#FFD700", True, img)


def t_activity_army(item, img, draw, badge):
    rng = random.Random(hashlib.md5(str(item.get("pdf_url") or item.get("url") or "").encode()).hexdigest())
    draw.rectangle([0, 0, W, H], fill="#2D3A2E")
    for i in range(0, H, 120):
        draw.line([(0, i + rng.randint(-20, 20)), (W, i + rng.randint(-20, 20))], fill="#3A4A3B", width=1)
    draw.ellipse([200, 380, 880, 1060], outline="#A6FF00", width=3)
    draw.ellipse([300, 480, 780, 960], outline="#A6FF00", width=2)
    draw_pill(draw, "活動", (60, 80), "#A6FF00", "#000000")
    paste_badge(img, badge)
    draw_title_block(draw, item.get("title", ""), "#FFFFFF", (70, 470, 1010, 1030))
    draw_bottom(draw, item, "#A6FF00", True, img)


def _wanted_base(item, img, draw, badge, pill_text):
    draw.rectangle([0, 0, W, H], fill="#E9D5A8")
    draw.rectangle([20, 20, W - 20, H - 20], outline="#8B5A2B", width=6)
    f = _font(120)
    tw = text_w(draw, "WANTED", f)
    draw.text((60 + (W - 320 - tw) / 2, 96), "WANTED", fill="#3D1E00", font=f)
    draw_pill(draw, pill_text, (60, 80), "#3D1E00")
    paste_badge(img, badge)
    draw_title_block(draw, item.get("title", ""), "#1b1206", (90, 480, 990, 1050))
    draw_bottom(draw, item, "#8B5A2B", False, img)


def t_service_wanted(item, img, draw, badge):
    _wanted_base(item, img, draw, badge, "服務")


def t_unc_scope(item, img, draw, badge):
    draw.rectangle([0, 0, W, H], fill="#000000")
    cx, cy = W // 2, 760
    for r in (200, 350, 500):
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline="#FF0000", width=2)
    draw.line([(cx - 600, cy), (cx + 600, cy)], fill="#FF0000", width=2)
    draw.line([(cx, cy - 600), (cx, cy + 600)], fill="#FF0000", width=2)
    draw_pill(draw, "其他", (60, 80), "#FF0000")
    paste_badge(img, badge)
    draw_title_block(draw, item.get("title", ""), "#FFFFFF", (90, 470, 990, 1050))
    draw_bottom(draw, item, "#FF0000", True, img)


def t_unc_topsecret(item, img, draw, badge):
    draw.rectangle([0, 0, W, H], fill="#000000")
    draw.rectangle([40, 200, 1040, 1650], fill="#C9B896")
    stamp = Image.new("RGBA", (760, 220), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.text((10, 20), "TOP SECRET", fill="#8B0000", font=_font(96))
    stamp = stamp.rotate(-14, expand=True)
    img.paste(stamp, (90, 230), stamp)
    draw_pill(draw, "其他", (60, 80), "#8B0000")
    paste_badge(img, badge)
    draw_title_block(draw, item.get("title", ""), "#111111", (120, 500, 960, 1060))
    draw.rectangle([120, 1180, 430, 1222], fill="#111111")
    draw.rectangle([120, 1246, 300, 1288], fill="#111111")
    draw_bottom(draw, item, "#8B0000", False, img)


def t_unc_glitch(item, img, draw, badge):
    draw.rectangle([0, 0, W, H], fill="#000000")
    for y in range(0, H, 4):
        draw.line([(0, y), (W, y)], fill=(20, 20, 20))
    title = str(item.get("title") or "UNEXPECTED EVENT")
    ghost = title[:14]
    gf = _font(84)
    draw.text((66, 306), ghost, fill="#00FFFF", font=gf)
    draw.text((58, 298), ghost, fill="#FF00FF", font=gf)
    draw_pill(draw, "其他", (60, 80), "#00FFFF", "#000000")
    paste_badge(img, badge)
    draw_title_block(draw, title, "#FFFFFF", (70, 470, 1010, 1050))
    draw_bottom(draw, item, "#00FFFF", True, img)


def t_unc_wanted_parchment(item, img, draw, badge):
    _wanted_base(item, img, draw, badge, "其他")


def t_unc_wanted_red(item, img, draw, badge):
    draw.rectangle([0, 0, W, H], fill="#FFFFFF")
    f = _font(150)
    tw = text_w(draw, "WANTED", f)
    draw.text((60 + (W - 320 - tw) / 2, 170), "WANTED", fill="#FF0000", font=f)
    draw.rectangle([30, 30, W - 30, H - 30], outline="#000000", width=8)
    draw_pill(draw, "其他", (60, 80), "#000000")
    paste_badge(img, badge)
    draw_title_block(draw, item.get("title", ""), "#000000", (90, 480, 990, 1080))
    draw_bottom(draw, item, "#FF0000", False, img)


def t_unc_wanted_blackfin(item, img, draw, badge):
    draw.rectangle([0, 0, W, H], fill="#0A0A0A")
    draw.rectangle([40, 40, W - 40, H - 40], fill="#E9D5A8")
    f = _font(118)
    tw = text_w(draw, "WANTED", f)
    draw.text((60 + (W - 320 - tw) / 2, 180), "WANTED", fill="#111111", font=f)
    draw_pill(draw, "其他", (60, 80), "#111111")
    paste_badge(img, badge)
    draw_title_block(draw, item.get("title", ""), "#111111", (100, 500, 980, 1080))
    draw_bottom(draw, item, "#111111", False, img)


POOLS = {
    "training": [t_train("#0066FF"), t_train("#FF6B00"), t_train("#00C950")],
    "competition": [t_competition_gold],
    "activity": [t_activity_army],
    "service": [t_service_wanted],
    "other": [t_unc_scope, t_unc_topsecret, t_unc_glitch,
              t_unc_wanted_parchment, t_unc_wanted_red, t_unc_wanted_blackfin],
}
POOL_NAMES = {
    "training": ["train_blue", "train_orange", "train_green"],
    "competition": ["competition_gold_black"],
    "activity": ["activity_army"],
    "service": ["service_wanted"],
    "other": ["unc_scope", "unc_topsecret", "unc_glitch",
              "unc_wanted_parchment", "unc_wanted_red", "unc_wanted_blackfin"],
}


def pick_template(item: dict):
    """hash(url) 定款：同一張通告永遠出同一款，唔會每日變樣。"""
    cat = item.get("category") if item.get("category") in POOLS else "other"
    pool = POOLS[cat]
    key = str(item.get("pdf_url") or item.get("url") or item.get("title") or "")
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
    i = h % len(pool)
    return cat, POOL_NAMES[cat][i], pool[i]


def build_index(stories_root: Path) -> Path:
    """掃 stories/<日期>/manifest.json，出 stories/index.json 俾專屬頁一發 fetch 搵 hero。
    key = pdf_url || url；同一通告多日有圖就留最新嗰日。"""
    dates = sorted(
        d.name for d in stories_root.iterdir()
        if d.is_dir() and (d / "manifest.json").exists()
    )
    items: dict[str, dict] = {}
    for d in dates:
        try:
            man = json.loads((stories_root / d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for it in man.get("items") or []:
            k = str(it.get("pdf_url") or it.get("url") or "").strip()
            f = str(it.get("file") or "").strip()
            if k and f:
                items[k] = {"k": k, "f": f"stories/{d}/{f}", "t": str(it.get("title") or "")}
    out = stories_root / "index.json"
    out.write_text(json.dumps({
        "version": 1,
        "days": dates,
        "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "items": [items[k] for k in sorted(items)],
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="story-queue.json")
    ap.add_argument("--orgs", default=str(ROOT / "icons/orgs/orgs.json"))
    ap.add_argument("--out", default="output")
    ap.add_argument("--limit", type=int, default=0,
                    help="最多幾多張；預設 0＝queue 內全部（正數只供手動測試）")
    ap.add_argument("--build-index", metavar="STORIES_DIR",
                    help="只抌索引：掃 <STORIES_DIR>/<日期>/manifest.json 出 index.json")
    args = ap.parse_args(argv)

    if args.build_index:
        out = build_index(Path(args.build_index))
        try:
            days = json.loads(out.read_text(encoding="utf-8"))
            print(f"✅ {out}：{len(days['items'])} 張通告有 hero（日子：{', '.join(days['days']) or '冇'}）")
        except (OSError, json.JSONDecodeError):
            print(f"✅ {out}")
        return 0

    _load_story_helpers()
    qp = Path(args.queue)
    if not qp.exists():
        print(f"❌ 搵唔到 {qp}（先行 story_queue.py）", file=sys.stderr)
        return 1
    queue = json.loads(qp.read_text(encoding="utf-8"))
    today = queue.get("today") or "unknown-date"
    out_dir = Path(args.out) / today
    out_dir.mkdir(parents=True, exist_ok=True)
    orgs = load_orgs(Path(args.orgs))

    manifest = {"today": today, "queue_generated_at": queue.get("generated_at", ""), "items": []}
    queue_items = queue.get("items") or []
    items = queue_items[: args.limit] if args.limit > 0 else queue_items
    for idx, item in enumerate(items):
        cat, tname, func = pick_template(item)
        img = Image.new("RGB", (W, H), "#FFFFFF")
        draw = ImageDraw.Draw(img, "RGBA")
        func(item, img, draw, badge_for(item, orgs))
        key = str(item.get("pdf_url") or item.get("url") or idx)
        stem = f"{idx:02d}_{tname}_{hashlib.md5(key.encode()).hexdigest()[:6]}"
        fname = f"{stem}.png"
        instagram_fname = f"{stem}.jpg"
        img.save(out_dir / fname, optimize=True)
        # Meta Content Publishing API 只接受 JPEG 圖片；保留 PNG 作 app hero
        # 及人工下載版，JPEG 以高質素輸出供 Story 發佈。
        img.save(out_dir / instagram_fname, format="JPEG", quality=94, optimize=True)
        manifest["items"].append({
            "file": fname, "instagram_file": instagram_fname,
            "template": tname, "category": cat,
            "title": item.get("title", ""), "source_site": item.get("source_site", ""),
            "url": item.get("url", ""), "pdf_url": item.get("pdf_url", ""),
            "attachment_url": story_attachment_url(item), "slogan": story_slogan(item),
        })
        print(f"✓ {today}/{fname} + {instagram_fname} ← {cat}/{tname} | {str(item.get('title',''))[:24]}")

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"出咗 {len(manifest['items'])} 張草稿 → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

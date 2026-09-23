#!/usr/bin/env python3
"""WebP 底圖 → PNG，方便去畀你自己嘅出圖腳本（templates/clean_no_text/）。

Repo 入面 story-bases/*.webp 係 9 張 AI 無字底圖（1080×1920，合共約 1 MB）。
你嗰個腳本用 Image.open 直接讀 PNG／JPG；PIL 其實一樣讀得 WebP，
但如果你想維持原本資料夾結構，就跑呢個：

  python3 tools/bases_webp_to_png.py --out templates/clean_no_text

之後你只需要喺 get_base() 個 list 頭加 ".webp"（或者用呢度出嘅 PNG）。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BASES = ROOT / "story-bases"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="story-bases WebP → PNG")
    ap.add_argument("--out", default=str(ROOT / "templates/clean_no_text"))
    ap.add_argument("--size", type=int, default=0, help="輸出長邊（0＝原尺寸 1080×1920）")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(BASES.glob("*.webp"))
    if not files:
        raise SystemExit(f"❌ {BASES} 冇 .webp 底圖")
    for f in files:
        im = Image.open(f).convert("RGB")
        if args.size:
            r = args.size / max(im.size)
            im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
        dst = out / f"{f.stem}.png"
        im.save(dst, optimize=True)
        print(f"  ✓ {dst}  {im.size[0]}×{im.size[1]}")
    print(f"\n完成：{len(files)} 張 → {out}")
    print("提醒：你腳本嘅 get_base() 搵 PNG／JPG／WebP 都可以；PIL 原生讀得 WebP。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

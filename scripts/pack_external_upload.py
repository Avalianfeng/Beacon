"""把索取/交棒目录里的文字表和图打成尽量少的上传件。

外部模型常有「一次几个文件」上限。本机可保留分文件；对外默认只要：
  <stem>.md   说明 + 全部 csv 原文
  <stem>.png  该目录下 png 拼成一张（张数少则纵向，4 张则 2×2）

示例：
  python scripts/pack_external_upload.py --dir problems/cumcm23-c/认知地图集/外部/索取 --stem 给第二家-打包
  python scripts/pack_external_upload.py --dir problems/cumcm23-c/eda --glob-png "附件*.png" --stem 概览四合一 --md-skip
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SKIP_NAME_PREFIXES = ("给第二家-打包", "概览四合一")
SKIP_SUFFIXES = (".py",)
SKIP_NAMES = {"_pack_for_upload.py"}


def _should_skip(path: Path, stem: str) -> bool:
    name = path.name
    if name.startswith("."):
        return True
    if path.stem == stem or name.startswith(stem):
        return True
    if any(name.startswith(p) for p in SKIP_NAME_PREFIXES):
        return True
    if path.suffix.lower() in SKIP_SUFFIXES or name in SKIP_NAMES:
        return True
    return False


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _collect(
    dir_path: Path,
    stem: str,
    glob_png: str,
    glob_md: str,
    glob_csv: str,
) -> tuple[list[Path], list[Path], list[Path]]:
    mds = [
        p
        for p in sorted(dir_path.glob(glob_md))
        if p.is_file() and p.suffix.lower() == ".md" and not _should_skip(p, stem)
    ]
    csvs = [
        p
        for p in sorted(dir_path.glob(glob_csv))
        if p.is_file() and p.suffix.lower() == ".csv" and not _should_skip(p, stem)
    ]
    pngs = [
        p
        for p in sorted(dir_path.glob(glob_png))
        if p.is_file() and p.suffix.lower() == ".png" and not _should_skip(p, stem)
    ]
    def _md_key(p: Path) -> tuple[int, str]:
        if "交棒" in p.name:
            return (0, p.name)
        if "轮2" in p.name:
            return (1, p.name)
        if p.name.startswith("给第二家") and "打包" not in p.name:
            return (2, p.name)
        if p.name.startswith("回填说明"):
            return (3, p.name)
        return (4, p.name)

    mds.sort(key=_md_key)
    return mds, csvs, pngs


def pack_markdown(mds: list[Path], csvs: list[Path], out_md: Path) -> None:
    parts: list[str] = [
        "<!-- packed by scripts/pack_external_upload.py · 对外上传用；分文件仍以目录内原件为准 -->\n",
        f"# 打包上传（{out_md.parent.name}）\n",
        "下面依次为说明稿与各表 CSV 原文。图见同目录打包 png（若已生成）。\n",
    ]
    for p in mds:
        parts.append(f"\n---\n\n## 文件：{p.name}\n\n")
        parts.append(_read_text(p).rstrip() + "\n")
    for p in csvs:
        parts.append(f"\n---\n\n## 表：{p.name}\n\n```csv\n")
        parts.append(_read_text(p).rstrip() + "\n```\n")
    out_md.write_text("".join(parts), encoding="utf-8")


def _font(size: int = 18) -> ImageFont.ImageFont:
    for name in ("msyh.ttc", "msyh.ttf", "simhei.ttf"):
        windir = Path("C:/Windows/Fonts") / name
        if windir.is_file():
            return ImageFont.truetype(str(windir), size)
    return ImageFont.load_default()


def _label_bar(width: int, text: str, height: int = 36) -> Image.Image:
    bar = Image.new("RGB", (width, height), (32, 32, 32))
    draw = ImageDraw.Draw(bar)
    draw.text((8, 8), text, fill=(255, 255, 255), font=_font(16))
    return bar


def stitch_pngs(pngs: list[Path], out_png: Path) -> None:
    if not pngs:
        return
    images = []
    for p in pngs:
        im = Image.open(p).convert("RGB")
        images.append((p.name, im))
    n = len(images)
    cols = 2 if n == 4 else 1
    rows = (n + cols - 1) // cols

    cell_w = max(im.width for _, im in images)
    # 统一宽度
    scaled: list[tuple[str, Image.Image]] = []
    for name, im in images:
        if im.width != cell_w:
            ratio = cell_w / im.width
            im = im.resize((cell_w, max(1, int(im.height * ratio))), Image.Resampling.LANCZOS)
        scaled.append((name, im))

    row_heights: list[int] = []
    for r in range(rows):
        chunk = scaled[r * cols : (r + 1) * cols]
        bar_h = 36
        row_heights.append(bar_h + max(im.height for _, im in chunk))

    canvas_w = cell_w * cols
    canvas_h = sum(row_heights)
    canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    y = 0
    for r in range(rows):
        chunk = scaled[r * cols : (r + 1) * cols]
        x = 0
        for name, im in chunk:
            bar = _label_bar(cell_w, name)
            canvas.paste(bar, (x, y))
            canvas.paste(im, (x, y + bar.height))
            x += cell_w
        y += row_heights[r]
    out_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_png, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="拼接索取/EDA 目录为少量上传件")
    parser.add_argument("--dir", type=Path, required=True, help="源目录")
    parser.add_argument("--stem", default="给第二家-打包", help="输出文件名（不含扩展名）")
    parser.add_argument("--glob-png", default="*.png")
    parser.add_argument("--glob-md", default="*.md")
    parser.add_argument("--glob-csv", default="*.csv")
    parser.add_argument("--md-skip", action="store_true", help="只拼图、不写 md")
    args = parser.parse_args()
    src = args.dir.resolve()
    if not src.is_dir():
        raise SystemExit(f"不是目录：{src}")
    mds, csvs, pngs = _collect(src, args.stem, args.glob_png, args.glob_md, args.glob_csv)
    out_md = src / f"{args.stem}.md"
    out_png = src / f"{args.stem}.png"
    if not args.md_skip:
        pack_markdown(mds, csvs, out_md)
        print(f"[OK] {out_md}  ({out_md.stat().st_size} bytes, md={len(mds)} csv={len(csvs)})")
    if pngs:
        stitch_pngs(pngs, out_png)
        print(f"[OK] {out_png}  ({out_png.stat().st_size} bytes, png={len(pngs)})")
    else:
        print("[SKIP] 无 png")
    print("对外上传：优先只要上述打包文件（分文件留作本机复现）。")


if __name__ == "__main__":
    main()

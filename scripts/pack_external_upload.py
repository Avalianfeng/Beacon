"""把索取/交棒目录里的文字表和图打成尽量少的上传件。

外部模型常有「一次几个文件」上限。本机可保留分文件；对外默认只要：
  <stem>.md   说明 + 全部 csv 原文
  <stem>.png  该目录下 png 拼成一张（张数少则纵向，4 张则 2×2）

示例：
  # 新题（学-37）：对着 V*/索取/轮N，自动解析 _共享 切片，成品进外发归档
  python scripts/pack_external_upload.py ^
    --dir problems/cumcm24-c/认知地图集/外部/V1/索取/轮1 ^
    --stem 给第二家-V1-轮1 --resolve-shared

  # 只拼 EDA 图
  python scripts/pack_external_upload.py --dir problems/cumcm24-c/eda --glob-png "补-*.png" --stem 概览补图 --md-skip

  # 历史混放形态（cumcm23 扁平索取，勿用于新题）
  python scripts/pack_external_upload.py --dir problems/cumcm23-c/认知地图集/外部/索取 --stem 给第二家-打包
"""
from __future__ import annotations

import argparse
import re
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SKIP_NAME_PREFIXES = ("给第二家-", "概览四合一", "概览三合一", "概览补图")
SKIP_SUFFIXES = (".py",)
SKIP_NAMES = {"_pack_for_upload.py", "清单.md"}
SHARED_PATH_RE = re.compile(r"_共享/切片/([^\s|`]+)")
SLICE_ID_RE = re.compile(r"\bS\d{3,4}\b")


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


def find_external_root(start: Path) -> Path | None:
    """从轮目录向上找到含 `_共享/切片` 的外部根。"""
    cur = start.resolve()
    for p in [cur, *cur.parents]:
        if (p / "_共享" / "切片").is_dir():
            return p
    return None


def default_out_dir(src: Path) -> Path | None:
    """…/V*/索取/轮N → …/V*/外发归档。"""
    src = src.resolve()
    if src.name.startswith("轮") and src.parent.name == "索取":
        out = src.parent.parent / "外发归档"
        return out
    return None


def parse_index(index_path: Path) -> dict[str, str]:
    """切片ID → 相对 `切片/` 的文件名。"""
    if not index_path.is_file():
        return {}
    mapping: dict[str, str] = {}
    for line in _read_text(index_path).splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        sid, fname = cells[0], cells[1]
        if not sid or sid.startswith("（") or sid == "切片ID" or set(sid) <= {"-", "—"}:
            continue
        if not fname or fname.startswith("（"):
            continue
        mapping[sid] = Path(fname).name
    return mapping


def parse_清单_refs(清单_path: Path) -> tuple[set[str], set[str]]:
    """返回 (切片ID集合, `_共享/切片/` 下的文件名集合)。"""
    if not 清单_path.is_file():
        return set(), set()
    text = _read_text(清单_path)
    ids = set(SLICE_ID_RE.findall(text))
    files = {Path(m).name for m in SHARED_PATH_RE.findall(text)}
    return ids, files


def resolve_shared_files(
    round_dir: Path,
    *,
    external_root: Path | None = None,
) -> list[Path]:
    """按清单 + 索引解析出需要纳入打包的共享切片路径（绝对路径）。"""
    root = external_root or find_external_root(round_dir)
    if root is None:
        raise FileNotFoundError(f"未找到 _共享/切片（从 {round_dir} 向上）")
    slice_dir = root / "_共享" / "切片"
    index = parse_index(slice_dir / "_索引.md")
    ids, files = parse_清单_refs(round_dir / "清单.md")
    resolved: list[Path] = []
    missing: list[str] = []
    for sid in sorted(ids):
        if sid not in index:
            missing.append(f"索引无 {sid}")
            continue
        path = slice_dir / index[sid]
        if not path.is_file():
            missing.append(f"{sid} → 缺文件 {path.name}")
            continue
        resolved.append(path)
    for name in sorted(files):
        path = slice_dir / name
        if not path.is_file():
            missing.append(f"缺 _共享/切片/{name}")
            continue
        if path not in resolved:
            resolved.append(path)
    if missing:
        raise FileNotFoundError("共享切片解析失败：\n  - " + "\n  - ".join(missing))
    return resolved


def materialize_shared(round_dir: Path, shared_files: list[Path]) -> list[Path]:
    """复制共享文件进轮目录（可选归档）；返回轮目录内路径。"""
    out: list[Path] = []
    for src in shared_files:
        dest = round_dir / src.name
        if dest.resolve() != src.resolve():
            shutil.copy2(src, dest)
        out.append(dest)
    return out


def stage_round_dir(
    round_dir: Path,
    stem: str,
    shared_files: list[Path],
    stage: Path,
) -> Path:
    """把轮目录本地件 + 共享切片拷进临时 stage（清单.md 保留）。"""
    stage.mkdir(parents=True, exist_ok=True)
    for p in round_dir.iterdir():
        if not p.is_file():
            continue
        if _should_skip(p, stem) and p.name != "清单.md":
            continue
        if p.name.startswith(stem):
            continue
        shutil.copy2(p, stage / p.name)
    for src in shared_files:
        dest = stage / src.name
        if not dest.exists():
            shutil.copy2(src, dest)
    return stage


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
    # 清单需要进包（对外说明本轮要了什么）
    清单 = dir_path / "清单.md"
    if 清单.is_file() and 清单 not in mds:
        mds.insert(0, 清单)
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
        if p.name == "清单.md":
            return (0, p.name)
        if "交棒" in p.name:
            return (1, p.name)
        if "轮2" in p.name:
            return (2, p.name)
        if p.name.startswith("给第二家") and "打包" not in p.name:
            return (3, p.name)
        if p.name.startswith("回填说明"):
            return (4, p.name)
        return (5, p.name)

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


def pack_dir(
    src: Path,
    stem: str,
    *,
    glob_png: str = "*.png",
    glob_md: str = "*.md",
    glob_csv: str = "*.csv",
    md_skip: bool = False,
    out_dir: Path | None = None,
) -> tuple[Path | None, Path | None]:
    mds, csvs, pngs = _collect(src, stem, glob_png, glob_md, glob_csv)
    dest = out_dir if out_dir is not None else src
    dest.mkdir(parents=True, exist_ok=True)
    out_md = dest / f"{stem}.md"
    out_png = dest / f"{stem}.png"
    wrote_md = wrote_png = None
    if not md_skip:
        pack_markdown(mds, csvs, out_md)
        print(f"[OK] {out_md}  ({out_md.stat().st_size} bytes, md={len(mds)} csv={len(csvs)})")
        wrote_md = out_md
    if pngs:
        stitch_pngs(pngs, out_png)
        print(f"[OK] {out_png}  ({out_png.stat().st_size} bytes, png={len(pngs)})")
        wrote_png = out_png
    else:
        print("[SKIP] 无 png")
    return wrote_md, wrote_png


def main() -> None:
    parser = argparse.ArgumentParser(description="拼接索取/EDA 目录为少量上传件")
    parser.add_argument("--dir", type=Path, required=True, help="源目录（轮N 或 eda）")
    parser.add_argument("--stem", default="给第二家-打包", help="输出文件名（不含扩展名）")
    parser.add_argument("--glob-png", default="*.png")
    parser.add_argument("--glob-md", default="*.md")
    parser.add_argument("--glob-csv", default="*.csv")
    parser.add_argument("--md-skip", action="store_true", help="只拼图、不写 md")
    parser.add_argument(
        "--resolve-shared",
        action="store_true",
        help="读轮目录清单.md，从 _共享/切片 拉入引用文件后再打包（推荐新题）",
    )
    parser.add_argument(
        "--materialize",
        action="store_true",
        help="与 --resolve-shared 联用：把共享切片复制进轮目录（归档用；默认只进临时 stage）",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="成品目录（默认：轮N → V*/外发归档；否则写回 --dir）",
    )
    args = parser.parse_args()
    src = args.dir.resolve()
    if not src.is_dir():
        raise SystemExit(f"不是目录：{src}")

    out_dir = args.out.resolve() if args.out else default_out_dir(src)
    work = src
    tmp: tempfile.TemporaryDirectory[str] | None = None

    try:
        if args.resolve_shared:
            shared = resolve_shared_files(src)
            print(f"[共享] 解析到 {len(shared)} 个切片：{[p.name for p in shared]}")
            if args.materialize:
                materialize_shared(src, shared)
                print(f"[共享] 已 materialize 进 {src}")
            tmp = tempfile.TemporaryDirectory(prefix="beacon_pack_")
            work = stage_round_dir(src, args.stem, shared, Path(tmp.name))
            print(f"[stage] {work}")

        pack_dir(
            work,
            args.stem,
            glob_png=args.glob_png,
            glob_md=args.glob_md,
            glob_csv=args.glob_csv,
            md_skip=args.md_skip,
            out_dir=out_dir if out_dir is not None else src,
        )
    finally:
        if tmp is not None:
            tmp.cleanup()

    where = out_dir if out_dir is not None else src
    print(f"对外上传：优先只要 {where} 下的打包文件（分文件留作本机复现）。")


if __name__ == "__main__":
    main()

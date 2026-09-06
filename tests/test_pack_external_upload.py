import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.pack_external_upload import (  # noqa: E402
    default_out_dir,
    find_external_root,
    pack_dir,
    pack_markdown,
    parse_index,
    parse_清单_refs,
    resolve_shared_files,
    stage_round_dir,
    stitch_pngs,
)
from scripts.scaffold_external_maps import scaffold  # noqa: E402


def test_pack_markdown_and_stitch(tmp_path: Path):
    d = tmp_path / "suqiu"
    d.mkdir()
    (d / "a.md").write_text("# A\nhello\n", encoding="utf-8")
    (d / "b.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    Image.new("RGB", (40, 20), (255, 0, 0)).save(d / "one.png")
    Image.new("RGB", (40, 30), (0, 255, 0)).save(d / "two.png")
    out_md = d / "给第二家-打包.md"
    pack_markdown([d / "a.md"], [d / "b.csv"], out_md)
    text = out_md.read_text(encoding="utf-8")
    assert "文件：a.md" in text
    assert "表：b.csv" in text
    assert "1,2" in text
    out_png = d / "给第二家-打包.png"
    stitch_pngs([d / "one.png", d / "two.png"], out_png)
    assert out_png.is_file()
    im = Image.open(out_png)
    assert im.width == 40
    assert im.height > 50


def test_scaffold_default_v1_only(tmp_path: Path):
    problem = tmp_path / "demo-c"
    problem.mkdir()
    scaffold(problem, ["V1"], force=False)
    ext = problem / "认知地图集" / "外部"
    assert (ext / "_共享" / "切片" / "_索引.md").is_file()
    assert (ext / "V1" / "索取" / "轮1" / "清单.md").is_file()
    assert not (ext / "V2").exists()
    # idempotent skip
    logs = scaffold(problem, ["V1"], force=False)
    assert any(x.startswith("skip ") for x in logs)


def test_resolve_shared_and_pack_to_archive(tmp_path: Path):
    problem = tmp_path / "demo-c"
    problem.mkdir()
    scaffold(problem, ["V1"], force=True)
    ext = problem / "认知地图集" / "外部"
    slice_dir = ext / "_共享" / "切片"
    (slice_dir / "S001_demo.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (slice_dir / "_索引.md").write_text(
        "# 索引\n\n| 切片ID | 文件 | 口径一句话 | 首次产出 | 复用 |\n"
        "|---|---|---|---|---|\n"
        "| S001 | S001_demo.csv | demo | V1/轮1 | |\n",
        encoding="utf-8",
    )
    round1 = ext / "V1" / "索取" / "轮1"
    (round1 / "清单.md").write_text(
        "# 清单\n\n| 序号 | 摘要 | 文件 | 用途 |\n|---|---|---|---|\n"
        "| 1 | demo | S001 | 回填 |\n",
        encoding="utf-8",
    )
    Image.new("RGB", (20, 10), (0, 0, 255)).save(round1 / "note.png")

    assert find_external_root(round1) == ext.resolve()
    assert default_out_dir(round1) == (ext / "V1" / "外发归档").resolve()
    assert parse_index(slice_dir / "_索引.md")["S001"] == "S001_demo.csv"
    ids, files = parse_清单_refs(round1 / "清单.md")
    assert ids == {"S001"}
    shared = resolve_shared_files(round1)
    assert [p.name for p in shared] == ["S001_demo.csv"]

    stage = tmp_path / "stage"
    stage_round_dir(round1, "给第二家-V1-轮1", shared, stage)
    assert (stage / "S001_demo.csv").is_file()
    assert (stage / "清单.md").is_file()
    assert (stage / "note.png").is_file()

    out = ext / "V1" / "外发归档"
    pack_dir(stage, "给第二家-V1-轮1", out_dir=out)
    assert (out / "给第二家-V1-轮1.md").is_file()
    assert (out / "给第二家-V1-轮1.png").is_file()
    md = (out / "给第二家-V1-轮1.md").read_text(encoding="utf-8")
    assert "S001_demo.csv" in md
    assert "1,2" in md

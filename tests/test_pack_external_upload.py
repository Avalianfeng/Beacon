import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.pack_external_upload import pack_markdown, stitch_pngs  # noqa: E402


def test_pack_markdown_and_stitch(tmp_path: Path):
    d = tmp_path / "suqiu"
    d.mkdir()
    (d / "a.md").write_text("# A\nhello\n", encoding="utf-8")
    (d / "b.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    from PIL import Image

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

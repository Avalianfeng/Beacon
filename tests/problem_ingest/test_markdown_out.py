from math_agent.problem_ingest.markdown_out import build_parsed_markdown, write_parsed_markdown


def test_build_parsed_markdown_front_matter():
    md = build_parsed_markdown(
        "题目正文\n\n$E=mc^2$",
        source="a.pdf",
        method="vision",
        garble_score=0.12,
        pages=3,
        warnings=["vision_fallback_used"],
    )
    assert md.startswith("---\n")
    assert 'source: "a.pdf"' in md
    assert 'method: "vision"' in md
    assert "garble_score: 0.12" in md
    assert "pages: 3" in md
    assert "vision_fallback_used" in md
    assert "$E=mc^2$" in md


def test_write_parsed_markdown(tmp_path):
    path = write_parsed_markdown(
        tmp_path / "problem_parsed.md",
        "hello",
        source="x.md",
        method="direct",
    )
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert 'method: "direct"' in text
    assert "hello" in text

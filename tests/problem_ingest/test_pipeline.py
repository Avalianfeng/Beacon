from math_agent.problem_ingest.pipeline import parse_problem_file


def test_parse_markdown_direct(tmp_path):
    src = tmp_path / "problem.md"
    src.write_text("# 题面\n\n目标：最小化成本。\n", encoding="utf-8")
    result = parse_problem_file(src, enable_vision_fallback=False)
    assert result.quality.method == "direct"
    assert result.quality.ok is True
    assert "最小化成本" in result.text
    assert result.parsed_md_path is not None
    assert result.parsed_md_path.is_file()
    assert "method: \"direct\"" in result.parsed_md_path.read_text(encoding="utf-8")


def test_parse_pdf_vision_fallback_on_garble(tmp_path, mocker):
    import fitz
    from math_agent.problem_ingest.garble import GarbleReport

    pdf_path = tmp_path / "garbled.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "客户时间窗与惩罚系数。", fontsize=11)
    doc.save(str(pdf_path))
    doc.close()

    mocker.patch(
        "math_agent.problem_ingest.pipeline.assess_garble",
        side_effect=[
            GarbleReport(
                ok=False, garble_ratio=0.15, empty_super_ratio=0.5,
                replacement_count=20, box_count=0, empty_super_count=4,
                super_count=8, non_ws_count=200,
                warnings=["math_glyphs_replaced"], should_vision_fallback=True,
            ),
            GarbleReport(
                ok=True, garble_ratio=0.0, empty_super_ratio=0.0,
                replacement_count=0, box_count=0, empty_super_count=0,
                super_count=0, non_ws_count=40, warnings=[], should_vision_fallback=False,
            ),
        ],
    )
    mocker.patch(
        "math_agent.problem_ingest.vision.transcribe_pdf_with_vision",
        return_value="## 题面\n\n设第 $i$ 个客户惩罚为 $\\alpha (s_i-e_i)^+$。\n",
    )

    result = parse_problem_file(pdf_path, enable_vision_fallback=True)
    assert result.quality.method == "vision"
    assert result.quality.ok is True
    assert "vision_fallback_used" in result.quality.warnings
    assert "惩罚" in result.text


def test_parse_pdf_vision_failure_keeps_text(tmp_path, mocker):
    import fitz
    from math_agent.problem_ingest.garble import GarbleReport

    pdf_path = tmp_path / "garbled2.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "公式变量损坏需要回退。", fontsize=11)
    doc.save(str(pdf_path))
    doc.close()

    mocker.patch(
        "math_agent.problem_ingest.pipeline.assess_garble",
        return_value=GarbleReport(
            ok=False, garble_ratio=0.2, empty_super_ratio=0.4,
            replacement_count=30, box_count=0, empty_super_count=3,
            super_count=6, non_ws_count=180,
            warnings=["math_glyphs_replaced"], should_vision_fallback=True,
        ),
    )
    mocker.patch(
        "math_agent.problem_ingest.vision.transcribe_pdf_with_vision",
        side_effect=RuntimeError("vision down"),
    )

    result = parse_problem_file(pdf_path, enable_vision_fallback=True)
    assert result.quality.method == "text_fallback"
    assert result.quality.ok is False
    assert any(w.startswith("vision_failed:") for w in result.quality.warnings)
    assert result.text


def test_page_batches_long_doc():
    from math_agent.problem_ingest.vision import _page_batches

    assert _page_batches(3) == [(0, 1), (1, 2), (2, 3)]
    batches = _page_batches(15)
    assert batches[0] == (0, 3)
    assert batches[-1][1] == 15


def test_parse_pdf_marks_needs_vision_without_blocking(tmp_path, mocker):
    """上传阶段默认不做视觉：只标记 needsVision，立即返回文本层。"""
    import fitz
    from math_agent.problem_ingest.garble import GarbleReport

    pdf_path = tmp_path / "mark.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "客户时间窗与惩罚。", fontsize=11)
    doc.save(str(pdf_path))
    doc.close()

    mocker.patch(
        "math_agent.problem_ingest.pipeline.assess_garble",
        return_value=GarbleReport(
            ok=False, garble_ratio=0.18, empty_super_ratio=0.5,
            replacement_count=22, box_count=0, empty_super_count=4,
            super_count=8, non_ws_count=200,
            warnings=["math_glyphs_replaced"], should_vision_fallback=True,
        ),
    )
    vision = mocker.patch("math_agent.problem_ingest.vision.transcribe_pdf_with_vision")

    result = parse_problem_file(pdf_path, enable_vision_fallback=False)
    assert result.quality.method == "text"
    assert result.quality.needs_vision is True
    assert result.quality.ok is False
    vision.assert_not_called()


def test_apply_vision_transcription_emits_progress(tmp_path, mocker):
    import fitz
    from math_agent.problem_ingest.pipeline import apply_vision_transcription

    pdf_path = tmp_path / "v.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    events = []

    def fake_transcribe(path, **kwargs):
        cb = kwargs.get("progress_cb")
        if cb:
            cb({"stage": "vision_batch", "message": "正在视觉转写第 1 页", "pages": 1, "batch": 1, "batches": 1})
        return "## 视觉结果\n\n$\\alpha=1$\n"

    mocker.patch(
        "math_agent.problem_ingest.vision.transcribe_pdf_with_vision",
        side_effect=fake_transcribe,
    )
    result = apply_vision_transcription(
        pdf_path,
        progress_cb=lambda e: events.append(e),
    )
    assert result.quality.method == "vision"
    assert result.quality.needs_vision is False
    assert events and events[0]["stage"] == "vision_batch"
    assert "视觉结果" in result.text

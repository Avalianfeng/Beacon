from math_agent.problem_ingest.garble import assess_garble


def test_clean_text_is_ok():
    text = "第 i 个客户的服务开始时间为 s_i，时间窗为 [e_i, l_i]。" * 5
    report = assess_garble(text)
    assert report.ok is True
    assert report.should_vision_fallback is False
    assert report.garble_ratio == 0.0


def test_replacement_chars_trigger_vision():
    # 模拟用户截图中的乱码：中文完好、公式变量变成 U+FFFD
    r = "\ufffd"
    body = (
        f"设第 i 个客户的实际开始服务时间为 {r}_i，时间窗为 [{r}_i, {r}_i]，"
        f"违反时间窗的惩罚采用二次型 {r}^{{}} = 10，{r}^{{}} = 20，"
        f"则惩罚项为 {r}({r}_i - {r}_i)^{{+}} + {r}({r}_i - {r}_i)^{{+}}。"
    ) * 4
    report = assess_garble(body)
    assert report.should_vision_fallback is True
    assert "math_glyphs_replaced" in report.warnings
    assert report.ok is False


def test_empty_superscripts_trigger_when_common():
    text = ("客户 i 的惩罚系数 α^{} β^{} γ^{} 与到达时间 t_i 相关。") * 6
    report = assess_garble(text)
    assert report.super_count >= 3
    assert report.should_vision_fallback is True
    assert "empty_superscripts" in report.warnings


def test_short_clean_text_not_forced():
    report = assess_garble("短文本 ok")
    assert report.should_vision_fallback is False

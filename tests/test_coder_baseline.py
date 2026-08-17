"""对照方案 prompt 构建器测试。"""
from math_agent.prompts.coder_baseline import BASELINE_SPECS, build_baseline_prompt


def test_baseline_specs_has_three():
    assert len(BASELINE_SPECS) == 3
    names = [s[0] for s in BASELINE_SPECS]
    assert "无调度" in names
    assert "简单平均预测" in names
    assert "贪婪启发式" in names


def test_baseline_prompt_contains_main_code():
    prompt = build_baseline_prompt(
        problem="共享单车调度",
        main_code="import numpy as np\nprint('main')",
        name="无调度",
        category="no_schedule",
        instruction="把优化步骤删除",
    )
    assert "import numpy as np" in prompt
    assert "无调度" in prompt
    assert "RESULT: baseline=no_schedule" in prompt


def test_baseline_prompt_contains_output_contract():
    prompt = build_baseline_prompt(
        problem="test",
        main_code="print(1)",
        name="贪婪",
        category="greedy",
        instruction="用贪心替换",
    )
    assert "RESULT: baseline=greedy" in prompt
    assert "JSON" in prompt


def test_coder_node_skips_logistics_baselines_without_green_attachments(monkeypatch):
    """非物流附件不得强制 no_schedule/simple_pred/greedy。"""
    from math_agent.nodes.coder import coder_node, CoderDraft
    from math_agent.state import MathModelingState, ModelVersion
    from math_agent.tools.runner import RunResult

    s = MathModelingState(problem="锚杆预紧", output_dir="/tmp/test_coder_baseline")
    s.model_versions.append(ModelVersion(
        stage="final", description="test model",
        variables={"x": "v"}, figure_purposes=["plot1"],
    ))

    def mock_complete(prompt, *, schema=None, **kw):
        return CoderDraft(
            purpose="main plot",
            code="print('RESULT: baseline=ours T_max=80.0 K=0.18')",
        )

    def mock_run(code, *, workdir, timeout=60, **kw):
        return RunResult(
            success=True,
            stdout="RESULT: baseline=ours T_max=80.0 K=0.18",
            artifact_paths=[],
        )

    monkeypatch.setattr("math_agent.nodes.coder.complete", mock_complete)
    monkeypatch.setattr("math_agent.nodes.coder.run_python", mock_run)

    result = coder_node(s)
    artifacts = result["code_artifacts"]
    assert len(artifacts) == 1
    assert not any(a.category.startswith("baseline:") for a in artifacts)


def test_missing_baseline_items_only_for_green_logistics():
    from math_agent.nodes.coder import _missing_baseline_items
    from math_agent.state import DataFileInfo, MathModelingState

    empty = MathModelingState(problem="锚杆预紧")
    assert _missing_baseline_items(empty, []) == []

    green = MathModelingState(problem="城市物流")
    green.data_files = [
        DataFileInfo(filename=name, file_type="xlsx", path=name)
        for name in ("订单信息.xlsx", "距离矩阵.xlsx", "时间窗.xlsx", "客户坐标信息.xlsx")
    ]
    items = _missing_baseline_items(green, [])
    assert {item["category"] for item in items} == {"no_schedule", "simple_pred", "greedy"}


def test_main_figure_prompt_includes_ours_result_contract():
    """I1 回归：主方案 prompt 必须要求输出 RESULT: baseline=ours，否则对比表缺本文方案行。"""
    from math_agent.prompts.coder_figure_one import build_prompt_figure_one
    from math_agent.state import DataFileInfo, ModelVersion
    m = ModelVersion(stage="final", description="test", variables={"x": "v"})
    green_files = [
        DataFileInfo(filename=name, file_type="xlsx", path=name)
        for name in ("订单信息.xlsx", "距离矩阵.xlsx", "时间窗.xlsx", "客户坐标信息.xlsx")
    ]
    prompt = build_prompt_figure_one(m, "plot1", data_files=green_files)
    assert "RESULT: baseline=ours" in prompt
    assert "O(n^2)" in prompt
    assert "内存不超过 1 GB" in prompt
    assert "拆成容量可行的多次访问" in prompt
    assert "while unserved" in prompt
    assert "read_only" in prompt


def test_generic_figure_prompt_forbids_logistics_metrics():
    from math_agent.prompts.coder_figure_one import build_prompt_figure_one
    from math_agent.state import ModelVersion

    prompt = build_prompt_figure_one(
        ModelVersion(stage="final", description="锚杆预紧"),
        "主图",
    )
    assert "RESULT: baseline=ours" in prompt
    assert "total_cost" in prompt
    assert "禁止输出与本题无关的物流指标" in prompt
    assert "while unserved" not in prompt
    assert "Branch-and-Cut" not in prompt
    assert "Excel 附件必须遍历全部工作表" in prompt


def test_main_figure_prompt_lists_subquestion_outputs():
    """主证据图必须逐问输出 expected_output；支撑图不重复逐问。"""
    from math_agent.prompts.coder_figure_one import build_prompt_figure_one
    from math_agent.state import ModelVersion, ProblemBlueprint, SubQuestionBlueprint

    bp = ProblemBlueprint(
        core_task="锚杆预紧",
        subquestions=[
            SubQuestionBlueprint(
                id="1.2", task_type="evaluation",
                original_text="求临界预紧力矩。",
                expected_output="临界预紧力矩的数值。",
            ),
            SubQuestionBlueprint(
                id="2.2", task_type="evaluation",
                original_text="求工况A和B的Tmax。",
                expected_output="工况A和工况B下的 Tmax 数值及是否加钢带的结论。",
            ),
        ],
    )
    model = ModelVersion(stage="final", description="锚杆预紧模型")

    main_prompt = build_prompt_figure_one(model, "主图", blueprint=bp)
    assert "逐问数值输出要求" in main_prompt
    assert "问题 1.2：临界预紧力矩的数值。" in main_prompt
    assert "问题 2.2：工况A和工况B下的 Tmax" in main_prompt
    assert "Q1.2: 临界预紧力矩=" in main_prompt
    assert "不得静默跳过" in main_prompt

    support_prompt = build_prompt_figure_one(
        model, "补充图", blueprint=bp,
        canonical_evidence="RESULT: baseline=ours R²=0.99 Tmax=80.0",
    )
    assert "逐问数值输出要求" not in support_prompt
    assert "唯一主方案证据" in support_prompt


def test_main_figure_prompt_forbids_masking_negative_margins():
    """安全裕度等负值不得被 max(0,...) 截断掩盖。"""
    from math_agent.prompts.coder_figure_one import build_prompt_figure_one
    from math_agent.state import ModelVersion

    prompt = build_prompt_figure_one(ModelVersion(stage="final", description="锚杆预紧"), "主图")
    assert "禁止截断掩盖" in prompt
    assert "max(0, ...)/clip/截断" in prompt
    assert "安全裕度为负表示超限" in prompt


def test_supporting_figure_prompt_reuses_canonical_evidence():
    from math_agent.prompts.coder_figure_one import build_prompt_figure_one
    from math_agent.state import DataFileInfo, ModelVersion

    model = ModelVersion(stage="final", description="test")
    green_files = [
        DataFileInfo(filename=name, file_type="xlsx", path=name)
        for name in ("订单信息.xlsx", "距离矩阵.xlsx", "时间窗.xlsx", "客户坐标信息.xlsx")
    ]
    prompt = build_prompt_figure_one(
        model,
        "补充图",
        canonical_evidence="RESULT: baseline=ours total_cost=100 service_rate=0.95",
        data_files=green_files,
    )

    assert "唯一主方案证据" in prompt
    assert "禁止重新运行路径优化" in prompt
    assert "total_cost=100" in prompt


def test_coder_prompt_includes_data_file_paths():
    from math_agent.state import ModelVersion, DataFileInfo
    from math_agent.prompts.coder_figure_one import build_prompt_figure_one

    model = ModelVersion(
        stage="basic", description="VRP model",
        equations=["min total_cost"], variables={"x": "binary route"},
    )
    data_files = [DataFileInfo(
        filename="orders.xlsx", file_type="xlsx", path="orders.xlsx",
        summary={"sheets": [{"name": "Sheet1", "rows": 100, "cols": 3}]}
    )]
    prompt = build_prompt_figure_one(
        model, "plot cost chart", data_dir="/data/run1", data_files=data_files,
    )
    assert "/data/run1" in prompt
    assert "orders.xlsx" in prompt
    assert "pd.read_excel" in prompt


def test_coder_prompt_no_data_hint_when_empty():
    from math_agent.state import ModelVersion
    from math_agent.prompts.coder_figure_one import build_prompt_figure_one

    model = ModelVersion(
        stage="basic", description="model", equations=[], variables={},
    )
    prompt = build_prompt_figure_one(model, "plot chart", data_dir=None, data_files=[])
    assert "可用数据文件" not in prompt

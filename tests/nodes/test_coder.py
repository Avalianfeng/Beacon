from math_agent.state import (
    CodeArtifact,
    MathModelingState,
    ModelCodeConsistencyReport,
    ModelVersion,
)
from math_agent.nodes.coder import coder_node, CoderDraft
import pytest


@pytest.fixture(autouse=True)
def _allow_coder_llm(monkeypatch, request):
    if request.function.__name__ == "test_coder_generate_blocks_llm_without_flag":
        monkeypatch.delenv("MATH_AGENT_ALLOW_CODER_LLM", raising=False)
    else:
        monkeypatch.setenv("MATH_AGENT_ALLOW_CODER_LLM", "1")


def test_coder_generate_blocks_llm_without_flag(mocker, workdir):
    from math_agent.nodes.coder import coder_generate_node, coder_prepare_node

    state = MathModelingState(problem="p", output_dir=str(workdir), allow_coder_llm=False)
    state.model_versions.append(ModelVersion(stage="final", description="d"))
    state = state.model_copy(update=coder_prepare_node(state))
    complete = mocker.patch("math_agent.nodes.coder.complete")

    delta = coder_generate_node(state)

    assert complete.call_count == 0
    assert delta["coder_phase"] == "done"
    assert delta["coder_work_queue"] == []
    assert delta["coder_pending_draft"] == {}
    assert any(
        e == "coder: LLM generate disabled; register T-19, put source/inject/, or --allow-coder-llm"
        for e in delta["errors"]
    )


def test_coder_runs_code_and_records_artifact(mocker, workdir):
    mocker.patch(
        "math_agent.nodes.coder.complete",
        return_value=CoderDraft(
            purpose="solve",
            code=("import matplotlib; matplotlib.use('Agg'); "
                  "import matplotlib.pyplot as plt; plt.savefig('fig.png'); "
                  "print('hello'); print('RESULT: baseline=ours T_max=10 K=0.18')"),
        ),
    )
    s = MathModelingState(problem="p", output_dir=str(workdir))
    s.model_versions.append(ModelVersion(stage="final", description="d", equations=["x=1"]))
    delta = coder_node(s)
    assert delta["code_artifacts"][0].success
    assert "hello" in delta["code_artifacts"][0].stdout


def test_consistency_retry_reuses_committed_primary_code_and_feedback(mocker, workdir):
    from math_agent.nodes.coder import coder_generate_node, coder_prepare_node

    previous_code = "print('previous-primary-sentinel')"
    state = MathModelingState(problem="p", output_dir=str(workdir))
    state.model_versions.append(ModelVersion(stage="final", description="d"))
    state.code_artifacts = [
        CodeArtifact(
            purpose="primary", code=previous_code, success=True,
            category="figure", evidence_role="primary", batch=1,
        )
    ]
    state.model_code_reports = [
        ModelCodeConsistencyReport(
            score=3, approved=False,
            issues=["缺少容量约束"], suggestions=["输出目标函数分解"],
        )
    ]
    state = state.model_copy(update=coder_prepare_node(state))
    complete = mocker.patch(
        "math_agent.nodes.coder.complete",
        return_value=CoderDraft(purpose="revised", code="print('revised')"),
    )

    delta = coder_generate_node(state)

    prompt = complete.call_args.args[0]
    assert previous_code in prompt
    assert "缺少容量约束" in prompt
    assert "输出目标函数分解" in prompt
    assert delta["coder_phase"] == "execute"


def test_supporting_figure_uses_strong_model_without_primary_source(mocker, workdir):
    from math_agent.nodes.coder import _supporting_figure_model, coder_generate_node

    primary_code = "print('previous-primary-sentinel')\n" * 40
    state = MathModelingState(problem="p", output_dir=str(workdir))
    state.model_versions.append(ModelVersion(stage="final", description="d"))
    state.coder_work_artifacts = [
        CodeArtifact(
            purpose="primary", code=primary_code, success=True,
            category="figure", evidence_role="primary", batch=1,
            stdout="RESULT: baseline=ours total_cost=100 service_rate=0.95 vehicles=3",
        )
    ]
    state.coder_phase = "generate"
    state.coder_work_queue = [{
        "kind": "figure", "id": "figure:1", "index": 1,
        "purpose": "补充图", "attempt": 0, "prev_err": "", "prev_kind": "",
        "evidence_target": "supporting",
    }]
    complete = mocker.patch(
        "math_agent.nodes.coder.complete",
        return_value=CoderDraft(purpose="fig", code="print(1)"),
    )

    coder_generate_node(state)

    prompt = complete.call_args.args[0]
    assert "previous-primary-sentinel" not in prompt
    assert "total_cost=100" in prompt
    assert complete.call_args.kwargs["model"] == _supporting_figure_model()


def test_coder_auto_fixes_literal_backslash_n_before_running(mocker, workdir):
    """字符串外字面量 \\n 自动修复后进入执行（L2），不再拒绝重试（r8 死循环成因）。"""
    from math_agent.nodes.coder import coder_node, CoderDraft
    from math_agent.tools.runner import RunResult

    mocker.patch(
        "math_agent.nodes.coder.complete",
        return_value=CoderDraft(
            purpose="solve",
            code=("import matplotlib; matplotlib.use('Agg')\n"
                  "import matplotlib.pyplot as plt\n"
                  "plt.savefig('fig.png')\n"
                  "control_B = '压陷' if Tmax_B == T_bearing_B else '屈服'"
                  "\\nuse_steel_A = control_A == '压陷'\n"
                  "print('RESULT: baseline=ours T_max=10 K=0.18')"),
        ),
    )
    spy_run = mocker.patch(
        "math_agent.nodes.coder.run_python",
        side_effect=lambda code, **kw: RunResult(
            success=True,
            stdout="RESULT: baseline=ours T_max=10 K=0.18",
            artifact_paths=["fig.png"],
        ),
    )
    s = MathModelingState(problem="p", output_dir=str(workdir))
    s.model_versions.append(ModelVersion(stage="final", description="d"))

    delta = coder_node(s)

    figures = [a for a in delta["code_artifacts"] if a.category == "figure"]
    assert figures[0].success is True
    assert "\\n" not in figures[0].code  # 修复后 artifact 内无字面量 \n
    assert spy_run.call_count >= 1
    assert "\\n" not in spy_run.call_args_list[0].args[0]


def test_coder_retries_once_on_failure(mocker, workdir):
    drafts = [
        CoderDraft(purpose="solve", code="raise RuntimeError('x')"),
        CoderDraft(
            purpose="solve",
            code=("import matplotlib; matplotlib.use('Agg'); "
                  "import matplotlib.pyplot as plt; plt.savefig('fig.png'); "
                  "print('ok'); print('RESULT: baseline=ours T_max=10 K=0.18')"),
        ),
    ]
    mocker.patch("math_agent.nodes.coder.complete", side_effect=drafts)
    s = MathModelingState(problem="p", output_dir=str(workdir))
    s.model_versions.append(ModelVersion(stage="final", description="d"))
    delta = coder_node(s)
    # 应当保留两个 figure artifact：第一次失败、第二次成功
    # （Phase 2 起主方案成功后还会追加 baseline 对照方案，按 category 过滤）
    arts = [a for a in delta["code_artifacts"] if a.category == "figure"]
    assert len(arts) == 2
    assert arts[0].success is False
    assert arts[1].success is True


def test_coder_records_error_when_all_retries_fail(mocker, workdir):
    """所有尝试都失败时，应在 state.errors 中显式记录。

    用 itertools.cycle 而非固定列表：若未来 MAX_CODE_RETRIES 上调，
    测试不会因 mock 耗尽而 StopIteration 掩盖真正问题。
    """
    from itertools import cycle
    mocker.patch(
        "math_agent.nodes.coder.complete",
        side_effect=cycle([CoderDraft(purpose="solve", code="raise RuntimeError('boom')")]),
    )
    s = MathModelingState(problem="p", output_dir=str(workdir))
    s.model_versions.append(ModelVersion(stage="final", description="d"))

    delta = coder_node(s)

    assert len(delta["code_artifacts"]) >= 1
    assert all(a.success is False for a in delta["code_artifacts"])
    assert "errors" in delta and delta["errors"]
    assert delta["errors"][0].startswith("coder:")


def test_coder_prompt_on_timeout_asks_to_shrink_scale(mocker, workdir):
    """attempt_0 超时时，attempt_1 的 prompt 应命中"缩小规模"提示而不是喂 stderr 修 bug。"""
    from math_agent.tools.runner import RunResult
    from unittest.mock import call

    drafts = [
        CoderDraft(purpose="s", code="import time; time.sleep(999)"),
        CoderDraft(purpose="s", code="print('ok')"),
    ]
    spy_complete = mocker.patch("math_agent.nodes.coder.complete", side_effect=drafts)
    # 第一次跑成 timeout，第二次跑成成功——不让真 subprocess 跑
    mocker.patch(
        "math_agent.nodes.coder.run_python",
        side_effect=[
            RunResult(success=False, stderr="timeout after 300s", error_kind="timeout"),
            RunResult(
                success=True,
                stdout="RESULT: baseline=ours T_max=10 K=0.18",
                artifact_paths=["fig.png"],
                error_kind="",
            ),
        ],
    )

    s = MathModelingState(problem="p", output_dir=str(workdir))
    s.model_versions.append(ModelVersion(stage="final", description="d"))
    coder_node(s)

    # 第 2 次 complete 的 prompt 应含"缩小"关键词，不含"stderr 节选"
    second_prompt = spy_complete.call_args_list[1].args[0]
    assert "缩小" in second_prompt
    assert "stderr 节选" not in second_prompt


def test_coder_prompt_on_runtime_asks_to_fix_via_stderr(mocker, workdir):
    """attempt_0 runtime 失败时，attempt_1 的 prompt 应喂 stderr 让 LLM 修 bug。"""
    from math_agent.tools.runner import RunResult

    drafts = [
        CoderDraft(purpose="s", code="raise ValueError('boom')"),
        CoderDraft(
            purpose="s",
            code="print('RESULT: baseline=ours T_max=10 K=0.18')",
        ),
    ]
    spy_complete = mocker.patch("math_agent.nodes.coder.complete", side_effect=drafts)
    mocker.patch(
        "math_agent.nodes.coder.run_python",
        side_effect=[
            RunResult(success=False, stderr="Traceback ... ValueError: boom",
                      error_kind="runtime"),
            RunResult(
                success=True,
                stdout="RESULT: baseline=ours T_max=10 K=0.18",
                artifact_paths=["fig.png"],
                error_kind="",
            ),
        ],
    )

    s = MathModelingState(problem="p", output_dir=str(workdir))
    s.model_versions.append(ModelVersion(stage="final", description="d"))
    coder_node(s)

    second_prompt = spy_complete.call_args_list[1].args[0]
    assert "stderr 节选" in second_prompt
    assert "ValueError: boom" in second_prompt
    assert "缩小" not in second_prompt
    assert "上一版可运行脚本" in second_prompt
    assert "raise ValueError('boom')" in second_prompt


def test_coder_applies_safe_local_repair_without_second_llm_call(mocker, workdir):
    """已知机械错误应复用上一版源码本地修补，避免再等待一次长模型请求。"""
    from math_agent.tools.runner import RunResult

    spy_complete = mocker.patch(
        "math_agent.nodes.coder.complete",
        return_value=CoderDraft(
            purpose="plot",
            code=("import matplotlib.rcparams as rc\n"
                  "print('RESULT: baseline=ours T_max=10 K=0.18')"),
        ),
    )
    spy_run = mocker.patch(
        "math_agent.nodes.coder.run_python",
        side_effect=[
            RunResult(
                success=False,
                stderr="ModuleNotFoundError: No module named 'matplotlib.rcparams'",
                error_kind="runtime",
            ),
            RunResult(
                success=True,
                stdout="RESULT: baseline=ours T_max=10 K=0.18",
                artifact_paths=["fig.png"],
            ),
        ],
    )
    mocker.patch("math_agent.nodes.coder._baseline_items", return_value=[])
    state = MathModelingState(problem="p", output_dir=str(workdir))
    state.model_versions.append(ModelVersion(stage="final", description="d"))

    delta = coder_node(state)

    figures = [a for a in delta["code_artifacts"] if a.category == "figure"]
    assert spy_complete.call_count == 1
    assert spy_run.call_count == 2
    assert figures[-1].success is True
    assert "from matplotlib import rcParams as rc" in figures[-1].code


def test_local_repair_uses_integer_distance_columns_after_int64_keyerror():
    from math_agent.nodes.coder import _local_repair_draft

    draft = _local_repair_draft(
        {
            "purpose": "primary",
            "prev_err": "pandas Int64Engine.get_loc KeyError: '0'",
        },
        "value = dist_df.loc[i, str(j)]\n",
    )

    assert draft is not None
    assert "dist_df.loc[i, j]" in draft.code
    assert "str(j)" not in draft.code


def test_local_repair_compacts_dense_distance_dictionary():
    from math_agent.nodes.coder import _local_repair_draft

    code = """cust_ids = list(dist_df.index)
coord_keys = set(coord_dict.keys())
dist_dict = {}
for i in cust_ids:
    for j in cust_ids:
        if i in coord_keys and j in coord_keys:
            dist_dict[(i, j)] = dist_df.loc[i, j]

# 补充可能缺失的距离（使用欧氏距离）
coord_keys_list = list(coord_keys)
for i in coord_keys_list:
    for j in coord_keys_list:
        if (i, j) not in dist_dict:
            xi, yi = coord_dict[i]
            xj, yj = coord_dict[j]
            dist_dict[(i, j)] = np.sqrt((xi-xj)**2 + (yi-yj)**2)
value = dist_dict[(0, 1)]
"""
    draft = _local_repair_draft(
        {"purpose": "primary", "prev_err": "Int64Engine KeyError: '0'"}, code,
    )

    assert draft is not None
    assert "class DistanceLookup" in draft.code
    assert "for j in cust_ids" not in draft.code
    assert "value = dist_dict[(0, 1)]" in draft.code


def test_local_repair_splits_overcapacity_demand_and_prevents_no_progress(workdir):
    from math_agent.nodes.coder import _local_repair_draft
    from math_agent.tools.runner import run_python

    code = """import numpy as np
import pandas as pd
customers = pd.DataFrame([{'重量': 1200.0, '体积': 3.0}, {'重量': np.nan, '体积': np.nan}])
VEHICLE_CAPACITY_WEIGHT = 500.0
VEHICLE_CAPACITY_VOLUME = 2.0
assigned = np.zeros(len(customers), dtype=bool)
vehicle_type = 0
routes = []
while not np.all(assigned):
    current_route = []
    for idx in np.where(~assigned)[0]:
        if customers.loc[idx, '重量'] <= VEHICLE_CAPACITY_WEIGHT and customers.loc[idx, '体积'] <= VEHICLE_CAPACITY_VOLUME:
            assigned[idx] = True
            current_route.append(idx)
            break
    if len(current_route) > 0:
        routes.append(current_route)
    vehicle_type = 1 - vehicle_type
print(f'RESULT: baseline=ours total_cost={len(routes)} vehicles={len(routes)} service_rate={assigned.mean()} total_carbon={len(customers)}')
"""

    draft = _local_repair_draft(
        {"purpose": "primary", "prev_kind": "timeout", "prev_err": "timeout after 120s"},
        code,
    )

    assert draft is not None
    assert "BEACON_CAPACITY_SPLIT" in draft.code
    assert "BEACON_PROGRESS_GUARD" in draft.code
    assert "_beacon_weight > 0.0 or _beacon_volume > 0.0" in draft.code
    result = run_python(draft.code, workdir=workdir / "capacity-repair", timeout=5)
    assert result.success, result.stderr
    assert "service_rate=1.0" in result.stdout


def test_code_timeout_is_configurable_and_bounded(monkeypatch):
    from math_agent.nodes.coder import _code_timeout_seconds

    monkeypatch.setenv("MATH_AGENT_CODE_TIMEOUT", "75")
    assert _code_timeout_seconds() == 75
    monkeypatch.setenv("MATH_AGENT_CODE_TIMEOUT", "1")
    assert _code_timeout_seconds() == 30


def test_code_timeout_defaults_to_hard_120_seconds(monkeypatch):
    from math_agent.nodes.coder import _code_timeout_seconds

    monkeypatch.delenv("MATH_AGENT_CODE_TIMEOUT", raising=False)
    assert _code_timeout_seconds() == 120


def test_service_time_contract_rejects_code_that_disagrees_with_problem():
    from math_agent.nodes.coder import _service_time_contract_error

    state = MathModelingState(
        problem="城市配送",
        background="每个客户服务时间约定为20分钟。",
    )

    assert "口径不一致" in _service_time_contract_error(
        "SERVICE_TIME = 10.0\n", state,
    )
    assert _service_time_contract_error("SERVICE_TIME = 20.0\n", state) == ""
    assert "observed_minutes=6" in _service_time_contract_error(
        "SERVICE_TIME = 0.1  # h\n", state,
    )


def test_local_repair_aligns_service_time_with_problem_contract():
    from math_agent.nodes.coder import _local_repair_draft

    draft = _local_repair_draft(
        {
            "purpose": "primary",
            "prev_err": (
                "题面规定统一客户服务时间为 20 分钟，"
                "代码 SERVICE_TIME=10 分钟，模型—代码口径不一致"
            ),
        },
        "SERVICE_TIME = 10.0\nprint('ok')\n",
    )

    assert draft is not None
    assert "SERVICE_TIME = 20.0" in draft.code

    ascii_draft = _local_repair_draft(
        {
            "purpose": "primary",
            "prev_err": "service_time_contract expected=20 observed=10 SERVICE_TIME",
        },
        "SERVICE_TIME = 10.0\nprint('ok')\n",
    )
    assert ascii_draft is not None
    assert "SERVICE_TIME = 20.0" in ascii_draft.code

    hours_draft = _local_repair_draft(
        {
            "purpose": "primary",
            "prev_err": (
                "SERVICE_TIME mismatch; service_time_contract "
                "expected_minutes=20 observed_minutes=6 assignment_unit=hours"
            ),
        },
        "SERVICE_TIME = 0.1  # h\nprint('ok')\n",
    )
    assert hours_draft is not None
    assert "SERVICE_TIME = 0.3333333333333333  # h" in hours_draft.code


def test_local_repair_restores_assignment_hidden_by_literal_newline():
    from math_agent.nodes.coder import _local_repair_draft

    code = "# 初始化未服务客户\\nunvisited = [1, 2]\nprint(len(unvisited))\n"
    draft = _local_repair_draft(
        {"purpose": "primary", "prev_err": "NameError: name 'unvisited' is not defined"},
        code,
    )

    assert draft is not None
    assert "# 初始化未服务客户\nunvisited = [1, 2]" in draft.code

    joined = _local_repair_draft(
        {"purpose": "primary", "prev_err": "unexpected character after line continuation"},
        "vehicles = []\\nunserved = []\\nused_ev = 0\n",
    )
    assert joined is not None
    assert joined.code.splitlines() == ["vehicles = []", "unserved = []", "used_ev = 0"]


def test_timeout_on_aggregated_unvisited_solver_is_split_in_place(tmp_path):
    from math_agent.nodes.coder import _local_repair_draft

    state = MathModelingState(
        problem="城市配送",
        data_dir=str(tmp_path),
        output_dir=str(tmp_path),
    )
    broken = """import numpy as np
import pandas as pd
df_cust_demand = df_orders.groupby('customer_id').sum()
df_cust = pd.DataFrame([{'customer_id': 1, 'total_weight': 1200.0, 'total_volume': 3.0}])
CAPACITY_WEIGHT = 500.0
CAPACITY_VOLUME = 2.0
cust_idx_to_global = {0: 1}
def find_nearest(unvisited, current_node, dist_matrix, cust_idx_to_global):
    best_dist = np.inf
    best_global = None
    for u in unvisited:
        global_u = cust_idx_to_global[u]
        d = 1
        if d < best_dist:
            best_dist = d
            best_global = global_u
    return best_global, best_dist
unvisited = list(range(len(df_cust_demand)))
while unvisited:
    served_this_vehicle = []
    best_global, best_dist = find_nearest(unvisited, 0, None, cust_idx_to_global)
    if best_global is None:
        break
    cust_idx = global_to_cust_idx[best_global]
    served_this_vehicle.append(cust_idx)
    unvisited.remove(cust_idx)
    # 结束当前车，返回配送中心
    route.append(0)
"""

    draft = _local_repair_draft(
        {
            "purpose": "primary",
            "prev_kind": "timeout",
            "prev_err": "timeout after 120s",
        },
        broken,
        state,
    )

    assert draft is not None
    assert "BEACON_AGGREGATE_SPLIT" in draft.code
    assert "BEACON_UNVISITED_PROGRESS" in draft.code
    assert "best_task = u" in draft.code
    assert "cust_idx = best_task" in draft.code
    assert "while unvisited:\n    pass" not in draft.code


def test_local_baseline_repair_reuses_code_and_fixes_relative_attachment_root(tmp_path):
    from math_agent.nodes.coder import _local_baseline_repair_draft

    data_dir = tmp_path / "附件"
    draft = _local_baseline_repair_draft(
        {
            "name": "贪婪启发式",
            "prev_err": "FileNotFoundError: 附件\\订单信息.xlsx",
        },
        data_dir=str(data_dir),
        previous_code="from pathlib import Path\ndata_dir = Path('./附件')\n",
    )

    assert draft is not None
    assert repr(str(data_dir.resolve())) in draft.code
    assert "Path('./附件')" not in draft.code


def test_planar_km_coordinate_schema_rejects_haversine_usage():
    from math_agent.nodes.coder import _uses_haversine_on_planar_km_schema
    from math_agent.state import DataFileInfo

    files = [DataFileInfo(
        filename="coords.xlsx", file_type="xlsx", path="coords.xlsx",
        summary={"columns": ["ID", "X (km)", "Y (km)"]},
    ), DataFileInfo(
        filename="distance.xlsx", file_type="xlsx", path="distance.xlsx",
        summary={"columns": 100},
    )]
    code = "def haversine(a, b): return 1\nd = haversine(p1, p2)"

    assert _uses_haversine_on_planar_km_schema(code, files) is True
    assert _uses_haversine_on_planar_km_schema("d = eucl(p1, p2)", files) is False


def test_coder_retries_when_exit_zero_stdout_reports_failure(mocker, workdir):
    """真实故障回归：脚本吞掉异常并 exit 0 时，artifact 仍必须标记失败并重试。"""
    drafts = [
        CoderDraft(
            purpose="solve",
            code=("print(\"Error during execution: '纬度'\")\n"
                  "print('RESULT: baseline=ours T_max=0 K=0')"),
        ),
        CoderDraft(
            purpose="solve",
            code=("import matplotlib; matplotlib.use('Agg'); "
                  "import matplotlib.pyplot as plt; plt.savefig('fig.png'); "
                  "print('RESULT: baseline=ours T_max=2470.93 K=0.18 T_crit=80 R2=0.99')"),
        ),
    ]
    mocker.patch("math_agent.nodes.coder.complete", side_effect=drafts)
    state = MathModelingState(problem="p", output_dir=str(workdir))
    state.model_versions.append(ModelVersion(stage="final", description="d"))

    delta = coder_node(state)

    figures = [a for a in delta["code_artifacts"] if a.category == "figure"]
    assert len(figures) == 2
    assert figures[0].success is False
    assert "Error during execution" in figures[0].stderr
    assert figures[1].success is True


def test_coder_rejects_impossible_vehicle_count_using_input_scale(mocker, workdir):
    from math_agent.state import DataFileInfo
    input_path = workdir / "订单.xlsx"
    input_path.write_bytes(b"fixture")

    drafts = [
        CoderDraft(
            purpose="solve",
            code=("print('RESULT: baseline=ours T_max=4812127.99 "
                  "veh_count=19011 T_crit=80 K=0.18 R2=0.92')"),
        ),
        CoderDraft(
            purpose="solve",
            code=(f"open({str(input_path)!r}, 'rb').read(1)\n"
                  "import matplotlib; matplotlib.use('Agg'); "
                  "import matplotlib.pyplot as plt; plt.savefig('fig.png')\n"
                  "T_max = 2470.93\nT_crit = 80\nK = 0.18\nR2 = 0.99\n"
                  "print(f'RESULT: baseline=ours T_max={T_max} T_crit={T_crit} "
                  "K={K} R2={R2}')"),
        ),
    ]
    mocker.patch("math_agent.nodes.coder.complete", side_effect=drafts)
    state = MathModelingState(problem="p", output_dir=str(workdir))
    state.data_files = [DataFileInfo(
        filename="订单.xlsx", file_type="xlsx", path="订单.xlsx",
        summary={"rows": 2170},
    )]
    state.model_versions.append(ModelVersion(stage="final", description="d"))

    delta = coder_node(state)

    figures = [a for a in delta["code_artifacts"] if a.category == "figure"]
    assert figures[0].success is False
    assert "veh_count" in figures[0].stderr
    assert figures[1].success is True


def test_coder_rejects_plausible_but_hardcoded_primary_results(mocker, workdir):
    """范围合理也不够：有附件时，主证据必须具备真实数据读取血缘。"""
    from math_agent.state import DataFileInfo
    input_path = workdir / "订单.xlsx"
    input_path.write_bytes(b"fixture")

    drafts = [
        CoderDraft(
            purpose="fake",
            code=("print('RESULT: baseline=ours T_max=46750 T_crit=80 "
                  "K=0.18 R2=0.88')"),
        ),
        CoderDraft(
            purpose="real",
            code=(f"open({str(input_path)!r}, 'rb').read(1)\n"
                  "import matplotlib; matplotlib.use('Agg'); "
                  "import matplotlib.pyplot as plt; plt.savefig('fig.png')\n"
                  "T_max = len(open(" + repr(str(input_path)) + ", 'rb').read()) + 46749\n"
                  "T_crit = 80\nK = 0.18\nR2 = 0.88\n"
                  "print(f'RESULT: baseline=ours T_max={T_max} T_crit={T_crit} "
                  "K={K} R2={R2}')"),
        ),
    ]
    mocker.patch("math_agent.nodes.coder.complete", side_effect=drafts)
    mocker.patch("math_agent.nodes.coder._baseline_items", return_value=[])
    state = MathModelingState(problem="p", output_dir=str(workdir))
    state.data_files = [DataFileInfo(
        filename="订单.xlsx", file_type="xlsx", path="订单.xlsx", summary={"rows": 2170},
    )]
    state.model_versions.append(ModelVersion(stage="final", description="d"))

    delta = coder_node(state)

    figures = [a for a in delta["code_artifacts"] if a.category == "figure"]
    assert figures[0].success is False
    assert "硬编码" in figures[0].stderr
    assert figures[1].success is True



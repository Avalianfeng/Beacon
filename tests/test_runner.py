from pathlib import Path

import pytest

from math_agent.tools.runner import run_python, RunResult


def test_runner_runs_simple_code(workdir):
    res = run_python("print(1 + 1)", workdir=workdir)
    assert res.success
    assert "2" in res.stdout


def test_runner_captures_stderr_on_error(workdir):
    res = run_python("raise ValueError('boom')", workdir=workdir)
    assert not res.success
    assert "boom" in res.stderr


def test_runner_times_out(workdir):
    res = run_python("import time; time.sleep(30)", workdir=workdir, timeout=1)
    assert not res.success
    assert "timeout" in res.stderr.lower() or "killed" in res.stderr.lower()


def test_runner_lists_produced_files(workdir):
    code = "open('out.txt','w').write('x')"
    res = run_python(code, workdir=workdir)
    assert res.success
    assert any(p.endswith("out.txt") for p in res.artifact_paths)


def test_runner_strips_host_env(workdir, monkeypatch):
    """父进程的敏感环境变量不应继承到子进程。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leaked")
    res = run_python(
        "import os; print(os.environ.get('OPENAI_API_KEY', 'MISSING'))",
        workdir=workdir,
    )
    assert res.success
    assert "MISSING" in res.stdout


def test_runner_accepts_relative_workdir(tmp_path, monkeypatch):
    """回归：workdir 传相对路径时不应触发 cwd+script 双重前缀。

    历史 bug：subprocess 切换 cwd 后，python 解释器把 argv 里的相对 script
    解释为相对于新 cwd，导致 "attempt_0/runs/.../attempt_0/_run.py"
    （所有平台都有此行为，不是 Windows 特有）。
    """
    monkeypatch.chdir(tmp_path)
    rel = Path("runs/x/attempt_0")
    res = run_python("print('relpath_ok')", workdir=rel)
    assert res.success, f"stderr={res.stderr!r}"
    assert "relpath_ok" in res.stdout


def test_runner_result_carries_error_kind_on_timeout(workdir):
    res = run_python("import time; time.sleep(30)", workdir=workdir, timeout=1)
    assert not res.success
    assert res.error_kind == "timeout"


def test_runner_result_carries_error_kind_on_runtime(workdir):
    res = run_python("raise ValueError('x')", workdir=workdir)
    assert not res.success
    assert res.error_kind == "runtime"


def test_runner_result_error_kind_empty_on_success(workdir):
    res = run_python("print('hi')", workdir=workdir)
    assert res.success
    assert res.error_kind == ""


def test_extract_numeric_results_baseline_format():
    """RESULT: baseline=X metric1=Y metric2=Z 格式。"""
    from math_agent.tools.runner import extract_numeric_results
    stdout = (
        "一些输出...\n"
        "RESULT: baseline=no_schedule total_cost=1245.3 service_rate=0.82\n"
        "更多输出\n"
        "RESULT: baseline=greedy total_cost=980.0 service_rate=0.91 solve_time=12.5\n"
    )
    results = extract_numeric_results(stdout)
    assert "no_schedule" in results
    assert results["no_schedule"]["total_cost"] == 1245.3
    assert results["no_schedule"]["service_rate"] == 0.82
    assert results["greedy"]["solve_time"] == 12.5


def test_extract_numeric_results_scenario_format():
    """RESULT: scenario=X metric=Y 格式也支持。"""
    from math_agent.tools.runner import extract_numeric_results
    stdout = "RESULT: scenario=high_demand objective=9876.5\n"
    results = extract_numeric_results(stdout)
    assert "high_demand" in results
    assert results["high_demand"]["objective"] == 9876.5


def test_extract_numeric_results_no_result_lines():
    """没有 RESULT 行返回空 dict。"""
    from math_agent.tools.runner import extract_numeric_results
    assert extract_numeric_results("普通输出\n没有结果行") == {}
    assert extract_numeric_results("") == {}


def test_extract_numeric_results_ignores_malformed():
    """RESULT 行缺 key=value 对时跳过。"""
    from math_agent.tools.runner import extract_numeric_results
    stdout = "RESULT: baseline=test\n"  # 没有 metric=value
    results = extract_numeric_results(stdout)
    assert results == {} or results.get("test") == {}


def test_validate_numeric_results_rejects_exit_zero_error_marker():
    """进程退出码为 0 也不能掩盖脚本自行打印的数据加载失败。"""
    from math_agent.tools.runner import validate_numeric_results

    valid, reason, _ = validate_numeric_results(
        "Data loading failed: '纬度'\n"
        "RESULT: baseline=ours total_cost=0 service_rate=0",
        require_result=True,
    )

    assert valid is False
    assert "Data loading failed" in reason


def test_validate_numeric_results_rejects_nonfinite_value_outside_result_line():
    from math_agent.tools.runner import validate_numeric_results

    valid, reason, _ = validate_numeric_results(
        "预测重量均值=nan\n"
        "RESULT: baseline=simple_pred total_cost=300 service_rate=1",
        require_result=True,
    )

    assert valid is False
    assert "非有限" in reason


def test_validate_numeric_results_rejects_impossible_entity_count():
    """实体数量不能远大于输入数据能够支持的规模。"""
    from math_agent.tools.runner import validate_numeric_results

    valid, reason, _ = validate_numeric_results(
        "RESULT: baseline=ours total_cost=4812127.99 veh_count=19011 service_rate=0.92",
        require_result=True,
        max_entity_count=2170,
    )

    assert valid is False
    assert "veh_count" in reason


def test_validate_numeric_results_accepts_plausible_metrics():
    from math_agent.tools.runner import validate_numeric_results

    valid, reason, parsed = validate_numeric_results(
        "RESULT: baseline=ours total_cost=2470.93 vehicles=7 service_rate=1.0 total_carbon=96.41",
        require_result=True,
        max_entity_count=2170,
        expected_identifier="ours",
    )

    assert valid is True, reason
    assert parsed["ours"]["vehicles"] == 7


@pytest.mark.parametrize(
    ("metrics", "needle"),
    [
        ("delivery_time=-1 total_cost=20 vehicles=1 service_rate=0.9", "delivery_time"),
        ("delivery_time=1 total_cost=20 vehicles=1 service_rate=1.01", "service_rate"),
        ("delivery_time=1 total_cost=20 vehicles=2171 service_rate=0.9", "vehicles"),
    ],
)
def test_validate_numeric_results_rejects_domain_bounds(metrics, needle):
    from math_agent.tools.runner import validate_numeric_results

    valid, reason, _ = validate_numeric_results(
        f"RESULT: baseline=ours {metrics}",
        require_result=True,
        max_entity_count=2170,
    )

    assert valid is False
    assert needle in reason


def test_validate_numeric_results_requires_enough_primary_metrics():
    from math_agent.tools.runner import validate_numeric_results

    valid, reason, _ = validate_numeric_results(
        "RESULT: baseline=ours total_cost=46750 service_rate=0.88",
        require_result=True,
        min_metrics_per_result=4,
    )

    assert valid is False
    assert "至少需要 4" in reason


def test_validate_numeric_results_min_metrics_only_applies_to_ours():
    """同 stdout 对照行可少指标；下限只打 ours，避免对照门反杀主证据。"""
    from math_agent.tools.runner import validate_numeric_results

    valid, reason, parsed = validate_numeric_results(
        "RESULT: baseline=ours total_cost=80 service_rate=0.95 vehicles=7 mae=1.2\n"
        "RESULT: baseline=WD90 mae=2.5\n"
        "RESULT: baseline=YOY mae=3.1\n",
        require_result=True,
        min_metrics_per_result=4,
    )

    assert valid is True, reason
    assert set(parsed) == {"ours", "WD90", "YOY"}
    assert len(parsed["WD90"]) == 1


def test_validate_numeric_results_limitation_exempts_metric_gap():
    """LIMITATION 声明可豁免指标缺口：模型适用边界是合法标注而非失败。"""
    from math_agent.tools.runner import validate_numeric_results

    valid, reason, _ = validate_numeric_results(
        "LIMITATION: Q3.2 当 e>10mm 时 P_ecc 公式根号内为负，模型不可用。\n"
        "LIMITATION: Q4 当 f<0.5 时 Topt 公式发散，模型不可用。\n"
        "RESULT: baseline=ours total_cost=46750 service_rate=0.88",
        require_result=True,
        min_metrics_per_result=4,
    )

    assert valid is True, reason


def test_validate_numeric_results_limitation_does_not_exempt_all_metrics():
    """LIMITATION 不能豁免全部指标：至少保留一半真实指标，防止凑数。"""
    from math_agent.tools.runner import validate_numeric_results

    valid, reason, _ = validate_numeric_results(
        "LIMITATION: Q1 公式不可用。\n"
        "LIMITATION: Q2 公式不可用。\n"
        "LIMITATION: Q3 公式不可用。\n"
        "RESULT: baseline=ours total_cost=46750",
        require_result=True,
        min_metrics_per_result=4,
    )

    assert valid is False
    assert "至少需要 4" in reason


def test_validate_numeric_results_empty_limitation_is_invalid():
    """空洞声明（过短/无实质内容）不计数，不能豁免缺口。"""
    from math_agent.tools.runner import extract_limitations, validate_numeric_results

    assert extract_limitations("LIMITATION: 无\n") == []
    assert extract_limitations("LIMITATION: nan\n") == []

    valid, reason, _ = validate_numeric_results(
        "LIMITATION: 无\n"
        "RESULT: baseline=ours total_cost=46750 service_rate=0.88",
        require_result=True,
        min_metrics_per_result=4,
    )

    assert valid is False
    assert "至少需要 4" in reason


def test_validate_code_data_usage_rejects_hardcoded_results():
    from math_agent.tools.runner import validate_code_data_usage

    valid, reason = validate_code_data_usage(
        "total_cost = 46750\nprint(total_cost)", ["订单.xlsx", "客户坐标.xlsx"],
    )

    assert valid is False
    assert "硬编码" in reason


def test_validate_code_data_usage_accepts_real_attachment_read():
    from math_agent.tools.runner import validate_code_data_usage

    valid, reason = validate_code_data_usage(
        "import pandas as pd\ndf = pd.read_excel('订单.xlsx')", ["订单.xlsx"],
    )

    assert valid is True, reason


def test_validate_code_data_usage_rejects_read_then_constant_result():
    from math_agent.tools.runner import validate_code_data_usage

    valid, reason = validate_code_data_usage(
        "open('orders.xlsx', 'rb').read(1)\n"
        "print('RESULT: baseline=ours total_cost=46750 vehicles=18 "
        "service_rate=0.88 total_carbon=850')",
        ["orders.xlsx"],
    )

    assert valid is False
    assert "硬编码" in reason


def test_run_python_audits_actual_attachment_reads(workdir):
    attachment = workdir / "orders.xlsx"
    attachment.write_bytes(b"fixture")

    read = run_python(
        f"open({str(attachment)!r}, 'rb').read(1)\nprint('ok')",
        workdir=workdir / "read",
        expected_input_paths=[attachment],
    )
    ignored = run_python(
        "print('ok')",
        workdir=workdir / "ignored",
        expected_input_paths=[attachment],
    )

    assert str(attachment).casefold() in read.read_paths
    assert ignored.read_paths == []


def test_validate_code_data_usage_accepts_dynamic_directory_discovery():
    from math_agent.tools.runner import validate_code_data_usage

    valid, reason = validate_code_data_usage(
        "from pathlib import Path\nimport pandas as pd\n"
        "files = list(Path('data').glob('*.xlsx'))\ndf = pd.read_excel(files[0])",
        ["订单.xlsx"],
    )

    assert valid is True, reason


def test_auto_fix_imports_handles_qualified_pyplot_after_matplotlib_import():
    from math_agent.tools.runner import _auto_fix_imports
    code = "import matplotlib\nmatplotlib.pyplot.plot([1, 2])"
    fixed = _auto_fix_imports(code)
    assert "import matplotlib.pyplot" in fixed.splitlines()[:3]


def test_normalize_common_import_mistakes_repairs_rcparams():
    from math_agent.tools.runner import _normalize_common_import_mistakes

    fixed = _normalize_common_import_mistakes(
        "import matplotlib.rcparams as rc\nrc['font.size'] = 10\n"
    )

    assert "from matplotlib import rcParams as rc" in fixed
    assert "matplotlib.rcparams" not in fixed


def test_normalize_escaped_source_repairs_double_escaped_script():
    from math_agent.tools.runner import _normalize_escaped_source
    code = "import math\\nprint(math.sqrt(4))\\n"
    fixed = _normalize_escaped_source(code)
    assert "print(math.sqrt(4))" in fixed
    assert "\\n" not in fixed


def test_run_python_executes_double_escaped_script(workdir):
    code = "value = 1 + 1\\nprint(value)\\n"
    res = run_python(code, workdir=workdir)
    assert res.success, res.stderr
    assert "2" in res.stdout


def test_runner_decodes_timeout_output_bytes(mocker, workdir):
    code = (
        "import sys, time\n"
        "sys.stdout.buffer.write(b'partial\\xff')\n"
        "sys.stdout.buffer.flush()\n"
        "time.sleep(30)\n"
    )
    res = run_python(code, workdir=workdir, timeout=1)
    assert isinstance(res.stdout, str)
    assert res.stdout.startswith("partial")


def test_runner_timeout_kills_descendant_process_tree(workdir):
    import psutil
    import time

    code = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(30)\n"
    )
    res = run_python(code, workdir=workdir, timeout=1)
    child_pid = int(res.stdout.strip().splitlines()[0])
    for _ in range(20):
        if not psutil.pid_exists(child_pid):
            break
        time.sleep(0.05)

    assert res.error_kind == "timeout"
    assert not psutil.pid_exists(child_pid)


def test_runner_enforces_process_tree_memory_limit(workdir):
    res = run_python(
        "import time\nx = bytearray(256 * 1024 * 1024)\ntime.sleep(30)\n",
        workdir=workdir,
        timeout=10,
        memory_limit_mb=128,
    )

    assert res.success is False
    assert res.error_kind == "resource"
    assert "memory limit exceeded" in res.stderr


# ── Agg 注入 + plt.show 剥离 测试 ──


def test_auto_fix_injects_agg_when_pyplot_already_imported():
    """LLM 已 import pyplot 但未设置 Agg → 仍应注入 matplotlib.use('Agg')。"""
    from math_agent.tools.runner import _auto_fix_imports
    code = (
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1, 2, 3])\n"
        "plt.show()\n"
    )
    fixed = _auto_fix_imports(code)
    assert "matplotlib.use('Agg')" in fixed


def test_auto_fix_skips_agg_when_already_present():
    """LLM 已显式设置 Agg → 不重复注入。"""
    from math_agent.tools.runner import _auto_fix_imports
    code = (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1, 2, 3])\n"
    )
    fixed = _auto_fix_imports(code)
    assert fixed.count("matplotlib.use('Agg')") == 1


def test_auto_fix_handles_rcParams_without_pyplot():
    """仅使用 matplotlib.rcParams 也应注入 Agg。"""
    from math_agent.tools.runner import _auto_fix_imports
    code = (
        "import matplotlib\n"
        "matplotlib.rcParams['font.size'] = 10\n"
    )
    fixed = _auto_fix_imports(code)
    assert "matplotlib.use('Agg')" in fixed


def test_strip_dangerous_calls_removes_plt_show():
    """plt.show() 被移除。"""
    from math_agent.tools.runner import _strip_dangerous_calls
    code = (
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1, 2, 3])\n"
        "plt.show()\n"
    )
    stripped = _strip_dangerous_calls(code)
    assert "# [auto-removed:" in stripped
    # 确认原始调用行（以 plt.show 开头的行）被替换
    assert not any(line.strip().startswith("plt.show(") for line in stripped.splitlines())


def test_strip_dangerous_calls_removes_plt_ion():
    """plt.ion() 被移除。"""
    from math_agent.tools.runner import _strip_dangerous_calls
    code = (
        "import matplotlib.pyplot as plt\n"
        "plt.ion()\n"
        "plt.plot([1, 2, 3])\n"
    )
    stripped = _strip_dangerous_calls(code)
    assert "# [auto-removed:" in stripped
    assert not any(line.strip().startswith("plt.ion(") for line in stripped.splitlines())


def test_strip_dangerous_calls_removes_fig_show():
    """fig.show() 被移除（Figure 对象调用 show 同理会阻塞）。"""
    from math_agent.tools.runner import _strip_dangerous_calls
    code = (
        "import matplotlib.pyplot as plt\n"
        "fig = plt.figure()\n"
        "fig.show()\n"
        "plt.savefig('out.png')\n"
    )
    stripped = _strip_dangerous_calls(code)
    assert "# [auto-removed:" in stripped
    assert not any(line.strip().startswith("fig.show(") for line in stripped.splitlines())


def test_strip_dangerous_calls_preserves_savefig():
    """savefig 不受影响。"""
    from math_agent.tools.runner import _strip_dangerous_calls
    code = (
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1, 2, 3])\n"
        "plt.savefig('out.png')\n"
    )
    stripped = _strip_dangerous_calls(code)
    assert "savefig" in stripped
    assert "auto-removed" not in stripped


def test_structured_evidence_lines_keeps_q_and_limitation():
    """论文证据行必须保留逐问输出（Q<id>:）与 LIMITATION 声明，丢弃调试行。"""
    from math_agent.tools.runner import structured_evidence_lines

    stdout = (
        "工作表列表: ['Sheet1_标准实验数据']\n"
        "0       18.0             50       12.68\n"
        "Q1.1: 直径=18.0mm, 扭矩系数K=0.162, R²=0.9663\n"
        "Q2.2: 工况A Tmax=368.08 N·m\n"
        "LIMITATION: Q3.2 当 e>10mm 时 P_ecc 公式根号内为负，模型不可用。\n"
        "RESULT: baseline=ours R²=0.9825 Tmax=368.08\n"
    )
    lines = structured_evidence_lines(stdout)
    assert lines == [
        "Q1.1: 直径=18.0mm, 扭矩系数K=0.162, R²=0.9663",
        "Q2.2: 工况A Tmax=368.08 N·m",
        "LIMITATION: Q3.2 当 e>10mm 时 P_ecc 公式根号内为负，模型不可用。",
        "RESULT: baseline=ours R²=0.9825 Tmax=368.08",
    ]


def test_structured_evidence_lines_keeps_scenario_prefixes():
    """车辆路径模板的既有证据前缀不受影响。"""
    from math_agent.tools.runner import structured_evidence_lines

    stdout = (
        "SCENARIO_BEGIN: baseline=no_policy\n"
        "RESULT: baseline=ours total_cost=1245.3\n"
        "SCENARIO_END:\n"
        "saved figure to C:/tmp/x.png\n"
    )
    lines = structured_evidence_lines(stdout)
    assert lines == [
        "SCENARIO_BEGIN: baseline=no_policy",
        "RESULT: baseline=ours total_cost=1245.3",
        "SCENARIO_END:",
    ]


def test_detect_literal_backslash_n_flags_comment_and_code_escapes():
    """字面量 \\n 的两种实测形态都必须命中：注释内吞语句（r6 批5）、代码区（r7 首轮）。"""
    from math_agent.tools.runner import detect_literal_backslash_n

    comment_case = (
        "# 钢带必要性判断。\nuse_steel_A = (min_idx_A == 3)  # 索引3为围岩压陷"
        "\\nuse_steel_B = (min_idx_B == 3)\nprint('x')"
    )
    assert detect_literal_backslash_n(comment_case) != ""

    code_case = (
        "control_B = '压陷' if Tmax_B == T_bearing_B else '屈服'"
        "\\nuse_steel_A = control_A == '压陷'"
    )
    assert detect_literal_backslash_n(code_case) != ""


def test_detect_literal_backslash_n_ignores_strings_and_clean_code():
    """字符串内的 \\n（如列名 '锚杆直径\\n/mm'）与正常代码不得误报。"""
    from math_agent.tools.runner import detect_literal_backslash_n

    clean = (
        "df1['锚杆直径\\n/mm'] = df1['锚杆直径\\n/mm'].ffill()\n"
        "# 前向填充直径\n"
        "print('x')  # 正常行内注释\n"
    )
    assert detect_literal_backslash_n(clean) == ""

    hash_in_string = "print('# 锚杆直径\\n/mm')"
    assert detect_literal_backslash_n(hash_in_string) == ""

    triple = "'''# 注释样例\\n 换行'''\nx = 1"
    assert detect_literal_backslash_n(triple) == ""

    line_continuation = "x = 1 + \\\n    2"
    assert detect_literal_backslash_n(line_continuation) == ""


def test_normalize_literal_backslash_n_fixes_comment_and_code_escapes():
    """字符串外字面量 \\n 替换为真实换行（r6 注释吞语句 / r7 代码区 / r8 连发）。"""
    from math_agent.tools.runner import normalize_literal_backslash_n

    comment_case = (
        "# 钢带必要性判断。\\nuse_steel_A = (min_idx_A == 3)  # 索引3为围岩压陷"
        "\\nuse_steel_B = (min_idx_B == 3)\nprint('x')"
    )
    fixed = normalize_literal_backslash_n(comment_case)
    assert "\\n" not in fixed
    compile(fixed, "<fixed>", "exec")  # 修复后必须可编译

    code_case = (
        "control_B = '压陷' if Tmax_B == T_bearing_B else '屈服'"
        "\\nuse_steel_A = control_A == '压陷'"
    )
    fixed2 = normalize_literal_backslash_n(code_case)
    assert "\\n" not in fixed2
    compile(fixed2, "<fixed2>", "exec")


def test_normalize_literal_backslash_n_preserves_strings_and_idempotent():
    """字符串内 \\n（如 '锚杆直径\\n/mm'）、三引号、行延续不得被改动。"""
    from math_agent.tools.runner import normalize_literal_backslash_n

    clean = (
        "df1['锚杆直径\\n/mm'] = df1['锚杆直径\\n/mm'].ffill()\n"
        "# 前向填充直径\n"
        "print('x')  # 正常行内注释\n"
    )
    assert normalize_literal_backslash_n(clean) == clean

    triple = "'''# 注释样例\\n 换行'''\nx = 1"
    assert normalize_literal_backslash_n(triple) == triple

    continuation = "x = 1 + \\\n    2"
    assert normalize_literal_backslash_n(continuation) == continuation

    # 幂等：修复后再修一次结果不变
    bad = "a = 1\\nb = 2\nc = 'x\\ny'"
    once = normalize_literal_backslash_n(bad)
    assert normalize_literal_backslash_n(once) == once


def test_run_python_auto_fixes_literal_backslash_n(workdir):
    """run_python 对注释吞语句形态自动修复后正常执行（端到端）。"""
    from math_agent.tools.runner import run_python

    code = (
        "import matplotlib; matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.savefig('fig.png')\n"
        "K = 0.18\\nR2 = 0.98\n"
        "print('RESULT: baseline=ours K=%s R2=%s' % (K, R2))\n"
    )
    result = run_python(code, workdir=workdir)
    assert result.success is True
    assert "RESULT: baseline=ours K=0.18 R2=0.98" in result.stdout
    assert any(str(p).endswith("fig.png") for p in result.artifact_paths)


def test_runner_detects_overwritten_same_name_file_in_reused_workdir(workdir):
    """跨批次复用的 attempt 目录中，覆盖同名产物也必须被检测（r10 冤杀根因）。"""
    from math_agent.tools.runner import run_python

    code = (
        "import matplotlib; matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.savefig('torque_force_regression.png')\n"
    )
    first = run_python(code, workdir=workdir)
    assert any(str(p).endswith("torque_force_regression.png") for p in first.artifact_paths)

    # 第二次同一目录、同名保存（覆盖旧文件）——必须仍被检测到
    second = run_python(code, workdir=workdir)
    assert any(str(p).endswith("torque_force_regression.png") for p in second.artifact_paths)


def test_runner_detects_figure_saved_in_subdirectory(workdir):
    """保存到子目录的图也必须被检测（rglob 递归快照）。"""
    from math_agent.tools.runner import run_python

    code = (
        "import os\n"
        "import matplotlib; matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "os.makedirs('figs', exist_ok=True)\n"
        "plt.savefig('figs/plot.png')\n"
    )
    result = run_python(code, workdir=workdir)
    assert result.success is True
    assert any(str(p).replace("\\", "/").endswith("figs/plot.png") for p in result.artifact_paths)


def test_runner_end_to_end_no_hang_from_plt_show(workdir):
    """端到端：含 plt.show() 的代码在 run_python 中不阻塞，正常完成。"""
    code = (
        "import matplotlib\n"
        "matplotlib.use('TkAgg')  # LLM 可能显式设 GUI backend\n"
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1, 2, 3])\n"
        "plt.show()\n"
        "print('DONE')\n"
    )
    res = run_python(code, workdir=workdir, timeout=10)
    # 即使 LLM 设了 TkAgg，_auto_fix_imports 会前置 Agg（因为
    # already_marker 检查 Agg 而非 pyplot import），随后 _strip_dangerous_calls
    # 移除 plt.show() → 必须不阻塞，不超时
    assert res.success, f"timed out or crashed: {res.stderr[:200]}"
    assert "DONE" in res.stdout

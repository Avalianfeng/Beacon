from __future__ import annotations

import os
import re
from pathlib import Path
import tempfile

from pydantic import BaseModel

from math_agent.llm import complete
from math_agent.config import (
    CODER_MODEL,
    LLM_FALLBACK_MODELS,
    MAX_CODE_RETRIES,
    MAX_CODE_VERIFY_ITERATIONS,
    MIN_MODEL_CODE_SCORE,
    MODEL_ROUTING,
    STRONG_MODEL,
)
from math_agent.prompts.coder import SYSTEM, build_prompt  # noqa: F401
from math_agent.prompts.coder_figure_one import (
    build_prompt_figure_one,
    metric_vars,
)
from math_agent.prompts.coder_baseline import BASELINE_SPECS, build_baseline_prompt
from math_agent.state import MathModelingState, CodeArtifact
from math_agent.tools.runner import (
    RunResult,
    detect_literal_backslash_n,
    infer_entity_upper_bound,
    normalize_literal_backslash_n,
    run_python,
    validate_code_data_usage,
    validate_numeric_results,
)


class CoderDraft(BaseModel):
    purpose: str
    code: str


def _baseline_items() -> list[dict]:
    return [
        {"kind": "baseline", "id": f"baseline:{category}", "name": name,
         "category": category, "instruction": instruction, "attempt": 0}
        for name, category, instruction in BASELINE_SPECS
    ]


def _has_primary_for_current_batch(
    state: MathModelingState, artifacts: list[CodeArtifact]
) -> bool:
    candidates = [
        *artifacts,
        *(a for a in state.code_artifacts if a.batch == state.coder_current_batch),
    ]
    return any(
        a.success and a.category == "figure" and a.evidence_role == "primary"
        for a in candidates
    )


def _current_primary_code(state: MathModelingState) -> str:
    candidates = [
        *state.coder_work_artifacts,
        *(a for a in state.code_artifacts if a.batch == state.coder_current_batch),
    ]
    return next(
        (
            a.code for a in reversed(candidates)
            if a.success and a.category == "figure"
            and a.evidence_role == "primary" and a.code
        ),
        "",
    )


def _missing_baseline_items(
    state: MathModelingState, artifacts: list[CodeArtifact]
) -> list[dict]:
    return []


def _generic_template_code(purpose: str, data_dir: str, index: int, blueprint=None) -> str:
    safe_title = purpose.replace("\\", "/").replace("\n", " ")[:80]
    safe_file = f"figure_{index}.png"
    if blueprint is not None and getattr(blueprint, "metrics", None):
        fields = " ".join(f"{name}={{{var}}}" for name, var in metric_vars(blueprint.metrics))
        result_line = f'print(f"RESULT: baseline=ours {fields}")'
    else:
        result_line = (
            'print(f"RESULT: baseline=ours metric_0={metric_0:.4f} '
            'metric_1={metric_1:.4f}")'
        )
    return f'''import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

x = list(range(1, 11))
y = [v * {index + 1} for v in [2, 3, 5, 4, 6, 7, 5, 8, 7, 9]]
fig, ax = plt.subplots(figsize=(10, 6), dpi=180)
ax.plot(x, y, marker="o", linewidth=2)
ax.set_title({safe_title!r})
ax.set_xlabel("Index")
ax.set_ylabel("Value")
ax.grid(True, alpha=0.3)
fig.tight_layout()
out = Path({safe_file!r})
fig.savefig(out, dpi=220, bbox_inches="tight")
plt.close(fig)
metric_0 = sum(y)
metric_1 = 0.95
{result_line}
print(f"saved={{out}} purpose={safe_title!r} data_dir={data_dir!r}")
'''


def _template_figure_draft(item: dict, data_dir: str, data_files: list | None,
                           blueprint=None) -> CoderDraft | None:
    index = int(item.get("index", 0))
    purpose = str(item.get("purpose", f"figure-{index}"))
    return CoderDraft(
        purpose=purpose,
        code=_generic_template_code(purpose, data_dir or "", index, blueprint=blueprint),
    )


def _use_deterministic_coder() -> bool:
    """本地模板只用于显式离线应急模式，不能替代正常的题目相关代码生成。"""
    return os.getenv("MATH_AGENT_CODER_DETERMINISTIC", "").strip() == "1"


def _max_figure_tasks() -> int:
    try:
        return max(1, int(os.getenv("MATH_AGENT_MAX_FIGURE_TASKS", "4")))
    except ValueError:
        return 4


def _code_timeout_seconds() -> int:
    try:
        return max(30, int(os.getenv("MATH_AGENT_CODE_TIMEOUT", "120")))
    except ValueError:
        return 120


def _validated_execution(
    state: MathModelingState,
    item: dict,
    result,
    *,
    code: str = "",
    require_data_usage: bool = False,
) -> tuple[bool, str, str]:
    """把进程结果提升为可进入论文的证据结果。"""
    if not result.success:
        return False, result.stderr or "Python 子进程执行失败", result.error_kind or "runtime"
    expected = item.get("category") if item.get("kind") == "baseline" else None
    # 主方案图要求 RESULT 行输出足够多指标，防止 1--2 个指标敷衍过关；但下限不能
    # 超过 blueprint 声明的指标数——coder prompt 严格要求 RESULT 指标名与 Blueprint
    # “一字不差”，若 blueprint 只有 3 个指标而门禁要 4 个，忠实代码永远无法通过，
    # 会形成无主证据的无限重试死锁（曾导致 30 轮、70 万+ token 空转）。
    blueprint = state.problem_blueprint
    blueprint_metric_count = (
        len(blueprint.metrics) if blueprint is not None and blueprint.metrics else 0
    )
    min_metrics = (
        4 if blueprint_metric_count == 0 else min(4, blueprint_metric_count)
    )
    valid, reason, parsed = validate_numeric_results(
        result.stdout,
        stderr=result.stderr,
        require_result=True,
        expected_identifier=expected,
        max_entity_count=infer_entity_upper_bound(state.data_files),
        min_metrics_per_result=(
            min_metrics if item.get("kind") == "figure" and require_data_usage else 0
        ),
    )
    if not valid:
        return False, reason, "output_validation"
    if require_data_usage:
        lineage_ok, lineage_reason = validate_code_data_usage(
            code, [info.filename for info in state.data_files],
        )
        if not lineage_ok:
            return False, lineage_reason, "output_validation"
        expected_paths = {str(path).casefold() for path in _input_paths(state)}
        observed_paths = {str(Path(path)).casefold() for path in result.read_paths}
        if expected_paths and not expected_paths.intersection(observed_paths):
            return False, "运行时未观察到对声明附件的真实读取", "output_validation"
        if _uses_haversine_on_planar_km_schema(code, state.data_files):
            return (
                False,
                "坐标附件字段为 X (km)/Y (km) 平面公里坐标，不能按经纬度调用 Haversine；"
                "应使用距离矩阵或欧氏距离以保持单位口径一致",
                "output_validation",
            )
        service_error = _service_time_contract_error(code, state)
        if service_error:
            return False, service_error, "output_validation"
    return True, "", ""


def _uses_haversine_on_planar_km_schema(code: str, data_files) -> bool:
    columns: set[str] = set()
    for info in data_files or []:
        summary = info.get("summary", {}) if isinstance(info, dict) else info.summary
        raw_columns = summary.get("columns", []) if isinstance(summary, dict) else []
        for column in raw_columns if isinstance(raw_columns, list) else []:
            columns.add(str(column).casefold())
    planar = "x (km)" in columns and "y (km)" in columns
    return planar and code.casefold().count("haversine(") > 1


def _service_time_contract_error(code: str, state: MathModelingState) -> str:
    """题面明确服务时长时，执行代码中的统一常数必须同口径。"""
    problem_text = "\n".join((state.problem or "", state.background or ""))
    required = re.search(r"(?:服务时间|服务时长).*?(\d+(?:\.\d+)?)\s*分钟", problem_text)
    assigned = re.search(
        r"(?mi)^\s*SERVICE_TIME\s*=\s*(\d+(?:\.\d+)?)"
        r"\s*(?:#\s*([^\r\n]*))?$",
        code or "",
    )
    if required is None or assigned is None:
        return ""
    expected = float(required.group(1))
    observed_raw = float(assigned.group(1))
    unit_hint = (assigned.group(2) or "").casefold()
    uses_hours = bool(re.search(r"(?:\bh\b|hours?|小时)", unit_hint))
    observed = observed_raw * 60.0 if uses_hours else observed_raw
    if abs(expected - observed) <= 1e-9:
        return ""
    return (
        f"题面规定统一客户服务时间为 {expected:g} 分钟，"
        f"代码 SERVICE_TIME={observed:g} 分钟，模型—代码口径不一致；"
        f"service_time_contract expected_minutes={expected:g} "
        f"observed_minutes={observed:g} assignment_unit={'hours' if uses_hours else 'minutes'}"
    )


def _input_paths(state: MathModelingState) -> list[Path]:
    base_value = state.data_dir or state.output_dir
    base = Path(base_value) if base_value else None
    paths: list[Path] = []
    for info in state.data_files:
        path = Path(info.path or info.filename)
        if not path.is_absolute() and base is not None:
            path = base / path
        paths.append(path.resolve())
    return paths


def _combined_stderr(stderr: str, validation_reason: str) -> str:
    parts = [part.strip() for part in (stderr, validation_reason) if part and part.strip()]
    return "\n".join(parts)


def _previous_figure_code(state: MathModelingState, item: dict) -> str:
    """返回当前图任务上一轮源码，支持旧 checkpoint 无 prev_code 的情况。"""
    explicit = str(item.get("prev_code") or "")
    if explicit:
        return explicit
    if int(item.get("attempt", 0)) <= 0:
        return ""
    for artifact in reversed(state.coder_work_artifacts):
        if artifact.category == "figure" and not artifact.success and artifact.code:
            return artifact.code
    return ""


def _consistency_repair_context(
    state: MathModelingState, *, evidence_target: str
) -> tuple[str, str]:
    """返回上一批主代码及一致性反馈，供定向修订而不是从头生成。"""
    if evidence_target != "primary" or not state.model_code_reports:
        return "", ""
    report = state.model_code_reports[-1]
    # 反馈阈值必须与门禁放行阈值对齐：只要门禁会拒（分数低于 MIN_MODEL_CODE_SCORE），
    # 就把审查意见和上一版代码喂回 coder 定向修订。若用固定 7 分会形成
    # “不放行、也不给修复意见”的死区（r3：7/10 的 7 条意见全部丢失、盲重试）。
    if report.approved and report.score >= MIN_MODEL_CODE_SCORE:
        return "", ""
    primary = next(
        (
            artifact for artifact in reversed(state.code_artifacts)
            if artifact.success and artifact.category == "figure"
            and artifact.evidence_role == "primary" and artifact.code
        ),
        None,
    )
    if primary is None:
        return "", ""
    details = [
        f"模型—代码一致性评分仅 {report.score}/10，必须在上一版代码上定向修订。",
        *[f"问题：{issue}" for issue in report.issues],
        *[f"建议：{suggestion}" for suggestion in report.suggestions],
    ]
    return primary.code, "\n".join(details)


def _local_repair_draft(
    item: dict,
    previous_code: str,
    state: MathModelingState | None = None,
) -> CoderDraft | None:
    """只处理可证明等价的常见机械错误；其余问题仍交给模型定向修复。"""
    if not previous_code:
        return None
    repaired = previous_code.replace(
        "import matplotlib.rcparams as rc",
        "from matplotlib import rcParams as rc",
    )
    # 常见的 JSON/Markdown 逃逸残留：模型把应有的源码换行写成字面 ``\n``，
    # 且落在注释后，使下一条赋值也被注释掉。这里只修复“注释 + 标识符赋值”形态，
    # 不碰路径、正则和普通字符串里的合法反斜杠。
    repaired = re.sub(
        r"(?m)^(\s*\#[^\r\n]*?)\\n(?=[A-Za-z_]\w*\s*=)",
        r"\1\n",
        repaired,
    )
    repaired = "\n".join(
        line.replace(r"\n", "\n")
        if r"\n" in line and "'" not in line and '"' not in line
        else line
        for line in repaired.split("\n")
    )
    error = str(item.get("prev_err") or "")
    if state is not None and "SERVICE_TIME" not in error:
        error = "\n".join(filter(None, (error, _service_time_contract_error(repaired, state))))
    if "SERVICE_TIME" in error:
        match = re.search(
            r"(?:服务时间为\s*|service_time_contract\s+expected(?:_minutes)?=)"
            r"(\d+(?:\.\d+)?)",
            error,
            flags=re.IGNORECASE,
        )
        if match:
            expected_minutes = float(match.group(1))
            assignment = re.search(
                r"(?mi)^(\s*SERVICE_TIME\s*=\s*)\d+(?:\.\d+)?"
                r"(\s*(?:#\s*[^\r\n]*)?)$",
                repaired,
            )
            if assignment:
                hint = assignment.group(2).casefold()
                value = expected_minutes / 60.0 if re.search(
                    r"(?:\bh\b|hours?|小时)", hint,
                ) else expected_minutes
                repaired = (
                    repaired[:assignment.start()]
                    + assignment.group(1) + repr(float(value)) + assignment.group(2)
                    + repaired[assignment.end():]
                )
    if "Int64Engine" in error and "KeyError: '0'" in error:
        repaired = repaired.replace(
            "dist_df.loc[i, str(j)]",
            "dist_df.loc[i, j]",
        )
    dense_distance_block = """cust_ids = list(dist_df.index)
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
            dist_dict[(i, j)] = np.sqrt((xi-xj)**2 + (yi-yj)**2)"""
    compact_distance_block = """class DistanceLookup:
    # 保留 pandas/NumPy 的紧凑矩阵，只在访问时按标签索引；避免复制成数百万个 tuple。
    def __init__(self, frame, coordinates):
        self.values = frame.to_numpy(dtype=float, copy=False)
        self.row_pos = {label: pos for pos, label in enumerate(frame.index)}
        self.col_pos = {label: pos for pos, label in enumerate(frame.columns)}
        self.coordinates = coordinates

    def __getitem__(self, pair):
        i, j = pair
        row = self.row_pos.get(i)
        col = self.col_pos.get(j)
        if row is not None and col is not None:
            return float(self.values[row, col])
        xi, yi = self.coordinates[i]
        xj, yj = self.coordinates[j]
        return float(np.hypot(xi - xj, yi - yj))

dist_dict = DistanceLookup(dist_df, coord_dict)"""
    if dense_distance_block in repaired:
        repaired = repaired.replace(dense_distance_block, compact_distance_block)
    if (
        str(item.get("prev_kind") or "") == "timeout"
        and "while not np.all(assigned):" in repaired
        and "VEHICLE_CAPACITY_WEIGHT" in repaired
        and "VEHICLE_CAPACITY_VOLUME" in repaired
        and "# BEACON_CAPACITY_SPLIT" not in repaired
    ):
        volume_line = next(
            (
                line for line in repaired.splitlines()
                if line.strip().startswith("VEHICLE_CAPACITY_VOLUME") and "=" in line
            ),
            "",
        )
        if volume_line and "customers" in repaired:
            capacity_split = """

# BEACON_CAPACITY_SPLIT：聚合客户需求必须拆成单车容量可行的访问任务。
_beacon_chunks = []
for _, _beacon_row in customers.iterrows():
    _beacon_weight = pd.to_numeric(_beacon_row['重量'], errors='coerce')
    _beacon_volume = pd.to_numeric(_beacon_row['体积'], errors='coerce')
    _beacon_weight = 0.0 if pd.isna(_beacon_weight) else float(_beacon_weight)
    _beacon_volume = 0.0 if pd.isna(_beacon_volume) else float(_beacon_volume)
    _beacon_parts = max(
        1,
        int(np.ceil(max(
            _beacon_weight / VEHICLE_CAPACITY_WEIGHT,
            _beacon_volume / VEHICLE_CAPACITY_VOLUME,
        ))),
    )
    for _beacon_part in range(_beacon_parts):
        _beacon_chunk = _beacon_row.copy()
        _beacon_chunk['重量'] = _beacon_weight / _beacon_parts
        _beacon_chunk['体积'] = _beacon_volume / _beacon_parts
        if _beacon_weight > 0.0 or _beacon_volume > 0.0:
            _beacon_chunks.append(_beacon_chunk)
customers = pd.DataFrame(_beacon_chunks).reset_index(drop=True)
"""
            repaired = repaired.replace(volume_line, volume_line + capacity_split, 1)
            repaired = repaired.replace(
                "while not np.all(assigned):",
                "_beacon_stalled_rounds = 0\nwhile not np.all(assigned):",
                1,
            )
            repaired = repaired.replace(
                "    while True:\n        best_cost = np.inf",
                "    while True:\n        unassigned = np.where(~assigned)[0]\n"
                "        best_cost = np.inf",
                1,
            )
            toggle = "    vehicle_type = 1 - vehicle_type"
            if toggle in repaired:
                progress_guard = """    # BEACON_PROGRESS_GUARD：连续两种车辆均无进展时立即失败，不等待硬期限。
    if len(current_route) == 0:
        _beacon_stalled_rounds += 1
        if _beacon_stalled_rounds >= 2:
            raise RuntimeError('no progress: remaining tasks violate capacity or route constraints')
    else:
        _beacon_stalled_rounds = 0
"""
                repaired = repaired.replace(toggle, progress_guard + toggle, 1)
    if (
        str(item.get("prev_kind") or "") == "timeout"
        and "while unvisited:" in repaired
        and ".groupby(" in repaired
        and "CAPACITY_WEIGHT" in repaired
        and "CAPACITY_VOLUME" in repaired
        and "total_weight" in repaired
        and "total_volume" in repaired
    ):
        # 客户聚合需求先拆成单车容量可行的访问任务，并让最近邻返回“任务索引”
        # 而不是会重复的客户编号。这样既保留原脚本的成本/绘图逻辑，也保证
        # unvisited 每轮真实减少；连续空路线则立即失败，不等到 120 秒。
        capacity_anchor = next((
            line for line in repaired.splitlines()
            if line.strip().startswith("CAPACITY_VOLUME") and "=" in line
        ), "")
        if capacity_anchor and "# BEACON_AGGREGATE_SPLIT" not in repaired:
            split_block = r'''

# BEACON_AGGREGATE_SPLIT：把客户聚合需求拆成单车容量可行的访问任务。
_beacon_rows = []
for _, _beacon_row in df_cust.iterrows():
    _beacon_weight = float(pd.to_numeric(_beacon_row['total_weight'], errors='coerce') or 0.0)
    _beacon_volume = float(pd.to_numeric(_beacon_row['total_volume'], errors='coerce') or 0.0)
    _beacon_parts = max(1, int(np.ceil(max(
        _beacon_weight / CAPACITY_WEIGHT,
        _beacon_volume / CAPACITY_VOLUME,
    ))))
    for _ in range(_beacon_parts):
        _beacon_part = _beacon_row.copy()
        _beacon_part['total_weight'] = _beacon_weight / _beacon_parts
        _beacon_part['total_volume'] = _beacon_volume / _beacon_parts
        _beacon_rows.append(_beacon_part)
df_cust = pd.DataFrame(_beacon_rows).reset_index(drop=True)
df_cust['customer_id'] = pd.to_numeric(df_cust['customer_id'], errors='raise').astype(int)
'''
            repaired = repaired.replace(capacity_anchor, capacity_anchor + split_block, 1)
        repaired = repaired.replace(
            "best_global = None\n    for u in unvisited:",
            "best_task = None\n    for u in unvisited:",
            1,
        ).replace(
            "best_global = global_u\n    return best_global, best_dist",
            "best_task = u\n    return best_task, best_dist",
            1,
        )
        repaired = re.sub(
            r"(?m)^(\s*)best_global, best_dist = find_nearest\(([^\r\n]+)\)\r?\n"
            r"\1if best_global is None:\r?\n\1    break\r?\n"
            r"\1cust_idx = global_to_cust_idx\[best_global\]",
            lambda match: (
                f"{match.group(1)}best_task, best_dist = find_nearest({match.group(2)})\n"
                f"{match.group(1)}if best_task is None:\n"
                f"{match.group(1)}    break\n"
                f"{match.group(1)}cust_idx = best_task\n"
                f"{match.group(1)}best_global = cust_idx_to_global[cust_idx]"
            ),
            repaired,
            count=1,
        )
        if "# BEACON_UNVISITED_PROGRESS" not in repaired:
            repaired = repaired.replace(
                "    # 结束当前车，返回配送中心\n    route.append(0)",
                "    # BEACON_UNVISITED_PROGRESS：空路线表示剩余任务不可行，立即失败。\n"
                "    if not served_this_vehicle:\n"
                "        raise RuntimeError('no progress: remaining tasks violate capacity constraints')\n"
                "    # 结束当前车，返回配送中心\n    route.append(0)",
                1,
            )
    if repaired == previous_code:
        return None
    return CoderDraft(purpose=str(item.get("purpose") or "figure"), code=repaired)


def _local_baseline_repair_draft(
    item: dict, *, data_dir: str, previous_code: str
) -> CoderDraft | None:
    """仅修复 attempt 工作目录导致的已知相对附件根路径错误。"""
    error = str(item.get("prev_err") or "")
    if not previous_code:
        return None
    if "SERVICE_TIME" in error:
        match = re.search(
            r"(?:服务时间为\s*|service_time_contract\s+expected=)(\d+(?:\.\d+)?)",
            error,
            flags=re.IGNORECASE,
        )
        if match:
            repaired = re.sub(
                r"(?m)^(\s*SERVICE_TIME\s*=\s*)\d+(?:\.\d+)?\s*$",
                rf"\g<1>{float(match.group(1))!r}",
                previous_code,
                count=1,
            )
            if repaired != previous_code:
                return CoderDraft(purpose=str(item.get("name") or "baseline"), code=repaired)
    if not data_dir or "FileNotFoundError" not in error:
        return None
    replacement = f"Path({str(Path(data_dir).resolve())!r})"
    repaired = previous_code
    for relative in (
        "Path('./附件')", 'Path("./附件")',
        "Path('附件')", 'Path("附件")',
    ):
        repaired = repaired.replace(relative, replacement)
    if repaired == previous_code:
        return None
    return CoderDraft(purpose=str(item.get("name") or "baseline"), code=repaired)

def coder_prepare_node(state: MathModelingState) -> dict:
    """Create a small, stable coding queue without calling the model."""
    model = state.latest_model()
    if model is None:
        return {"errors": ["coder: missing model"], "coder_phase": "done"}
    batch = max((a.batch for a in state.code_artifacts), default=0) + 1
    purposes = (model.figure_purposes or [model.description])[:_max_figure_tasks()]
    purposes[0] = (
        "主方案数值求解与核心证据图：必须读取真实附件，实现最终模型的轻量可复现求解，"
        "先计算完整 RESULT 指标，再绘制一张核心证据图。原始图意图："
        f"{purposes[0]}"
    )
    queue = [
        {"kind": "figure", "id": f"figure:{i}", "purpose": purpose,
         "index": i, "attempt": 0, "prev_err": "", "prev_kind": "",
         "evidence_target": "primary" if i == 0 else "supporting"}
        for i, purpose in enumerate(purposes)
    ]
    return {
        "coder_phase": "generate", "coder_work_queue": queue,
        "coder_work_artifacts": [], "coder_current_batch": batch,
        "coder_pending_draft": {},
    }


# 首次 coder_generate 真实运行已用到 8810 completion tokens；execute 失败后的
# 定向修复还要带回 previous_code。6000 会让 DeepSeek 返回空 content。
_CODER_GENERATE_MAX_TOKENS = 12000


def _supporting_figure_model() -> str:
    """补充图与主图一致使用强模型（STRONG_MODEL）。

    曾经在 STRONG==CODER 时退到 failover 里的 flash 省 token，但 flash 生成
    含 previous_code 的完整草稿时频繁在 12000 token 上限处截断 JSON，导致
    CoderDraft 校验失败 → supervisor 恢复循环（r6 两次崩溃，每次浪费约 5 分钟
    与 2×12k tokens）。强模型在同等预算下不截断，总成本反而更低。
    """
    return STRONG_MODEL


def coder_generate_node(state: MathModelingState) -> dict:
    """Generate code for the current queue item, then hand off to execute."""
    queue = list(state.coder_work_queue)
    if not queue:
        return {"coder_phase": "done"}
    item = dict(queue[0])
    evidence_target = item.get(
        "evidence_target", "primary" if int(item.get("index", 0)) == 0 else "supporting"
    )
    model = state.latest_model()
    if item["kind"] == "figure":
        # 显式离线应急模式下使用本地模板；正常流程一律走 LLM 生成。
        if _use_deterministic_coder():
            draft = _template_figure_draft(
                item, state.data_dir, state.data_files,
                blueprint=state.problem_blueprint,
            )
        else:
            primary = next(
                (
                    a for a in state.coder_work_artifacts
                    if a.success and a.category == "figure" and a.evidence_role == "primary"
                ),
                None,
            )
            is_supporting = evidence_target == "supporting"
            previous_code = (
                str(item.get("prev_code") or "")
                if is_supporting
                else _previous_figure_code(state, item)
            )
            consistency_code, consistency_feedback = ("", "")
            if not is_supporting:
                consistency_code, consistency_feedback = _consistency_repair_context(
                    state, evidence_target=evidence_target,
                )
                if not previous_code and consistency_code:
                    previous_code = consistency_code
            feedback = item.get("prev_err") or consistency_feedback or None
            failure_kind = item.get("prev_kind", "") or (
                "consistency" if consistency_feedback else ""
            )
            draft = None
            if not is_supporting:
                draft = _local_repair_draft(item, previous_code, state)
            if draft is None:
                try:
                    draft = complete(
                        build_prompt_figure_one(
                            model, item["purpose"], feedback,
                            failure_kind, blueprint=state.problem_blueprint,
                            data_dir=state.data_dir, data_files=state.data_files,
                            canonical_evidence=primary.stdout if primary else "",
                            previous_code=previous_code,
                            brief=state.brief,
                        ),
                        schema=CoderDraft, system=SYSTEM,
                        model=_supporting_figure_model() if is_supporting else MODEL_ROUTING["coder"],
                        profile="code", temperature=0.1,
                        max_tokens=_CODER_GENERATE_MAX_TOKENS,
                    )
                except Exception:
                    # B10: figure 生成异常上抛走崩溃→checkpoint→recover，不再节点内吞错消耗 502 预算。
                    raise
    else:
        main_code = _current_primary_code(state)
        try:
            draft = _local_baseline_repair_draft(
                item, data_dir=state.data_dir,
                previous_code=str(item.get("prev_code") or ""),
            )
            if draft is None:
                draft = complete(
                    build_baseline_prompt(state.problem, main_code, item["name"],
                                          item["category"], item["instruction"],
                                          item.get("prev_err") or None,
                                          item.get("prev_kind", ""),
                                          item.get("prev_code", "")),
                    schema=CoderDraft, system=SYSTEM, model=MODEL_ROUTING["coder"],
                    profile="code", temperature=0.1,
                    max_tokens=_CODER_GENERATE_MAX_TOKENS,
                )
        except Exception as exc:
            artifacts = list(state.coder_work_artifacts)
            artifacts.append(CodeArtifact(
                purpose=f"{item['name']}对照方案（失败）", code="", stderr=str(exc)[:500],
                success=False, category=f"baseline:{item['category']}",
                evidence_role="none",
                batch=state.coder_current_batch,
            ))
            queue.pop(0)
            if queue:
                return {
                    "coder_work_queue": queue,
                    "coder_work_artifacts": artifacts,
                    "coder_pending_draft": {},
                    "coder_phase": "generate",
                }
            return _coder_done_delta(artifacts, state=state)
    return {"coder_pending_draft": draft.model_dump(), "coder_phase": "execute"}


def coder_execute_node(state: MathModelingState) -> dict:
    """Execute already-checkpointed code so a crash does not trigger re-generation."""
    queue = list(state.coder_work_queue)
    if not queue:
        return {"coder_phase": "done", "coder_pending_draft": {}}
    item = dict(queue[0])
    evidence_target = item.get(
        "evidence_target", "primary" if int(item.get("index", 0)) == 0 else "supporting"
    )
    draft = CoderDraft.model_validate(state.coder_pending_draft)
    workdir = Path(state.output_dir) if state.output_dir else Path(tempfile.mkdtemp(prefix="math_agent_"))
    workdir.mkdir(parents=True, exist_ok=True)
    artifacts = list(state.coder_work_artifacts)

    if item["kind"] == "figure":
        # L2 机械噪声自动修复：字符串之外的字面量 \n（注释吞语句/代码区 SyntaxError，
        # r6/r7/r8 连续复现）词法替换为真实换行，零 LLM 轮次成本。替换后不可能再
        # 命中，fail-fast 仅作安全网。
        code_to_run = normalize_literal_backslash_n(draft.code)
        comment_escape_reason = detect_literal_backslash_n(code_to_run)
        if comment_escape_reason:
            result = RunResult(
                success=False, stdout="", stderr=comment_escape_reason,
                error_kind="generation",
            )
        else:
            result = run_python(
                code_to_run,
                workdir=workdir / f"fig_{item['index']}_attempt_{item['attempt']}",
                timeout=_code_timeout_seconds(),
                expected_input_paths=_input_paths(state),
            )
        has_primary = _has_primary_for_current_batch(state, artifacts)
        effective_success, validation_reason, error_kind = _validated_execution(
            state, item, result, code=code_to_run,
            require_data_usage=bool(state.data_files) and evidence_target == "primary",
        )
        # 绘图任务必须真的产出图片（r6 批次 7 三个 figure artifact 全部
        # artifact_paths=[]，执行成功但没有图，导致 figure_pipeline 空转、
        # 论文图表数为 0、paper_critic 扣分）。没有 png 的 figure 视为执行失败，
        # 反馈给模型重试而不是放行。
        if effective_success and item["kind"] == "figure":
            png_paths = [
                p for p in (result.artifact_paths or [])
                if str(p).lower().endswith(".png")
            ]
            if not png_paths:
                effective_success = False
                validation_reason = (
                    "figure 任务未产出图片文件：代码执行成功但工作目录没有任何 .png。"
                    "必须调用 plt.savefig(...) 把核心证据图保存为 .png 后再结束脚本。"
                )
                error_kind = "output_validation"
        evidence_role = (
            "primary" if effective_success and evidence_target == "primary"
            else "supporting" if effective_success and evidence_target == "supporting" and has_primary
            else "none"
        )
        artifacts.append(CodeArtifact(
            purpose=draft.purpose, code=code_to_run, stdout=result.stdout,
            stderr=_combined_stderr(result.stderr, validation_reason), success=effective_success,
            artifact_paths=result.artifact_paths,
            read_paths=getattr(result, "read_paths", []),
            batch=state.coder_current_batch,
            evidence_role=evidence_role,
        ))
        if not effective_success and item["attempt"] < MAX_CODE_RETRIES:
            feedback = validation_reason or result.stderr or result.stdout[-1000:]
            item.update(
                attempt=item["attempt"] + 1, prev_err=feedback,
                prev_kind=error_kind, prev_code=draft.code,
            )
            queue[0] = item
        else:
            queue.pop(0)
            if evidence_target == "primary" and not effective_success:
                # 任意绘图任务不能顶替失败的主求解。结束本批次，让一致性闭环开启新批次。
                queue = [work for work in queue if work.get("kind") != "figure"]
            if (
                not any(work.get("kind") == "figure" for work in queue)
                and not any(work.get("kind") == "baseline" for work in queue)
                and _has_primary_for_current_batch(state, artifacts)
            ):
                queue.extend(_missing_baseline_items(state, artifacts))
    else:
        result = run_python(
            draft.code,
            workdir=workdir / f"baseline_{item['category']}_attempt_{item['attempt']}",
            timeout=_code_timeout_seconds(),
            expected_input_paths=_input_paths(state),
        )
        effective_success, validation_reason, error_kind = _validated_execution(
            state, item, result, code=draft.code,
            require_data_usage=bool(state.data_files),
        )
        artifacts.append(CodeArtifact(
            purpose=draft.purpose, code=draft.code, stdout=result.stdout,
            stderr=_combined_stderr(result.stderr, validation_reason), success=effective_success,
            artifact_paths=result.artifact_paths,
            read_paths=getattr(result, "read_paths", []),
            category=f"baseline:{item['category']}",
            batch=state.coder_current_batch,
            evidence_role="baseline" if effective_success else "none",
        ))
        if not effective_success and item["attempt"] < MAX_CODE_RETRIES:
            feedback = validation_reason or result.stderr or result.stdout[-1000:]
            item.update(
                attempt=item["attempt"] + 1, prev_err=feedback,
                prev_kind=error_kind, prev_code=draft.code,
            )
            queue[0] = item
        else:
            queue.pop(0)
            if (
                effective_success and not queue
                and _has_primary_for_current_batch(state, artifacts)
            ):
                queue.extend(_missing_baseline_items(state, artifacts))

    if queue:
        return {
            "coder_work_queue": queue, "coder_work_artifacts": artifacts,
            "coder_pending_draft": {}, "coder_phase": "generate",
        }

    return _coder_done_delta(artifacts, state=state)


def _coder_done_delta(
    artifacts: list[CodeArtifact], *, state: MathModelingState | None = None
) -> dict:
    delta: dict = {
        "code_artifacts": artifacts, "coder_work_queue": [],
        "coder_work_artifacts": [], "coder_pending_draft": {}, "coder_phase": "done",
    }
    has_primary = (
        _has_primary_for_current_batch(state, artifacts)
        if state is not None else any(
            a.success and a.category == "figure" and a.evidence_role == "primary"
            for a in artifacts
        )
    )
    if not has_primary:
        delta["errors"] = ["coder: all code tasks failed"]
    return delta


def coder_node(state: MathModelingState) -> dict:
    """Legacy compatibility path: run prepare/generate/execute in one node."""
    current = state
    delta = coder_prepare_node(current)
    current = current.model_copy(update=delta)
    for _ in range(100):
        if current.coder_phase == "done":
            break
        if current.coder_phase == "generate":
            delta = coder_generate_node(current)
        else:
            delta = coder_execute_node(current)
        current = current.model_copy(update=delta)
    return {
        "code_artifacts": current.code_artifacts,
        "coder_work_queue": current.coder_work_queue,
        "coder_work_artifacts": current.coder_work_artifacts,
        "coder_pending_draft": current.coder_pending_draft,
        "coder_phase": current.coder_phase,
        "errors": current.errors,
    }

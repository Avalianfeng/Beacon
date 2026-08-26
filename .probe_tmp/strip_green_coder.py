# -*- coding: utf-8 -*-
"""一次性脚本：从 coder.py 中移除绿色物流专属代码块。"""
from pathlib import Path

path = Path(r"e:\git_clone\Beacon\src\math_agent\nodes\coder.py")
text = path.read_text(encoding="utf-8")


def cut(start_anchor: str, end_anchor: str) -> None:
    """删除从 start_anchor 起到 end_anchor 之前（保留 end_anchor）的文本。"""
    global text
    i = text.index(start_anchor)
    j = text.index(end_anchor, i)
    assert i < j, (start_anchor, end_anchor)
    text = text[:i] + text[j:]


# 1. 删除 _green_logistics_template_code（含 DUAL_SCENARIO wrapper）
cut(
    'def _green_logistics_template_code(data_dir: str) -> str:',
    'def _template_figure_draft(',
)

# 2. _template_figure_draft：移除物流附件分支
old = '''def _template_figure_draft(item: dict, data_dir: str, data_files: list | None,
                           blueprint=None) -> CoderDraft | None:
    index = int(item.get("index", 0))
    purpose = str(item.get("purpose", f"figure-{index}"))
    filenames = {
        str(info.get("filename") if isinstance(info, dict) else info.filename)
        for info in (data_files or [])
    }
    required = {"订单信息.xlsx", "距离矩阵.xlsx", "时间窗.xlsx", "客户坐标信息.xlsx"}
    if index == 0 and required <= filenames:
        return CoderDraft(purpose=purpose, code=_green_logistics_template_code(data_dir or ""))
    return CoderDraft(
'''
new = '''def _template_figure_draft(item: dict, data_dir: str, data_files: list | None,
                           blueprint=None) -> CoderDraft | None:
    index = int(item.get("index", 0))
    purpose = str(item.get("purpose", f"figure-{index}"))
    return CoderDraft(
'''
assert old in text
text = text.replace(old, new, 1)

# 3. 删除 _safe_baseline_draft 整个函数
cut(
    'def _safe_baseline_draft(item: dict, main_code: str) -> CoderDraft | None:',
    'def _safe_solver_model_contract(',
)

# 4. 删除 _safe_solver_model_contract
cut(
    'def _safe_solver_model_contract(',
    'def _use_deterministic_coder(',
)

# 5. 删除 _matches_green_logistics_contract
cut(
    'def _matches_green_logistics_contract(',
    'def _max_figure_tasks(',
)

# 6. 删除 _green_depth_evidence_error 与 _leaked_green_metrics
cut(
    'def _green_depth_evidence_error(stdout: str) -> str:',
    'def _validated_execution(',
)

# 7. _validated_execution：删除 green_schema 相关判定
old = '''    filenames = {info.filename for info in state.data_files}
    green_schema = _GREEN_LOGISTICS_FILES <= filenames
    if not green_schema:
        leaked = _leaked_green_metrics(parsed)
        if leaked:
            return (
                False,
                "非物流题禁止输出物流指标：" + ", ".join(leaked),
                "output_validation",
            )
    if green_schema and item.get("kind") == "figure" and require_data_usage:
        metrics = parsed.get("ours", {})
        required_metrics = {
            "total_cost", "vehicles", "service_rate", "total_carbon", "total_distance",
            "fuel_vehicles", "ev_vehicles", "timewin_rate", "response_time",
        }
        missing = sorted(required_metrics - set(metrics))
        if missing:
            return False, f"城市物流主证据缺少关键指标：{missing}", "output_validation"
        if metrics["service_rate"] < 0.95:
            return (
                False,
                f"城市物流主方案服务率 service_rate={metrics['service_rate']:.4f} 低于 0.95，"
                "属于结构性未服务结果，不能作为主证据",
                "output_validation",
            )
        if metrics["vehicles"] > 185:
            return False, f"车辆数 {metrics['vehicles']:g} 超过题面有限车队 185 辆", "output_validation"
        if metrics["fuel_vehicles"] > 160 or metrics["ev_vehicles"] > 25:
            return False, "燃油车或新能源车启用数超过题面分类上限", "output_validation"
        if abs(metrics["fuel_vehicles"] + metrics["ev_vehicles"] - metrics["vehicles"]) > 1e-9:
            return False, "燃油车与新能源车数量之和不等于总车辆数", "output_validation"
        depth_error = _green_depth_evidence_error(result.stdout)
        if depth_error:
            return False, depth_error, "output_validation"
    if require_data_usage:
'''
new = '''    if require_data_usage:
'''
assert old in text
text = text.replace(old, new, 1)

old = '''        if green_schema and not expected_paths.issubset(observed_paths):
            missing_paths = sorted(expected_paths - observed_paths)
            return False, f"城市物流主证据未读取全部四个附件：{missing_paths}", "output_validation"
'''
assert old in text
text = text.replace(old, "", 1)

# 8. _local_repair_draft 中的 groupby→模板回退（物流专属救援路径）
old = '''    if (
        state is not None
        and str(item.get("prev_kind") or "") in {"runtime", "timeout", "output_validation"}
        and any(marker in error for marker in (
            "无法服务任何客户", "no progress", "timeout after 120", "service_rate=", "缺少关键指标",
        ))
        and ".groupby(" in repaired
    ):
        filenames = {info.filename for info in state.data_files}
        required = {"订单信息.xlsx", "距离矩阵.xlsx", "时间窗.xlsx", "客户坐标信息.xlsx"}
        if required <= filenames and _matches_green_logistics_contract(state):
            return _template_figure_draft(
                item, state.data_dir, state.data_files,
                blueprint=state.problem_blueprint,
            )
'''
assert old in text
text = text.replace(old, "", 1)

# 9. coder_generate_node figure 分支：移除 green_contract 相关逻辑
old = '''    if item["kind"] == "figure":
        filenames = {info.filename for info in state.data_files}
        green_schema = _GREEN_LOGISTICS_FILES <= filenames
        green_contract = green_schema and _matches_green_logistics_contract(state)
        deterministic_green_primary = (
            evidence_target == "primary"
            and int(item.get("index", 0)) == 0
            and green_contract
        )
        # 这类附件已有经过真实数据、血缘和深度门禁验证的专用求解器。直接生成
        # 确定性草稿，随后仍由 coder_execute_node 执行全部验证；避免让 LLM
        # 重写一万余字符代码时反复产生空 JSON 或截断 JSON。
        if _use_deterministic_coder() or deterministic_green_primary:
'''
new = '''    if item["kind"] == "figure":
        # 显式离线应急模式下使用本地模板；正常流程一律走 LLM 生成。
        if _use_deterministic_coder():
'''
assert old in text
text = text.replace(old, new, 1)

old = '''            fallback_after_verified_cycle = (
                evidence_target == "primary"
                and green_contract
                and state.code_verify_iteration >= 1
                and primary is None
            )
            refresh_safe_solver = (
                failure_kind == "consistency"
                and "BEACON_GREEN_LOGISTICS_SAFE_SOLVER" in previous_code
                and green_contract
            )
            draft = None
            if not is_supporting:
                draft = (
                    _template_figure_draft(
                        item, state.data_dir, state.data_files,
                        blueprint=state.problem_blueprint,
                    )
                    if fallback_after_verified_cycle or refresh_safe_solver
                    else _local_repair_draft(item, previous_code, state)
                )
'''
new = '''            draft = None
            if not is_supporting:
                draft = _local_repair_draft(item, previous_code, state)
'''
assert old in text
text = text.replace(old, new, 1)

# 10. baseline 分支：移除 _safe_baseline_draft 调用
old = '''            if draft is None:
                draft = _safe_baseline_draft(item, main_code)
            if draft is None:
                draft = complete(
'''
new = '''            if draft is None:
                draft = complete(
'''
assert old in text
text = text.replace(old, new, 1)

old = '''        except Exception as exc:
            fallback = _safe_baseline_draft(item, main_code)
            if fallback is not None:
                return {
                    "coder_pending_draft": fallback.model_dump(),
                    "coder_phase": "execute",
                }
            artifacts = list(state.coder_work_artifacts)
'''
new = '''        except Exception as exc:
            artifacts = list(state.coder_work_artifacts)
'''
assert old in text
text = text.replace(old, new, 1)

# 11. _coder_done_delta：移除 _safe_solver_model_contract 对齐
old = '''    if not has_primary:
        delta["errors"] = ["coder: all code tasks failed"]
    elif state is not None:
        aligned = _safe_solver_model_contract(state, artifacts)
        if aligned is not None:
            delta["model_versions"] = [aligned]
    return delta
'''
new = '''    if not has_primary:
        delta["errors"] = ["coder: all code tasks failed"]
    return delta
'''
assert old in text
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("OK, remaining green refs:")
import re as _re
for n, line in enumerate(text.splitlines(), 1):
    if _re.search(r"green|GREEN|SAFE_SOLVER", line, _re.IGNORECASE):
        print(n, line.strip()[:120])

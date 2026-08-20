import json
import re
from datetime import datetime, timezone
from pathlib import Path

from math_agent.llm import complete
from math_agent.config import MODEL_ROUTING
from math_agent.prompts.model_code_consistency import SYSTEM, build_prompt
from math_agent.state import MathModelingState, ModelCodeConsistencyReport
from math_agent.tools.runner import (
    extract_valid_result_lines,
    infer_entity_upper_bound,
    structured_evidence_lines,
)


def _curate_review_stdout(artifact, limit: int = 2000) -> str:
    """评审证据优先展示结构化行（Q<id>/RESULT/LIMITATION），避免被调试打印淹没。

    r9 曾用 ``a.stdout[:1000]``：stdout 开头 1100+ 字符全是列名/head 等调试打印，
    Q2.2/RESULT 数值行到不了评审，产生“stdout 未输出 Tmax 具体数值”的误判与
    无效反馈（与 P09 证据白名单同类缺陷，此处为一致性评审侧）。
    """
    structured = structured_evidence_lines(artifact.stdout)
    text = "\n".join(structured) if structured else artifact.stdout
    if len(text) <= limit:
        return text
    return text[:limit] + "\n……（已截断）"


def _consistency_delta(
    state: MathModelingState, report: ModelCodeConsistencyReport, has_primary: bool,
) -> dict:
    """构造节点返回：总轮次 +（有主证据但未达门禁时）低分修复轮次计数。

    两个预算分开计：无主证据轮次用 code_verify_iteration（上限
    MAX_CODE_NO_PRIMARY_ITERATIONS），有主证据但低分的定向修复轮次用
    code_verify_low_score_iteration（上限 MAX_CODE_VERIFY_ITERATIONS），
    避免无主证据轮次提前耗尽修复预算。
    """
    from math_agent.config import MIN_MODEL_CODE_SCORE
    delta = {
        "model_code_reports": [report],
        "code_verify_iteration": state.code_verify_iteration + 1,
    }
    passed = bool(report.approved and report.score >= MIN_MODEL_CODE_SCORE)
    if has_primary and not passed:
        delta["code_verify_low_score_iteration"] = (
            state.code_verify_low_score_iteration + 1
        )
    return delta


def _write_gate_diagnostics(
    state: MathModelingState, report: ModelCodeConsistencyReport, has_primary: bool,
) -> None:
    """把一致性门禁当前值写到 run 目录，供 supervisor/watch 观察与死循环提示。

    节点与 supervisor 是不同进程，直接写 supervisor.json 会与心跳竞争，因此节点
    写独立侧车文件 gate_diagnostics.json，由 supervisor 心跳合并进
    supervisor.json["gate"]；watch 也会直接读本文件兜底。
    """
    out_dir = getattr(state, "output_dir", None)
    if not out_dir:
        return
    try:
        from math_agent.config import (
            MAX_CODE_VERIFY_ITERATIONS, MAX_CODE_NO_PRIMARY_ITERATIONS,
            MIN_MODEL_CODE_SCORE,
        )
        issues = list(report.issues or [])
        latest_issue = issues[0] if issues else ""
        consecutive = 1 if latest_issue else 0
        if latest_issue:
            for prev in reversed(state.model_code_reports or []):
                prev_first = (list(prev.issues or []) or [""])[0]
                if prev_first == latest_issue:
                    consecutive += 1
                else:
                    break
        iteration = state.code_verify_iteration + 1
        passed = bool(report.approved and report.score >= MIN_MODEL_CODE_SCORE)
        low_score_iteration = state.code_verify_low_score_iteration + (
            1 if (has_primary and not passed) else 0
        )
        cap = (
            MAX_CODE_NO_PRIMARY_ITERATIONS if not has_primary
            else MAX_CODE_VERIFY_ITERATIONS
        )
        budget = iteration if not has_primary else low_score_iteration
        payload = {
            "node": "model_code_consistency",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "code_verify_iteration": iteration,
            "code_verify_low_score_iteration": low_score_iteration,
            "max_code_verify_iterations": MAX_CODE_VERIFY_ITERATIONS,
            "max_code_no_primary_iterations": MAX_CODE_NO_PRIMARY_ITERATIONS,
            "min_model_code_score": MIN_MODEL_CODE_SCORE,
            "has_primary": bool(has_primary),
            "approved": bool(report.approved),
            "score": report.score,
            "latest_issue": latest_issue[:240],
            "consecutive_same_issue": consecutive,
            "stall": consecutive >= 3,
            "over_limit": budget >= cap,
        }
        path = Path(out_dir) / "gate_diagnostics.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        # 诊断信息写入失败不影响门禁本身
        pass


def model_code_consistency_node(state: MathModelingState) -> dict:
    blueprint = state.problem_blueprint
    model = state.latest_model()

    if model is None:
        report = ModelCodeConsistencyReport(
            score=0, approved=False,
            issues=["model_code_consistency: 没有 model_versions，无法审查"],
        )
        _write_gate_diagnostics(state, report, has_primary=False)
        return _consistency_delta(state, report, has_primary=False)

    # 只看最新批次的 artifact（batch 递增机制保证 retry 不产生脏数据）
    max_batch = max((a.batch for a in state.code_artifacts), default=0)
    upper_bound = infer_entity_upper_bound(state.data_files)

    def _has_valid_result(artifact) -> bool:
        expected = (
            artifact.category.split(":", 1)[1]
            if artifact.category.startswith("baseline:") else None
        )
        return bool(extract_valid_result_lines(
            artifact.stdout,
            stderr=artifact.stderr,
            expected_identifier=expected,
            max_entity_count=upper_bound,
        ))

    main_artifacts = [
        a for a in state.code_artifacts
        if a.success and a.category == "figure" and a.batch == max_batch
        and a.evidence_role == "primary" and _has_valid_result(a)
    ]
    baseline_artifacts = [
        a for a in state.code_artifacts
        if a.success and a.category.startswith("baseline:") and a.batch == max_batch
        and a.evidence_role == "baseline" and _has_valid_result(a)
    ]
    failed_artifacts = [
        a for a in state.code_artifacts
        if not a.success and a.batch == max_batch
    ]

    if not main_artifacts:
        # 没有成功主方案代码 -> 直接未通过。把最近一批失败原因带进报告，
        # 让 insight/watch 一眼看到真正卡点，而不是只看到泛化的 0 分。
        reasons: list[str] = []
        seen: set[str] = set()
        for artifact in state.latest_code_artifacts():
            reason = (artifact.stderr or "").strip()
            if not reason or reason in seen:
                continue
            seen.add(reason)
            label = artifact.category or "figure"
            reasons.append(f"[{label}] {reason[:240]}")
            if len(reasons) >= 3:
                break
        issue = "model_code_consistency: 没有成功的主方案代码 artifact，无法审查一致性"
        if reasons:
            issue += "（最近失败：" + "；".join(reasons) + "）"
        report = ModelCodeConsistencyReport(
            score=0, approved=False,
            missing_variables=list(model.variables.keys()),
            issues=[issue],
        )
        _write_gate_diagnostics(state, report, has_primary=False)
        return _consistency_delta(state, report, has_primary=False)

    # 构造审查输入
    blueprint_json = blueprint.model_dump_json(indent=2) if blueprint else "（无 blueprint）"
    model_json = model.model_dump_json(indent=2)

    # 主方案通常在数据读取之后才定义目标、约束和求解循环；只取前 2000 字符
    # 会系统性地把这些实现截掉，造成“代码只做了聚合”的假阴性。单个正式主脚本
    # 仍设置 16k 有界上限，避免异常生成内容无限扩大审查请求。
    main_summaries = "\n---\n".join(
        f"purpose: {a.purpose}\ncode:\n{a.code[:16000]}"
        for a in main_artifacts
    )
    main_stdout = "\n---\n".join(
        f"[{a.purpose}]\n{_curate_review_stdout(a)}" for a in main_artifacts if a.stdout
    ) or "（无 stdout）"
    baseline_stdout = "\n---\n".join(
        f"[{a.category}]\n{_curate_review_stdout(a, limit=1200)}"
        for a in baseline_artifacts if a.stdout
    ) or "（无 baseline stdout）"
    failed_stderr = "\n---\n".join(
        f"[{a.category or 'figure'}]\n{a.stderr[:300]}" for a in failed_artifacts if a.stderr
    ) or "（无失败 artifact）"

    prompt = build_prompt(
        blueprint_json, model_json, main_summaries, main_stdout,
        baseline_stdout, failed_stderr,
    )
    out: ModelCodeConsistencyReport = complete(
        prompt, schema=ModelCodeConsistencyReport, system=SYSTEM,
        model=MODEL_ROUTING["model_critic"],
    )
    out = _apply_numeric_fatal_backstop(out)
    _write_gate_diagnostics(state, out, has_primary=True)
    return _consistency_delta(state, out, has_primary=True)


# 评审自身已认定致命数值缺陷却仍放行的兜底（r6 曾以 8/10 放行“与工程经验
# 严重不符”的 Tmax=0.37）。评审模型可能按“结构实现完整”给分而忽略自己
# 列出的数量级错误；这里把这类自认的致命缺陷强制转为不通过。
_NUMERIC_FATAL_PATTERNS = (
    "严重不符", "明显不合理", "数量级错误", "严重错误", "编造", "伪造",
)


def _apply_numeric_fatal_backstop(
    report: ModelCodeConsistencyReport,
) -> ModelCodeConsistencyReport:
    if not report.approved or not report.issues:
        return report
    fatal = [
        issue for issue in report.issues
        if any(pattern in issue for pattern in _NUMERIC_FATAL_PATTERNS)
    ]
    if not fatal:
        return report
    report.approved = False
    report.score = min(report.score, 5)
    report.issues = [
        *fatal,
        "（确定性兜底）评审已认定数值严重不符/明显不合理，按致命缺陷强制不通过，"
        "需修正单位或数量级后重试。",
        *[i for i in report.issues if i not in fatal],
    ]
    return report

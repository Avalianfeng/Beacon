"""figure_pipeline：扫描 code_artifacts/sensitivity_runs 里的 PNG，
对每张图做 Critic 评分（最多重试 1 次）+ Analyst 写图说。

不重新生成图（重生成的成本/收益不划算）；只评分、解读，
低质量图保留但 quality_score 反映在 Evaluation 中。
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from math_agent.config import MODEL_ROUTING
from math_agent.llm import complete
from math_agent.prompts.figure_critic import (
    SYSTEM as FC_SYSTEM, build_prompt as fc_prompt,
)
from math_agent.prompts.figure_analyst import (
    SYSTEM as FA_SYSTEM, build_prompt as fa_prompt,
)
from math_agent.state import FigureArtifact, MathModelingState
from math_agent.nodes.sensitivity import formal_sensitivity_runs
from math_agent.tools.image import inspect_image, encode_image_to_data_url
from math_agent.tools.runner import extract_numeric_results


class FigureCriticOut(BaseModel):
    score: int = Field(ge=0, le=10)
    issues: list[str] = []
    suggestions: list[str] = []
    approved: bool = False


class FigureAnalysisOut(BaseModel):
    analysis: str


_MAX_CRITIC_RETRIES = 1  # critic 不通过时，最多再问一次（不重新生成图）

def _figure_purpose_and_context(path: str, artifact) -> tuple[str, str]:
    return artifact.purpose, artifact.stdout[:500]


_GENERIC_EVIDENCE_KEYS = (
    "R²", "R2", "T_max", "Tmax", "T_opt", "Topt", "安全裕度",
)


def _extract_generic_metrics(stdout: str) -> dict[str, float]:
    """从 stdout 提取通用指标（R²/T_max/T_opt/安全裕度）作为一致性键。

    任一字段解析失败则跳过该键，避免键缺失误杀。
    """
    emitted = extract_numeric_results(stdout).get("ours", {})
    generic: dict[str, float] = {}
    for key in _GENERIC_EVIDENCE_KEYS:
        value = emitted.get(key)
        if isinstance(value, (int, float)) and value == value and value not in (float("inf"), float("-inf")):
            generic[key] = float(value)
    return generic


def _matches_primary_evidence(stdout: str, primary: dict[str, float]) -> bool:
    """拒绝仍携带旧主方案口径的补充图，避免图说污染正式论文。

    用主方案 RESULT 的通用键（R²/T_max/T_opt/安全裕度）做偏差校验，>20%
    视为漂移。任一指标存在数量级灾难值（与主方案相差 10 倍以上）也拒绝。
    """
    emitted = extract_numeric_results(stdout).get("ours", {})
    if not primary or not emitted:
        return True
    # 通用键（R²/T_max/T_opt/安全裕度）
    generic_primary = _extract_generic_metrics(
        "RESULT: baseline=ours " + " ".join(f"{k}={v}" for k, v in primary.items())
    )
    generic_emitted = _extract_generic_metrics(stdout)
    for key, expected in generic_primary.items():
        observed = generic_emitted.get(key)
        if observed is None:
            continue
        if abs(expected) < 1e-12:
            if abs(observed) > 1e-6:
                return False
            continue
        if abs(observed) > abs(expected) * 10 or abs(expected) > abs(observed) * 10:
            return False  # 数量级灾难
        if abs(observed - expected) > abs(expected) * 0.2:
            return False  # 口径漂移
    return True


def _collect_pngs(state: MathModelingState) -> list[tuple[str, str, str]]:
    """返回 [(path, purpose, context_text), ...]"""
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    primary_artifact = next(
        (
            artifact for artifact in reversed(state.latest_code_artifacts())
            if artifact.success and artifact.evidence_role == "primary"
        ),
        None,
    )
    primary_metrics = (
        extract_numeric_results(primary_artifact.stdout).get("ours", {})
        if primary_artifact is not None else {}
    )
    for art in state.latest_code_artifacts():
        # baseline 派生的图保留在磁盘作为可复核证据，但论文视觉流水线只审
        # 主方案/辅助图，避免同版式重复。supporting 图与主方案同批同源（coder
        # 工作队列正式产物），接受但要通过数值一致性校验（R²/T_max/T_opt/安全
        # 裕度偏差>20%或灾难值拒绝），防止漂移/坏图混入（r11 fig_1 曾输出
        # R²=0.000000/T_max=0.08 灾难值仍 success=true）。
        # 敏感性图由下方独立、已校验的 sensitivity_runs 提供。
        if not art.success:
            continue
        if art.evidence_role not in {"primary", "supporting"}:
            continue
        if not _matches_primary_evidence(art.stdout, primary_metrics):
            continue
        for p in art.artifact_paths:
            if p.lower().endswith(".png") and p not in seen:
                seen.add(p)
                purpose, context = _figure_purpose_and_context(p, art)
                out.append((p, purpose, context))
    for r in formal_sensitivity_runs(state):
        if (r.figure_path and r.figure_path.lower().endswith(".png")
                and r.figure_path not in seen):
            seen.add(r.figure_path)
            ctx = f"parameter={r.parameter} values={r.values} {r.metric}={r.results}"
            out.append((r.figure_path, f"敏感性分析: {r.parameter}", ctx))
    return out


def _allowed_figure_paths(state: MathModelingState) -> set[str]:
    return {path for path, _, _ in _collect_pngs(state)}


def figure_prepare_node(state: MathModelingState) -> dict:
    """创建逐图审查队列，不把图片 base64 写进 checkpoint。"""
    queue = [
        {"id": f"figure:{i}", "path": path, "purpose": purpose, "context": context}
        for i, (path, purpose, context) in enumerate(_collect_pngs(state))
    ]
    return {
        "figure_work_queue": queue, "figure_work_results": [],
        "figure_current_critic": {}, "figure_critic_attempt": 0,
        "figure_phase": "critic" if queue else "done",
    }


def figure_critic_node(state: MathModelingState) -> dict:
    """对当前图片执行一次 critic 调用。"""
    # 兼容已持久化旧队列：恢复时清掉 baseline 重复图，并同步过滤已完成结果。
    allowed = _allowed_figure_paths(state)
    queue = [item for item in state.figure_work_queue if item.get("path") in allowed]
    completed = [
        figure for figure in state.figure_work_results if figure.path in allowed
    ]
    if not queue:
        return {
            "figures": completed,
            "figure_work_queue": [],
            "figure_work_results": [],
            "figure_current_critic": {},
            "figure_critic_attempt": 0,
            "figure_phase": "done",
        }
    item = queue[0]
    try:
        info = inspect_image(item["path"])
        url = encode_image_to_data_url(item["path"])
    except (OSError, ValueError) as exc:
        queue.pop(0)
        delta = {
            "errors": [f"figure_pipeline: 无法读取图像 {item['path']}: {exc}"],
            "figure_work_queue": queue,
            "figure_phase": "critic" if queue else "done",
        }
        if not queue and state.figure_work_results:
            delta["figures"] = completed
            delta["figure_work_results"] = []
        return delta
    meta = f"{info.width}x{info.height}px, dpi={info.dpi}"
    critic: FigureCriticOut = complete(
        fc_prompt(item["purpose"], meta), schema=FigureCriticOut,
        system=FC_SYSTEM, model=MODEL_ROUTING["figure_critic"],
        images=[url], profile="vision",
    )
    attempt = state.figure_critic_attempt
    if not critic.approved and attempt < _MAX_CRITIC_RETRIES:
        return {
            "figure_current_critic": critic.model_dump(),
            "figure_critic_attempt": attempt + 1, "figure_phase": "critic",
        }
    return {
        "figure_current_critic": critic.model_dump(),
        "figure_critic_attempt": attempt, "figure_phase": "analysis",
    }


def figure_analysis_node(state: MathModelingState) -> dict:
    """解释当前图片并完成该工作项；下一张图片从新 checkpoint 开始。"""
    queue = list(state.figure_work_queue)
    if not queue:
        return {"figure_phase": "done"}
    item = queue.pop(0)
    url = encode_image_to_data_url(item["path"])
    analysis: FigureAnalysisOut = complete(
        fa_prompt(item["purpose"], item["context"]), schema=FigureAnalysisOut,
        system=FA_SYSTEM, model=MODEL_ROUTING["figure_analyst"],
        images=[url], profile="vision",
    )
    critic = FigureCriticOut.model_validate(state.figure_current_critic)
    results = [*state.figure_work_results, FigureArtifact(
        path=item["path"], purpose=item["purpose"], caption=analysis.analysis[:60],
        quality_score=critic.score, quality_issues=list(critic.issues),
        analysis=analysis.analysis,
    )]
    if queue:
        return {
            "figure_work_queue": queue, "figure_work_results": results,
            "figure_current_critic": {}, "figure_critic_attempt": 0,
            "figure_phase": "critic",
        }
    return {
        "figures": results, "figure_work_queue": [], "figure_work_results": [],
        "figure_current_critic": {}, "figure_critic_attempt": 0,
        "figure_phase": "done",
    }


def figure_pipeline_node(state: MathModelingState) -> dict:
    figures: list[FigureArtifact] = []
    errors: list[str] = []
    for path, purpose, context in _collect_pngs(state):
        try:
            info = inspect_image(path)
            url = encode_image_to_data_url(path)
        except (OSError, ValueError) as exc:
            errors.append(f"figure_pipeline: 无法读取图像 {path}: {exc}")
            continue
        meta = f"{info.width}x{info.height}px, dpi={info.dpi}"

        critic: FigureCriticOut | None = None
        for _ in range(_MAX_CRITIC_RETRIES + 1):
            critic = complete(
                fc_prompt(purpose, meta),
                schema=FigureCriticOut, system=FC_SYSTEM,
                model=MODEL_ROUTING["figure_critic"],
                images=[url],
                profile="vision",
            )
            if critic.approved:
                break

        analysis: FigureAnalysisOut = complete(
            fa_prompt(purpose, context),
            schema=FigureAnalysisOut, system=FA_SYSTEM,
            model=MODEL_ROUTING["figure_analyst"],
            images=[url],
            profile="vision",
        )

        figures.append(FigureArtifact(
            path=path, purpose=purpose,
            caption=analysis.analysis[:60],   # 简短题注（正文用）
            quality_score=critic.score if critic else 0,
            quality_issues=list(critic.issues) if critic else [],
            analysis=analysis.analysis,
        ))

    delta: dict = {}
    if figures:
        delta["figures"] = figures
    if errors:
        delta["errors"] = errors
    return delta

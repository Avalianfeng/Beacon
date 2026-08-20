"""论文离线评审使用的结构化证据提取与动态一致性检查。"""

from __future__ import annotations

import math
import re

from math_agent.nodes.sensitivity import formal_sensitivity_issues
from math_agent.state import MathModelingState
from math_agent.tools.runner import infer_entity_upper_bound, validate_numeric_results


PAPER_FIELDS = (
    "abstract",
    "problem_restatement",
    "assumptions",
    "notation",
    "model_section",
    "solution",
    "sensitivity",
    "conclusion",
)


def paper_body(state: MathModelingState) -> str:
    return "\n".join(
        str(getattr(state.paper, field, "") or "")
        for field in PAPER_FIELDS
    )


def verified_result_map(
    state: MathModelingState,
) -> dict[str, dict[str, float]]:
    """只提取最新批次、已成功且通过统一数值门禁的正式 RESULT。"""
    results: dict[str, dict[str, float]] = {}
    upper_bound = infer_entity_upper_bound(state.data_files)
    for artifact in state.latest_code_artifacts():
        if (
            not artifact.success
            or artifact.evidence_role not in {"primary", "baseline"}
        ):
            continue
        expected = (
            artifact.category.split(":", 1)[1]
            if artifact.category.startswith("baseline:")
            else None
        )
        valid, _, parsed = validate_numeric_results(
            artifact.stdout,
            stderr=artifact.stderr,
            require_result=True,
            expected_identifier=expected,
            max_entity_count=upper_bound,
        )
        if not valid:
            continue
        if artifact.evidence_role == "primary":
            if set(parsed) != {"ours"}:
                continue
            results["ours"] = parsed["ours"]
            continue
        if expected is None or set(parsed) != {expected}:
            continue
        results[expected] = parsed[expected]
    return results


def verified_structured_map(
    state: MathModelingState,
    label: str,
    scenario: str = "",
) -> dict[str, float]:
    """从最新成功主证据 stdout 的指定结构化行提取数值字段。"""
    primary = next(
        (
            artifact
            for artifact in reversed(state.latest_code_artifacts())
            if artifact.success
            and artifact.evidence_role == "primary"
        ),
        None,
    )
    if primary is None:
        return {}
    source = primary.stdout
    if scenario:
        scenario_match = re.search(
            rf"(?ms)^SCENARIO_BEGIN:\s*{re.escape(scenario)}\s*$"
            rf"(.*?)^SCENARIO_END:\s*{re.escape(scenario)}\s*$",
            source,
        )
        if scenario_match:
            source = scenario_match.group(1)
    match = re.search(rf"(?m)^{re.escape(label)}:\s+(.+)$", source)
    if match is None:
        return {}
    values = {
        item.group(1): float(item.group(2))
        for item in re.finditer(
            r"([A-Za-z_][\w]*)=(-?(?:\d+(?:\.\d+)?|\.\d+))",
            match.group(1),
        )
    }
    return values if all(math.isfinite(value) for value in values.values()) else {}


def _contains_number_after_label(
    body: str,
    value: float,
    labels: tuple[str, ...],
    *,
    suffix: str = "",
    max_gap: int = 48,
    blockers: tuple[str, ...] = (),
) -> bool:
    """要求数值紧跟语义标签，避免同段内其他指标的数值串位。"""
    compact = body.replace(",", "")
    magnitude = abs(value)
    decimals = (
        (6, 8, 10)
        if 0 < magnitude < 0.01
        else (2, 4, 6, 8) if magnitude < 1 else (0, 2, 4, 6, 8)
    )
    tokens: set[str] = set()
    for places in decimals:
        fixed = f"{value:.{places}f}"
        tokens.add(fixed)
        if places:
            tokens.add(fixed.rstrip("0").rstrip("."))
    for label in labels:
        for label_match in re.finditer(re.escape(label), compact):
            tail = compact[label_match.end():label_match.end() + max_gap]
            for token in tokens:
                pattern = rf"(?<![\d.]){re.escape(token)}{re.escape(suffix)}(?![\d.])"
                number_match = re.search(pattern, tail)
                if (
                    number_match is not None
                    and not any(
                        blocker in tail[:number_match.start()]
                        for blocker in blockers
                    )
                ):
                    return True
    return False


def offline_evidence_issues(
    state: MathModelingState,
    body: str | None = None,
) -> list[str]:
    """确认离线高分所引用的数值来自本次正式结构化产物。"""
    body = body if body is not None else paper_body(state)
    results = verified_result_map(state)
    issues: list[str] = []
    if "ours" not in results:
        issues.append("缺少本次正式结构化结果：ours")
    result_labels = {
        "ours": ("本文方案", "主方案"),
        "no_schedule": ("无邻域与发车优化", "no_schedule"),
        "simple_pred": ("定速预测", "simple_pred"),
        "greedy": ("贪婪构造", "greedy"),
    }
    all_result_labels = tuple({
        label
        for labels in result_labels.values()
        for label in labels
    })
    for identifier, metrics in results.items():
        total_cost = metrics.get("total_cost", metrics.get("cost"))
        labels = result_labels.get(identifier, (identifier,))
        if total_cost is not None and not _contains_number_after_label(
            body,
            total_cost,
            labels,
            max_gap=48,
            blockers=tuple(
                label for label in all_result_labels if label not in labels
            ),
        ):
            issues.append(
                f"正文未引用本次 {identifier} 的 total_cost={total_cost:.12g}"
            )

    issues.extend(formal_sensitivity_issues(state))
    return issues

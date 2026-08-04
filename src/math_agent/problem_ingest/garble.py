"""题面文本乱码/数学字形损坏启发式检测。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# 替换字符、方框占位、常见失败字形
_REPLACEMENT = "\ufffd"
_BOX = "\u25a1"
_EMPTY_SUPER = re.compile(r"\^\{\s*\}")
_SUPER_SPAN = re.compile(r"\^\{([^}]*)\}")

# 非空白字符中替换/方框占比超过此值 → 触发视觉回退
DEFAULT_GARBLE_RATIO_THRESHOLD = 0.02
# 空上标占全部上标的比例
DEFAULT_EMPTY_SUPER_RATIO_THRESHOLD = 0.25
# 至少这么多非空白字符才判定；过短文本避免误触发
_MIN_NON_WS = 80


@dataclass
class GarbleReport:
    ok: bool
    garble_ratio: float
    empty_super_ratio: float
    replacement_count: int
    box_count: int
    empty_super_count: int
    super_count: int
    non_ws_count: int
    warnings: list[str] = field(default_factory=list)
    should_vision_fallback: bool = False


def assess_garble(
    text: str,
    *,
    garble_ratio_threshold: float = DEFAULT_GARBLE_RATIO_THRESHOLD,
    empty_super_ratio_threshold: float = DEFAULT_EMPTY_SUPER_RATIO_THRESHOLD,
) -> GarbleReport:
    """评估抽取文本的乱码程度。"""
    if not text:
        return GarbleReport(
            ok=False,
            garble_ratio=1.0,
            empty_super_ratio=0.0,
            replacement_count=0,
            box_count=0,
            empty_super_count=0,
            super_count=0,
            non_ws_count=0,
            warnings=["empty_text"],
            should_vision_fallback=True,
        )

    non_ws = [c for c in text if not c.isspace()]
    non_ws_count = len(non_ws)
    replacement_count = text.count(_REPLACEMENT)
    box_count = text.count(_BOX)
    bad = replacement_count + box_count
    garble_ratio = (bad / non_ws_count) if non_ws_count else 0.0

    supers = _SUPER_SPAN.findall(text)
    super_count = len(supers)
    empty_super_count = sum(1 for s in supers if not s.strip() or set(s) <= {_REPLACEMENT, _BOX, " "})
    # 也计入 ^{} 字面空上标
    empty_super_count = max(empty_super_count, len(_EMPTY_SUPER.findall(text)))
    empty_super_ratio = (empty_super_count / super_count) if super_count else 0.0

    warnings: list[str] = []
    if replacement_count:
        warnings.append("math_glyphs_replaced")
    if box_count:
        warnings.append("box_placeholder_chars")
    if empty_super_count:
        warnings.append("empty_superscripts")

    trigger = False
    if non_ws_count >= _MIN_NON_WS:
        if garble_ratio >= garble_ratio_threshold:
            trigger = True
        if super_count >= 3 and empty_super_ratio >= empty_super_ratio_threshold:
            trigger = True
    elif bad > 0 and non_ws_count > 0 and garble_ratio >= 0.1:
        trigger = True

    ok = not trigger and not warnings
    # 有轻微警告但仍低于阈值：ok=False 以便 UI 提示核对，但不强制视觉
    if warnings and not trigger:
        ok = False

    return GarbleReport(
        ok=ok,
        garble_ratio=round(garble_ratio, 4),
        empty_super_ratio=round(empty_super_ratio, 4),
        replacement_count=replacement_count,
        box_count=box_count,
        empty_super_count=empty_super_count,
        super_count=super_count,
        non_ws_count=non_ws_count,
        warnings=warnings,
        should_vision_fallback=trigger,
    )

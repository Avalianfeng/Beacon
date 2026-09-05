"""分阶段编组的 CLI 帮助文案（D-002 操作面 · P6 认知卫生）。

供 ``typer.Typer(help=ROOT_HELP)`` 与子命令组 ``GROUP_HELP`` 引用；
测试通过 ``STAGE_HELP_MARKERS`` 断言默认做题链标记存在。
"""

from __future__ import annotations

ROOT_HELP = """\
做题主路径（D-002 / D-005；默认只用这些）：
  S0 导入     math-agent problem import|show|stage
  S1/S2       无 CLI：写 data_profile.md / exploration.md / 领域知识.md（人检，见 stage --json d007_missing）
  S3 方向     math-agent brief init|check；收束后 math-agent plan build|check
  S4 预检     math-agent run --dry-run
  S5 验证     math-agent reference verify|recertify
  S6 写作     math-agent run --plan plan.json --brief …（先 plan check + reference add + inject/sensitivity.py；应急才 --from writer）
  S7 评审     math-agent review-check（--strict 核关键 RESULT）；停机交棒 math-agent critic-handoff
  S8 人审     math-agent accept

可选遗留执行器（S9；不作无人值守主路径，D-005）：
  math-agent start|supervise|watch|status|pause|recover
  math-agent restart --from coder|writer；review / resume
  全图 run（无 --from / 无 --dry-run）亦可用；勿与 review-check / accept 混用

非做题路径：ingest（RAG，当前不启用）· bench（回归基准）· brief dialogue（TTY 交互，真跑不用）
"""

# 默认做题链标记（S9 仍出现在 ROOT_HELP 降权段，但不进本元组）
STAGE_HELP_MARKERS: tuple[str, ...] = ("S0", "S3", "S4", "S5", "S6", "S7", "S8")

GROUP_HELP: dict[str, str] = {
    "problem": "S0 题目资产：导入/归档/总览/阶段（problem import|show|stage）",
    "brief": "S3 方向收敛：brief init|check（dialogue 为非做题路径）",
    "plan": "S3/S6：plan build|check（brief→plan v0；注入前零 token 预检）",
    "reference": "S5/S6：verify|recertify + add|run|tables|paper",
    "review": "S7 评审：包装 check_*（review-check；与流水线 review 分开）",
    "accept": "S8 人审登记：accept（与流水线 resume 分开）",
}

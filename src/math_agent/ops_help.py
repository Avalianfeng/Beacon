"""分阶段编组的 CLI 帮助文案（D-002 操作面）。

供 ``typer.Typer(help=ROOT_HELP)`` 与子命令组 ``GROUP_HELP`` 引用；
测试通过 ``STAGE_HELP_MARKERS`` 断言阶段标记存在。
"""

from __future__ import annotations

ROOT_HELP = """\
按阶段（D-002 操作面；流水线为可选执行器）：
  S0 导入     math-agent problem import|show|stage
  S3 方向     math-agent brief init|check
  S4 预检     math-agent run --dry-run
  S5 验证     math-agent reference verify
  S6 登记     math-agent reference add|run|tables|paper
  S7 评审     math-agent review-check
  S9 可选流水线  math-agent start|supervise|watch|status|pause|recover|restart
"""

STAGE_HELP_MARKERS: tuple[str, ...] = ("S0", "S3", "S6", "S7", "S9")

GROUP_HELP: dict[str, str] = {
    "problem": "S0 题目资产：导入/归档/总览/阶段（problem import|show|stage）",
    "brief": "S3 方向收敛：生成与校验 brief.json（brief init|check）",
    "reference": "S6 登记装配：参考实现与论文装配（reference add|run|tables|paper|verify）",
    "review": "S7 评审：包装 check_* 脚本（review-check；与流水线 review 命令分开）",
}

<!-- doc: type=plan status=superseded updated=2026-08-27 -->
> **superseded（2026-08-27 文档收口）**：机制修复 M 系列已收口——M1/M6/M5-prompt 完成、M2 并入图体系重设计（暂缓）、M3 不排期、M4 冻结、M5 校验层冻结（决策落点：[07-待决策与超范围](实现计划-8-20/07-待决策与超范围.md) + [8-26-大模块规划](实现计划-8-20/8-26-大模块规划-必须做但不着急.md)）；验证清单角色 → [8-27-操作面契约](实现计划-8-20/8-27-操作面契约.md) S4–S5。本文保留作历史账本与评审记录参考。

# Modeling Brief：实现到哪一步、如何验证、下一步路线

- 建立日期：2026-08-19
- 关联：[实施计划书](10-ModelingBrief实施计划书.md)、[MCM-51 迭代计划](08-MCM51整改迭代计划.md)、[体系流程优化报告 A2](09-体系流程优化报告.md)
- 定位：**验证清单 + 下一步工作安排**。不替代计划书里的 schema/决策；只回答三件事：
  1. 信息够不够开下一轮「路线更迭」；
  2. 目标句现在实现到哪一层；
  3. 接手者按什么顺序验证、验证通过后才改 coder/modeler。
- 工作区：HEAD `9f2906c`；全量 pytest **810 passed / 0 failed / 4 skipped**（收集 814，2026-08-20 实测；12 个既有失败已修复入库，与 brief 链路无关）。

---

## 一、目标句拆开对照（现在做到哪）

目标原文：

> 任务开始前，由人 + AI 对话产出 `brief.json`（八字段：逐题方向/公式注意/讨论点/红线/图表/评分/数据注意/文献方向），注入流水线，在源头杜绝方向性错误。

| 子句 | 代码/产物现状 | 是否已用真题跑通 | 结论 |
|---|---|---|---|
| 任务开始前 | CLI `brief init/check/dialogue` 在主图之外；`run/supervise --brief` 启动时写入 `state.brief` | 未做带 `--brief` 的正式 run | **管道就绪，未实跑** |
| 人 + AI 对话产出 | CLI `brief dialogue --assist`：每字段 LLM 起草 + 人工确认；失败可手填 | **从未**用 MCM-51 走完一轮对话 | **能力有，无使用证据** |
| 八字段 `brief.json` | `ModelingBrief` schema + `problems/mcm51-a/brief.json`（40 条 id，`brief check` [OK]；M6 增 `1.2-reg-coef`） | 文件由人按迭代计划填写，不是对话产物 | **内容有，来源不是对话** |
| 注入流水线 | 六处：analyst / blueprint_critic / model_critic / modeler / coder / writer_section；`run_manifest.brief_sha256`；`out/brief.json` 副本 | 仅单测 mock prompt 含块 | **接线已测，流水线未测** |
| 在源头杜绝方向性错误 | `brief_coverage` 只校验「analyst 是否逐条回应」，**不评判方向对错**；方向错了只能改 brief 重跑 | 无论文/代码对照 1.2 变点检测等 | **防忽略 ≠ 防方向错；后者未验证** |
| Web 对话 | 本迭代明确只做文件透传（`briefPath` → `--brief`） | 无对话 UI | **按决策后置** |

一句话：**A2 的「管道」已经接到图上；A2 的「效果」（源头不再犯 1.2/3.1/3.2/4 方向错）一次都还没在真实流水线上证明。**

分层认知仍成立，不要把下一轮做成「再评估 brief 对不对」：

- 方向级：前置**题目探索** + 对话 / 现成 `brief.json`（2026-08-21 明确：探索先于建模——
  「先问可能要求看到什么，再问怎么解」，协议见 docs/brief-playbook.md）；
- 实现级：现有 critic / consistency / runner 门禁；
- 传递级：`brief_coverage` 硬停（已实现、有单测）。

---

## 二、信息是否足够开「路线更迭」

**够用来写代码转向清单，不够用来宣称体系已完善。**

已经足够、不必再调研就能动手的：

- 方向对不对：见 [iteration-plan](08-MCM51整改迭代计划.md) 第三、四节（变点检测、F_bond 钻孔直径、调心垫圈 233%、偏心压陷、围岩分级）。
- 注入什么约束：见 `problems/mcm51-a/brief.json` 的 39 个稳定 id。
- 流水线怎么吃 brief：见计划书第三、四节 + 本仓库未提交的 `brief.py` / 六处 prompt。

还必须补证据、否则「路线更迭」会和 r11 一样盲改：

- **没有**带 `--brief` 的 MCM-51 新 run（analyst 的 `brief_coverage`、coder 是否避开红线、论文是否出现 3.1-e0 讨论，全无 runs 产物）。
- **没有**把对话走通：不知道 `--assist` 在本机网关/模型下是否可用、耗时、人要改多少。
- 全量 12 失败（coder 多图、granular recovery、graph smoke 不出 paper）与 brief 无关，已作**另案**交 Cursor 修复（2026-08-20：全量 810/0/4，入库 `9f2906c`）。

建议顺序：**先验证管道（第三节）→ 再开一条带 brief 的 MCM-51 短跑 → 用第四节清单判定方向是否被执行 → 最后才改 coder/modeler 实现。** 不要在未验证注入的情况下直接大改求解代码。

---

## 三、如何验证「管道」——不联网 / 低成本（应先做）

工作目录：`E:\git_clone\Beacon`。Python 用 `.venv\Scripts\python.exe`，不要 `uv run`（本机 uv cache 常无权限）。

### 3.1 模块能 import、brief 合法

```powershell
.venv\Scripts\python.exe -m py_compile src\math_agent\cli.py src\math_agent\brief.py
.venv\Scripts\python.exe -m math_agent.cli brief --help
.venv\Scripts\python.exe -m math_agent.cli brief check --brief docs\problems\mcm51-a\brief.json
.venv\Scripts\python.exe -m pytest tests\test_brief.py tests\test_routing.py tests\nodes\test_analyst.py tests\nodes\test_blueprint_critic.py tests\test_cli.py -q
```

通过标准：`brief check` 输出 `[OK]` 且「共 40 条待回应条目」（M6 增 1.2-reg-coef）；上述 pytest 全绿（T4 曾 131 passed 子集）。

### 3.2 无 brief 时行为不变（向后兼容）

不传 `--brief` 启动（或看单测：routing 原 4 条零改动）。门禁 `brief_coverage_problems(None, …) == []`。

### 3.3 CLI 对话（可选、要 LLM）

```powershell
.venv\Scripts\python.exe -m math_agent.cli brief dialogue --problem <题面 spec.json> --out docs\problems\mcm51-a\brief-from-dialogue.json --assist
```

通过标准：能逐字段出草稿或提示起草失败后手填；落盘后再 `brief check`。  
**失败不算 A2 管道失败**（无密钥/网关时 `draft_field` 返回 None 是设计）。失败则继续用已有 `problems/mcm51-a/brief.json`。

### 3.4 Web 透传（不要求对话 UI）

高级选项填 `problems/mcm51-a/brief.json`，启动后 `run.log` / `run.command` 含 `--brief` 与经 `safeProjectPath` 的路径。  
`npm.cmd test -- --run`：brief 四场景应绿；若 `GET /api/active-run` 403，先看 `runs/.beacon-active.json` 是否指向仓外 pytest 临时目录（环境脏，与 brief 无关）。

---

## 四、如何验证「源头杜绝方向错」——必须有一次真跑（下一步核心）

管道绿 **不能** 代替这一节。`brief_coverage=followed` 只说明 analyst **声称**跟了 brief，不说明代码做了变点检测。

### 4.1 建议的最小真跑

新目录，禁止 recover 旧 `51mcm-a-*`：

```text
math-agent supervise --problem <MCM-51 spec> --out runs/51mcm-a-brief-v1 --brief problems/mcm51-a/brief.json --thread default
```

（Web 等价：同一 `--out` + 高级选项 brief 路径。）

跑到至少 **blueprint_critic 之后**（更好：穿过 coder 首轮 execute）。不必一次出 PDF。

### 4.2 产物核对清单（有文件才算数）

| 检查项 | 看哪里 | 通过 |
|---|---|---|
| brief 进了这次 run | `runs/51mcm-a-brief-v1/brief.json` 与源文件一致；`run_manifest.json` 有 `brief_sha256` | 有副本、hash 对得上 |
| 状态带 brief | checkpoint / `state_summary` / insights 中 analyst 输入含「人工建模预备」 | prompt 不是空注入 |
| 传递完整性 | `problem_blueprint.brief_coverage` 覆盖全部 40 个 id（M6 后）；`followed` 或 `deviated`+非空 reason | 缺一条会 retry，预算尽则 **stop**（不是带病进 modeler） |
| 方向是否落地（抽样） | 蓝图/模型/代码/论文是否出现：1.2 分段回归；F_bond 用钻孔直径；3.1 调心垫圈/e=0/233%；禁止 600.71 硬编码；禁止 `T_opt=0.8·T_max` | **人工抽 5 条红线+方向**；未出现 = 管道通、效果未通 |
| writer 讨论点 | `paper.md` 对应章节是否含 `3.1-e0` 等 required_discussions | 按 `sections` 白名单 |

### 4.3 判定语言（避免把「接到了」说成「杜绝了」）

- **管道成立**：4.2 前三行通过。
- **防忽略成立**：coverage 缺项会停，不会默默丢掉 brief。
- **源头杜绝方向错成立**：4.2 抽样方向在 **代码与论文** 中可指认（对照 iteration-plan 空白 40 分项）。这一条在本文撰写时 **尚未有 runs 证据**。
- **coverage 是弱指标**：39/39 followed 只证明 analyst 声称逐条回应，不证明内容在后续节点落地（智慧中枢 H05）；账本化改造方向见 [docs/13](13-注入体系补全计划.md) 第七节。

若管道成立但方向未落地：先改 prompt 注入容量/措辞或收紧 coder 红线提示，再考虑改求解实现；不要先加「方向再评估」图节点（计划书红线）。

---

## 五、下一步工作安排（按序）

1. **提交 brief 全栈**（需你明确说 commit）：冻结管道，避免下一轮和未提交 diff 缠在一起。12 个既有失败不要塞进这次 commit。
2. **第三节低成本验证**（本机 10 分钟）：check + 相关 pytest；可选 `brief dialogue`。
3. **第四节真跑 `51mcm-a-brief-v1`**：停在蓝图后也可先出 coverage 报告，再决定是否烧 coder 预算。
4. **按抽样结果分支**：
   - coverage 都 followed 但 1.2 仍走力学 min → 注入未改变决策，改 analyst/modeler prompt 或 brief 措辞，重跑；
     （恢复语义提醒：**修 prompt（代码）可 `recover` 续跑（沿用 checkpoint 内旧 brief）；修 brief 只能全新 `run`**
     （新 `--out` 或 `--force`）；`recover`/`supervise-resume`/`supervise-recover` 均不接受 `--brief`；
     门禁 `stop` 后 checkpoint `next=()`，`recover` 为空转）
   - coverage 反复 stop → analyst 吃不下 39 条，做容量（每条 ≤200 字、整块 ≤1500）或拆 brief；
   - 方向已写进蓝图但 coder 仍错 F_bond → 进入 iteration-plan 的代码转向（实现级），此时信息才够改求解器。
5. **后置（本迭代不做）**：Web 对话式建模预备 UI；并行蓝图 / RAG 资料包（A2 以外方案）。「把 brief 做成方向再评估」已按 C2 细化（2026-08-20）：无依据 LLM 投票式评审维持不做；确定性证据反证允许，实施见 16 阶段 2。

路线更迭的「代码改什么」仍以 [iteration-plan 第四节](08-MCM51整改迭代计划.md) 为准；**启动条件**是第四节至少有一次带 brief 的蓝图/coder 证据。

---

## 六、接手者开场四件事

1. 读 [modeling-brief-plan.md](10-ModelingBrief实施计划书.md) 第二、三节（决策与 schema），再读本文第三、四节（怎么验）。
2. 仓库仍可能 dirty；**禁止 `git checkout` 恢复** brief 相关文件。
3. 12 个全量失败已修复清零（2026-08-20，入库 `9f2906c`），不要当成 brief 回滚信号。
4. 没有 `runs/*/brief.json` + coverage 抽样前，不要写「已在源头杜绝方向性错误」。

---

## 八、机制修复清单（brief-v1 评审后，下一轮 run 的前置条件，2026-08-19）

> 修**体系机制**（改代码/prompt/门禁让下一轮不再犯），而不是修这篇论文。
> 执行顺序（v2，2026-08-21）：**M1 / M6 / M5-prompt 已完成**（批次 0）；
> **M3 → 主线工作项 2（批次 1）、M2 → 主线工作项 3（批次 3 文档 §3.1 单拎）**，两者在第一次真跑前落地；
> **M4 冻结**（前几题手工补对照 + 17#8 诚实记录）；M5 校验层待评估（冻结，07 行 8）；
> 主验证改为 **mcm51-b 干净题真跑**（实现计划-8-20/00 演练），A 题 brief-v2 降级为可选实验（见 实现计划-8-20/README v2）。

| # | 机制项 | 证据（brief-v1 评审） | 内容 | 量级 | 设计债 |
|---|---|---|---|---|---|
| M1 | LaTeX 转义保护 | `paper.tex:183` 符号表裸 `[sigma]` → 编译失败 | **已完成（2026-08-20）**：根因=`\\` 后 `[` 被当可选参数；`_md_table_to_latex` 行首 `[` 加 `{[}` 守卫（`\[` 是 display math 不可用）。单测 3 例 + paper.md 全篇重转换 xelatex 两遍零错误 | 小 | B18（已解决） |
| M2 | figure_plan 注入 | brief 计划 8 张图只落地 2 张，fig6（3 分）缺失归零 | injection-plan 阶段 1：figure 环节注入 figure_plan 子集 | 中 | B17 |
| M3 | brief 红线确定性校验 | K_avg=0.1783 违反禁整体 K 红线仍 8 分压线放行 | 从 brief 解析禁止项 → consistency 门禁机器可读校验，违反即停（不再靠 LLM 压线） | 中 | B16 |
| M4 | 对照方案执行机制 | 有效对照方案 0 个（门禁要求 ≥2），「基线对照」纯文字 | baseline/supporting 方案真实执行并注册证据 | 中 | B20 |
| M5 | 单位/量纲口径约束 | T_VM(0)=2.20 MPa 应力与力矩混比（P 用 500 N 而非 500 kN） | **prompt 层已完成（2026-08-20）**：render_coder_brief/render_modeler_brief 加量纲口径块；校验层量纲检查待评估（07 待决策） | 小 | B19（处理中） |
| M6 | 回归方程数值要求 | 1.2 稳定段回归系数缺失（官方 P≈0.217T+4.02 类可得分项未落） | **已落地（2026-08-20）**：brief.json data_notes 新增 `1.2-reg-coef`（40 条，brief check [OK]）；sample_brief_direction.py 加第 6 项检查 | 小 | —（论文级） |

> 机制修复完成并跑过 brief-v2 后，才有「修 vs 新问题」的干净对比；
> 在此之前不宣称方向问题已闭环（承接 4.3 判定语言与 9.5 近期顺序）。

---

## 七、brief-v1 真跑评审结论（2026-08-19，对照官方评分参考标准）

> 评审依据：仅官方《评分参考标准（资料文件）》；`总体思路*.md` 为 GPT 二手推演，未作依据。

- 建立日期：2026-08-19
- 被评审运行：`runs/51mcm-a-brief-v1`（第一次带 `--brief` 的真跑；coverage 39/39 followed）
- **污染警示**：MCM-51 经多轮同题调试且评审依据已知官方标准，属**已污染开发集**，本节分数不得作泛化证据（智慧中枢 H16）；泛化证据待 docs/16 阶段 1 无参考盲测。
- 评审依据：**仅官方《2026年第二十三届五一数学建模竞赛 A题 评分参考标准（资料文件）.md》**
  （`C:\Users\m1995\Desktop\数学建模-8-16\26年五一赛题\2026-51MCM-Problems\2026-51MCM-Problem A\` 下，
  目录里的 `总体思路*.md` 为 GPT 二手推演，**未作为评审依据**）
- 被评审论文：`runs/51mcm-a-brief-v1/paper.md`（492 行；全部数值已按参考值手工复核）
- 对照基线：r11（无 brief）预估 35–40/100

---

## 一、结论摘要

- **总分重估：约 74–86 / 100（中点 ≈ 80）**；对照 r11 **进步约 +40~45 分（接近翻倍）**。
- **brief 真实解决了方向问题**：r11 基本空白的 40 分（1.2 变点 / 3.1 调心垫圈 / 3.2 偏心压陷 / 4 围岩分级）
  全部被填充命中，且 39/39 coverage 与论文实际内容一致（不是表面转述）。
- **但属「骨架 + 参考值注入型」命中**：论文大量直接复述 brief 给定的公式与数值
  （论文 L301 自认 3.1 显式公式"仅直接引用、未推导"）。方向对 ≠ 交付达标：
  数值实现硬伤（3.2 单位、1.2 回归方程、3.1 图、Q4 恒值）+ 三个 degraded 门禁仍在。
- 内部质量门禁综合 6.4/10（≈64 折算）低于 rubric 打分——内容质量维度（创新 6、结果正确 6、深度 6）是短板。

### 已证明 / 未证明（智慧中枢 H02 采纳，2026-08-19）

- **已证明**：高价值人工信息（含官方参考值）可被流水线高保真传递并命中评分点——**信息传递能力**。
- **未证明**：无参考答案时的自主建模能力；去参考反事实实验未做；自主能力下界仍接近 r11。
- 口径：74–86 是带目标泄漏的事后上界；「源头杜绝方向性错误」类表述在无参考盲测（docs/16 阶段 1）前不得使用。

## 二、逐题对照打分（保守区间，满分 100）

| 分点 | 满分 | 估计 | 关键命中 / 扣分点 |
|---|---|---|---|
| 摘要与总体 | 10 | 6–7 | 结构完整；仅 2 张正文图；**3.1 关键图缺失**；LaTeX 失败无 PDF 直接伤排版分 |
| 1.1 | 10 | 8–9 | K₁₈=0.1620/K₂₀=0.1831/K₂₂=0.1899 全命中（0.16~0.19）；R²>0.96；缺显式回归方程系数 |
| 1.2 | 10 | 7–8 | 分段回归+网格搜索；岩石 T_c=150、煤体 175 命中区间；±5% 容差声明；**稳定段回归方程数值缺失** |
| 2.1 | 10 | 8–9 | P_max=min(P_yield,F_bond)、Winkler δ 判据全对；**求解章 prose 写三约束 min，与模型章矛盾** |
| 2.2 | 20 | 17–19 | 10 个分点全命中（τ=4.75/1.50、F_bond≈334/170、T_max 606.27/665.50 在 ±5% 内、δ=0.425/2.068）；**实现用 K_avg=0.1783 违反 brief 禁整体 K**（结果侥幸在容差内） |
| 3.1 | 20 | 14–16 | 显式 T_max(e) 公式与官方逐字一致、四层局限性、404.97/121.74/232.7%/e_cr=3.66 定量全中；**中间参数只列符号未给数值、fig6 三线图缺失（3 分归零）** |
| 3.2 | 10 | 7–9 | 偏心压陷修正公式满分；四约束+数值验证有；**T_VM(0)=2.20 MPa 单位口径错误**（应力 vs 力矩，P 误用 500 N 而非 500 kN），3.2 正文自相矛盾 |
| 4 | 10 | 7–9 | 三档分级+C1–C4+min{T1..T4}+E(f) 参数化声明；**T_opt 恒 404.97 与"低 f 压陷主控"叙事矛盾、敏感性全零退化** |

## 三、残留硬伤清单（后置门禁没拦住）

1. **K_avg=0.1783 违反 brief 红线**（`2.2-fbond-red`/`2.2-direction` 明确禁止整体 K）——
   consistency 8 分压线放行。**这是"brief 红线无机器可读确定性校验"的实证**（设计债 B16）。
2. **3.1 关键图 fig6 缺失**——figure_plan 无 figure 环节注入点，8 张计划图只落地 2 张（设计债 B17，B06 注入缺口实证）。
3. **3.2 T_VM(0) 单位口径错误** + 3.2 正文自相矛盾（先写 VM 不控制又宣布 VM 主控）（设计债 B19）。
4. 1.2 稳定段回归方程数值缺失（官方 P≈0.217T+4.02 一类可得分项未落）。
5. Q4 T_opt 恒 404.97、敏感性全零退化，与主控分区叙事矛盾。
6. 2.1 求解章 prose 三约束 vs 模型章两约束矛盾。

## 四、degraded 三因

| 因 | 详情 |
|---|---|
| a) LaTeX 编译失败 | `paper.tex:183` 符号表 `[sigma]` 未转义成数学模式 → "Missing number, treated as zero"；markdown→TeX 转义语法错误（非缺包/字体）（设计债 B18） |
| b) 论文评审 7 分 < 9 | 主要扣分：3.2 T_VM(0) 单位、Q4 T4 概念混用、K_avg、1.2 可复现细节、E(f) 取值依据、压陷公式量纲、W_b 未入问题 4 变量表 |
| c) 有效对照方案 0 个（需 ≥2） | final_state 证据角色全 primary、RESULT 全 baseline=ours；「各方案结果对比表」仅一行"本文方案\|—"；「基线对照」纯文字，无 alternative 被执行（设计债 B20） |

## 五、下一步优先级（若继续迭代）

1. 修 3.2 的 T_VM(0) 单位口径（力矩、P 用 kN，消除自相矛盾）；
2. 补 1.2 稳定段回归方程数值 + 3.1 三线图（fig6）；
3. Q4 让 T_opt(f) 随 f 变化或明确解释 T4 恒主控的物理原因、补非退化敏感性；
4. 补 ≥2 个真实可执行的对照方案（"三约束 min"与"平均 K"方案实际计算并列表）；
5. 修 LaTeX 符号表 `[sigma]` 转义，重新编译出 PDF。

---

## 附：brief 效果逐条对照（哪些靠 brief 命中）

- **r11 空白 → 本次命中**：1.2-direction/tc-discuss/tc/mean（变点检测全套）、2.2-fbond/ref/score（τ/F_bond/T_max/δ 参考值）、3.1-tmax-e/e0/ecr/score（显式公式+定量）、3.2-indent-e/eccentric/vm（修正模型结构）、4-topt/ef/grade/ef-assume/topt-red（分级+min 结构+参数化声明）、5 条红线 4 条实现干净（600.71、0.8·T_max、钻孔直径、E 单位）。
- **未命中/瑕疵**：3.2 T_VM 数值口径、1.2 回归方程数值、3.1 关键图、Q4 恒值、K 口径违规。

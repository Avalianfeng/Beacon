<!-- 全流程分析 · brief 检查系列 · 05 · 2026-08-29 · 节点 × brief 子集覆盖矩阵（ACT-03 最小改进面，源码核实，只读） -->

# 05 · 节点 × brief 子集覆盖矩阵

> **快照声明（2026-08-29 ACT-03 关账）**：本文件是 **D-022 落地前** 的探查快照；P1 三项（evaluation 接 scoring_notes、S7/S9 红线校验、coder data_notes）已在 D-022 / C-01～C-03 兑现。**勿当现行注入图重探**——现行切片见 `src/math_agent/brief.py` 的 `NODE_BRIEF_SLICE` 与 `docs/adr/D-022-brief硬信号与schema-v2.md`。

> **来源**：2026-08-29 委派——`后续行动清单.md` 第五节第 4 条（ACT-03「硬信号优先落地」的最小改进面）；站在 `brief检查/01–04` 与 `brief真实调用检查.md` 既有事实上，不做重复枚举，本次**补全 grep 遗漏点 + 产出矩阵 + 断供点清单 + 硬约束落点候选**。
> **方法**：`grep -rn brief src/math_agent/` 全量（22 个文件命中），逐一核对消费性质；只读，未改任何代码。
> **结论一句话**：brief 8 字段 × 12 节点 = 96 格中，**✅ 直接注入 34 / ⚠️ 经上游转述 25 / ❌ 断供 36 / ➖ 不适用 1**；断供集中在四个硬约束字段（scoring_notes / red_lines / data_notes / figure_plan）的「评审与验收」侧（evaluation / paper_critic / S7 / figure 生成链），全部有「本该有用」的正当理由——即 ACT-03 的最小改进面。

---

## 一、消费节点全枚举（含本次补全）

### 1.1 S9 流水线注入点（7 处，其中 coder 一处本次勘误）

| 节点 | 传参点 | 渲染器 | 注入字段 | 行号证据 |
|---|---|---|---|---|
| analyst | nodes/analyst.py:32 | `render_full_brief`（brief.py:207） | **全 8 字段** | prompts/analyst.py:87-88 |
| blueprint_critic | nodes/blueprint_critic.py:26 | `render_full_brief` | **全 8 字段** | prompts/blueprint_critic.py:33-34 |
| modeler | nodes/modeler.py:49 | `render_modeler_brief`（brief.py:272） | per_question_direction + formula_notes | prompts/modeler.py:60-61 |
| coder（主求解+图代码） | nodes/coder.py:718 | `render_coder_brief`（brief.py:294） | red_lines + formula_notes | prompts/coder_figure_one.py:145-146 |
| model_critic | nodes/model_critic.py:13 | `render_critic_brief`（brief.py:313） | formula_notes + red_lines | prompts/model_critic.py:69-71 |
| writer_section | prompts/writer_section.py:367-370（节点侧 nodes/writer.py:376 起） | `render_discussions_for_group`（brief.py:343） | required_discussions（按章节分组） | — |
| 门禁（routing） | routing.py:28-29 | `brief_coverage_problems`（brief.py:174-195，纯函数） | 7 个条目字段的 **id 覆盖**（brief.py:74-82 `_BRIEF_ITEM_FIELDS`） | — |

**本次补全/勘误（相对既有 6 注入点清单）**：

1. **coder 唯一注入点是 figure_one 渲染器**：`nodes/coder.py` 全文件仅 1 处 brief 引用（:718，`build_prompt_figure_one(..., brief=state.brief)`）；`prompts/coder.py` 的 `build_prompt` **零 brief 引用**且实际未被调用（nodes/coder.py:25 `# noqa: F401` 仅为 re-export SYSTEM）。即「coder 注入」= prompts/coder_figure_one.py:145-146，主求解代码与 supporting 图代码共用该渲染器（工作队列 kind 均为 figure，nodes/coder.py:598-611）。
2. **coder 的 baseline / frozen 分支不达 brief**：`nodes/coder.py:737` `build_baseline_prompt`（prompts/coder_baseline.py 零 brief）与 :649-660 frozen 确定性 wrapper（零 LLM）均无 brief——baseline 对照方案不收红线。
3. **checkpointing.py:13-25 的 5 处 brief 引用是类型白名单**（checkpoint 序列化许可），非消费。
4. **paper_expand.py:197-207**（S6 展开侧）`_brief_excerpt` 读 required_discussions + per_question_direction 两字段，与 cli.py 侧同源（见下）。
5. 其余命中文件均为证据链/文案：cli.py（157 处，入口/sha256/展示/S6 消费）、state.py:313-314（state.brief 存储）、ops_preflight.py:24,73（字符串回显）、ops_stage.py:25,147（存在性）、ops_handoff.py:66-93（交棒文案，S6 不显式传 --brief）、ops_help.py（文案）。

### 1.2 操作面与评审侧（消费或应有消费）

| 位置 | 消费 | 证据 |
|---|---|---|
| S6 装配（reference paper/expand） | **2 字段**：required_discussions（仅 disc-assumptions 进模型假设节）+ per_question_direction（方向首句进各问摘要） | cli.py:1104-1126、1139-1149、1372、1391-1397；paper_expand.py:197-207；缺省路径隐式命中 problems/<id>/brief.json（cli.py:1068） |
| S7 评审 | **零字段消费**；`check_l4_gates --brief` 为操作面死参数 | ops_review.py 全文零命中；check_l4_gates.py:111,137-142（全文拼接进语料）vs ops_review.py:89-93（从不传） |
| evaluation 节点 | **零消费 + 死承诺** | nodes/evaluation.py 零命中；prompts/evaluation.py:20「若提供评分细则/得分点清单则逐条核对」但 build_prompt（:24）无任何 scoring 参数 |
| paper_critic 节点 | **零消费**（连 brief 都不收） | nodes/paper_critic.py:117-126 实参无 brief |
| S5 验证（ops_verify/ops_recertify）、S8 登记（ops_accept） | 零接触 | 01 报告已证，不重复 |
| figure 生成链（figure_pipeline/figure_placement）、sensitivity、table_assembler、model_code_consistency、human_review、finalizer、rendering、latex_* | **全部零引用**（grep 证实） | 无注入、无转述 |

---

## 二、覆盖矩阵（8 字段 × 12 节点）

图例：✅ 直接注入（带行号）/ ⚠️ 间接（经 ProblemBlueprint 转述，依赖 analyst 单点消化）/ ❌ 不达 / ➖ 不适用。
「门禁」列 ✅ 表示该字段条目 id 进 brief_coverage 覆盖校验（只查被回应、不查内容遵守，brief.py:174-195）。

| brief 字段 | analyst | blueprint_critic | modeler | coder（主求解） | coder_figure_one | model_critic | writer_section | paper_critic | evaluation | S6 装配 | S7 评审 | 门禁 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **per_question_direction**（逐题方向） | ✅ analyst.py:87-88 | ✅ bp_critic.py:33-34 | ✅ modeler.py:60-61 | ⚠️ 经 blueprint 转述¹ | ⚠️ 经 blueprint 转述¹ | ⚠️ 经 blueprint 转述¹ | ⚠️ 经 blueprint 约束块² | ❌ | ❌ | ✅ cli.py:1139-1149 | ❌ | ✅ id |
| **formula_notes**（公式注意） | ✅ | ✅ | ✅ | ✅ coder_figure_one.py:146 | ✅ | ✅ model_critic.py:69-71 | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ id |
| **required_discussions**（必答讨论点） | ✅ | ✅ | ⚠️ 转述¹ | ⚠️ 转述¹ | ⚠️ 转述¹ | ⚠️ 转述¹ | ✅ writer_section.py:367-370 | ❌ | ❌ | ✅ cli.py:1104-1126 | ❌ | ✅ id |
| **red_lines**（红线） | ✅ | ✅ | ⚠️ 转述¹ | ✅ coder_figure_one.py:146 | ✅ | ✅ model_critic.py:69-71 | ⚠️ 转述² | ❌ | ❌ | ❌ | ❌ 死参数³ | ✅ id |
| **figure_plan**（图计划） | ✅ | ✅ | ⚠️ 转述¹ | ⚠️ 转述¹ | ⚠️ 转述¹ | ⚠️ 转述¹ | ⚠️ 转述² | ❌ | ❌ | ❌ | ❌ | ✅ id |
| **scoring_notes**（评分要点） | ✅ | ✅ | ⚠️ 转述¹ | ⚠️ 转述¹ | ⚠️ 转述¹ | ⚠️ 转述¹ | ⚠️ 转述² | ❌ | ❌ 死承诺⁴ | ❌ | ❌ | ✅ id |
| **data_notes**（数据注意） | ✅ | ✅ | ⚠️ 转述¹ | ⚠️ 转述¹ | ⚠️ 转述¹ | ⚠️ 转述¹ | ⚠️ 转述² | ❌ | ❌ | ❌ | ❌ | ✅ id |
| **reference_direction**（文献方向） | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ➖ 无 id 不进门禁⁵ |

> ① ⚠️ 转述通道：modeler/coder/model_critic 的 prompt 均带 `blueprint` 参数（modeler.py:46 `_blueprint_summary`、coder.py:712 `blueprint=state.problem_blueprint`、model_critic.py:13），blueprint 是 analyst 消化 brief 后的结构产物——字段经「analyst 单点翻译」间接可达，**不保证逐条原文保留**。
> ② writer 的 blueprint 约束块（writer_section.py:341-354）只含 core_task/小问/变量/目标/约束/指标/验证计划，不含 brief_coverage 原文；figure_plan/scoring_notes/data_notes 若 analyst 未消化进 blueprint 结构字段则 writer 实际收不到。
> ③ check_l4_gates.py:111,137-142 有 `--brief` 参数，但 ops_review.py:89-93 从不传——操作面死参数（01 报告 §七.3）。
> ④ prompts/evaluation.py:20 承诺「若提供评分细则则逐条核对」，build_prompt（:24）无参数、nodes/evaluation.py 零引用——永久死路径。
> ⑤ reference_direction 为 list[str] 无 id（brief.py:106），不在 `_BRIEF_ITEM_FIELDS`（brief.py:74-82），门禁不覆盖（04 报告 §3.4）。

**汇总**：✅ 34 / ⚠️ 25 / ❌ 36 / ➖ 1（96 格）。
- 直接注入仅覆盖「建模预备→蓝图→模型/代码/写作」的**生产侧**；「评审/验收侧」（evaluation、paper_critic、S7）对 7 个内容字段**全部 ❌**。
- ⚠️ 25 格全部集中在四节点（modeler/coder/figure_one/model_critic/writer）对「非渲染字段」的依赖转述——**转述链强度 = analyst 消化质量**（04 评估①「押注 analyst 单点翻译」的量化面）。

---

## 三、断供点清单（❌ 格 × 本该有用？）

> 判定原则：该节点职责是否天然需要该字段。仅列「本该有用」的 ❌，按 ACT-03 硬信号优先级排序。

| # | 字段 → 断供节点 | 本该有用？ | 依据（职责/承诺） | 现有兜底 | 级别 |
|---|---|---|---|---|---|
| D1 | scoring_notes → **evaluation** | ✅ **是（承诺）** | prompts/evaluation.py:20 白纸黑字承诺「若提供评分细则/得分点清单则逐条核对」，接线缺失 = 承诺自欺（ACT-04） | 无（死路径） | 🔴 硬 |
| D2 | scoring_notes → **paper_critic / S7 评审** | ✅ 是 | 终审与交付物验收的天然输入；S7 现在只数证据数字 token（check_paper_numbers.py:98-129），评分点齐备性无人核对 | S8 人工自查 | 🔴 硬 |
| D3 | red_lines → **S7 评审 / 产物校验** | ✅ 是（M3 设计） | 设计文档规划 `redline_violations` 纯函数（02-批次1:42-43）；5 个 check 工具零结构消费；B16 实证红线违规仍「8 分压线放行」（02 报告 §五） | LLM 评审自觉 | 🔴 硬 |
| D4 | data_notes → **coder（主求解）** | ✅ 是 | data_notes 9 条（mcm51-c）多为实现级口径（缺失处理/均值化/列对齐），render_coder_brief（brief.py:294-311）只渲红线+公式，**数据注意不达写代码的节点** | 经 blueprint ⚠️ 转述 | 🔴 硬 |
| D5 | data_notes / figure_plan → **S7 评审** | ✅ 是 | 后续行动清单待查项原文：「图/数据口径兑现目前 S7 机器评审看不见，只能靠 S8 人工自查」；`--evidence` 白名单与图计划零映射（01 报告 §五特别标注） | S8 人工 | 🔴 硬 |
| D6 | figure_plan → **figure 生成链**（figure_pipeline/figure_placement） | ✅ 是（推测） | figure_plan.requirements（标注/元素要求）是图代码的天然输入，但两节点零引用；图任务目的实际来自 model.figure_purposes（modeler 产出，nodes/coder.py:597-601）——图要求的传递完全依赖 modeler 消化 | modeler 消化 | 🟡 中（推测） |
| D7 | reference_direction → **writer** | ✅ 是（本意推测） | 04 报告 §2a/§4：文献方向不达 writer，select_references 独立于 brief；「本意指导文献章节」为推测 | Semantic Scholar + 静态库 | 🟡 中（推测） |
| D8 | red_lines / scoring_notes / figure_plan / data_notes → **modeler** | ⚠️ 部分 | 直接渲染器不含这些字段（render_modeler_brief 仅方向+公式）；modeler 选路线时看不见红线/评分点（如 rl-greedy 禁止贪心冒充主方案——modeler 恰恰是主方案的第一决策点） | blueprint ⚠️ 转述 | 🟡 中 |
| D9 | 门禁 × 内容遵守（结构性） | — | brief_coverage_problems 只查「id 被回应」，不查「禁令被遵守」（brief.py:174-195）；幻觉 id 不拦（03 报告 §4.4）——门禁对 8 字段都是「覆盖级」而非「遵守级」 | — | 🔴 结构 |
| D10 | coder baseline/frozen 分支 | ⚠️ 待裁定 | baseline 对照方案零 brief（nodes/coder.py:737），frozen wrapper 零 LLM（:649-660）；baseline 是否应受 rl-leak 等实现红线约束未决（推测：应受，与证据职责隔离不冲突） | — | 🟡 中（推测） |

**断供总数**：36 个 ❌ 格中，上述 10 条覆盖了全部「本该有用」的判定面；其余 ❌（如 scoring_notes × S6 装配、per_question_direction × evaluation）判定为「该节点职责上确实不需要」，不构成改进面。

---

## 四、硬约束落点候选表（方案候选，不实现）

> 分级原则（子agent分析/04）：红线/数据口径/评分点 = **硬约束** → 落机器校验或参数传递；方向/讨论点 = **软约束** → 文本注入够。落点判断基于现有结构（check 脚本族 + ops_review 聚合 + routing 门禁 + 渲染器扩展）。

| 字段 | 升级为硬信号的最自然落点 | 现有结构依据 | 改动量级（估） | 优先级 |
|---|---|---|---|---|
| **red_lines** | ① 新 `scripts/check_redlines.py`（M3 最小版：literal_ban/expr_ban/result_rule → warn/hard），挂 ops_review 聚合（`_CHECK_NAMES` ops_review.py:8-16 + argv 构造 :33-63）→ **操作面 S7 产物侧校验**；② S9 侧 routing.py `after_model_code_consistency` 前接 `redline_violations`（M3 规划接入点 02-批次1:42-43），hard 违规 → retry/stop；③ schema v2：brief.py 加 redline_rules 字段 + brief check 规则合法性校验（cli.py:2228-2252 扩展） | M3 设计文档已给全 schema；7/13 红线可直接机器化（02 报告 §四）；check 脚本族 stdin+退出码 0/1/2 范式现成 | 最小版 ≈0.5–1 天（02 报告 §六） | P1 |
| **scoring_notes** | ① **evaluation 接线**（ACT-04）：prompts/evaluation.py:24 `build_prompt` 加 `scoring_notes` 参数 + nodes/evaluation.py 从 state.brief 传参——最小改动，兑现已有承诺；② 后置核对：新 check 或扩展 check_l4_gates 做「交付物/得分点齐备性」核对，挂 ops_review | 承诺已存在（evaluation.py:20）；check 聚合范式现成 | ①极小（加参数+传参）；②中 | P1（①） |
| **data_notes** | ① **文本补注**：render_coder_brief（brief.py:294-311）扩字段加 data_notes——一行级改动，先堵 D4；② 机器侧：数据口径断言仿 check_paper_numbers 数字溯源范式（:254-310 `run_traceability`），但需数据血缘辅助（推测成本高，可先 WARN 级） | 渲染器扩展范式现成（brief.py 各 render 函数同构）；check 溯源范式现成 | ①极小；②中-高 | P1（①）/P3（②） |
| **figure_plan** | ① S7 清单核对：新 check（论文/figures 产物 vs brief.figure_plan 逐项比对），挂 ops_review——直接回答后续行动清单待查项；② figure_pipeline 节点文本注入 figure_plan.requirements（软兜底） | check 脚本族范式；figure 产物路径现成 | 中 | P2 |
| **reference_direction** | writer_section.py:367-370 处加 reference_direction 注入块（软约束，文本注入够） | 注入位现成（同 discussions 块） | 极小 | P3 |
| **per_question_direction / required_discussions / formula_notes** | **现状已够**（✅ 覆盖生产侧 + S6；软约束性质，⚠️ 转述可接受） | — | 不动 | — |
| **门禁（结构性）** | brief_coverage 扩「遵守级」校验属 M3 范畴（redline_rules 落地后自然衔接）；coverage 幻觉 id 拦截可加「多余 id 记 WARN」（brief.py:174-195 单向检查补盲，03 报告 §4.4） | 门禁纯函数现成 | 小 | P3 |

**最小改进面结论**（ACT-03）：先做 P1 三项——① scoring_notes 接线 evaluation（最小改动兑现承诺）；② red_lines 产物校验最小版（M3 已有设计）；③ data_notes 文本补注 render_coder_brief。三者合计改动面 <1 个工作日量级（估），覆盖 D1–D4 四个 🔴 断供点；D5（S7 图/数据口径核对）作为 P2 与既有待查项合并处置。

---

## 五、证据速查

- 注入点：nodes/analyst.py:32、blueprint_critic.py:26、modeler.py:49、model_critic.py:13、coder.py:718；prompts/analyst.py:87-88、blueprint_critic.py:33-34、modeler.py:60-61、coder_figure_one.py:145-146、model_critic.py:69-71、writer_section.py:367-370
- 渲染器：brief.py:207（full）、272（modeler）、294（coder）、313（critic）、343（discussions）
- 门禁：routing.py:28-29 + brief.py:174-195；条目字段清单 brief.py:74-82；reference_direction 无 id brief.py:106
- S6：cli.py:1068（缺省路径）、1104-1126（假设）、1139-1149（方向）；paper_expand.py:197-207
- S7 死参数：check_l4_gates.py:111,137-142 vs ops_review.py:89-93；evaluation 死承诺：prompts/evaluation.py:20,24 + nodes/evaluation.py 零引用
- paper_critic 全盲：nodes/paper_critic.py:117-126
- coder 分支：nodes/coder.py:718（figure_one）、737（baseline 无 brief）、649-660（frozen 确定性）、25（build_prompt 未用 noqa）
- 零引用节点族（grep 证实）：figure_pipeline / figure_placement / sensitivity / table_assembler / model_code_consistency / human_review / finalizer / rendering / latex_transform / latex_node / paper_evidence / evaluation / paper_critic / writer.py 本体

## 六、与既有报告的关系

- 本矩阵是 `brief真实调用检查.md` 待查项「节点 × brief 子集覆盖矩阵（ACT-03 最小改进面）」的产出；断供点 D1–D5 与 01 报告 §七、04 报告 §4、`后续行动清单.md` 待查项（S7 纳入 figure_plan/data_notes）直接衔接，无新增冲突事实。
- 本次唯一新事实：**coder 的直接注入 = prompts/coder_figure_one.py（非 prompts/coder.py）**，且 baseline/frozen 分支不达——既有「注入矩阵」表（brief真实调用检查.md）中「coder、coder_figure_one」两行实为同一注入点，建议后续表述合并为「coder（figure_one 渲染器）」，并补 baseline/frozen 例外。
